"""Thin functional wrapper over the GM Python SDK (`gm.api`)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# gm is imported lazily so unit tests can mock it without the SDK installed.
_api = None


def _sdk():
    global _api
    if _api is None:
        from gm import api as gm_api
        _api = gm_api
    return _api


def initialize(token: str, address: Optional[str] = None) -> None:
    """Set GM token (and optional address). Raises on invalid token."""
    sdk = _sdk()
    sdk.set_token(token)
    if address:
        # Python SDK uses `set_serv_addr` (C# version was `SetAddr`).
        if hasattr(sdk, "set_serv_addr"):
            sdk.set_serv_addr(address)
        elif hasattr(sdk, "set_addr"):
            sdk.set_addr(address)
        else:
            logger.warning("No set_addr/set_serv_addr function in gm SDK; using default")
    logger.info("GM API initialized (address=%s)", address or "(default)")


def history_bars(
    symbol: str,
    frequency: str,
    start: datetime,
    end: datetime,
) -> List[dict]:
    """Fetch historical bars for a single symbol in [start, end]. Returns a
    list of dicts keyed by lowercase bar fields (`bob`, `eob`, `open`,
    `close`, `high`, `low`, `volume`, `amount`).
    """
    sdk = _sdk()
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end.strftime("%Y-%m-%d %H:%M:%S")

    df = sdk.history(
        symbol=symbol,
        frequency=frequency,
        start_time=start_str,
        end_time=end_str,
        adjust=sdk.ADJUST_NONE,
        df=True,
    )
    if df is None or len(df) == 0:
        return []

    records = df.to_dict("records")
    return [_normalize_bar(r) for r in records]


def _normalize_bar(row: dict) -> dict:
    """Convert pandas Timestamps in bob/eob to naive Python datetimes."""
    out = dict(row)
    for key in ("bob", "eob"):
        v = out.get(key)
        if isinstance(v, pd.Timestamp):
            out[key] = v.to_pydatetime().replace(tzinfo=None)
    return out


def history_bars_batch(
    symbols: List[str],
    frequency: str,
    start: datetime,
    end: datetime,
) -> dict:
    """Fetch historical bars for multiple symbols in a single GM call.

    Returns a dict {symbol: [bar_dicts]} keyed by GM symbol. Symbols with
    no data (suspended/delisted/pre-IPO) are absent. Auto-halves the batch
    on status 1029 ('query result too large').
    """
    if not symbols:
        return {}

    sdk = _sdk()
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end.strftime("%Y-%m-%d %H:%M:%S")

    try:
        df = sdk.history(
            symbol=symbols,
            frequency=frequency,
            start_time=start_str,
            end_time=end_str,
            adjust=sdk.ADJUST_NONE,
            df=True,
        )
    except Exception as ex:
        msg = str(ex)
        if "1029" in msg and len(symbols) > 1:
            mid = len(symbols) // 2
            logger.info(
                "Batch of %d too large (1029); splitting into %d + %d",
                len(symbols), mid, len(symbols) - mid,
            )
            left = history_bars_batch(symbols[:mid], frequency, start, end)
            right = history_bars_batch(symbols[mid:], frequency, start, end)
            left.update(right)
            return left
        raise

    if df is None or len(df) == 0 or "symbol" not in df.columns:
        return {}

    result: dict[str, List[dict]] = {}
    for symbol, group in df.groupby("symbol"):
        result[symbol] = [_normalize_bar(r) for r in group.to_dict("records")]
    return result


# ============================================================
#  Index Constituents (universe membership)
# ============================================================

def get_index_constituents(index: str, trade_date: Optional[str] = None) -> List[dict]:
    """Fetch index constituents as of trade_date (YYYY-MM-DD string or None=latest).

    Wraps `stk_get_index_constituents`. Returns list of dicts with keys
    including `symbol` (GM format like 'SHSE.600000'), `weight`, `trade_date`.
    Empty list if the index has no constituents on the given date (e.g.
    non-trading day).
    """
    sdk = _sdk()
    kwargs = {"index": index, "df": True}
    if trade_date is not None:
        kwargs["trade_date"] = trade_date
    df = sdk.stk_get_index_constituents(**kwargs)
    if df is None or len(df) == 0:
        return []
    return df.to_dict("records")


# ============================================================
#  Fundamentals — Pt (multi-symbol, single-day cross-section)
# ============================================================

def _pt_call(fn, symbols_csv: str, fields_csv: str, date: str,
             rpt_type: Optional[int], data_type: Optional[int]) -> List[dict]:
    """Invoke a stk_get_*_pt function.

    Quarterly variants take rpt_type/data_type;
    daily variants (valuation/mktvalue/basic) do not.
    """
    if rpt_type is not None and data_type is not None:
        df = fn(symbols=symbols_csv, fields=fields_csv, rpt_type=rpt_type,
                data_type=data_type, date=date, df=True)
    else:
        df = fn(symbols=symbols_csv, fields=fields_csv, trade_date=date, df=True)
    if df is None or len(df) == 0:
        return []
    return df.to_dict("records")


def stk_balance_pt(symbols_csv: str, fields_csv: str,
                   rpt_type: Optional[int], data_type: Optional[int],
                   date: str) -> List[dict]:
    """Fetch balance sheet (Pt, multi-symbol, single-day)."""
    return _pt_call(_sdk().stk_get_fundamentals_balance_pt,
                    symbols_csv, fields_csv, date, rpt_type, data_type)


def stk_cashflow_pt(symbols_csv: str, fields_csv: str,
                    rpt_type: Optional[int], data_type: Optional[int],
                    date: str) -> List[dict]:
    """Fetch cashflow statement (Pt, multi-symbol, single-day)."""
    return _pt_call(_sdk().stk_get_fundamentals_cashflow_pt,
                    symbols_csv, fields_csv, date, rpt_type, data_type)


def stk_income_pt(symbols_csv: str, fields_csv: str,
                  rpt_type: Optional[int], data_type: Optional[int],
                  date: str) -> List[dict]:
    """Fetch income statement (Pt, multi-symbol, single-day)."""
    return _pt_call(_sdk().stk_get_fundamentals_income_pt,
                    symbols_csv, fields_csv, date, rpt_type, data_type)


def stk_prime_pt(symbols_csv: str, fields_csv: str,
                 rpt_type: Optional[int], data_type: Optional[int],
                 date: str) -> List[dict]:
    """Fetch finance prime (Pt, multi-symbol, single-day)."""
    return _pt_call(_sdk().stk_get_finance_prime_pt,
                    symbols_csv, fields_csv, date, rpt_type, data_type)


def stk_deriv_pt(symbols_csv: str, fields_csv: str,
                 rpt_type: Optional[int], data_type: Optional[int],
                 date: str) -> List[dict]:
    """Fetch finance derivative (Pt, multi-symbol, single-day)."""
    return _pt_call(_sdk().stk_get_finance_deriv_pt,
                    symbols_csv, fields_csv, date, rpt_type, data_type)


def stk_valuation_pt(symbols_csv: str, fields_csv: str, trade_date: str) -> List[dict]:
    """Fetch daily valuation (Pt, multi-symbol, single-day)."""
    return _pt_call(_sdk().stk_get_daily_valuation_pt,
                    symbols_csv, fields_csv, trade_date, None, None)


def stk_mktvalue_pt(symbols_csv: str, fields_csv: str, trade_date: str) -> List[dict]:
    """Fetch daily market value (Pt, multi-symbol, single-day)."""
    return _pt_call(_sdk().stk_get_daily_mktvalue_pt,
                    symbols_csv, fields_csv, trade_date, None, None)


def stk_basic_pt(symbols_csv: str, fields_csv: str, trade_date: str) -> List[dict]:
    """Fetch daily basic (Pt, multi-symbol, single-day)."""
    return _pt_call(_sdk().stk_get_daily_basic_pt,
                    symbols_csv, fields_csv, trade_date, None, None)


# ============================================================
#  Fundamentals — time-series (single symbol, multi-day)
# ============================================================

def _ts_call(fn, symbol: str, fields_csv: str,
             start_date: str, end_date: str,
             rpt_type: Optional[int], data_type: Optional[int]) -> List[dict]:
    if rpt_type is not None and data_type is not None:
        df = fn(symbol=symbol, fields=fields_csv, rpt_type=rpt_type,
                data_type=data_type, start_date=start_date, end_date=end_date, df=True)
    else:
        df = fn(symbol=symbol, fields=fields_csv,
                start_date=start_date, end_date=end_date, df=True)
    if df is None or len(df) == 0:
        return []
    return df.to_dict("records")


def stk_balance(symbol: str, fields_csv: str,
                rpt_type: Optional[int], data_type: Optional[int],
                start_date: str, end_date: str) -> List[dict]:
    """Fetch balance sheet (time-series, single symbol)."""
    return _ts_call(_sdk().stk_get_fundamentals_balance,
                    symbol, fields_csv, start_date, end_date, rpt_type, data_type)


def stk_cashflow(symbol: str, fields_csv: str,
                 rpt_type: Optional[int], data_type: Optional[int],
                 start_date: str, end_date: str) -> List[dict]:
    """Fetch cashflow statement (time-series, single symbol)."""
    return _ts_call(_sdk().stk_get_fundamentals_cashflow,
                    symbol, fields_csv, start_date, end_date, rpt_type, data_type)


def stk_income(symbol: str, fields_csv: str,
               rpt_type: Optional[int], data_type: Optional[int],
               start_date: str, end_date: str) -> List[dict]:
    """Fetch income statement (time-series, single symbol)."""
    return _ts_call(_sdk().stk_get_fundamentals_income,
                    symbol, fields_csv, start_date, end_date, rpt_type, data_type)


def stk_prime(symbol: str, fields_csv: str,
              rpt_type: Optional[int], data_type: Optional[int],
              start_date: str, end_date: str) -> List[dict]:
    """Fetch finance prime (time-series, single symbol)."""
    return _ts_call(_sdk().stk_get_finance_prime,
                    symbol, fields_csv, start_date, end_date, rpt_type, data_type)


def stk_deriv(symbol: str, fields_csv: str,
              rpt_type: Optional[int], data_type: Optional[int],
              start_date: str, end_date: str) -> List[dict]:
    """Fetch finance derivative (time-series, single symbol)."""
    return _ts_call(_sdk().stk_get_finance_deriv,
                    symbol, fields_csv, start_date, end_date, rpt_type, data_type)


def stk_valuation(symbol: str, fields_csv: str,
                  start_date: str, end_date: str) -> List[dict]:
    """Fetch daily valuation (time-series, single symbol)."""
    return _ts_call(_sdk().stk_get_daily_valuation,
                    symbol, fields_csv, start_date, end_date, None, None)


def stk_mktvalue(symbol: str, fields_csv: str,
                 start_date: str, end_date: str) -> List[dict]:
    """Fetch daily market value (time-series, single symbol)."""
    return _ts_call(_sdk().stk_get_daily_mktvalue,
                    symbol, fields_csv, start_date, end_date, None, None)


def stk_basic(symbol: str, fields_csv: str,
              start_date: str, end_date: str) -> List[dict]:
    """Fetch daily basic (time-series, single symbol)."""
    return _ts_call(_sdk().stk_get_daily_basic,
                    symbol, fields_csv, start_date, end_date, None, None)
