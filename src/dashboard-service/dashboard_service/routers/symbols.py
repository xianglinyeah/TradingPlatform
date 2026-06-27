"""Symbol search endpoint - lookup against PostgreSQL kline_min_metadata.

data-ingestion writes one row per (symbol, trade_date) into
public.kline_min_metadata. We SELECT DISTINCT symbol and optionally
filter by a search prefix so the dashboard's typeahead box is fast.

The `name` column is currently null (data-ingestion does not populate
it yet); we surface null rather than fabricating.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..db.postgres import postgres_pool
from ..models import SymbolHit, SymbolsResponse


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
