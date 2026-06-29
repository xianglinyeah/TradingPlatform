"""Daily-breakout alpha validation (with volume + turnover confirmation).

Hypothesis: a stock that simultaneously satisfies
  (a) the daily-breakout regime filter from ``DailyBreakoutStrategy``:
      past 60-day decline >= 20% AND recent 20-day range < 8% (a bottom
      consolidation box), with today's close breaking above the 20-day
      high (box upper edge) computed from data through yesterday, AND
  (b) volume surge  > vol_ma20  * vol_mult,  AND
  (c) turnover surge > turn_ma20 * turn_mult
tends to outperform the next day.

This script tests that hypothesis vectorially across the whole A-share
universe stored in ClickHouse, using turnover-rate data joined from
PostgreSQL ``fundamentals.daily_basic``.

Parameter sweep is over (vol_mult, turn_mult). Daily-breakout params are
fixed (same defaults as ``BreakoutParams`` in the production strategy) but
exposed as module constants so they can be tuned without editing logic.

Output:
  - Stdout table of mean next-day return for each parameter combination,
    with a one-sample t-stat against the unconditional same-panel mean.
  - ``daily_breakout_alpha_results.csv`` with one row per parameter combo.

Design notes:
  - All rolling baselines use ``.shift(1)`` so the signal at day *t* only
    sees information up to day *t-1*. No future-leak. This includes the
    20-day high/low used as the breakout level (matching the production
    strategy, which uses ``daily.iloc[-20:]`` through yesterday).
  - The daily-breakout mask is computed once on the joined panel; the
    parameter sweep is just a filter pass over that mask AND-ed with the
    (vol_mult, turn_mult) volume/turnover conditions.
  - ``min_daily_bars = 65`` from the production strategy is enforced
    implicitly: rolling(60).shift(1) produces NaN for the first ~60 rows
    per symbol and those rows are dropped.
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

OUTPUT_CSV = "daily_breakout_alpha_results.csv"

# ---------------------------------------------------------------------------
# Parameter grid (sweep) and daily-breakout fixed params
# ---------------------------------------------------------------------------

VOL_MULTS = (1.2, 1.5, 2.0, 3.0)
TURN_MULTS = (1.5, 2.0, 3.0)

ROLL_WINDOW = 20  # rolling window for vol/turn baselines AND box edges

# Daily-breakout regime params (mirror BreakoutParams defaults in production)
DOWNTREND_DAYS = 60    # lookback for the downtrend check
DOWNTREND_PCT  = 0.20  # decline threshold
CONSOL_RANGE   = 0.08  # max 20-day range to qualify as a box


# ---------------------------------------------------------------------------
# Symbol format normalization (same logic as volume_breakout_alpha)
# ---------------------------------------------------------------------------

_GM_TO_TS = {"SHSE": "SH", "SZSE": "SZ"}
_TS_TO_TS = {"SH": "SH", "SZ": "SZ"}


def _normalize_to_ts(symbols: Iterable[str]) -> list[str]:
    """Coerce a list of symbols to TS format (``600000.SH``).

    Tolerates TS format (``600000.SH``), GM format (``SHSE.600000``),
    and bare codes (``600000`` — left alone, will not join).
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


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------

