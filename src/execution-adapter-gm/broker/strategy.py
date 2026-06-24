"""GM Strategy callbacks for execution_adapter_gm.

Python GM SDK requires `order_volume` (and friends) to be called from the
strategy thread (the same thread that runs `run()`). The gRPC servicer runs
on a worker pool — so we hand requests to the strategy thread via a queue.

The strategy thread polls the queue inside `schedule(...)`. The Python SDK's
`schedule(schedule_func, date_rule, time_rule)` fires `schedule_func` on the
strategy thread at minute granularity during the configured session window.
That's acceptable: PlaceOrder has a 30s future timeout, far longer than one
poll interval.

Lifecycle:
  init(context)           → set up schedule + subscriptions
  on_schedule(context)    → drain REQUEST_QUEUE, call order_volume, register Future
  on_order_status(ctx, order) → resolve pending Future by cl_ord_id
  on_execution_report(ctx, rpt) → log fill details (informational)
  on_error(ctx, code, msg)     → log
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
}

# Whether `init()` has been invoked (used by main.py for sanity log).
_initialized = threading.Event()


def prepare(
    *,
    account: str,
    strategy_id: str,
    poll_frequency_ms: int = 200,
    session_start: str = "09:15",
    session_end: str = "15:30",
) -> None:
    _RUN_CFG["account"] = account
    _RUN_CFG["strategy_id"] = strategy_id
    _RUN_CFG["poll_frequency_ms"] = poll_frequency_ms
    _RUN_CFG["session_start"] = session_start
    _RUN_CFG["session_end"] = session_end


def init(context):
    """GM SDK init callback. We don't subscribe to any market data feed —
    only need the strategy thread alive so we can call `order_volume` from it.
    Register a schedule to drain the request queue during the trading session.
    """
    from gm.api import schedule

    logger.info(
        "[GM_TRADING] Initializing GM trading service (strategy_id=%s, account=%s)",
        _RUN_CFG["strategy_id"],
        _RUN_CFG["account"] or "(default)",
    )

    # `schedule` fires `on_schedule` once per minute during the session window.
    # minute granularity is the finest interval supported by the SDK.
    time_rule = f"{_RUN_CFG['session_start']}-{_RUN_CFG['session_end']}"
    try:
        schedule(on_schedule, date_rule="1d", time_rule=time_rule)
        logger.info(
            "[GM_TRADING] Schedule registered: date_rule=1d time_rule=%s",
            time_rule,
        )
    except Exception as ex:
        logger.exception("[GM_TRADING] schedule() failed: %s", ex)
        raise

    _initialized.set()
    logger.info("[GM_TRADING] GM trading service initialized successfully")


def on_schedule(context):
    """Drain the request queue and submit each order via `order_volume`.

    Runs on the strategy thread (the only thread from which trading calls
    may be issued).
    """
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
    """Call order_volume on the strategy thread, then register the Future under
    the returned cl_ord_id. Final-state orders resolve the Future immediately."""
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

    # Register Future so on_order_status can resolve it. If the order is
    # already final, resolve immediately (don't wait for a callback).
    PENDING_ORDERS.register(cl_ord_id, job.future)

    if order_enums.is_gm_status_final(int(getattr(order, "status", 0))):
        logger.info(
            "[GM_TRADING] Order already final: cl_ord_id=%s status=%s",
            cl_ord_id,
            order.status,
        )
        if not job.future.done():
            job.future.set_result(order)
        PENDING_ORDERS.remove(cl_ord_id)


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
        logger.debug(
            "[GM_TRADING] No pending Future for cl_ord_id=%s (likely query-only)",
            cl_ord_id,
        )
        return

    if not order_enums.is_gm_status_final(int(status)):
        # Submitted / PartiallyFilled / etc — keep waiting
        return

    if not future.done():
        future.set_result(order)
    PENDING_ORDERS.remove(cl_ord_id)
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


# ---------- Direct trading calls (used by gRPC query handlers) ----------
#
# These query functions are safe to call from any thread per the C# implementation
# (GetCash/GetPosition/GetOrders don't modify state). If the Python SDK turns out
# to be stricter, the call sites fall back to enqueuing onto REQUEST_QUEUE.


def query_cash(account: str):
    """Query cash balance for the given account."""
    from gm.api import get_cash
    return get_cash(account_id=account or None)


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
