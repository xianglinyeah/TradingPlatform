"""Fundamentals incremental update via the multi-symbol point-in-time APIs.

Mirrors C# `FundamentalsIngestor.RunIncrementalPt`. Each Pt call returns
the entire symbol universe for one date — ~50-100x faster than per-symbol
incremental.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Optional

from sources import gm_api
from core.schema import (
    FundTableSpec,
    TableKind,
    TABLES,
    PREFLIGHT_MIN_COUNTS,
    batch,
)
from pipelines.fundamentals.merge import merge_batches as _merge_batches
from storage.postgres import PostgresStorage
from config import (
    FundamentalsIncrementalConfig,
    parse_pg_conn,
)

logger = logging.getLogger(__name__)


# Dispatch tables for the 8 Pt API methods.
_PT_QUARTERLY: dict = {
    "balance": gm_api.stk_balance_pt,
    "cashflow": gm_api.stk_cashflow_pt,
    "income": gm_api.stk_income_pt,
    "prime": gm_api.stk_prime_pt,
    "deriv": gm_api.stk_deriv_pt,
}
_PT_DAILY: dict = {
    "valuation": gm_api.stk_valuation_pt,
    "mktvalue": gm_api.stk_mktvalue_pt,
    "basic": gm_api.stk_basic_pt,
}


@dataclass
class IncrementalSummary:
    processed: int = 0
    rows_upserted: int = 0
    error_count: int = 0
    errors: list = field(default_factory=list)
    started_at: datetime = None
    completed_at: datetime = None
    daily_window_days: int = 0
    quarterly_window_days: int = 0
    gap_days: int = 0


def run_fundamentals_incremental_pt(cfg, fcfg: FundamentalsIncrementalConfig) -> IncrementalSummary:
    log = logging.getLogger("data_ingestion.fundamentals")
    pg_conn = parse_pg_conn(cfg.storage.connection_string)
    storage = PostgresStorage(pg_conn)
    storage.ensure_schema()

    # Preflight safety check
    _preflight(storage)

    # Build symbol pool (force-refresh cache for IPOs).
    if fcfg.symbol_source.upper() == "CUSTOM":
        symbols = list(fcfg.symbol_filter) if fcfg.symbol_filter else list(fcfg.symbols)
        log.info("Symbol source CUSTOM: %d symbols", len(symbols))
    else:
        from core import symbol_pool
        symbols = symbol_pool.refresh(fcfg.daily_dir, fcfg.symbols_cache_file)

    today = date.today()
    last_run = storage.get_last_successful_run_time()

    if last_run is None:
        gap_days = 0
        actual_daily = fcfg.daily_lookback_days
        actual_quarterly = fcfg.quarterly_lookback_days
        log.info("[Pt] First-ever incremental run, using configured windows: daily=%d, quarterly=%d",
                 actual_daily, actual_quarterly)
    else:
        gap_days = (today - last_run.date()).days
        if gap_days > fcfg.max_gap_days:
            msg = (f"[Pt] Refuse to run incremental: gap {gap_days} days exceeds "
                   f"max_gap_days={fcfg.max_gap_days}.")
            log.error(msg)
            raise RuntimeError(msg)
        actual_daily = max(fcfg.daily_lookback_days, gap_days + fcfg.safety_buffer_days)
        actual_quarterly = max(fcfg.quarterly_lookback_days, gap_days + fcfg.safety_buffer_days)
        log.info("[Pt] Last run: %s, gap: %dd, windows: daily=%d, quarterly=%d",
                 last_run, gap_days, actual_daily, actual_quarterly)

    run_id = storage.start_run(
        "incremental_pt", actual_daily, actual_quarterly,
        gap_days if gap_days > 0 else None,
    )

    try:
        summary = _run_core(symbols, actual_daily, actual_quarterly,
                            rpt_type=fcfg.rpt_type, data_type=fcfg.data_type,
                            retry_count=fcfg.retry_count,
                            request_delay_ms=fcfg.request_delay_ms,
                            symbol_filter=fcfg.symbol_filter,
                            storage=storage)
        summary.gap_days = gap_days
        storage.complete_run(run_id, "completed", summary.processed,
                             summary.rows_upserted, summary.error_count)
        _log_summary("Incremental(Pt)", summary)
        return summary
    except Exception as ex:
        msg = str(ex)[:2000]
        storage.complete_run(run_id, "failed", 0, 0, 0, msg)
        raise


def _run_core(symbols: List[str],
              daily_lookback: int,
              quarterly_lookback: int,
              rpt_type: int,
              data_type: int,
              retry_count: int,
              request_delay_ms: int,
              symbol_filter: List[str],
              storage: PostgresStorage) -> IncrementalSummary:
    log = logging.getLogger("data_ingestion.fundamentals")

    symbols_list = sorted(symbols)
    if symbol_filter:
        symbols_list = sorted(set(symbol_filter))
        log.info("[Pt] In-process symbol filter active: %d symbols", len(symbols_list))
    symbols_csv = ",".join(symbols_list)

    today = date.today()
    started_at = datetime.utcnow()
    total_rows = 0
    error_count = 0
    total_calls = 0
    errors: list = []

    total_dates = max(daily_lookback, quarterly_lookback)
    log.info("[Pt] Core starting: %d symbols × %d dates (daily≤%d, quarterly≤%d)",
             len(symbols_list), total_dates, daily_lookback, quarterly_lookback)

    # Use a single mutable counter list shared across calls (Python closures over
    # the list reference; int itself is immutable so re-assigning wouldn't propagate).
    counters = [0, 0]  # [total_calls, error_count]

    for day_offset in range(1, total_dates + 1):
        d = today - timedelta(days=day_offset)
        date_str = d.strftime("%Y-%m-%d")
        do_daily = day_offset <= daily_lookback
        do_quarterly = day_offset <= quarterly_lookback

        for spec in TABLES:
            is_daily_kind = spec.kind == TableKind.Daily
            if is_daily_kind and not do_daily:
                continue
            if not is_daily_kind and not do_quarterly:
                continue

            rows = _ingest_one_table_pt(
                symbols_csv, spec, date_str,
                rpt_type=rpt_type, data_type=data_type,
                retry_count=retry_count,
                request_delay_ms=request_delay_ms,
                counters=counters,
                errors=errors,
            )
            if rows:
                total_rows += storage.upsert_rows(spec, rows)

        log.info("[Pt] day -%d (%s) done — %d rows upserted, %d calls, %d errors",
                 day_offset, date_str, total_rows, counters[0], counters[1])

    total_calls = counters[0]
    error_count = counters[1]
    log.info("[Pt] Core finished: %d rows upserted, %d API calls, %d errors",
             total_rows, total_calls, error_count)

    return IncrementalSummary(
        processed=len(symbols_list),
        rows_upserted=total_rows,
        error_count=error_count,
        errors=errors,
        started_at=started_at,
        completed_at=datetime.utcnow(),
        daily_window_days=daily_lookback,
        quarterly_window_days=quarterly_lookback,
    )


def _ingest_one_table_pt(symbols_csv: str,
                         spec: FundTableSpec,
                         date_str: str,
                         rpt_type: int,
                         data_type: int,
                         retry_count: int,
                         request_delay_ms: int,
                         counters: list,
                         errors: list) -> List[dict]:
    """Fetch one table for one date, batching fields ≤20 per call.
    Returns merged rows ready for `PostgresStorage.upsert_rows`.

    `counters` is a 2-element list `[total_calls, error_count]` mutated in place
    so the caller's accumulators stay consistent across invocations.
    """
    log = logging.getLogger("data_ingestion.fundamentals")

    batches = batch(list(spec.fields))
    merged: List[dict] = []

    for batch_idx, field_batch in enumerate(batches):
        fields_csv = ",".join(field_batch)
        retries = 0
        while retries <= retry_count:
            try:
                if spec.kind == TableKind.Quarterly:
                    fn = _PT_QUARTERLY[spec.method.value]
                    rows = fn(symbols_csv, fields_csv, rpt_type, data_type, date_str)
                else:
                    fn = _PT_DAILY[spec.method.value]
                    rows = fn(symbols_csv, fields_csv, date_str)
                counters[0] += 1

                if batch_idx == 0:
                    merged.extend(rows)
                else:
                    _merge_batches(merged, rows, spec)
                break
            except Exception as ex:
                retries += 1
                if retries > retry_count:
                    counters[1] += 1
                    errors.append(("ALL", spec.table_name, str(ex)))
                    log.warning("[Pt] FAILED %s/%s: %s", spec.table_name, date_str, ex)
                else:
                    time.sleep(max(0.5, request_delay_ms / 1000.0))

        if request_delay_ms > 0:
            time.sleep(request_delay_ms / 1000.0)

    return merged


def _preflight(storage: PostgresStorage) -> None:
    for spec in TABLES:
        try:
            count = storage.get_table_count(spec.table_name)
        except Exception as ex:
            raise RuntimeError(
                f"Preflight FAILED: cannot read fundamentals.{spec.table_name} ({ex}). "
                "Aborting to prevent full re-download."
            )
        if count == 0:
            raise RuntimeError(
                f"Preflight FAILED: fundamentals.{spec.table_name} is empty. "
                "Aborting to prevent full re-download."
            )
        min_count = PREFLIGHT_MIN_COUNTS.get(spec.table_name, 0)
        if count < min_count:
            raise RuntimeError(
                f"Preflight FAILED: fundamentals.{spec.table_name} count {count} "
                f"below safe threshold {min_count}. Aborting to prevent full re-download."
            )
    logger.info("Preflight safety check passed: all 8 fundamentals tables non-empty and above thresholds")


def _log_summary(label: str, s: IncrementalSummary) -> None:
    logger.info("%s summary: processed=%d rows_upserted=%d errors=%d daily_window=%d quarterly_window=%d gap_days=%d",
                label, s.processed, s.rows_upserted, s.error_count,
                s.daily_window_days, s.quarterly_window_days, s.gap_days)
    if s.errors:
        logger.warning("%s completed with %d errors; first few:", label, len(s.errors))
        for e in s.errors[:10]:
            logger.warning("  %s/%s: %s", e[0], e[1], e[2])
