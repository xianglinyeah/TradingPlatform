"""sec_master sync from GM SDK to PostgreSQL market_ref.sec_master.

Pulls instrument contract info via `get_symbol_infos` for each sec_type1
class we care about (stocks, convertible bonds, ETFs), normalizes the rows,
and upserts them into market_ref.sec_master keyed by TS-format symbol.

execution-service reads this table at order-validation time to pick the
right market-rule implementation (T+1 stock vs T+0 convertible bond) and to
compute board-aware price-limit bands (§4).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import psycopg2

from config import parse_pg_conn
from sources import gm_api
from storage.parquet import gm_to_ts_code

logger = logging.getLogger(__name__)


# (sec_type1 code, normalized sec_type, default exchange) tuples.
# Exchange in each row is used only as a fallback when the SDK row lacks an
# `exchange` field. The GM SDK returns exchange per row in most versions.
_SEC_CLASSES: List[tuple] = [
    (gm_api.SEC_TYPE_STOCK, "stock", None),
    (gm_api.SEC_TYPE_CONVERTIBLE_BOND, "convertible_bond", None),
    (gm_api.SEC_TYPE_ETF, "etf", None),
    (gm_api.SEC_TYPE_REIT, "reit", None),
]

# A-share board classification by 6-digit numeric code. Returns None for
# non-equity instruments. Captured here so ingestion and any consumer that
# wants to recompute board from symbol are aligned.
_BOARD_PATTERNS: List[tuple] = [
    (re.compile(r"^(688|689)\d"), "star"),       # STAR Market (Shanghai)
    (re.compile(r"^(300|301)\d"), "chinext"),    # ChiNext (Shenzhen)
    (re.compile(r"^[8]\d"),       "beijing"),    # BSE main board
    (re.compile(r"^[4]\d"),       "beijing"),    # BSE old / preferred
    (re.compile(r"^(600|601|603|605)\d"), "main"),  # Shanghai main board
    (re.compile(r"^(000|001|002|003)\d"), "main"),  # Shenzhen main board
]


def _classify_board(numeric_code: str) -> Optional[str]:
    if not numeric_code:
        return None
    for pat, board in _BOARD_PATTERNS:
        if pat.match(numeric_code):
            return board
    return None


def _is_st(name: Optional[str]) -> bool:
    if not name:
        return False
    n = name.strip()
    return n.startswith("ST") or n.startswith("*ST") or n.startswith("SST")


def _first(row: dict, *keys: str, default=None):
    """First present value among `keys` (case-insensitive). GM SDK column
    names vary slightly across versions; this normalizes the lookup."""
    lowered = {k.lower(): v for k, v in row.items()}
    for k in keys:
        v = lowered.get(k.lower())
        if v is not None and v != "":
            return v
    return default


def _normalize(row: dict, default_sec_type: str) -> Optional[dict]:
    """Map a GM SDK symbol-info row to a market_ref.sec_master row dict.

    Returns None for rows we cannot identify (no symbol at all).
    """
    gm_symbol = _first(row, "symbol", "sec_code", "code")
    if not gm_symbol:
        return None

    ts_symbol = gm_to_ts_code(str(gm_symbol))
    name = _first(row, "sec_name", "name", "symbol_name")
    exchange = _first(row, "exchange", "listed_exchange")

    # Derive numeric prefix for board classification. Use the GM symbol's
    # numeric portion (after the dot in 'SHSE.600000').
    numeric = ""
    parts = str(gm_symbol).split(".")
    if len(parts) == 2:
        numeric = parts[1]
    board = _classify_board(numeric)

    return {
        "symbol": ts_symbol,
        "gm_symbol": str(gm_symbol),
        "sec_type": default_sec_type,
        "sec_type_code": _first(row, "sec_type1", "sec_type"),
        "board": board,
        "name": name,
        "is_st": _is_st(name),
        "exchange": exchange,
        "updated_at": datetime.utcnow(),
    }


def _ensure_schema(cur) -> None:
    """Idempotent schema creation. Mirrors scripts/db/create_sec_master.sql."""
    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS market_ref;
        CREATE TABLE IF NOT EXISTS market_ref.sec_master (
            symbol          VARCHAR(20) PRIMARY KEY,
            gm_symbol       VARCHAR(30) NOT NULL,
            sec_type        VARCHAR(30) NOT NULL,
            sec_type_code   INTEGER,
            board           VARCHAR(20),
            name            VARCHAR(100),
            is_st           BOOLEAN NOT NULL DEFAULT FALSE,
            exchange        VARCHAR(10),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_sec_master_sec_type
            ON market_ref.sec_master(sec_type);
        CREATE INDEX IF NOT EXISTS idx_sec_master_board
            ON market_ref.sec_master(board)
            WHERE board IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_sec_master_is_st
            ON market_ref.sec_master(is_st)
            WHERE is_st = TRUE;
    """)


def _upsert(cur, rows: Iterable[dict]) -> int:
    sql = """
        INSERT INTO market_ref.sec_master
            (symbol, gm_symbol, sec_type, sec_type_code, board,
             name, is_st, exchange, updated_at)
        VALUES (%(symbol)s, %(gm_symbol)s, %(sec_type)s, %(sec_type_code)s,
                %(board)s, %(name)s, %(is_st)s, %(exchange)s, %(updated_at)s)
        ON CONFLICT (symbol) DO UPDATE SET
            gm_symbol     = EXCLUDED.gm_symbol,
            sec_type      = EXCLUDED.sec_type,
            sec_type_code = EXCLUDED.sec_type_code,
            board         = EXCLUDED.board,
            name          = EXCLUDED.name,
            is_st         = EXCLUDED.is_st,
            exchange      = EXCLUDED.exchange,
            updated_at    = EXCLUDED.updated_at
    """
    written = 0
    for r in rows:
        try:
            cur.execute(sql, r)
            written += 1
        except Exception as ex:
            logger.warning("Upsert failed for %s: %s", r.get("symbol"), ex)
    return written


def sync_sec_master(conn_str: str) -> Dict[str, int]:
    """Sync every configured sec_type class from GM SDK into market_ref.sec_master.

    Returns a dict {sec_type: rows_upserted}. Failures for individual classes
    are logged but do not abort the run — partial syncs are still useful and
    the next run will retry.
    """
    summary: Dict[str, int] = {}
    conn = psycopg2.connect(**parse_pg_conn(conn_str))
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            _ensure_schema(cur)

            for sec_type1, sec_type, _default_exchange in _SEC_CLASSES:
                logger.info("Fetching sec_type1=%s (%s)", sec_type1, sec_type)
                try:
                    raw_rows = gm_api.get_symbol_infos(sec_type1=sec_type1)
                except Exception as ex:
                    logger.error("Failed to fetch %s: %s", sec_type, ex)
                    continue

                logger.info("Fetched %d raw rows for %s", len(raw_rows), sec_type)

                normalized: List[dict] = []
                for raw in raw_rows:
                    n = _normalize(raw, default_sec_type=sec_type)
                    if n is not None:
                        normalized.append(n)

                written = _upsert(cur, normalized)
                summary[sec_type] = written
                logger.info("Upserted %d rows for %s", written, sec_type)

        conn.commit()
        logger.info("sec_master sync committed. Summary: %s", summary)
        return summary
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    args = sys.argv[1:]
    if not args:
        print("Usage: python sync.py <pg_conn_str>")
        sys.exit(2)
    summary = sync_sec_master(args[0])
    for sec_type, count in summary.items():
        print(f"{sec_type}: {count}")
