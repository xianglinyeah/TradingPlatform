"""Universe membership sync from GM SDK to PostgreSQL.

Pulls index constituents via `stk_get_index_constituents` for each
`market_ref.universe_definition` row that has a `source_index`, computes
membership changes versus the latest persisted snapshot, and applies
effective-time updates (close old rows, open new ones) so point-in-time
queries remain accurate for backtests.

For composite universes (e.g. `a_all`, where `source_index` is NULL) the
sync looks up the membership by union of constituent indices listed in
the `description` metadata; the well-known `a_all` universe unions
SHSE.000001 (SSE composite) + SZSE.399106 (SZSE composite).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Sequence

import psycopg2

from config import parse_pg_conn
from sources import gm_api
from storage.parquet import gm_to_ts_code

logger = logging.getLogger(__name__)

# Composite universes map a universe_id to the list of source indices that
# should be unioned. Defined here rather than in DB so the rule lives next
# to the code that enforces it. Add new composite rules here as needed.
_COMPOSITE_SOURCES: Dict[str, List[str]] = {
    "a_all": ["SHSE.000001", "SZSE.399106"],
}


def _connect(conn_str: str):
    return psycopg2.connect(**parse_pg_conn(conn_str))


def _fetch_definitions(conn) -> List[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT universe_id, name, source_index "
            "FROM market_ref.universe_definition ORDER BY universe_id"
        )
        rows = cur.fetchall()
    return [
        {"universe_id": r[0], "name": r[1], "source_index": r[2]}
        for r in rows
    ]


def _latest_members(conn, universe_id: str) -> set[str]:
    """Return the set of currently-active (effective_to IS NULL) symbols."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM market_ref.universe_member "
            "WHERE universe_id = %s AND effective_to IS NULL",
            (universe_id,),
        )
        return {r[0] for r in cur.fetchall()}


def _fetch_constituents(
    universe_id: str,
    source_index: Optional[str],
    trade_date: Optional[str],
) -> set[str]:
    """Fetch the universe's symbol set as TS-formatted codes for trade_date.

    For composite universes (source_index IS NULL), unions the configured
    constituent indices from _COMPOSITE_SOURCES.
    """
    indices: Sequence[str]
    if source_index:
        indices = [source_index]
    else:
        indices = _COMPOSITE_SOURCES.get(universe_id, [])
        if not indices:
            logger.warning(
                "Universe %s has no source_index and no composite rule; skipped",
                universe_id,
            )
            return set()

    members: set[str] = set()
    for idx in indices:
        try:
            rows = gm_api.get_index_constituents(idx, trade_date)
        except Exception as ex:
            logger.error("Failed to fetch constituents for %s (%s): %s",
                         universe_id, idx, ex)
            continue
        for row in rows:
            gm_symbol = row.get("symbol") or row.get("Symbol")
            if not gm_symbol:
                continue
            members.add(gm_to_ts_code(gm_symbol))
        logger.info("Universe %s source %s: %d constituents",
                    universe_id, idx, len(rows))
    return members


def _apply_delta(
    conn,
    universe_id: str,
    new_members: set[str],
    as_of: date,
) -> None:
    """Persist membership delta for one universe as of `as_of`.

    - Symbols that left (in DB but not in new_members): close their row
      by setting effective_to = as_of.
    - Symbols that joined (in new_members but not in DB): insert a new row
      with effective_from = as_of.
    - Symbols unchanged: no-op (preserves their original effective_from).
    """
    current = _latest_members(conn, universe_id)
    left = current - new_members
    joined = new_members - current

    with conn.cursor() as cur:
        if left:
            cur.executemany(
                "UPDATE market_ref.universe_member SET effective_to = %s "
                "WHERE universe_id = %s AND symbol = %s AND effective_to IS NULL",
                [(as_of, universe_id, s) for s in sorted(left)],
            )
            logger.info("Universe %s: %d symbols left", universe_id, len(left))

        if joined:
            cur.executemany(
                "INSERT INTO market_ref.universe_member "
                "(universe_id, symbol, effective_from, effective_to) "
                "VALUES (%s, %s, %s, NULL)",
                [(universe_id, s, as_of) for s in sorted(joined)],
            )
            logger.info("Universe %s: %d symbols joined", universe_id, len(joined))

    unchanged = current & new_members
    if unchanged:
        logger.info("Universe %s: %d symbols unchanged", universe_id, len(unchanged))


def sync_universe(conn_str: str, trade_date: Optional[str] = None) -> Dict[str, int]:
    """Sync all universe definitions from GM SDK to PostgreSQL.

    Args:
        conn_str: Npgsql-style connection string.
        trade_date: YYYY-MM-DD string for point-in-time sync. If None, the
            GM SDK returns the latest trading day.

    Returns:
        Dict mapping universe_id -> active member count after sync.
    """
    as_of = (
        datetime.strptime(trade_date, "%Y-%m-%d").date()
        if trade_date
        else date.today()
    )

    conn = _connect(conn_str)
    try:
        conn.autocommit = False
        definitions = _fetch_definitions(conn)
        if not definitions:
            logger.warning("No universe_definition rows found; run create_universe_tables.sql first")
            return {}

        result: Dict[str, int] = {}
        for d in definitions:
            universe_id = d["universe_id"]
            logger.info("=== Syncing universe %s (%s) ===", universe_id, d["name"])
            members = _fetch_constituents(universe_id, d["source_index"], trade_date)
            if not members:
                logger.warning("Universe %s resolved to 0 members; skipping delta",
                               universe_id)
                continue
            _apply_delta(conn, universe_id, members, as_of)
            result[universe_id] = len(members)

        conn.commit()
        logger.info("Universe sync committed. Summary: %s", result)
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    # Standalone entry: python sync.py <conn_str> [trade_date]
    args = sys.argv[1:]
    if not args:
        print("Usage: python sync.py <pg_conn_str> [YYYY-MM-DD]")
        sys.exit(2)
    summary = sync_universe(args[0], args[1] if len(args) > 1 else None)
    for uid, count in summary.items():
        print(f"{uid}: {count}")
