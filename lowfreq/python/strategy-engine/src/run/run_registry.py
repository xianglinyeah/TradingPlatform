"""RunRegistry and RunContext - per-run_id strategy isolation.

A RunContext bundles everything the Kafka consumer needs to process bars
belonging to one replay/backtest run:

  - run_id (== SessionId, see module docstring)
  - strategy_name + params (the hot-loaded configuration)
  - strategy_instance (isolated state: positions, history, indicators)
  - status (active | completed | error)
  - created_at / last_activity_at (used by the GC sweep)

The registry is a thread-safe dict[run_id -> RunContext]. The FastAPI
endpoints write to it from the worker thread; the Kafka consumer reads
from it on the main thread. An RLock is sufficient because we never hold
the lock across I/O.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from ..common.strategy_registry import STRATEGY_CLASSES
from ..strategies import BaseStrategy

logger = logging.getLogger(__name__)


class RunStatus(str, Enum):
    """Lifecycle of a RunContext.

    Values are strings so they serialize straight to JSON in the API layer.
    """
    ACTIVE = "active"
    COMPLETED = "completed"
    ERROR = "error"


class UnknownRunError(KeyError):
    """Raised when a bar arrives for a run_id that was never registered.

    Usually means Dashboard.Service called /replay/start before
    /runs/{run_id}/config (a spec violation). The consumer drops the bar
    and logs an error rather than silently using the wrong strategy.
    """


@dataclass
class RunContext:
    """Isolated execution context for a single replay/backtest run."""
    run_id: str
    strategy_name: str
    params: dict
    strategy_instance: BaseStrategy
    symbols: List[str] = field(default_factory=list)
    exclude_symbols: List[str] = field(default_factory=list)
    status: RunStatus = RunStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    bars_processed: int = 0
    signals_generated: int = 0
    error_message: Optional[str] = None

    def touch(self) -> None:
        """Mark activity for GC sweep / staleness checks."""
        self.last_activity_at = time.time()

    def to_summary(self) -> dict:
        """JSON-serializable summary for the API layer.

        We intentionally do NOT serialize internal strategy state here -
        the canonical results live in PostgreSQL (orders/trades tables),
        queried via Dashboard.Service. This endpoint is just for
        liveness / debugging.
        """
        return {
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "params": self.params,
            "symbols": self.symbols,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "bars_processed": self.bars_processed,
            "signals_generated": self.signals_generated,
            "error_message": self.error_message,
        }


class RunRegistry:
    """Thread-safe registry of RunContext keyed by run_id.

    Designed to be a process-wide singleton. The Kafka consumer and the
    FastAPI worker share one instance.
    """

    def __init__(self) -> None:
        self._runs: Dict[str, RunContext] = {}
        self._lock = threading.RLock()

    # ---- write path (called by FastAPI endpoints) ----------------------

    def register(
        self,
        run_id: str,
        strategy_name: str,
        params: Optional[dict] = None,
        symbols: Optional[List[str]] = None,
        exclude_symbols: Optional[List[str]] = None,
    ) -> RunContext:
        """Create (or replace) a RunContext with a fresh strategy instance.

        Re-registering the same run_id is allowed: it resets strategy state.
        This is the intended behaviour when Dashboard.Service re-runs a
        backtest with the same run_id after a parameter change.
        """
        params = params or {}
        symbols = list(symbols or [])
        exclude_symbols = list(exclude_symbols or [])

        if strategy_name not in STRATEGY_CLASSES:
            raise ValueError(
                f"Unknown strategy '{strategy_name}'. "
                f"Available: {list(STRATEGY_CLASSES.keys())}"
            )

        strategy_class = STRATEGY_CLASSES[strategy_name]
        # Strategy `name` is what gets stamped on every signal/order as
        # strategy_id - keep it derived from run_id so Execution.Service
        # and PostgreSQL can be joined back to this run.
        strategy_instance = strategy_class(
            name=f"{strategy_name}::{run_id}",
            symbols=symbols,
            exclude_symbols=exclude_symbols,
            params=params,
        )

        ctx = RunContext(
            run_id=run_id,
            strategy_name=strategy_name,
            params=params,
            strategy_instance=strategy_instance,
            symbols=symbols,
            exclude_symbols=exclude_symbols,
        )

        with self._lock:
            self._runs[run_id] = ctx

        logger.info(
            "Registered run_id=%s strategy=%s params=%s",
            run_id, strategy_name, params,
        )
        return ctx

    # ---- read path (called by Kafka consumer) --------------------------

    def get(self, run_id: str) -> RunContext:
        """Fetch a RunContext or raise UnknownRunError.

        Caller (Kafka consumer) is expected to catch UnknownRunError and
        drop the bar with a loud log line - see live_engine.py.
        """
        with self._lock:
            ctx = self._runs.get(run_id)
        if ctx is None:
            raise UnknownRunError(run_id)
        return ctx

    def has(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._runs

    def list_runs(self) -> List[RunContext]:
        with self._lock:
            return list(self._runs.values())

    # ---- cleanup path --------------------------------------------------

    def mark_completed(self, run_id: str, error_message: Optional[str] = None) -> None:
        """Mark a run as finished. Does NOT remove from registry - the GC
        sweep below is responsible for that, after a grace period.

        The grace period matters: Execution.Service may still be settling
        the final orders when we receive the replay 'completed' sentinel,
        and Dashboard.Service polls /runs/{run_id} to confirm completion.
        """
        with self._lock:
            ctx = self._runs.get(run_id)
            if ctx is None:
                return
            ctx.status = RunStatus.ERROR if error_message else RunStatus.COMPLETED
            ctx.error_message = error_message

    def cleanup(self, run_id: str) -> bool:
        """Force-remove a run from the registry."""
        with self._lock:
            existed = run_id in self._runs
            self._runs.pop(run_id, None)
        if existed:
            logger.info("Cleaned up run_id=%s", run_id)
        return existed

    def sweep_stale(self, max_age_seconds: int = 3600) -> int:
        """Remove completed/error runs older than max_age_seconds.

        Called periodically by the API server's background sweeper. Active
        runs are never swept even if old - they may be long-running live
        trading sessions.
        """
        now = time.time()
        removed = 0
        with self._lock:
            stale_ids = [
                rid for rid, ctx in self._runs.items()
                if ctx.status != RunStatus.ACTIVE
                and (now - ctx.last_activity_at) > max_age_seconds
            ]
            for rid in stale_ids:
                self._runs.pop(rid, None)
                removed += 1
        if removed:
            logger.info("Swept %d stale run(s) from registry", removed)
        return removed


# Process-wide singleton. Both the FastAPI app and the engine import this.
_GLOBAL_REGISTRY = RunRegistry()


def get_global_registry() -> RunRegistry:
    return _GLOBAL_REGISTRY
