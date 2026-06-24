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

    `order_id` is the client-supplied cl_ord_id. After `order_volume` returns
    we record the Future under both the client cl_ord_id and any native id the
    SDK assigns (we trust they match — the C# version also keys on cl_ord_id).
    """
    order_id: str
    gm_symbol: str
    gm_side: int
    gm_order_type: int
    quantity: int
    price: float
    account: str
    future: "Future[Any]"


# Thread-safe queue consumed by the strategy thread.
# maxsize=1000 prevents unbounded growth if the GM SDK thread stalls —
# instead, PlaceOrder will fast-fail with queue.Full rather than OOM the process.
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

    def clear(self) -> None:
        with self._lock:
            self._table.clear()


# Singleton registry — on_order_status needs to reach it from module scope.
PENDING_ORDERS = PendingOrderRegistry()
