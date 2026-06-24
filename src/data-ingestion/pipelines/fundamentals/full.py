"""Full fundamentals back-fill via time-series APIs (one symbol's full history per call).

Mirrors C# `FundamentalsIngestor.Run`. For each symbol in the pool, sequentially
ingests all 8 tables, batching fields per API call. Idempotent and resumable
via `public.fundamentals_ingestion_progress`.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List

from sources import gm_api
from core import symbol_pool
from core.schema import (
    FundTableSpec,
    TableKind,
    TABLES,
    batch,
)
from pipelines.fundamentals.merge import merge_batches as _merge_batches
from storage.postgres import PostgresStorage
from config import (
    FundamentalsConfig,
    parse_pg_conn,
)

logger = logging.getLogger(__name__)


# Dispatch tables for time-series APIs.
_TS_QUARTERLY = {
    "balance": gm_api.stk_balance,
    "cashflow": gm_api.stk_cashflow,
    "income": gm_api.stk_income,
    "prime": gm_api.stk_prime,
    "deriv": gm_api.stk_deriv,
}
_TS_DAILY = {
    "valuation": gm_api.stk_valuation,
    "mktvalue": gm_api.stk_mktvalue,
    "basic": gm_api.stk_basic,
}


def run_fundamentals_full(cfg, fcfg: FundamentalsConfig) -> None:
    pg_conn = parse_pg_conn(cfg.storage.connection_string)
    storage = PostgresStorage(pg_conn)
    storage.ensure_schema()
    _ensure_progress(pg_conn)

    # Build symbol pool
    if fcfg.symbol_source.upper() == "CUSTOM":
        symbols = list(fcfg.symbols)
    else:
        symbols = symbol_pool.refresh(fcfg.daily_dir, fcfg.symbols_cache_file)

    start_date = fcfg.start_date or "2005-01-01"
    end_date = fcfg.end_date or ""
    logger.info("=== Fundamentals ingestion starting ===")
    logger.info("Start=%s End=%s DelayMs=%d RptType=%d DataType=%d",
                start_date, end_date or "(latest)", fcfg.request_delay_ms,
                fcfg.rpt_type, fcfg.data_type)
    logger.info("Symbol pool size: %d", len(symbols))

    pool = sorted(symbols)
    processed = 0
    started_at = datetime.utcnow()

    for i, symbol in enumerate(pool):
        if fcfg.symbol_filter and symbol not in fcfg.symbol_filter:
            continue

        for spec in TABLES:
            if _is_completed(pg_conn, symbol, spec.table_name):
                continue

            retries = 0
            success = False
            while not success and retries <= fcfg.retry_count:
                try:
                    rows = _ingest_one_table_ts(
                        symbol, spec, start_date, end_date,
                        rpt_type=fcfg.rpt_type, data_type=fcfg.data_type,
                        request_delay_ms=fcfg.request_delay_ms,
                    )
                    written = storage.upsert_rows(spec, rows) if rows else 0
                    _update_progress(pg_conn, symbol, spec.table_name, "completed", written)
                    success = True
                except Exception as ex:
                    retries += 1
                    logger.warning("Failed %s/%s (attempt %d/%d): %s",
                                   symbol, spec.table_name, retries, fcfg.retry_count, ex)
                    if retries > fcfg.retry_count:
                        _update_progress(pg_conn, symbol, spec.table_name, "error", 0, str(ex)[:500])
                    else:
                        time.sleep(max(0.5, fcfg.request_delay_ms / 1000.0))

            if fcfg.request_delay_ms > 0:
                time.sleep(fcfg.request_delay_ms / 1000.0)

        processed += 1
        if i % 20 == 0 or i == len(pool) - 1:
            elapsed = datetime.utcnow() - started_at
            rate = elapsed.total_seconds() / (i + 1) if i else 0
            logger.info("[%d/%d] %s done — elapsed %.0fs",
                        i + 1, len(pool), symbol, elapsed.total_seconds())
            if rate > 0:
                eta = (len(pool) - i - 1) * rate
                logger.info("  ETA ~%.0fs", eta)

    logger.info("=== Fundamentals ingestion finished — %d symbols processed ===", processed)


def _ingest_one_table_ts(symbol: str, spec: FundTableSpec,
                         start_date: str, end_date: str,
                         rpt_type: int, data_type: int,
                         request_delay_ms: int) -> List[dict]:
    """Time-series call for one (symbol, table). Field-batched internally."""
    batches = batch(list(spec.fields))
    merged: List[dict] = []

    for batch_idx, field_batch in enumerate(batches):
        fields_csv = ",".join(field_batch)
        if spec.kind == TableKind.Quarterly:
            fn = _TS_QUARTERLY[spec.method.value]
            rows = fn(symbol, fields_csv, rpt_type, data_type, start_date, end_date)
        else:
            fn = _TS_DAILY[spec.method.value]
            rows = fn(symbol, fields_csv, start_date, end_date)

        if batch_idx == 0:
            merged.extend(rows)
        else:
            _merge_batches(merged, rows, spec)

        if request_delay_ms > 0:
            time.sleep(request_delay_ms / 1000.0)

    return merged


# ------------------------- Progress tracker -------------------------

def _ensure_progress(pg_conn: dict) -> None:
    import psycopg2
    with psycopg2.connect(**pg_conn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.fundamentals_ingestion_progress (
                    symbol VARCHAR(20) NOT NULL,
                    table_name VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    rows_written INTEGER DEFAULT 0,
                    last_attempt TIMESTAMP,
                    error_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (symbol, table_name)
                );
            """)
        conn.commit()


def _is_completed(pg_conn: dict, symbol: str, table_name: str) -> bool:
    import psycopg2
    with psycopg2.connect(**pg_conn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT status FROM public.fundamentals_ingestion_progress
                WHERE symbol = %s AND table_name = %s;
            """, (symbol, table_name))
            row = cur.fetchone()
    return bool(row and row[0] == "completed")


def _update_progress(pg_conn: dict, symbol: str, table_name: str,
                    status: str, rows_written: int,
                    error_msg: str = None) -> None:
    import psycopg2
    with psycopg2.connect(**pg_conn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO public.fundamentals_ingestion_progress
                    (symbol, table_name, status, rows_written, last_attempt,
                     error_count, last_error)
                VALUES (%(sym)s, %(tbl)s, %(status)s, %(rows)s,
                        CURRENT_TIMESTAMP, 0, %(err)s)
                ON CONFLICT (symbol, table_name) DO UPDATE SET
                    status = EXCLUDED.status,
                    rows_written = EXCLUDED.rows_written,
                    last_attempt = EXCLUDED.last_attempt,
                    last_error = EXCLUDED.last_error,
                    updated_at = CURRENT_TIMESTAMP;
            """, {
                "sym": symbol, "tbl": table_name, "status": status,
                "rows": rows_written, "err": error_msg,
            })
        conn.commit()
