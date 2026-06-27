"""Shared Pydantic models for request/response shapes.

Keeping them in one place avoids circular imports between routers that
embed each other's types (e.g. backtest results reference strategy params).
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ---- K-line / fundamentals -------------------------------------------

class KlineBar(BaseModel):
    time: int  # unix seconds (UTC) - TradingView Lightweight Charts format
    open: float
    high: float
    low: float
    close: float
    volume: float


class KlineResponse(BaseModel):
    symbol: str
    interval: str
    bars: List[KlineBar]


class FundamentalPoint(BaseModel):
    date: str
    pe_ttm: Optional[float] = None
    pb_lyr: Optional[float] = None
    dv_ttm: Optional[float] = None
    turnover_rate: Optional[float] = None


class FundamentalsResponse(BaseModel):
    symbol: str
    data: List[FundamentalPoint]


# ---- Backtest orchestration ------------------------------------------

class BacktestRunRequest(BaseModel):
    """Body for POST /api/backtest/run.

    Speed defaults to 10000 (max) since most replays are batch backtests
    where the user wants results fast. Lower for visual debugging.
    """
    start_date: str = Field(..., description="ISO date, e.g. '2024-01-01'")
    end_date: str = Field(..., description="ISO date, e.g. '2024-01-15'")
    symbols: List[str] = Field(..., min_length=1)
    speed: float = Field(10000.0, gt=0)
    strategy_name: str = Field(..., description="Key from GET /api/strategies")
    strategy_params: dict[str, Any] = Field(default_factory=dict)


class BacktestRunResponse(BaseModel):
    run_id: str
    status: str


class BacktestStatusResponse(BaseModel):
    status: str  # idle | running | completed | error | pending
    progress: Optional[str] = None
    bars_sent: Optional[int] = None
    run_id: str


class BacktestSummary(BaseModel):
    total_pnl: float
    win_rate: float
    total_trades: int
    max_drawdown: float
    sharpe_ratio: Optional[float] = None


class PnlCurvePoint(BaseModel):
    timestamp: str
    cumulative_pnl: float


class TradeRow(BaseModel):
    timestamp: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: str


class BacktestResults(BaseModel):
    run_id: str
    summary: BacktestSummary
    pnl_curve: List[PnlCurvePoint]
    trades: List[TradeRow]


class RunRecord(BaseModel):
    run_id: str
    strategy_name: str
    strategy_params: dict[str, Any]
    symbols: List[str]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    speed: Optional[float] = None
    status: str
    total_pnl: Optional[float] = None
    created_at: str
    error_message: Optional[str] = None


class RunsListResponse(BaseModel):
    runs: List[RunRecord]


class CompareResponse(BaseModel):
    runs: List[BacktestResults]


# ---- Strategy metadata -----------------------------------------------

class StrategyParamSchema(BaseModel):
    key: str
    label: str
    type: str
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None


class StrategyInfo(BaseModel):
    name: str
    class_name: str
    display_name: str
    description: str
    params_schema: List[dict]


class StrategiesResponse(BaseModel):
    strategies: List[StrategyInfo]


# ---- Symbols --------------------------------------------------------

class SymbolHit(BaseModel):
    symbol: str
    name: Optional[str] = None


class SymbolsResponse(BaseModel):
    symbols: List[SymbolHit]
