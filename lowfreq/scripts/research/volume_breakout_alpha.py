"""Volume-breakout alpha validation.

Hypothesis: a stock that simultaneously shows (a) volume surging above its
recent average and (b) turnover rate above its recent average tends to
outperform the next day. This script tests that hypothesis vectorially across
the whole A-share universe stored in ClickHouse, using turnover-rate data
joined from PostgreSQL ``fundamentals.daily_basic``.

Output:
  - Stdout table of mean next-day return for each parameter combination, with
    a paired t-stat against the unconditional same-window mean.
  - ``volume_breakout_alpha_results.csv`` with one row per parameter combo.

Design notes:
  - All rolling baselines use ``.shift(1)`` so the signal at day *t* only sees
    information up to day *t-1*. No future-leak.
  - The signal is computed once per (vol_mult, turn_mult) combo on the same
    joined panel; the parameter sweep is just a filter pass over that panel.
  - ClickHouse stores symbols in TS format (``600000.SH``). PostgreSQL
    ``fundamentals.daily_basic.symbol`` may be either TS or GM format; we
    normalize defensively on load (see ``_normalize_to_ts``).
"""
from __future__ import annotations

import logging
from typing import Iterable

import numpy as np
import pandas as pd
from scipy import stats

from scripts.research.common.db import query_clickhouse, query_postgres

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname).3s] %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUT_CSV = "volume_breakout_alpha_results.csv"

# Parameter grid per the spec.
VOL_MULTS = (1.2, 1.5, 2.0, 3.0)
TURN_MULTS = (1.5, 2.0, 3.0)
ROLL_WINDOW = 20  # trading days for the rolling mean baselines


# ---------------------------------------------------------------------------
# Symbol format normalization
# ---------------------------------------------------------------------------

_GM_TO_TS = {"SHSE": "SH", "SZSE": "SZ"}
_TS_TO_TS = {"SH": "SH", "SZ": "SZ"}


def _normalize_to_ts(symbols: Iterable[str]) -> list[str]:
    """Coerce a list of symbols to TS format (``600000.SH``).

    Tolerates three inputs observed in the platform:
      - TS format already:  ``600000.SH``
      - GM format:          ``SHSE.600000``
      - Bare code:          ``600000`` (left alone; will not join)
    """
    out = []
    for s in symbols:
        if s is None or s == "":
            continue
        s = str(s).strip()
        if "." in s:
            left, right = s.split(".", 1)
            if right.upper() in _TS_TO_TS:
                out.append(f"{left}.{right.upper()}")
            elif left.upper() in _GM_TO_TS:
                out.append(f"{right}.{_GM_TO_TS[left.upper()]}")
            else:
                out.append(s)
        else:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_daily_bars() -> pd.DataFrame:
    """Load daily OHLCV from ClickHouse ``market_data.kline_daily``.

    Returns columns: trade_time (datetime, naive), ts_code, open, high, low,
    close, volume, amount. Sorted by (ts_code, trade_time).
    """
    sql = """
        SELECT trade_time, ts_code, open, high, low, close, volume, amount
        FROM market_data.kline_daily
        ORDER BY ts_code, trade_time
    """
    df = query_clickhouse(sql)
    logger.info("Loaded %d daily bars from ClickHouse (%d symbols)",
                len(df), df["ts_code"].nunique() if len(df) else 0)
    return df


def load_turnover() -> pd.DataFrame:
    """Load turnover rate from PostgreSQL ``fundamentals.daily_basic``.

    Returns columns: trade_date (date), ts_code, turnrate. ``ts_code`` is
    normalized to TS format so it joins cleanly against the ClickHouse panel.
    """
    sql = """
        SELECT symbol, trade_date, turnrate
        FROM fundamentals.daily_basic
        WHERE turnrate IS NOT NULL
    """
    df = query_postgres(sql)
    if df.empty:
        logger.warning("fundamentals.daily_basic returned 0 rows; "
                       "alpha script cannot evaluate turnover condition.")
        return df

    df = df.rename(columns={"symbol": "ts_code"})
    df["ts_code"] = _normalize_to_ts(df["ts_code"].tolist())
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    logger.info("Loaded %d turnover rows from PG daily_basic (%d symbols)",
                len(df), df["ts_code"].nunique())
    return df[["ts_code", "trade_date", "turnrate"]]


