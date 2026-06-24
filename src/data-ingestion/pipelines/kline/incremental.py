"""Adaptive-window incremental k-line update.

Mirrors C# `KlineIncrementalService.RunIncrementalAsync`:
- Per-frequency lookback window (minute / daily separately)
- Per-symbol gap check vs `max_gap_days`; skip if exceeded
- Per-symbol error tolerance; one bad symbol doesn't abort the pool
- Idempotent writes: Parquet (read-merge-dedupe-rewrite) + ClickHouse (DELETE-then-INSERT)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List

from sources import gm_api
from storage.clickhouse import (
    ClickHouseStorage,
    TABLE_1MIN,
    TABLE_DAILY,
)
from storage.parquet import gm_to_ts_code, MinuteParquetStorage, DailyParquetStorage
from config import KlineIncrementalConfig, parse_pg_conn

logger = logging.getLogger(__name__)

FREQ_MINUTE = "60s"
FREQ_DAILY = "1d"


@dataclass
class KlineSummary:
    started_at: datetime = None
    completed_at: datetime = None
    total_symbols: int = 0
    processed_symbols: int = 0
    skipped_gap_too_large: int = 0
    minute_bars_added: int = 0
    daily_bars_added: int = 0
    errors: list = field(default_factory=list)


def load_symbols(kcfg: KlineIncrementalConfig) -> List[str]:
    """CUSTOM vs CSI_ALL with optional in-process filter (mirrors C# LoadKlineSymbols)."""
    if kcfg.symbol_source.upper() == "CUSTOM":
        syms = list(kcfg.symbol_filter) if kcfg.symbol_filter else list(kcfg.symbols)
        logger.info("Symbol source CUSTOM: %d symbols", len(syms))
        return syms

    from core import symbol_pool
    syms = symbol_pool.refresh(kcfg.daily_dir, kcfg.symbols_cache_file)
    if kcfg.symbol_filter and kcfg.symbol_source.upper() == "CSI_ALL":
        allowed = set(kcfg.symbol_filter)
        syms = [s for s in syms if s in allowed]
        logger.info("Applied symbol_filter: %d symbols remaining", len(syms))
    return syms


def run_incremental(kcfg: KlineIncrementalConfig,
                    pg_conn_str: str,
                    symbols: List[str]) -> KlineSummary:
    """Main incremental entry point. Returns a summary dataclass."""
    pg_conn = parse_pg_conn(pg_conn_str)
    minute_storage = MinuteParquetStorage(kcfg.minute_dir, pg_conn=pg_conn)
    daily_storage = DailyParquetStorage(kcfg.daily_dir)
    ch_storage = ClickHouseStorage(
        host=kcfg.clickhouse.host, port=kcfg.clickhouse.port,
        user=kcfg.clickhouse.user, password=kcfg.clickhouse.password,
        database=kcfg.clickhouse.database,
    )

    pool = sorted(symbols)
    logger.info("=== K-line incremental starting: %d symbols ===", len(pool))
    logger.info("Windows: minute=%dd, daily=%dd, buffer=%d, max_gap=%d",
                kcfg.minute_lookback_days, kcfg.daily_lookback_days,
                kcfg.safety_buffer_days, kcfg.max_gap_days)

    summary = KlineSummary(started_at=datetime.utcnow(), total_symbols=len(pool))
    now = datetime.now()

    for i, symbol in enumerate(pool):
        logger.info("[%d/%d] Processing %s", i + 1, len(pool), symbol)
        try:
            _process_symbol(kcfg, minute_storage, daily_storage, ch_storage, symbol, now, summary)
            summary.processed_symbols += 1
        except Exception as ex:
            summary.errors.append((symbol, str(ex)))
            logger.warning("FAILED %s: %s", symbol, ex)

        if kcfg.request_delay_ms > 0:
            time.sleep(kcfg.request_delay_ms / 1000.0)

    summary.completed_at = datetime.utcnow()
    logger.info(
        "=== K-line incremental done: processed=%d, skipped_gap=%d, "
        "minute_bars_added=%d, daily_bars_added=%d, errors=%d, duration=%.1fs ===",
        summary.processed_symbols, summary.skipped_gap_too_large,
        summary.minute_bars_added, summary.daily_bars_added, len(summary.errors),
        (summary.completed_at - summary.started_at).total_seconds(),
    )
    return summary


def _process_symbol(kcfg, minute_storage, daily_storage, ch_storage,
                    gm_symbol: str, now: datetime, summary: KlineSummary) -> None:
    # Minute
    _fetch_and_apply(kcfg, minute_storage, daily_storage, ch_storage,
                     table=TABLE_1MIN, gm_symbol=gm_symbol, freq=FREQ_MINUTE,
                     lookback_days=kcfg.minute_lookback_days, now=now,
                     summary=summary, is_minute=True)
    # Daily
    _fetch_and_apply(kcfg, minute_storage, daily_storage, ch_storage,
                     table=TABLE_DAILY, gm_symbol=gm_symbol, freq=FREQ_DAILY,
                     lookback_days=kcfg.daily_lookback_days, now=now,
                     summary=summary, is_minute=False)


def _fetch_and_apply(kcfg, minute_storage, daily_storage, ch_storage,
                     table: str, gm_symbol: str, freq: str,
                     lookback_days: int, now: datetime,
                     summary: KlineSummary, is_minute: bool) -> None:
    ts_code = gm_to_ts_code(gm_symbol)

    last_bar = None
    try:
        last_bar = ch_storage.get_last_bar_time(table, ts_code)
    except Exception as ex:
        logger.warning("CH GetLastBarTime failed for %s/%s; falling back to first-time window: %s",
                       table, ts_code, ex)

    if last_bar is None:
        from_dt = now.date() - timedelta(days=lookback_days * 2 + kcfg.safety_buffer_days)
        from_dt = datetime.combine(from_dt, datetime.min.time())
        logger.info("%s/%s: first-time fetch, from=%s", freq, ts_code, from_dt)
    else:
        gap_days = (now.date() - last_bar.date()).days
        if gap_days > kcfg.max_gap_days:
            logger.warning("%s/%s: gap %dd exceeds max_gap_days=%d; skipping (requires full back-fill)",
                           freq, ts_code, gap_days, kcfg.max_gap_days)
            summary.skipped_gap_too_large += 1
            return
        from_dt = last_bar - timedelta(days=kcfg.safety_buffer_days)
        logger.info("%s/%s: last_bar=%s, gap=%dd, from=%s",
                    freq, ts_code, last_bar, gap_days, from_dt)

    # Fetch with retry
    bars: List[dict] = []
    retries = 0
    while retries <= kcfg.retry_count:
        try:
            bars = gm_api.history_bars(gm_symbol, freq, from_dt, now)
            break
        except Exception as ex:
            retries += 1
            if retries > kcfg.retry_count:
                summary.errors.append((ts_code, f"{freq} GM fetch: {ex}"))
                logger.warning("%s/%s GM fetch failed after %d attempts: %s",
                               freq, ts_code, retries, ex)
                return
            time.sleep(max(0.5, kcfg.request_delay_ms / 1000.0))

    if not bars:
        logger.info("%s/%s: GM returned 0 bars in [%s, %s] (likely delisted or pre-IPO)",
                    freq, ts_code, from_dt, now)
        return

    # 1. Parquet append (idempotent)
    if is_minute:
        # Group by year
        by_year: dict[int, List[dict]] = {}
        for b in bars:
            bob = b["bob"]
            year = bob.year if hasattr(bob, "year") else bob.date().year
            by_year.setdefault(year, []).append(b)
        net_new = 0
        for year, grp in by_year.items():
            _, added = minute_storage.append_bars(gm_symbol, year, grp)
            net_new += added
        summary.minute_bars_added += net_new
    else:
        _, net_new = daily_storage.append_bars_all(gm_symbol, bars)
        summary.daily_bars_added += net_new
    logger.info("%s/%s: GM fetched %d, net new parquet rows %d",
                freq, ts_code, len(bars), net_new)

    # 2. ClickHouse delete-then-insert (idempotent)
    ch_from = min(b["bob"] for b in bars)
    ch_to = max(b["bob"] for b in bars)
    try:
        ch_storage.delete_range(table, ts_code, ch_from, ch_to)
        ch_storage.insert_bars(table, bars, ts_code)
    except Exception as ex:
        summary.errors.append((ts_code, f"{freq} CH write: {ex}"))
        logger.warning("%s/%s CH write failed (Parquet already updated): %s",
                       freq, ts_code, ex)
