"""PostgreSQL storage for the fundamentals schema (psycopg2).

Mirrors C# `FundamentalsStorageService`:
- `ensure_schema()` creates schema, 8 tables, indexes, run_log, progress.
- `upsert_rows(spec, rows)` — idempotent UPSERT in a single tx.
- run_log lifecycle (`start_run` / `complete_run` / `get_last_successful_run_time`).
- `get_table_count(table)` for preflight.
- `get_last_successful_run_time()` for incremental gap computation.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import psycopg2

from core.schema import FundTableSpec, TableKind, TABLES

logger = logging.getLogger(__name__)


def _parse_double(raw) -> Optional[float]:
    """GM SDK returns field values as strings/None; convert to float or None.
    Empty / 'nan' / '--' / '-' → None. Invalid → None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            f = float(raw)
            return f if f == f else None  # filter NaN
        except (TypeError, ValueError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    sl = s.lower()
    if sl in ("nan", "null", "--", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


class PostgresStorage:
    """PostgreSQL storage for the fundamentals schema (8 tables + run_log + progress)."""

    def __init__(self, pg_conn: dict):
        self.pg_conn = pg_conn

    # ------------------------- Schema -------------------------

    def ensure_schema(self) -> None:
        with psycopg2.connect(**self.pg_conn) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE SCHEMA IF NOT EXISTS fundamentals;")
                for spec in TABLES:
                    self._create_table(cur, spec)
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
                    CREATE INDEX IF NOT EXISTS idx_fund_progress_status
                        ON public.fundamentals_ingestion_progress(status);
                """)
                self._ensure_run_log(cur)
            conn.commit()
        logger.info("Fundamentals schema and %d tables ensured", len(TABLES))

    def _ensure_run_log(self, cur) -> None:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.fundamentals_run_log (
                run_id BIGSERIAL PRIMARY KEY,
                run_mode VARCHAR(20) NOT NULL,
                started_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                symbols_processed INT,
                rows_upserted INT,
                error_count INT DEFAULT 0,
                daily_window_days INT,
                quarterly_window_days INT,
                gap_days INT,
                status VARCHAR(20) NOT NULL,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fund_runlog_status_started
                ON public.fundamentals_run_log(status, started_at DESC);
        """)

    def _create_table(self, cur, spec: FundTableSpec) -> None:
        cols = [
            "symbol VARCHAR(20) NOT NULL",
            "pub_date TIMESTAMP",
            "rpt_date TIMESTAMP",
            "trade_date DATE",
            "rpt_type SMALLINT",
            "data_type SMALLINT",
        ]
        cols.extend(f"{f} DOUBLE PRECISION" for f in spec.fields)
        cols.append("updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

        if spec.kind == TableKind.Quarterly:
            pk = ("(symbol, rpt_date, data_type)" if spec.returns_rpt_type
                  else "(symbol, rpt_date)")
        else:
            pk = "(symbol, trade_date)"

        sql = f"CREATE TABLE IF NOT EXISTS fundamentals.{spec.table_name} ({', '.join(cols)}, PRIMARY KEY {pk});"
        cur.execute(sql)

        idx = f"idx_{spec.table_name}"
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {idx}_symbol ON fundamentals.{spec.table_name}(symbol);"
        )
        if spec.kind == TableKind.Quarterly:
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {idx}_rpt ON fundamentals.{spec.table_name}(rpt_date);"
            )
        else:
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {idx}_trade ON fundamentals.{spec.table_name}(trade_date);"
            )

    # ------------------------- Run log -------------------------

    def start_run(self, mode: str, daily_window: int, quarterly_window: int,
                  gap_days: Optional[int]) -> int:
        with psycopg2.connect(**self.pg_conn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.fundamentals_run_log
                        (run_mode, started_at, status, daily_window_days,
                         quarterly_window_days, gap_days)
                    VALUES (%(mode)s, CURRENT_TIMESTAMP, 'running',
                            %(daily)s, %(quarterly)s, %(gap)s)
                    RETURNING run_id;
                """, {
                    "mode": mode, "daily": daily_window,
                    "quarterly": quarterly_window, "gap": gap_days,
                })
                run_id = cur.fetchone()[0]
            conn.commit()
        logger.info("Started run_log run_id=%d mode=%s", run_id, mode)
        return run_id

    def complete_run(self, run_id: int, status: str, symbols_processed: int,
                     rows_upserted: int, error_count: int,
                     error_msg: Optional[str] = None) -> None:
        with psycopg2.connect(**self.pg_conn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE public.fundamentals_run_log
                    SET completed_at = CURRENT_TIMESTAMP,
                        status = %(status)s,
                        symbols_processed = %(proc)s,
                        rows_upserted = %(rows)s,
                        error_count = %(errs)s,
                        error_message = %(msg)s
                    WHERE run_id = %(run_id)s;
                """, {
                    "run_id": run_id, "status": status, "proc": symbols_processed,
                    "rows": rows_upserted, "errs": error_count, "msg": error_msg,
                })
            conn.commit()
        logger.info("Completed run_log run_id=%d status=%s rows=%d errs=%d",
                    run_id, status, rows_upserted, error_count)

    def get_last_successful_run_time(self) -> Optional[datetime]:
        with psycopg2.connect(**self.pg_conn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT MAX(completed_at)
                    FROM public.fundamentals_run_log
                    WHERE status = 'completed';
                """)
                row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return row[0]

    def get_table_count(self, table_name: str) -> int:
        with psycopg2.connect(**self.pg_conn) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM fundamentals.{table_name};")
                row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # ------------------------- Upsert -------------------------

    def upsert_rows(self, spec: FundTableSpec, rows: List[dict]) -> int:
        """Upsert all rows for one (symbol, table) in a single tx.

        Each `row` is a dict with keys: symbol, pub_date, rpt_date, trade_date,
        rpt_type, data_type, plus per-field values keyed by field name.
        """
        if not rows:
            return 0

        col_names = ["symbol", "pub_date", "rpt_date", "trade_date", "rpt_type", "data_type"]
        col_names.extend(spec.fields)
        col_list = ", ".join(col_names)
        placeholders = ", ".join(["%s"] * len(col_names))

        if spec.kind == TableKind.Quarterly:
            conflict = ("(symbol, rpt_date, data_type)" if spec.returns_rpt_type
                        else "(symbol, rpt_date)")
        else:
            conflict = "(symbol, trade_date)"

        set_parts = [
            "pub_date = EXCLUDED.pub_date",
            "rpt_date = EXCLUDED.rpt_date",
            "trade_date = EXCLUDED.trade_date",
            "rpt_type = EXCLUDED.rpt_type",
            "data_type = EXCLUDED.data_type",
        ]
        set_parts.extend(f"{f} = EXCLUDED.{f}" for f in spec.fields)
        set_parts.append("updated_at = CURRENT_TIMESTAMP")
        set_clause = ", ".join(set_parts)

        sql = (f"INSERT INTO fundamentals.{spec.table_name} ({col_list}) "
               f"VALUES ({placeholders}) "
               f"ON CONFLICT {conflict} DO UPDATE SET {set_clause};")

        written = 0
        with psycopg2.connect(**self.pg_conn) as conn:
            with conn.cursor() as cur:
                for r in rows:
                    values = [
                        r.get("symbol"),
                        r.get("pub_date"),
                        r.get("rpt_date"),
                        r.get("trade_date"),
                        r.get("rpt_type"),
                        r.get("data_type"),
                    ]
                    values.extend(_parse_double(r.get(f)) for f in spec.fields)
                    try:
                        cur.execute(sql, values)
                        written += 1
                    except Exception as ex:
                        logger.warning("Upsert failed for %s %s rpt=%s trade=%s: %s",
                                       spec.table_name, r.get("symbol"),
                                       r.get("rpt_date"), r.get("trade_date"), ex)
            conn.commit()
        return written
