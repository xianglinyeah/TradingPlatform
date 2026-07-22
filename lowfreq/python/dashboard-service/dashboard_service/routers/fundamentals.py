"""Fundamentals endpoint - read PE/PB/div-yield/turnover from PostgreSQL.

data-ingestion populates `fundamentals.daily_valuation`. We project the
columns Dashboard.Web needs (PE/PB/div-yield/turnover) into a stable
JSON shape and leave nulls for any field the upstream pipeline hasn't
collected yet - that way the UI degrades gracefully.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db.postgres import postgres_pool
from ..models import FundamentalPoint, FundamentalsResponse


router = APIRouter(tags=["fundamentals"])


@router.get("/fundamentals/{symbol}", response_model=FundamentalsResponse)
async def get_fundamentals(
    symbol: str,
    start_date: str = Query(..., description="ISO date, e.g. '2024-01-01'"),
    end_date: str = Query(..., description="ISO date, e.g. '2024-01-15'"),
) -> FundamentalsResponse:
    # Column names follow fundamentals.daily_valuation (see data-ingestion
    # core/schema.py Valuation spec). We tolerate the table being missing
    # by returning an empty list rather than 500ing - the UI shows "no data".
    sql = (
        "SELECT trade_date, pe_ttm, pb_lyr, dv_ttm, turnover_rate "
        "FROM fundamentals.daily_valuation "
        "WHERE symbol = $1 AND trade_date >= $2 AND trade_date <= $3 "
        "ORDER BY trade_date ASC"
    )
    try:
        rows = await postgres_pool.fetch(sql, symbol, start_date, end_date)
    except Exception as exc:
        # Most likely cause: schema/table not yet created in this env.
        raise HTTPException(
            status_code=502,
            detail=f"PostgreSQL query failed (is fundamentals.daily_valuation populated?): {exc}",
        )

    points = []
    for r in rows:
        # asyncpg returns datetime.date for DATE columns.
        d = r["trade_date"]
        points.append(
            FundamentalPoint(
                date=d.isoformat() if hasattr(d, "isoformat") else str(d),
                pe_ttm=_to_float(r["pe_ttm"]),
                pb_lyr=_to_float(r["pb_lyr"]),
                dv_ttm=_to_float(r["dv_ttm"]),
                turnover_rate=_to_float(r["turnover_rate"]),
            )
        )

    return FundamentalsResponse(symbol=symbol, data=points)


def _to_float(v) -> float | None:
    """Coerce Decimal/None to float/None for JSON."""
    if v is None:
        return None
    return float(v)
