"""FastAPI app exposing run registration + strategy metadata.

Endpoints (mounted on port 8080, run in a daemon thread from main.py):

  POST   /runs/{run_id}/config    Register strategy + params for a run
  GET    /runs/{run_id}           Inspect a run (liveness/debug)
  GET    /runs                    List all known runs
  DELETE /runs/{run_id}           Force-remove a run
  GET    /strategies              List registered strategies + param schema
  GET    /health                  Liveness probe (for k8s)

Dashboard.Service orchestrates a backtest by calling:
  1. POST /runs/{run_id}/config   (this file)
  2. POST /api/Replay/start       (market-data-replay, with same run_id as
                                   SessionId - market-data-replay generates
                                   the SessionId, so Dashboard.Service must
                                   use the returned value here)

The two calls MUST be ordered: config first, replay second. See
marketdata-replay-strategy-engine-spec.md section 4.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..common.strategy_registry import STRATEGY_CLASSES
from .run_registry import RunRegistry, RunStatus, UnknownRunError, get_global_registry


# ---------------------------------------------------------------------------
# Request/response models (Pydantic v2)
# ---------------------------------------------------------------------------

class RunConfigRequest(BaseModel):
    """Body for POST /runs/{run_id}/config.

    `symbols` is optional: when omitted the strategy processes every bar
    routed to its run_id (filtered only by the global SymbolMatcher if any).
    """
    strategy_name: str = Field(..., description="Key in STRATEGY_CLASSES, e.g. 'MovingAverageStrategy'")
    params: Dict[str, object] = Field(default_factory=dict)
    symbols: Optional[List[str]] = Field(
        default=None,
        description="Symbol whitelist; None means no symbol filtering at the run level",
    )
    exclude_symbols: Optional[List[str]] = Field(default=None)


class RunConfigResponse(BaseModel):
    registered: bool
    run_id: str
    strategy_name: str
    params: Dict[str, object]


class StrategyMetadata(BaseModel):
    name: str
    class_name: str
    display_name: str
    description: str
    params_schema: List[dict]


class StrategiesResponse(BaseModel):
    strategies: List[StrategyMetadata]


class HealthResponse(BaseModel):
    status: str
    runs_active: int
    runs_total: int
    uptime_seconds: float


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_APP: Optional[FastAPI] = None
_APP_LOCK = threading.Lock()
_START_TIME = time.time()
_SWEEPER_STARTED = False


def _strategy_metadata() -> List[StrategyMetadata]:
    out: List[StrategyMetadata] = []
    for class_name, cls in STRATEGY_CLASSES.items():
        out.append(
            StrategyMetadata(
                # Use the class name as the canonical `name`. Configs refer to
                # strategies by class_name (see STRATEGY_CLASSES keys). We also
                # expose `display_name` for UI rendering.
                name=class_name,
                class_name=class_name,
                display_name=getattr(cls, "DISPLAY_NAME", "") or class_name,
                description=getattr(cls, "DESCRIPTION", "") or "",
                params_schema=list(getattr(cls, "PARAMS_SCHEMA", []) or []),
            )
        )
    return out


def _start_sweeper_if_needed(registry: RunRegistry) -> None:
    """Start a background thread that reaps stale completed runs.

    Runs are tiny but unbounded; without this the registry grows forever
    in a long-lived service. Active runs are preserved.
    """
    global _SWEEPER_STARTED
    if _SWEEPER_STARTED:
        return
    _SWEEPER_STARTED = True

    def _loop():
        # Sweep once per 5 minutes; window is 1 hour of inactivity after
        # completion before eviction. Active runs are immune.
        while True:
            time.sleep(300)
            try:
                registry.sweep_stale(max_age_seconds=3600)
            except Exception as exc:  # pragma: no cover - defensive
                # Never let the sweeper die; a transient failure should not
                # take down cleanup permanently.
                import logging
                logging.getLogger(__name__).warning("Run sweeper error: %s", exc)

    t = threading.Thread(target=_loop, name="run-registry-sweeper", daemon=True)
    t.start()


def build_app(registry: Optional[RunRegistry] = None) -> FastAPI:
    """Construct the FastAPI app bound to a specific registry.

    Defaults to the process-wide singleton so the Kafka consumer (which
    also imports the singleton) and the API see the same data.
    """
    global _APP
    with _APP_LOCK:
        if _APP is not None:
            return _APP

        if registry is None:
            registry = get_global_registry()

        app = FastAPI(
            title="strategy-engine run control",
            version="1.0.0",
            description="Hot-load strategy configs and query strategy metadata",
        )

        @app.get("/health", response_model=HealthResponse)
        def health():
            runs = registry.list_runs()
            active = sum(1 for r in runs if r.status == RunStatus.ACTIVE)
            return HealthResponse(
                status="ok",
                runs_active=active,
                runs_total=len(runs),
                uptime_seconds=time.time() - _START_TIME,
            )

        @app.get("/strategies", response_model=StrategiesResponse)
        def list_strategies():
            return StrategiesResponse(strategies=_strategy_metadata())

        @app.post("/runs/{run_id}/config", response_model=RunConfigResponse)
        def register_run(run_id: str, body: RunConfigRequest):
            try:
                ctx = registry.register(
                    run_id=run_id,
                    strategy_name=body.strategy_name,
                    params=body.params,
                    symbols=body.symbols,
                    exclude_symbols=body.exclude_symbols,
                )
            except ValueError as exc:
                # Unknown strategy name - 400 is the right code (client error).
                raise HTTPException(status_code=400, detail=str(exc))
            return RunConfigResponse(
                registered=True,
                run_id=ctx.run_id,
                strategy_name=ctx.strategy_name,
                params=ctx.params,
            )

        @app.get("/runs/{run_id}")
        def get_run(run_id: str):
            try:
                ctx = registry.get(run_id)
            except UnknownRunError:
                raise HTTPException(status_code=404, detail=f"run_id={run_id} not registered")
            return ctx.to_summary()

        @app.get("/runs")
        def list_runs():
            return [ctx.to_summary() for ctx in registry.list_runs()]

        @app.delete("/runs/{run_id}")
        def delete_run(run_id: str):
            removed = registry.cleanup(run_id)
            if not removed:
                raise HTTPException(status_code=404, detail=f"run_id={run_id} not registered")
            return {"deleted": True, "run_id": run_id}

        _start_sweeper_if_needed(registry)
        _APP = app
        return app
