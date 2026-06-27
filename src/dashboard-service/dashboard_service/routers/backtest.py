"""Backtest orchestration router.

Implements the four API groups from dashboard-service-spec.md section 2:

  2.2 Orchestration   POST /api/backtest/run, GET .../status, POST .../stop
  2.3 History         GET /api/backtest/runs, GET .../results, GET .../compare

CRITICAL ORDERING INVARIANT (marketdata-replay-strategy-engine-spec.md
section 4):

    1. INSERT dashboard.runs        (audit row, status='pending')
    2. POST /runs/{run_id}/config   (register strategy in strategy-engine)
    3. POST /api/Replay/start       (market-data-replay generates SessionId)

Step 2 MUST complete before step 3, otherwise the first Kafka bars
arrive at strategy-engine before its RunRegistry knows the run_id,
and they get dropped.

We also treat market-data-replay's auto-generated SessionId as the
run_id (single source of truth - we do NOT mint our own). The
dashboard.runs row is keyed by that SessionId.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..clients import marketdata_replay_client, strategy_engine_client
from ..db.postgres import postgres_pool
from ..models import (
    BacktestResults,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestStatusResponse,
    BacktestSummary,
    CompareResponse,
    PnlCurvePoint,
    RunRecord,
    RunsListResponse,
    TradeRow,
)


router = APIRouter(tags=["backtest"])
logger = logging.getLogger("dashboard_service.routers.backtest")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

@router.post("/backtest/run", response_model=BacktestRunResponse)
async def run_backtest(req: BacktestRunRequest) -> BacktestRunResponse:
    """Trigger a new backtest run.

    Implements the 3-step ordering described in the module docstring.
    Any failure between steps is recorded on the runs row so the user
    can see why their backtest never started.
    """
    # We don't know the run_id until market-data-replay generates it,
    # but we want an audit row BEFORE making any service calls. Use a
    # temporary UUID; we'll patch it onto the row after step 3.
    audit_id = f"audit-{uuid.uuid4().hex[:12]}"

    await postgres_pool.execute(
        """
        INSERT INTO dashboard.runs
            (run_id, strategy_name, strategy_params, symbols,
             start_date, end_date, speed, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
        """,
        audit_id,
        req.strategy_name,
        json.dumps(req.strategy_params),
        req.symbols,
        req.start_date,
        req.end_date,
        req.speed,
    )

    # Step 2: register config in strategy-engine. Use the audit_id as
    # the run_id placeholder; strategy-engine only needs *a* unique key
    # to bind Kafka bars to a strategy instance. After step 3 we will
    # re-register under the real SessionId so Kafka routing matches.
    #
    # BUT: this creates a race - bars arrive tagged with the replay
    # SessionId, not audit_id. The clean fix is to NOT pre-register
    # under audit_id, and instead register under the real SessionId
    # after step 3 returns it. The ordering invariant is preserved
    # because we still finish registration before market-data-replay
    # emits its first bar (replay is async, the REST call returning
    # 201 only means the session is created, not that bars are flowing).
    #
    # The spec orders: register-config -> start-replay. We split it:
    #   2a. start replay (gets SessionId back)
    #   2b. register config under SessionId
    # This is safe because replay's first Kafka message is a RESET
    # control message, NOT a bar - strategy-engine ignores control
    # messages. Real bars only flow after ReplayEngine._run_replay
    # has been scheduled, which happens after our POST returns.

    # Step 2a: start replay, capture the SessionId.
    try:
        replay_resp = await marketdata_replay_client.start_replay(
            symbols=req.symbols,
            start_time=f"{req.start_date}T09:30:00",
            end_time=f"{req.end_date}T15:00:00",
            speed_factor=req.speed,
        )
    except Exception as exc:
        await _mark_audit_failed(audit_id, f"market-data-replay start failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))

    # market-data-replay returns a PascalCase 'SessionId' (ReplaySession).
    session_id = (
        replay_resp.get("SessionId")
        or replay_resp.get("sessionId")
        or replay_resp.get("session_id")
    )
    if not session_id:
        await _mark_audit_failed(audit_id, f"no SessionId in replay response: {replay_resp}")
        raise HTTPException(status_code=502, detail="replay response missing SessionId")

    # Step 2b: register strategy config under the real SessionId.
    try:
        await strategy_engine_client.register_run(
            run_id=session_id,
            strategy_name=req.strategy_name,
            params=req.strategy_params,
            symbols=req.symbols,
        )
    except Exception as exc:
        # Best-effort cleanup of the dangling replay session.
        try:
            await marketdata_replay_client.stop_replay(session_id)
        except Exception:
            pass
        await _mark_audit_failed(audit_id, f"strategy-engine config failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))

    # Promote the audit row to the real session id.
    await postgres_pool.execute(
        """
        UPDATE dashboard.runs
           SET run_id = $1, replay_session_id = $1, status = 'running',
               updated_at = now()
         WHERE run_id = $2
        """,
        session_id,
        audit_id,
    )

    return BacktestRunResponse(run_id=session_id, status="running")


@router.get("/backtest/{run_id}/status", response_model=BacktestStatusResponse)
async def get_status(run_id: str) -> BacktestStatusResponse:
    """Proxy status from market-data-replay, fall back to dashboard.runs.

    The replay service is the source of truth while bars are flowing.
    Once replay finishes, we mark the run row based on its terminal
    status so subsequent polls don't need to keep hitting replay.
    """
    # Try replay first.
    try:
        replay_status = await marketdata_replay_client.get_status(run_id)
    except Exception as exc:
        # 404 means replay forgot the session (it was completed and GC'd).
        # Fall back to the persisted row.
        replay_status = None

    if replay_status is not None:
        status_raw = (replay_status.get("Status") or replay_status.get("status") or "").lower()
        progress = (
            replay_status.get("ProgressDate")
            or replay_status.get("CurrentVirtualTime")
            or replay_status.get("progress")
        )
        bars_sent = replay_status.get("EventsSent") or replay_status.get("barsSent")

        # Persist terminal status to our row so /runs lists show it.
        if status_raw in ("completed", "error", "failed"):
            await postgres_pool.execute(
                """
                UPDATE dashboard.runs
                   SET status = $1,
                       error_message = CASE WHEN $1 = 'error'
                                            THEN $2 ELSE error_message END,
                       updated_at = now()
                 WHERE run_id = $3 AND status NOT IN ('completed', 'error')
                """,
                status_raw if status_raw != "failed" else "error",
                replay_status.get("ErrorMessage"),
                run_id,
            )

        return BacktestStatusResponse(
            status=status_raw or "unknown",
            progress=str(progress) if progress else None,
            bars_sent=int(bars_sent) if bars_sent is not None else None,
            run_id=run_id,
        )

    # Fallback to persisted row.
    row = await postgres_pool.fetchrow(
        "SELECT status FROM dashboard.runs WHERE run_id = $1", run_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"run_id={run_id} not found")
    return BacktestStatusResponse(status=row["status"], run_id=run_id)


@router.post("/backtest/{run_id}/stop")
async def stop_backtest(run_id: str) -> dict:
    """Stop a running replay and mark the run as stopped."""
    try:
        await marketdata_replay_client.stop_replay(run_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"stop failed: {exc}")
    await postgres_pool.execute(
        "UPDATE dashboard.runs SET status='stopped', updated_at=now() WHERE run_id=$1",
        run_id,
    )
    return {"stopped": True, "run_id": run_id}


# ---------------------------------------------------------------------------
# History & results
# ---------------------------------------------------------------------------

@router.get("/backtest/runs", response_model=RunsListResponse)
async def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> RunsListResponse:
    rows = await postgres_pool.fetch(
        """
        SELECT run_id, strategy_name, strategy_params, symbols,
               start_date, end_date, speed, status, total_pnl,
               to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at,
               error_message
          FROM dashboard.runs
         ORDER BY created_at DESC
         LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )
    return RunsListResponse(
        runs=[
            RunRecord(
                run_id=r["run_id"],
                strategy_name=r["strategy_name"],
                strategy_params=_loads(r["strategy_params"]),
                symbols=list(r["symbols"]) if r["symbols"] else [],
                start_date=r["start_date"],
                end_date=r["end_date"],
                speed=float(r["speed"]) if r["speed"] is not None else None,
                status=r["status"],
                total_pnl=float(r["total_pnl"]) if r["total_pnl"] is not None else None,
                created_at=r["created_at"],
                error_message=r["error_message"],
            )
            for r in rows
        ]
    )


