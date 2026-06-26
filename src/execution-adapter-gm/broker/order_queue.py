"""Thread-safe request queue + Future registry.

Bridges the gRPC thread pool and the GM Strategy event loop:

  gRPC thread → REQUEST_QUEUE  → strategy thread (calls order_volume inside run())
  GM callback thread → PENDING_ORDERS registry (matches cl_ord_id → Future)

`REQUEST_QUEUE` is a plain `queue.Queue` (already thread-safe).
`PENDING_ORDERS` is a dict guarded by a Lock.
"""
from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class PlaceOrderJob:
    """A request enqueued by the gRPC PlaceOrder handler.

    `order_id` is the client-supplied cl_ord_id used as the registry key.
    """
    order_id: str
    gm_symbol: str
    gm_side: int
    gm_order_type: int
    quantity: int
    price: float
    account: str
    future: "Future[Any]"


# Bounded queue so a stalled GM SDK thread surfaces as queue.Full instead of OOM.
REQUEST_QUEUE: "queue.Queue[PlaceOrderJob]" = queue.Queue(maxsize=1000)


class PendingOrderRegistry:
    """cl_ord_id → Future registry, populated by the strategy thread and
    resolved by `on_order_status` (on the GM callback thread)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._table: dict[str, Future] = {}

    def register(self, cl_ord_id: str, future: Future) -> None:
        with self._lock:
            self._table[cl_ord_id] = future

    def pop(self, cl_ord_id: str) -> Optional[Future]:
        with self._lock:
            return self._table.pop(cl_ord_id, None)

    def get(self, cl_ord_id: str) -> Optional[Future]:
        with self._lock:
            return self._table.get(cl_ord_id)

    def remove(self, cl_ord_id: str) -> None:
        with self._lock:
            self._table.pop(cl_ord_id, None)

    def pop_any(self) -> Optional[tuple]:
        """Return and remove any single pending (cl_ord_id, future). Used as
        a fallback when on_order_status fires with a server-assigned cl_ord_id
        that does not match the client-supplied key. Safe because the poll
        loop processes orders one at a time.
        """
        with self._lock:
            if not self._table:
                return None
            cl_ord_id = next(iter(self._table))
            future = self._table.pop(cl_ord_id)
            return cl_ord_id, future

    def clear(self) -> None:
        with self._lock:
            self._table.clear()


# Singleton registry — on_order_status needs to reach it from module scope.
PENDING_ORDERS = PendingOrderRegistry()
