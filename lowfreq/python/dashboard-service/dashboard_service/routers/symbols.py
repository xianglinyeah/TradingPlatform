"""Symbol search + universe lookup endpoints.

Two concerns:

  /symbols              - kline_min_metadata autocomplete (single-stock search)
  /universes/...        - market_ref universe definitions & members

The universe endpoints back the Dashboard.Web backtest page's universe
dropdown so users pick from real instrument-pool names (csi300, sse50...)
instead of typing raw symbols.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..db.postgres import postgres_pool
from ..models import (
    SymbolHit,
    SymbolsResponse,
    UniverseInfo,
    UniverseMembersResponse,
    UniversesListResponse,
)


router = APIRouter(tags=["symbols"])


@router.get("/symbols", response_model=SymbolsResponse)
async def list_symbols(
    search: str | None = Query(
        None, description="Case-insensitive prefix filter on symbol"
    ),
    limit: int = Query(50, ge=1, le=500),
) -> SymbolsResponse:
    if search:
        sql = (
            "SELECT DISTINCT symbol FROM kline_min_metadata "
            "WHERE symbol LIKE $1 "
            "ORDER BY symbol LIMIT $2"
        )
        rows = await postgres_pool.fetch(sql, f"{search.upper()}%", limit)
    else:
        sql = (
            "SELECT DISTINCT symbol FROM kline_min_metadata "
            "ORDER BY symbol DESC LIMIT $1"
        )
        rows = await postgres_pool.fetch(sql, limit)

    return SymbolsResponse(
        symbols=[SymbolHit(symbol=r["symbol"], name=None) for r in rows]
    )


# ---- Universe endpoints ---------------------------------------------

@router.get("/universes", response_model=UniversesListResponse)
async def list_universes() -> UniversesListResponse:
    """Return all universe definitions for the Dashboard.Web dropdown."""
    rows = await postgres_pool.fetch(
        "SELECT universe_id, name, source_index, description "
        "FROM market_ref.universe_definition ORDER BY universe_id"
    )
    return UniversesListResponse(
        universes=[
            UniverseInfo(
                universe_id=r["universe_id"],
                name=r["name"],
                source_index=r["source_index"],
                description=r["description"],
            )
            for r in rows
        ]
    )


@router.get("/universes/{universe_id}/members", response_model=UniverseMembersResponse)
async def get_universe_members(
    universe_id: str,
    as_of: Optional[str] = Query(
        None, description="ISO date for point-in-time lookup. Default: today."
    ),
) -> UniverseMembersResponse:
    """Return active members of a universe (optionally as of a date)."""
    trade_date = date.fromisoformat(as_of) if as_of else date.today()

    exists = await postgres_pool.fetchrow(
        "SELECT 1 FROM market_ref.universe_definition WHERE universe_id = $1",
        universe_id,
    )
    if not exists:
        raise HTTPException(
            status_code=404, detail=f"universe_id={universe_id!r} not found"
        )

    rows = await postgres_pool.fetch(
        "SELECT symbol FROM market_ref.universe_member "
        "WHERE universe_id = $1 "
        "  AND effective_from <= $2 "
        "  AND (effective_to IS NULL OR effective_to >= $2) "
        "ORDER BY symbol",
        universe_id,
        trade_date,
    )
    symbols = [r["symbol"] for r in rows]
    return UniverseMembersResponse(
        universe_id=universe_id,
        count=len(symbols),
        symbols=symbols,
    )
