"""Strategy metadata endpoint - proxied to strategy-engine.

Dashboard.Web calls this to dynamically render the parameter form for
each strategy. We just forward strategy-engine's /strategies response
so the data lives in one place (the strategy classes themselves).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..clients import strategy_engine_client
from ..models import StrategiesResponse


router = APIRouter(tags=["strategies"])


@router.get("/strategies", response_model=StrategiesResponse)
async def list_strategies() -> StrategiesResponse:
    try:
        payload = await strategy_engine_client.list_strategies()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach strategy-engine /strategies: {exc}",
        )
    return StrategiesResponse(**payload)
