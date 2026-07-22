"""K-line bar endpoint - direct read from ClickHouse.

The C# replay service and Python data-ingestion both write bars to
ClickHouse with the same column layout (see db/clickhouse.py), so this
endpoint works identically for live and historical data.

TradingView Lightweight Charts expects unix-seconds timestamps; we
convert ClickHouse DateTime values (which are naive UTC in our schema)
to that format on the way out.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db.clickhouse import clickhouse_client
from ..models import KlineBar, KlineResponse


router = APIRouter(tags=["kline"])

# Map UI interval tokens to ClickHouse tables.
# 1m reads the raw 1-minute table. Other intervals aggregate on the fly.
_INTERVAL_TABLE = {
    "1m": ("kline_1min", None),
    "1d": ("kline_daily", None),
}


@router.get("/kline/{symbol}", response_model=KlineResponse)
async def get_kline(
    symbol: str,
    start_date: str = Query(..., description="ISO date, e.g. '2024-01-01'"),
    end_date: str = Query(..., description="ISO date, e.g. '2024-01-15'"),
    interval: str = Query("1d", description="One of: 1m, 1d"),
) -> KlineResponse:
    if interval not in _INTERVAL_TABLE:
        raise HTTPException(
            status_code=400,
            detail=f"interval must be one of {list(_INTERVAL_TABLE.keys())}, got '{interval}'",
        )
    table, _ = _INTERVAL_TABLE[interval]

    # NOTE: ts_code in ClickHouse is like '000001.SZ' (matches the symbol
    # the caller passes). trade_time is a DateTime column; we treat it
    # as UTC for the unix-second conversion.
    sql = (
        f"SELECT trade_time, open, high, low, close, volume "
        f"FROM {table} "
        f"WHERE ts_code = %(symbol)s "
        f"  AND trade_time >= %(start)s AND trade_time <= %(end)s "
        f"ORDER BY trade_time ASC"
    )
    try:
        rows = await clickhouse_client.query(
            sql,
            {
                "symbol": symbol,
                "start": f"{start_date} 00:00:00",
                "end": f"{end_date} 23:59:59",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ClickHouse query failed: {exc}")

    bars = []
    for r in rows:
        t = r["trade_time"]
        # clickhouse-connect returns datetime.datetime; convert to unix seconds.
        ts = int(t.timestamp()) if hasattr(t, "timestamp") else int(t)
        bars.append(
            KlineBar(
                time=ts,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"]),
            )
        )

    return KlineResponse(symbol=symbol, interval=interval, bars=bars)