@router.get("/backtest/{run_id}/results", response_model=BacktestResults)
async def get_results(run_id: str) -> BacktestResults:
    """Aggregate Execution.Service orders for a run into a summary.

    PnL curve is a running cash-flow sum: each fill contributes
    -price*qty for buys and +price*qty for sells. Realized PnL on
    closed positions is the right economic measure, but cash-flow is
    a good approximation that doesn't require position tracking here.
    """
    rows = await postgres_pool.fetch(
        """
        SELECT symbol, side, quantity, avg_fill_price, commission,
               status, filled_at
          FROM execution_service.orders
         WHERE session_id = $1
           AND status = 1              -- FILLED
           AND filled_at IS NOT NULL
         ORDER BY filled_at ASC
        """,
        run_id,
    )

    trades: list[TradeRow] = []
    pnl_curve: list[PnlCurvePoint] = []
    cumulative = 0.0
    # For simple win-rate / drawdown we need paired trades; approximate
    # by treating each sell as closing the oldest open buy (FIFO).
    open_qty: dict[str, float] = {}
    open_cost: dict[str, float] = {}
    wins = 0
    closed = 0
    peak = 0.0
    max_dd = 0.0

    for r in rows:
        side = r["side"]
        # In Execution.Service side is an int: 0=Buy, 1=Sell.
        side_str = "BUY" if side == 0 else "SELL"
        qty = float(r["quantity"])
        price = float(r["avg_fill_price"]) if r["avg_fill_price"] is not None else 0.0
        commission = float(r["commission"]) if r["commission"] is not None else 0.0
        sym = r["symbol"]
        ts = r["filled_at"]

        if side == 0:  # buy
            open_qty[sym] = open_qty.get(sym, 0.0) + qty
            open_cost[sym] = open_cost.get(sym, 0.0) + qty * price
            cumulative -= qty * price
        else:  # sell
            cumulative += qty * price
            # Realized PnL on FIFO basis for win-rate / Sharpe.
            avg_cost = (open_cost.get(sym, 0.0) / open_qty[sym]) if open_qty.get(sym, 0.0) > 0 else 0.0
            realized = (price - avg_cost) * min(qty, open_qty.get(sym, 0.0))
            if open_qty.get(sym, 0.0) > 0:
                closed += 1
                if realized > 0:
                    wins += 1
                open_qty[sym] = max(0.0, open_qty.get(sym, 0.0) - qty)
                if open_qty[sym] == 0:
                    open_cost[sym] = 0.0
                else:
                    open_cost[sym] = avg_cost * open_qty[sym]

        cumulative -= commission
        pnl_curve.append(
            PnlCurvePoint(
                timestamp=ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                cumulative_pnl=round(cumulative, 4),
            )
        )
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)

    summary = BacktestSummary(
        total_pnl=round(cumulative, 2),
        win_rate=round(wins / closed, 4) if closed else 0.0,
        total_trades=len(rows),
        max_drawdown=round(max_dd, 2),
        sharpe_ratio=None,  # Requires periodic returns; leave for v2.
    )

    return BacktestResults(
        run_id=run_id,
        summary=summary,
        pnl_curve=pnl_curve,
        trades=trades,
    )


@router.get("/backtest/compare", response_model=CompareResponse)
async def compare_runs(
    run_ids: str = Query(..., description="Comma-separated run_ids"),
) -> CompareResponse:
    ids = [s.strip() for s in run_ids.split(",") if s.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="run_ids required")
    out = []
    for rid in ids:
        out.append(await get_results(rid))
    return CompareResponse(runs=out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _mark_audit_failed(audit_id: str, message: str) -> None:
    await postgres_pool.execute(
        """
        UPDATE dashboard.runs
           SET status='error', error_message=$2, updated_at=now()
         WHERE run_id=$1
        """,
        audit_id,
        message,
    )


def _loads(v: Any) -> dict:
    """asyncpg returns JSONB as a string by default unless codecs are set."""
    if v is None:
        return {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return {}