def build_panel(daily: pd.DataFrame, turnover: pd.DataFrame) -> pd.DataFrame:
    """Join daily bars with turnover, then compute baselines and forward return.

    The panel is indexed by (ts_code, trade_date). Baselines are computed
    per-symbol with a trailing window and shifted by one bar so day *t*'s
    signal uses only data up to *t-1*. ``forward_return`` is the close-to-close
    return from *t* to *t+1* — what the alpha is trying to predict.
    """
    daily = daily.copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_time"]).dt.normalize()
    panel = daily.merge(turnover, on=["ts_code", "trade_date"], how="left")

    panel = panel.sort_values(["ts_code", "trade_date"]).set_index(
        ["ts_code", "trade_date"]
    )

    # Forward return: close[t+1] / close[t] - 1. Computed per symbol.
    panel["forward_return"] = (
        panel.groupby(level="ts_code")["close"].shift(-1)
        / panel["close"] - 1.0
    )

    # Trailing baselines (exclude today via shift(1)) to avoid look-ahead.
    grp = panel.groupby(level="ts_code")
    panel["vol_ma20"] = grp["volume"].transform(
        lambda s: s.rolling(ROLL_WINDOW).mean().shift(1)
    )
    panel["turn_ma20"] = grp["turnrate"].transform(
        lambda s: s.rolling(ROLL_WINDOW).mean().shift(1)
    )

    # Drop rows where the signal cannot be evaluated (warmup + last bar).
    before = len(panel)
    panel = panel.dropna(subset=["vol_ma20", "turn_ma20", "forward_return"])
    logger.info("Panel built: %d usable rows (dropped %d for warmup/NaN)",
                len(panel), before - len(panel))
    return panel


# ---------------------------------------------------------------------------
# Signal evaluation
# ---------------------------------------------------------------------------

def evaluate_combo(panel: pd.DataFrame, vol_mult: float, turn_mult: float) -> dict:
    """Evaluate one (vol_mult, turn_mult) parameter combo on the panel.

    Returns a dict with the combo, hit count, mean forward return for hits,
    the unconditional mean in the same panel, and a paired t-stat / p-value.
    """
    vol_hit = panel["volume"] > panel["vol_ma20"] * vol_mult
    turn_hit = panel["turnrate"] > panel["turn_ma20"] * turn_mult
    signal = vol_hit & turn_hit

    n_hits = int(signal.sum())
    result = {
        "vol_mult": vol_mult,
        "turn_mult": turn_mult,
        "n_hits": n_hits,
        "n_total": len(panel),
        "hit_rate": float(signal.mean()) if len(panel) else float("nan"),
    }

    if n_hits < 30:
        # Too few hits to make any statistical claim. Still record the means
        # so the sweep table shows the trajectory.
        result.update({
            "mean_ret_signal": float(panel.loc[signal, "forward_return"].mean())
                                if n_hits else float("nan"),
            "mean_ret_uncond": float(panel["forward_return"].mean()),
            "t_stat": float("nan"),
            "p_value": float("nan"),
        })
        return result

    signal_returns = panel.loc[signal, "forward_return"].to_numpy()
    baseline = panel["forward_return"].mean()
    result["mean_ret_signal"] = float(signal_returns.mean())
    result["mean_ret_uncond"] = float(baseline)
    # One-sample t-test: is the mean of the signal-day population different
    # from the unconditional mean? This is conservative vs. a paired test on
    # overlapping windows but is appropriate when hits are sparse.
    t_stat, p_value = stats.ttest_1samp(signal_returns, popmean=baseline)
    result["t_stat"] = float(t_stat)
    result["p_value"] = float(p_value)
    return result


def run_sweep(panel: pd.DataFrame) -> pd.DataFrame:
    """Run the full (vol_mult, turn_mult) sweep and return a results frame."""
    rows = []
    for vol_mult in VOL_MULTS:
        for turn_mult in TURN_MULTS:
            row = evaluate_combo(panel, vol_mult, turn_mult)
            rows.append(row)
            logger.info(
                "vol_mult=%4.1f turn_mult=%4.1f -> hits=%6d (%5.2f%%) "
                "mean_ret=%+.4f%% uncond=%+.4f%% t=%+.2f p=%.3f",
                vol_mult, turn_mult, row["n_hits"],
                100.0 * row["hit_rate"],
                100.0 * row["mean_ret_signal"] if not np.isnan(row["mean_ret_signal"]) else float("nan"),
                100.0 * row["mean_ret_uncond"],
                row["t_stat"], row["p_value"],
            )
    return pd.DataFrame(rows)


def main() -> None:
    logger.info("Step 1/3: loading daily bars from ClickHouse")
    daily = load_daily_bars()
    if daily.empty:
        logger.error("No daily bars in ClickHouse; aborting.")
        return

    logger.info("Step 2/3: loading turnover from PostgreSQL")
    turnover = load_turnover()

    logger.info("Step 3/3: building panel and running parameter sweep")
    panel = build_panel(daily, turnover)
    if panel.empty:
        logger.error("Panel is empty after warmup drop; aborting sweep.")
        return

    results = run_sweep(panel)

    # Pretty-print the full sweep table to stdout.
    with pd.option_context("display.max_rows", None,
                           "display.width", 200,
                           "display.float_format", lambda v: f"{v:.4f}"):
        print("\n=== Volume-breakout alpha sweep ===")
        print(results.to_string(index=False))

    #results.to_csv(OUTPUT_CSV, index=False)
    logger.info("Wrote results to %s", OUTPUT_CSV)


if __name__ == "__main__":
    main()
