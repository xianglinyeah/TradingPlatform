"""Run isolation registry for hot-loaded strategy configurations.

This module provides per-run_id isolation of strategy state. Each replay/backtest
run registers its strategy + params via the HTTP API; the Kafka consumer then
routes incoming bars (which carry a SessionId) to the matching RunContext.

`run_id` re-uses the existing `SessionId` field on Kafka messages and gRPC
orders - we do NOT introduce a parallel identifier (see ADR: run_id == SessionId).
"""
from .run_registry import RunContext, RunRegistry, RunStatus, UnknownRunError
from .api_server import build_app, get_global_registry

__all__ = [
    "RunContext",
    "RunRegistry",
    "RunStatus",
    "UnknownRunError",
    "build_app",
    "get_global_registry",
]
