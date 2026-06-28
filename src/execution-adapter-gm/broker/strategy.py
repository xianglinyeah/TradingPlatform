"""GM Strategy callbacks for execution_adapter_gm.

The Python GM SDK requires `order_volume` to be called from the strategy
thread (the one that runs `run()`). The gRPC servicer runs on a worker pool,
so PlaceOrder requests are handed to the strategy thread via REQUEST_QUEUE.

Lifecycle:
  init(context)              → start order-poll daemon thread
  on_schedule(context)       → drain REQUEST_QUEUE, call order_volume
  on_order_status(ctx, ord)  → resolve pending Future by cl_ord_id
  on_execution_report(ctx, rpt) → log fill details
  on_error(ctx, code, msg)   → log
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from broker import enums as order_enums
from broker.order_queue import PENDING_ORDERS, REQUEST_QUEUE, PlaceOrderJob

logger = logging.getLogger("gm_strategy")


# Runtime config — set via `prepare()` before `run()`.
_RUN_CFG: dict = {
    "poll_frequency_ms": 200,
    "session_start": "09:15",
    "session_end": "15:30",
    "account": "",  # default account (paper or live)
    "strategy_id": "gm-trading-adaptor",
    # Per-order broker acknowledgement timeout (seconds). Override via
    # prepare(..., order_ack_timeout_seconds=...). Kept separate from the
    # gRPC servicer's default_timeout_seconds (which is the end-to-end gRPC
    # budget) — the broker ack should normally complete well within that.
    "order_ack_timeout_seconds": 30,
}

# Whether `init()` has been invoked (used by main.py for sanity log).
_initialized = threading.Event()

# Cooperative shutdown signal for the order-poll thread. Set by shutdown()
# below; the poll loop checks this between iterations so the daemon thread
# can exit cleanly instead of being killed mid-order on process termination.
_STOP = threading.Event()


def prepare(
    *,
    account: str,
    strategy_id: str,
    poll_frequency_ms: int = 200,
    session_start: str = "09:15",
    session_end: str = "15:30",
    order_ack_timeout_seconds: int = 30,
) -> None:
    _RUN_CFG["account"] = account
    _RUN_CFG["strategy_id"] = strategy_id
    _RUN_CFG["poll_frequency_ms"] = poll_frequency_ms
    _RUN_CFG["session_start"] = session_start
    _RUN_CFG["session_end"] = session_end
    _RUN_CFG["order_ack_timeout_seconds"] = order_ack_timeout_seconds


def init(context):
    """GM SDK init callback. Keeps the strategy thread alive for `order_volume`
    calls and starts a daemon thread that drains REQUEST_QUEUE once per second.
    The poll thread checks the module-level _STOP event each iteration so
    `shutdown()` can stop it cleanly without losing in-flight order results.
    """
    logger.info(
        "[GM_TRADING] Initializing GM trading service (strategy_id=%s, account=%s)",
        _RUN_CFG["strategy_id"],
        _RUN_CFG["account"] or "(default)",
    )

    import time as _time

    def _poll_loop():
        while not _STOP.is_set():
            try:
                on_schedule(context)
            except Exception as ex:
                logger.exception("[GM_TRADING] poll loop error: %s", ex)
            # Short sleeps so shutdown signal is observed within ~1s.
            _STOP.wait(1.0)
        logger.info("[GM_TRADING] Order poll thread exiting (shutdown requested)")

    t = threading.Thread(target=_poll_loop, name="order-poll", daemon=True)
    t.start()
    logger.info("[GM_TRADING] Order poll thread started (1s interval)")

    _initialized.set()
    logger.info("[GM_TRADING] GM trading service initialized successfully")


def shutdown(timeout_seconds: float = 5.0) -> None:
    """Signal the order-poll thread to stop and wait briefly for it to drain.

    Called from main.py during process shutdown. The GM SDK's own event loop
    (running on the gm-strategy thread) does not expose a clean stop API, so
    that thread stays daemon=True and will be killed when the process exits.
    The poll thread, however, can stop cooperatively — and any `_submit_order`
    call it's currently inside will finish (or hit its 30s future timeout)
    before the loop checks _STOP again, so we don't lose order results.
    """
    _STOP.set()
    deadline = _time.time() + timeout_seconds
    # Allow the in-flight on_schedule() iteration to finish so we don't cut
    # an order placement in half.
    while _time.time() < deadline and _STOP.is_set():
        # No thread handle to join (we didn't store it); rely on the loop
        # exiting on its own within the timeout. Poll-log surfaces if it didn't.
        _time.sleep(0.2)
        # Best-effort: if the queue is empty, we know the loop is idle.
        if REQUEST_QUEUE.empty():
            break
    logger.info("[GM_TRADING] shutdown() complete")


# Module-level import for shutdown()'s use; kept lazy to avoid cluttering
# module import order during SDK initialization.
import time as _time  # noqa: E402


def on_schedule(context):
    """Drain REQUEST_QUEUE and submit each order via `order_volume`."""
    from gm.api import order_volume

    drained = 0
    while True:
        try:
            job: PlaceOrderJob = REQUEST_QUEUE.get_nowait()
        except Exception:
            break

        drained += 1
        try:
            _submit_order(order_volume, job)
        except Exception as ex:
            logger.exception(
                "[GM_TRADING] order_volume exception for order_id=%s: %s",
                job.order_id,
                ex,
            )
            if not job.future.done():
                job.future.set_exception(ex)

    if drained:
        logger.info("[GM_TRADING] Drained %d order(s) from queue", drained)


def _submit_order(order_volume_fn, job: PlaceOrderJob) -> None:
    """Place an order and block until it reaches a terminal state (or 30s timeout)."""
    logger.info(
        "[GM_TRADING] Placing order: order_id=%s symbol=%s side=%d type=%d qty=%d @ %.4f account=%s",
        job.order_id,
        job.gm_symbol,
        job.gm_side,
        job.gm_order_type,
        job.quantity,
        job.price,
        job.account or "(default)",
    )

    # Register before order_volume: the SDK may dispatch on_order_status from a
    # separate thread during the call. Keyed under our own order_id; the callback
    # falls back to pop_any() when the server-assigned cl_ord_id does not match.
    PENDING_ORDERS.register(job.order_id, job.future)

    order = order_volume_fn(
        symbol=job.gm_symbol,
        volume=job.quantity,
        side=job.gm_side,
        order_type=job.gm_order_type,
        position_effect=order_enums.position_effect_open(),
        price=job.price,
        account=job.account or "",
    )

    if order is None:
        # SDK reported failure synchronously
        PENDING_ORDERS.remove(job.order_id)
        if not job.future.done():
            job.future.set_exception(
                RuntimeError("GM order_volume returned None (rejected by SDK)")
            )
        return

    cl_ord_id = getattr(order, "cl_ord_id", None) or job.order_id
    logger.info(
        "[GM_TRADING] GM order placed: cl_ord_id=%s status=%s symbol=%s",
        cl_ord_id,
        getattr(order, "status", "?"),
        getattr(order, "symbol", "?"),
    )

    if order_enums.is_gm_status_final(int(getattr(order, "status", 0))):
        logger.info(
            "[GM_TRADING] Order already final: cl_ord_id=%s status=%s",
            cl_ord_id,
            order.status,
        )
        PENDING_ORDERS.remove(job.order_id)
        if not job.future.done():
            job.future.set_result(order)
        return

    # Block until on_order_status resolves the Future. This serializes order
    # processing so at most one order is in-flight, keeping pop_any() safe.
    try:
        order = job.future.result(timeout=_RUN_CFG["order_ack_timeout_seconds"])
        logger.info(
            "[GM_TRADING] Order resolved via callback: cl_ord_id=%s status=%s",
            cl_ord_id,
            getattr(order, "status", "?"),
        )
    except Exception as ex:
        PENDING_ORDERS.remove(job.order_id)
        if not job.future.done():
            job.future.set_exception(ex)
        raise


# ---------- GM SDK event callbacks ----------


def on_order_status(context, order):
    """Fired by the SDK when an order's state changes. Resolve any Future
    registered under `order.cl_ord_id` once the status is final."""
    cl_ord_id = getattr(order, "cl_ord_id", None)
    status = getattr(order, "status", "?")
    symbol = getattr(order, "symbol", "?")
    logger.info(
        "[GM_TRADING] Order status changed: cl_ord_id=%s status=%s symbol=%s side=%s",
        cl_ord_id,
        status,
        symbol,
        getattr(order, "side", "?"),
    )

    if cl_ord_id is None:
        logger.warning("[GM_TRADING] Order status with no cl_ord_id; ignoring")
        return

    future = PENDING_ORDERS.get(cl_ord_id)
    if future is None:
        # Server may assign a different cl_ord_id than the client-supplied one.
        # Fall back to the single in-flight Future (orders are processed serially).
        entry = PENDING_ORDERS.pop_any()
        if entry is None:
            logger.debug(
                "[GM_TRADING] No pending Future for cl_ord_id=%s (likely query-only)",
                cl_ord_id,
            )
            return
        registered_id, future = entry
        logger.info(
            "[GM_TRADING] cl_ord_id mismatch (callback=%s, registered=%s); resolving by fallback",
            cl_ord_id, registered_id,
        )

    if not order_enums.is_gm_status_final(int(status)):
        # Not terminal yet; re-register so subsequent callbacks can still find it.
        PENDING_ORDERS.register(cl_ord_id, future)
        return

    if not future.done():
        future.set_result(order)
    PENDING_ORDERS.remove(cl_ord_id)

    if int(status) == order_enums.OrderStatus_Rejected:
        reason = getattr(order, "ord_rej_reason", "") or getattr(order, "reject_reason", "") or "(no reason field)"
        logger.warning(
            "[GM_TRADING] Order REJECTED: cl_ord_id=%s symbol=%s reason=%s",
            cl_ord_id, symbol, reason,
        )
    logger.info(
        "[GM_TRADING] Order completed, removed from pending list: cl_ord_id=%s",
        cl_ord_id,
    )


def on_execution_report(context, rpt) -> None:
    """Log execution report details (informational only)."""
    logger.info(
        "[GM_TRADING] Execution report: cl_ord_id=%s qty=%s price=%s",
        getattr(rpt, "cl_ord_id", "?"),
        getattr(rpt, "volume", "?"),
        getattr(rpt, "price", "?"),
    )


def on_error(context, code, msg) -> None:
    """GM SDK error callback."""
    logger.error("[GM_TRADING] GM SDK error: code=%s msg=%s", code, msg)


def on_backtest_finished(context, indicator):
    """Not used in live mode but defined for completeness."""
    logger.info("[GM_TRADING] Backtest finished (not applicable in live mode)")


# Direct query helpers (called by gRPC query handlers).
# Safe from any thread (no state mutation), mirroring the C# implementation.


def query_cash(account: str):
    """Query cash balance. Wraps the single DictLikeObject returned by the SDK
    in a list so callers can iterate uniformly."""
    from gm.api import get_cash
    result = get_cash(account_id=account or None)
    return [result] if result is not None else []


def query_position(account: str):
    """Query positions for the given account."""
    from gm.api import get_position
    return get_position(account_id=account or None)


def query_orders():
    """Query all orders."""
    from gm.api import get_orders
    return get_orders()


def cancel_order(order_id: str, account: str) -> int:
    """Order cancel — takes a list of dicts per SDK signature."""
    from gm.api import order_cancel
    result = order_cancel([{"cl_ord_id": order_id, "account_id": account or ""}])
    return result if isinstance(result, int) else 0
