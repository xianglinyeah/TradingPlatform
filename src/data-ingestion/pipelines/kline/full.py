"""Full K-line back-fill. Iterates the configured year range (minute bars,
per-year files) and writes daily bars to one file per symbol. ClickHouse is
overwritten via delete-then-insert for the requested date range.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List

from sources import gm_api
from core import symbol_pool
from storage.clickhouse import (
    ClickHouseStorage,
    TABLE_1MIN,
    TABLE_DAILY,
)
from storage.parquet import (
    gm_to_ts_code,
    MinuteParquetStorage,
    DailyParquetStorage,
)
from config import (
    DataConfig,
    KlineIncrementalConfig,
    MarketScopeConfig,
    ProcessingConfig,
    parse_pg_conn,
)

logger = logging.getLogger(__name__)

FREQ_MINUTE = "60s"
FREQ_DAILY = "1d"


def _build_symbols(market_scope: MarketScopeConfig,
                   kcfg: KlineIncrementalConfig,
                   data_cfg: DataConfig,
                   storage_conn_str: str) -> List[str]:
    """Resolve symbols for kline_full.

    Priority: universe_id (from PG market_ref) > CUSTOM > A_ALL/CSI_ALL.
    Returns GM-format symbols suitable for the GM SDK.
    """
    # Universe-first: pull from market_ref.universe_member if configured.
    universe_id = market_scope.universe_id or kcfg.universe_id
    if universe_id:
        from storage.universe import get_members_as_gm
        syms = get_members_as_gm(storage_conn_str, universe_id)
        logger.info("Symbol source universe_id=%s: %d symbols", universe_id, len(syms))
        return syms

    scope = market_scope.scope_type.upper()
    if scope == "CUSTOM":
        syms = list(market_scope.custom_symbols) or list(kcfg.symbols)
        logger.info("Symbol source CUSTOM: %d symbols", len(syms))
        return syms
    if scope in ("A_ALL", "CSI_ALL"):
        return symbol_pool.refresh(kcfg.daily_dir, kcfg.symbols_cache_file)
    raise ValueError(f"Unsupported market_scope.scope_type for kline_full: {scope}")


def run_kline_full(market_scope: MarketScopeConfig,
                   data_cfg: DataConfig,
                   processing: ProcessingConfig,
                   kcfg: KlineIncrementalConfig,
                   storage_conn_str: str) -> None:
    """Full minute-bar back-fill (per-year) + daily-bar back-fill (one file/symbol)."""
    pg_conn = parse_pg_conn(storage_conn_str)
    minute_storage = MinuteParquetStorage(kcfg.minute_dir, pg_conn=pg_conn)
    daily_storage = DailyParquetStorage(kcfg.daily_dir)
    ch_storage = ClickHouseStorage(
        host=kcfg.clickhouse.host, port=kcfg.clickhouse.port,
        user=kcfg.clickhouse.user, password=kcfg.clickhouse.password,
        database=kcfg.clickhouse.database,
    )

    symbols = _build_symbols(market_scope, kcfg, data_cfg, storage_conn_str)
    logger.info("=== K-line full back-fill starting: %d symbols, years %d-%d ===",
                len(symbols), data_cfg.start_year, data_cfg.end_year)

    # Minute bars per-year
    for year in range(data_cfg.start_year, data_cfg.end_year + 1):
        start_dt = datetime(year, 1, 1, 0, 0, 0)
        end_dt = datetime(year, 12, 31, 23, 59, 59)
        for i, gm_symbol in enumerate(symbols):
            logger.info("[year=%d %d/%d] %s (minute)", year, i + 1, len(symbols), gm_symbol)
            try:
                _do_full_one(gm_symbol, FREQ_MINUTE, TABLE_1MIN,
                             start_dt, end_dt, year,
                             minute_storage, daily_storage, ch_storage,
                             is_minute=True)
            except Exception as ex:
                logger.error("FAILED minute %s %d: %s", gm_symbol, year, ex)
            if processing.delay_between_requests > 0:
                time.sleep(processing.delay_between_requests / 1000.0)

    # Daily bars all years in one call
    start_dt = datetime(data_cfg.start_year, 1, 1, 0, 0, 0)
    end_dt = datetime(data_cfg.end_year, 12, 31, 23, 59, 59)
    for i, gm_symbol in enumerate(symbols):
        logger.info("[daily %d/%d] %s", i + 1, len(symbols), gm_symbol)
        try:
            _do_full_one(gm_symbol, FREQ_DAILY, TABLE_DAILY,
                         start_dt, end_dt, None,
                         minute_storage, daily_storage, ch_storage,
                         is_minute=False)
        except Exception as ex:
            logger.error("FAILED daily %s: %s", gm_symbol, ex)
        if processing.delay_between_requests > 0:
            time.sleep(processing.delay_between_requests / 1000.0)


def _do_full_one(gm_symbol: str, freq: str, table: str,
                 start_dt: datetime, end_dt: datetime, year,
                 minute_storage, daily_storage, ch_storage,
                 is_minute: bool) -> None:
    bars = gm_api.history_bars(gm_symbol, freq, start_dt, end_dt)
    if not bars:
        logger.info("%s/%s %s: 0 bars", freq, gm_symbol, year or "")
        return

    ts_code = gm_to_ts_code(gm_symbol)
    if is_minute:
        # Year was provided by caller; in case bars cross years, group for safety.
        by_year: dict[int, List[dict]] = {}
        for b in bars:
            bob = b["bob"]
            y = bob.year if hasattr(bob, "year") else bob.date().year
            by_year.setdefault(y, []).append(b)
        for y, grp in by_year.items():
            minute_storage.save_bars(gm_symbol, y, grp)
    else:
        daily_storage.save_bars_all(gm_symbol, bars)

    # CH delete-then-insert for the full window
    ch_from = min(b["bob"] for b in bars)
    ch_to = max(b["bob"] for b in bars)
    try:
        ch_storage.delete_range(table, ts_code, ch_from, ch_to)
        ch_storage.insert_bars(table, bars, ts_code)
    except Exception as ex:
        logger.warning("%s/%s CH write failed: %s", freq, ts_code, ex)