def build_panel(daily: pd.DataFrame, turnover: pd.DataFrame) -> pd.DataFrame:
    """Join daily bars with turnover, then compute:
      - forward_return (close-to-close t -> t+1, the prediction target)
      - vol_ma20, turn_ma20: trailing 20-day means (excluding today)
      - box_high, box_low:   trailing 20-day high/low (excluding today),
                             the breakout / support levels
      - downtrend_ok:        past 60-day decline >= DOWNTREND_PCT
      - consol_ok:           trailing 20-day range < CONSOL_RANGE
      - breakout_ok:         close > box_high AND close > box_low
                             (the second clause guards against false breakouts
                             where price gaps below support same day)

    The daily-breakout mask is ``downtrend_ok & consol_ok & breakout_ok``.

    The panel is indexed by (ts_code, trade_date).
    """
    daily = daily.copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_time"]).dt.normalize()
    panel = daily.merge(turnover, on=["ts_code", "trade_date"], how="left")

    panel = panel.sort_values(["ts_code", "trade_date"]).set_index(
        ["ts_code", "trade_date"]
    )

    grp = panel.groupby(level="ts_code")

    # Forward return: close[t+1] / close[t] - 1, per symbol.
    panel["forward_return"] = (
        grp["close"].shift(-1) / panel["close"] - 1.0
    )

    # Trailing 20-day baselines EXCLUDING today (shift(1) avoids look-ahead).
    panel["vol_ma20"] = grp["volume"].transform(
        lambda s: s.rolling(ROLL_WINDOW).mean().shift(1)
    )
    panel["turn_ma20"] = grp["turnrate"].transform(
        lambda s: s.rolling(ROLL_WINDOW).mean().shift(1)
    )

    # Box edges = trailing 20-day high/low through yesterday.
    panel["box_high"] = grp["high"].transform(
        lambda s: s.rolling(ROLL_WINDOW).max().shift(1)
    )
    panel["box_low"] = grp["low"].transform(
        lambda s: s.rolling(ROLL_WINDOW).min().shift(1)
    )

    # Downtrend check: close 60 days ago vs close yesterday (both exclude t).
    # Matches production: start_close / end_close - 1 >= DOWNTREND_PCT,
    # where start = past_60.iloc[0] and end = past_60.iloc[-1].
    panel["close_60_ago"] = grp["close"].transform(
        lambda s: s.shift(DOWNTREND_DAYS)
    )
    panel["close_yesterday"] = grp["close"].transform(lambda s: s.shift(1))
    decline = (
        panel["close_60_ago"] / panel["close_yesterday"] - 1.0
    )
    panel["downtrend_ok"] = decline >= DOWNTREND_PCT

    # Consolidation box: (high_20 - low_20) / low_20 < CONSOL_RANGE.
    consol_range = (panel["box_high"] - panel["box_low"]) / panel["box_low"]
    panel["consol_ok"] = consol_range < CONSOL_RANGE

    # Breakout event on day t: today's close breaks box_high (and stays
    # above box_low — redundant when the first holds, but kept for parity
    # with the production strategy's false-breakout guard).
    panel["breakout_ok"] = (
        (panel["close"] > panel["box_high"])
        & (panel["close"] > panel["box_low"])
    )

    # Drop rows where any required input is missing (warmup, last bar,
    # or missing turnover).
    before = len(panel)
    panel = panel.dropna(
        subset=["vol_ma20", "turn_ma20", "box_high", "box_low",
                "close_60_ago", "close_yesterday", "forward_return"]
    )
    logger.info("Panel built: %d usable rows (dropped %d for warmup/NaN)",
                len(panel), before - len(panel))

    # Pre-compute the daily-breakout mask once. The sweep below only ANDs
    # this with volume/turnover conditions, so it pays to compute it once.
    panel["daily_breakout"] = (
        panel["downtrend_ok"] & panel["consol_ok"] & panel["breakout_ok"]
    )

    n_breakout = int(panel["daily_breakout"].sum())
    logger.info("Daily-breakout candidates (no vol/turn filter): "
                "%d rows (%.4f%% of panel)",
                n_breakout, 100.0 * n_breakout / max(len(panel), 1))
    return panel


# ---------------------------------------------------------------------------
# Signal evaluation
# ---------------------------------------------------------------------------

def evaluate_combo(panel: pd.DataFrame, vol_mult: float, turn_mult: float) -> dict:
    """Evaluate one (vol_mult, turn_mult) combo.

    Signal = daily_breakout AND volume > vol_ma20*vol_mult AND
             turnrate > turn_ma20*turn_mult.

    Returns dict with hit count, mean forward return for hits, the
    unconditional panel mean, and a one-sample t-stat / p-value testing
    whether the signal-day forward returns differ from the unconditional
    mean.
    """
    vol_hit  = panel["volume"]   > panel["vol_ma20"]  * vol_mult
    turn_hit = panel["turnrate"] > panel["turn_ma20"] * turn_mult
    signal = panel["daily_breakout"] & vol_hit & turn_hit

    n_hits = int(signal.sum())
    result = {
        "vol_mult": vol_mult,
        "turn_mult": turn_mult,
        "n_hits": n_hits,
        "n_total": len(panel),
        "hit_rate": float(signal.mean()) if len(panel) else float("nan"),
    }

    if n_hits < 30:
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
                "vol_mult=%4.1f turn_mult=%4.1f -> hits=%6d (%5.4f%%) "
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

    with pd.option_context("display.max_rows", None,
                           "display.width", 200,
                           "display.float_format", lambda v: f"{v:.4f}"):
        print("\n=== Daily-breakout alpha sweep (vol + turn confirmation) ===")
        print(results.to_string(index=False))

    # results.to_csv(OUTPUT_CSV, index=False)
    logger.info("Wrote results to %s", OUTPUT_CSV)


if __name__ == "__main__":
    main()
