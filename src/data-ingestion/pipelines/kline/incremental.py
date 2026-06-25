"""Adaptive-window incremental k-line update.

Mirrors C# `KlineIncrementalService.RunIncrementalAsync`:
- Per-frequency lookback window (minute / daily separately)
- Per-symbol gap check vs `max_gap_days`; skip if exceeded
- Per-symbol error tolerance; one bad symbol doesn't abort the pool
- Idempotent writes: Parquet (read-merge-dedupe-rewrite) + ClickHouse (DELETE-then-INSERT)

Performance mode (default):
- GM `history()` accepts `symbol: str|List`, so minute/daily are fetched
  in batches of BATCH_SIZE symbols per call. Auto-halves on status 1029
  ('query result too large'). Falls back to per-symbol mode if a batch
  fails with a non-1029 error.
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

# Default batch size for GM history() calls.
# 100 fits a 3-day minute-bar window comfortably (well under GM's 1029 limit).
# Auto-halves on status 1029 ('query result too large').
BATCH_SIZE = 100


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
    logger.info("=== K-line incremental starting: %d symbols (batch mode, size=%d) ===",
                len(pool), BATCH_SIZE)
    logger.info("Windows: minute=%dd, daily=%dd, buffer=%d, max_gap=%d",
                kcfg.minute_lookback_days, kcfg.daily_lookback_days,
                kcfg.safety_buffer_days, kcfg.max_gap_days)

    summary = KlineSummary(started_at=datetime.utcnow(), total_symbols=len(pool))
    now = datetime.now()

    # ---------- Phase 1: plan per-symbol from_dt (CH queries only, no GM) ----------
    plan = _plan_symbols(kcfg, ch_storage, pool, now, summary)
    active = [s for s in pool if s in plan]
    logger.info("Plan: %d active, %d skipped (gap too large or no work)",
                len(active), len(pool) - len(active))

    # ---------- Phase 2: batch GM fetch + per-symbol writes ----------
    for batch_start in range(0, len(active), BATCH_SIZE):
        batch = active[batch_start:batch_start + BATCH_SIZE]
        batch_no = batch_start // BATCH_SIZE + 1
        total_batches = (len(active) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info("Batch %d/%d: %d symbols", batch_no, total_batches, len(batch))
        _process_batch(kcfg, minute_storage, daily_storage, ch_storage,
                       batch, plan, now, summary)

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


# ============================================================
# Phase 1: per-symbol planning
# ============================================================

def _plan_symbols(kcfg, ch_storage, pool, now, summary) -> dict:
    """Pre-compute `from_dt` per (symbol, freq).

    Returns: {gm_symbol: {'minute': dt|None, 'daily': dt|None}}
    Symbols with both None or gap > max_gap_days are excluded.
    """
    plan = {}
    for symbol in pool:
        ts_code = gm_to_ts_code(symbol)
        entry = {}

        for freq, table, lookback, key in [
            (FREQ_MINUTE, TABLE_1MIN, kcfg.minute_lookback_days, "minute"),
            (FREQ_DAILY, TABLE_DAILY, kcfg.daily_lookback_days, "daily"),
        ]:
            from_dt = _compute_from_dt(kcfg, ch_storage, table, ts_code,
                                       symbol, freq, lookback, now, summary)
            if from_dt is not None:
                entry[key] = from_dt

        if entry:
            plan[symbol] = entry
    return plan


def _compute_from_dt(kcfg, ch_storage, table, ts_code, gm_symbol, freq,
                     lookback_days, now, summary):
    """Return from_dt if work needed, None if skip."""
    last_bar = None
    try:
        last_bar = ch_storage.get_last_bar_time(table, ts_code)
    except Exception as ex:
        logger.warning("CH GetLastBarTime failed for %s/%s; falling back to first-time window: %s",
                       table, ts_code, ex)

    if last_bar is None:
        from_dt = now.date() - timedelta(days=lookback_days * 2 + kcfg.safety_buffer_days)
        return datetime.combine(from_dt, datetime.min.time())

    gap_days = (now.date() - last_bar.date()).days
    if gap_days > kcfg.max_gap_days:
        logger.warning("%s/%s: gap %dd exceeds max_gap_days=%d; skipping",
                       freq, ts_code, gap_days, kcfg.max_gap_days)
        summary.skipped_gap_too_large += 1
        return None

    return last_bar - timedelta(days=kcfg.safety_buffer_days)


# ============================================================
# Phase 2: batch processing
# ============================================================

def _process_batch(kcfg, minute_storage, daily_storage, ch_storage,
                   batch_symbols, plan, now, summary) -> None:
    """Process a batch of symbols: batch GM fetch + per-symbol writes."""
    # Minute frequency
    _process_batch_freq(
        kcfg, minute_storage, daily_storage, ch_storage,
        batch_symbols, plan, now, summary,
        freq=FREQ_MINUTE, table=TABLE_1MIN, plan_key="minute", is_minute=True,
    )
    # Daily frequency
    _process_batch_freq(
        kcfg, minute_storage, daily_storage, ch_storage,
        batch_symbols, plan, now, summary,
        freq=FREQ_DAILY, table=TABLE_DAILY, plan_key="daily", is_minute=False,
    )

    # Count processed (each symbol processed once, regardless of freq outcomes)
    for symbol in batch_symbols:
        summary.processed_symbols += 1


def _process_batch_freq(kcfg, minute_storage, daily_storage, ch_storage,
                        batch_symbols, plan, now, summary,
                        freq, table, plan_key, is_minute) -> None:
    """Fetch one frequency for the whole batch, then batch CH writes.

    Flow:
      1. ONE GM `history()` call → bars for all N symbols
      2. Per-symbol Parquet append (file-per-symbol, can't batch)
      3. ONE ClickHouse `ALTER TABLE DELETE` with OR clauses (batch delete)
      4. ONE ClickHouse `INSERT` with all rows (batch insert)
    """
    syms = [s for s in batch_symbols if plan.get(s, {}).get(plan_key)]
    if not syms:
        return

    batch_from = min(plan[s][plan_key] for s in syms)

    # ---- 1. GM batch fetch ----
    try:
        bars_by_sym = gm_api.history_bars_batch(syms, freq, batch_from, now)
    except Exception as ex:
        logger.warning("Batch %s GM fetch failed (%s); falling back to per-symbol",
                       freq, ex)
        _fallback_per_symbol(kcfg, minute_storage, daily_storage, ch_storage,
                             syms, plan, plan_key, freq, table,
                             is_minute, now, summary)
        return

    fetched_count = sum(len(v) for v in bars_by_sym.values())
    logger.info("%s batch: %d/%d symbols returned data, %d total bars",
                freq, len(bars_by_sym), len(syms), fetched_count)

    # ---- 2. Per-symbol Parquet + collect for batch CH ----
    bars_to_insert: dict[str, List[dict]] = {}
    ranges_to_delete: List[tuple] = []

    for symbol in syms:
        sym_from = plan[symbol][plan_key]
        raw = bars_by_sym.get(symbol, [])
        bars = [b for b in raw if b["bob"] >= sym_from]
        if not bars:
            logger.info("%s/%s: no bars in batch result (likely delisted/suspended)",
                        freq, gm_to_ts_code(symbol))
            continue

        ts_code = gm_to_ts_code(symbol)

        # Parquet write (per-symbol; file-per-symbol by design)
        try:
            net_new = _parquet_write(minute_storage, daily_storage,
                                     symbol, bars, is_minute, summary)
            logger.info("%s/%s: GM fetched %d, net new parquet rows %d",
                        freq, ts_code, len(bars), net_new)
        except Exception as ex:
            summary.errors.append((ts_code, f"{freq} parquet write: {ex}"))
            logger.warning("%s/%s parquet write failed: %s", freq, ts_code, ex)
            continue  # skip CH write for this symbol

        # Collect for batch CH
        bars_to_insert[ts_code] = bars
        ch_from = min(b["bob"] for b in bars)
        ch_to = max(b["bob"] for b in bars)
        ranges_to_delete.append((ts_code, ch_from, ch_to))

    if not bars_to_insert:
        logger.info("%s batch: nothing to write to CH", freq)
        return

    # ---- 3. Batch CH delete (single ALTER TABLE) ----
    try:
        ch_storage.delete_ranges_batch(table, ranges_to_delete)
    except Exception as ex:
        logger.warning("%s batch CH delete failed (%s); falling back to per-symbol",
                       freq, ex)
        for ts_code, ch_from, ch_to in ranges_to_delete:
            try:
                ch_storage.delete_range(table, ts_code, ch_from, ch_to)
            except Exception as ex2:
                summary.errors.append((ts_code, f"{freq} CH delete: {ex2}"))
                logger.warning("%s/%s CH delete failed: %s", freq, ts_code, ex2)

    # ---- 4. Batch CH insert (single INSERT) ----
    try:
        ch_storage.insert_bars_batch(table, bars_to_insert)
    except Exception as ex:
        logger.warning("%s batch CH insert failed (%s); falling back to per-symbol",
                       freq, ex)
        for ts_code, bars in bars_to_insert.items():
            try:
                ch_storage.insert_bars(table, bars, ts_code)
            except Exception as ex2:
                summary.errors.append((ts_code, f"{freq} CH insert: {ex2}"))
                logger.warning("%s/%s CH insert failed: %s", freq, ts_code, ex2)


def _parquet_write(minute_storage, daily_storage, gm_symbol, bars,
                   is_minute, summary) -> int:
    """Apply Parquet write for one symbol. Returns net new rows."""
    if is_minute:
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
        return net_new
    else:
        _, net_new = daily_storage.append_bars_all(gm_symbol, bars)
        summary.daily_bars_added += net_new
        return net_new


def _write_bars(minute_storage, daily_storage, ch_storage,
                table, gm_symbol, bars, is_minute, summary, freq) -> None:
    """Apply Parquet + ClickHouse writes for one symbol's bars (idempotent)."""
    ts_code = gm_to_ts_code(gm_symbol)

    # 1. Parquet append
    if is_minute:
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

    # 2. ClickHouse delete-then-insert
    ch_from = min(b["bob"] for b in bars)
    ch_to = max(b["bob"] for b in bars)
    try:
        ch_storage.delete_range(table, ts_code, ch_from, ch_to)
        ch_storage.insert_bars(table, bars, ts_code)
    except Exception as ex:
        summary.errors.append((ts_code, f"{freq} CH write: {ex}"))
        logger.warning("%s/%s CH write failed (Parquet already updated): %s",
                       freq, ts_code, ex)


# ============================================================
# Fallback: per-symbol mode (used when batch fails for non-1029 reasons)
# ============================================================

def _fallback_per_symbol(kcfg, minute_storage, daily_storage, ch_storage,
                         syms, plan, plan_key, freq, table,
                         is_minute, now, summary) -> None:
    """Fetch each symbol individually; isolated failures."""
    for symbol in syms:
        sym_from = plan[symbol][plan_key]
        retries = 0
        bars: List[dict] = []
        while retries <= kcfg.retry_count:
            try:
                bars = gm_api.history_bars(symbol, freq, sym_from, now)
                break
            except Exception as ex:
                retries += 1
                if retries > kcfg.retry_count:
                    ts_code = gm_to_ts_code(symbol)
                    summary.errors.append((ts_code, f"{freq} fallback fetch: {ex}"))
                    logger.warning("%s/%s fallback fetch failed after %d attempts: %s",
                                   freq, ts_code, retries, ex)
                    break
                time.sleep(max(0.5, kcfg.request_delay_ms / 1000.0))

        if not bars:
            continue

        try:
            _write_bars(minute_storage, daily_storage, ch_storage,
                        table, symbol, bars, is_minute, summary, freq)
        except Exception as ex:
            ts_code = gm_to_ts_code(symbol)
            summary.errors.append((ts_code, f"{freq} write: {ex}"))
            logger.warning("%s/%s write failed: %s", freq, ts_code, ex)
