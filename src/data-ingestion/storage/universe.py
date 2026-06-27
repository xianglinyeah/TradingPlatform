"""Synchronous universe membership lookup for data-ingestion pipelines.

Reads from `market_ref.universe_member` via psycopg2 (already a dependency).
Returns symbols in TS format (`600000.SH`); convert to GM format with
`storage.parquet.ts_to_gm_code` when feeding the GM SDK.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional

import psycopg2

from config import parse_pg_conn

logger = logging.getLogger(__name__)


def get_members(conn_str: str, universe_id: str,
                trade_date: Optional[date] = None) -> List[str]:
    """Return symbols active in `universe_id` AS OF `trade_date` (point-in-time).

    If `trade_date` is None, returns the currently active membership
    (effective_to IS NULL OR effective_to >= today).
    """
    as_of = trade_date or date.today()
    with psycopg2.connect(**parse_pg_conn(conn_str)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol FROM market_ref.universe_member "
                "WHERE universe_id = %s "
                "  AND effective_from <= %s "
                "  AND (effective_to IS NULL OR effective_to >= %s) "
                "ORDER BY symbol",
                (universe_id, as_of, as_of),
            )
            return [r[0] for r in cur.fetchall()]


def get_members_as_gm(conn_str: str, universe_id: str,
                      trade_date: Optional[date] = None) -> List[str]:
    """Same as get_members but returns GM-format symbols (SHSE.600000)."""
    from storage.parquet import ts_to_gm_code
    return [ts_to_gm_code(s) for s in get_members(conn_str, universe_id, trade_date)]
