"""Tests for RunRegistry - per-run_id strategy isolation.

Verifies the core invariant: two runs with the same strategy class but
different params have completely independent strategy state, even when
processing the same bars.
"""
import sys
from pathlib import Path

import pytest

# Ensure src/ is on the path when pytest is run from the project root.
SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.run.run_registry import RunRegistry, RunStatus, UnknownRunError  # noqa: E402


def test_register_creates_isolated_instances():
    """Two runs of the same strategy class must hold separate state."""
    registry = RunRegistry()

    ctx_a = registry.register("run-a", "MovingAverageStrategy",
                              params={"ema_period": 5}, symbols=["000001.SZ"])
    ctx_b = registry.register("run-b", "MovingAverageStrategy",
                              params={"ema_period": 50}, symbols=["600519.SH"])

    assert ctx_a.run_id == "run-a"
    assert ctx_b.run_id == "run-b"
    # Different instances, not shared state.
    assert ctx_a.strategy_instance is not ctx_b.strategy_instance
    assert ctx_a.strategy_instance.ema_period == 5
    assert ctx_b.strategy_instance.ema_period == 50
    # Strategy `name` is namespaced by run_id so orders route back.
    assert "::run-a" in ctx_a.strategy_instance.name
    assert "::run-b" in ctx_b.strategy_instance.name


def test_get_unknown_run_raises():
    registry = RunRegistry()
    with pytest.raises(UnknownRunError):
        registry.get("never-registered")


def test_has_and_cleanup():
    registry = RunRegistry()
    assert not registry.has("run-x")
    registry.register("run-x", "MovingAverageStrategy", params={})
    assert registry.has("run-x")
    assert registry.cleanup("run-x")
    assert not registry.has("run-x")
    # Idempotent: cleaning again returns False, no raise.
    assert not registry.cleanup("run-x")


def test_register_unknown_strategy_raises_value_error():
    registry = RunRegistry()
    with pytest.raises(ValueError):
        registry.register("run-z", "NoSuchStrategy", params={})


def test_sweep_preserves_active_runs():
    """The sweeper must never evict ACTIVE runs, only completed/error ones."""
    registry = RunRegistry()
    active = registry.register("active", "MovingAverageStrategy", params={})
    completed = registry.register("done", "MovingAverageStrategy", params={})
    registry.mark_completed("done")

    # Force last_activity_at into the past for both, beyond the sweep window.
    import time
    long_ago = time.time() - 7200
    active.last_activity_at = long_ago
    completed.last_activity_at = long_ago

    removed = registry.sweep_stale(max_age_seconds=3600)
    assert removed == 1
    assert registry.has("active")
    assert not registry.has("done")


def test_mark_completed_with_error_sets_status():
    registry = RunRegistry()
    registry.register("err", "MovingAverageStrategy", params={})
    registry.mark_completed("err", error_message="boom")
    ctx = registry.get("err")
    assert ctx.status == RunStatus.ERROR
    assert ctx.error_message == "boom"


def test_reregister_resets_state():
    """Re-registering the same run_id is allowed and resets state.

    Dashboard.Service may re-run a backtest with the same id after a
    parameter tweak; we must not leak the previous run's positions.
    """
    registry = RunRegistry()
    ctx1 = registry.register("dup", "MovingAverageStrategy",
                             params={"ema_period": 5})
    ctx1.strategy_instance.bar_count = 100
    ctx1.strategy_instance.positions["000001.SZ"] = object()

    ctx2 = registry.register("dup", "MovingAverageStrategy",
                             params={"ema_period": 50})
    assert ctx2.strategy_instance.bar_count == 0
    assert ctx2.strategy_instance.positions == {}
    assert ctx2.strategy_instance.ema_period == 50
