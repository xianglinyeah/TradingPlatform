"""Unit tests for ``broker.order_queue``.

Covers:
  * ``REQUEST_QUEUE`` is bounded (maxsize=1000) to prevent OOM if the GM
    SDK thread stalls.
  * ``PendingOrderRegistry`` register / get / pop / remove / clear
    semantics, including the documented "double-remove is safe" rule and
    basic thread safety under concurrent access.
"""
import queue
import threading
from concurrent.futures import Future

import pytest

from broker.order_queue import (
    PENDING_ORDERS,
    REQUEST_QUEUE,
    PendingOrderRegistry,
    PlaceOrderJob,
)


# ---------- REQUEST_QUEUE ----------

def test_request_queue_is_queue_queue():
    """REQUEST_QUEUE must be a stdlib ``queue.Queue`` (already thread-safe)."""
    assert isinstance(REQUEST_QUEUE, queue.Queue)


def test_request_queue_has_maxsize():
    """Queue is bounded at 1000 to fast-fail instead of OOM under backpressure."""
    assert REQUEST_QUEUE.maxsize == 1000


def test_request_queue_singleton_is_empty_at_import():
    """The module-level singleton starts drained so tests don't leak state.

    We drain rather than assume emptiness because earlier tests in the same
    session may have left items; we then put one back to confirm round-trip.
    """
    while not REQUEST_QUEUE.empty():
        REQUEST_QUEUE.get_nowait()
    assert REQUEST_QUEUE.empty()

    f: Future = Future()
    job = PlaceOrderJob(
        order_id="x",
        gm_symbol="SHSE.600000",
        gm_side=1,
        gm_order_type=1,
        quantity=100,
        price=7.19,
        account="acct",
        future=f,
    )
    REQUEST_QUEUE.put(job)
    assert REQUEST_QUEUE.qsize() == 1
    assert REQUEST_QUEUE.get_nowait() is job
    # Clean up for subsequent tests.
    assert REQUEST_QUEUE.empty()


def test_request_queue_full_raises_queue_full():
    """Putting past maxsize must raise ``queue.Full`` (fast-fail contract)."""
    # Use a local queue with the same maxsize to avoid poisoning the global
    # singleton in case another test runs concurrently.
    local_q: "queue.Queue[PlaceOrderJob]" = queue.Queue(maxsize=1000)
    f: Future = Future()
    job = PlaceOrderJob(
        order_id="x",
        gm_symbol="SHSE.600000",
        gm_side=1,
        gm_order_type=1,
        quantity=100,
        price=7.19,
        account="acct",
        future=f,
    )
    for _ in range(1000):
        local_q.put_nowait(job)
    assert local_q.full()
    with pytest.raises(queue.Full):
        local_q.put_nowait(job)


# ---------- PendingOrderRegistry: basic CRUD ----------

def test_pending_order_registry_register_and_get():
    """Register a future, then retrieve it by cl_ord_id."""
    reg = PendingOrderRegistry()
    f: Future = Future()
    reg.register("order-1", f)
    assert reg.get("order-1") is f


def test_pending_order_registry_get_missing_returns_none():
    """get() on an unknown id returns None (no KeyError)."""
    reg = PendingOrderRegistry()
    assert reg.get("does-not-exist") is None


def test_pending_order_registry_register_overwrites():
    """Re-registering the same cl_ord_id replaces the prior future."""
    reg = PendingOrderRegistry()
    old: Future = Future()
    new: Future = Future()
    reg.register("id", old)
    reg.register("id", new)
    assert reg.get("id") is new
    assert reg.get("id") is not old


def test_pending_order_registry_pop_returns_and_removes():
    """pop() returns the future AND removes it from the registry."""
    reg = PendingOrderRegistry()
    f: Future = Future()
    reg.register("pop-id", f)
    assert reg.pop("pop-id") is f
    # Second access must miss.
    assert reg.get("pop-id") is None
    assert reg.pop("pop-id") is None


def test_pending_order_registry_remove():
    """remove() deletes the entry; subsequent get() returns None."""
    reg = PendingOrderRegistry()
    f: Future = Future()
    reg.register("rm-id", f)
    reg.remove("rm-id")
    assert reg.get("rm-id") is None


def test_pending_order_registry_double_remove_safe():
    """Removing a non-existent id must not raise."""
    reg = PendingOrderRegistry()
    # Never registered.
    reg.remove("never-existed")
    # Remove twice in a row after registering.
    f: Future = Future()
    reg.register("dbl", f)
    reg.remove("dbl")
    reg.remove("dbl")  # second remove must be a no-op


def test_pending_order_registry_clear():
    """clear() empties the whole table."""
    reg = PendingOrderRegistry()
    reg.register("a", Future())
    reg.register("b", Future())
    reg.register("c", Future())
    reg.clear()
    assert reg.get("a") is None
    assert reg.get("b") is None
    assert reg.get("c") is None


# ---------- PendingOrderRegistry: thread safety ----------

def test_pending_order_registry_concurrent_register_pop():
    """Hammer register/pop from many threads; every pop returns a real future.

    This is a smoke test for the internal Lock: it should never raise and
    never return a half-constructed object. Total operations == N_WORKERS *
    N_PER_WORKER, and each registered id is unique.
    """
    reg = PendingOrderRegistry()
    N_WORKERS = 8
    N_PER_WORKER = 200
    popped: list = []
    pop_lock = threading.Lock()

    def producer(worker_id: int) -> None:
        for i in range(N_PER_WORKER):
            key = f"w{worker_id}-{i}"
            reg.register(key, Future())

    def consumer() -> None:
        seen = 0
        while seen < N_WORKERS * N_PER_WORKER:
            # Drain whatever is currently registered.
            for key in list(reg._table.keys()):
                fut = reg.pop(key)
                if fut is not None:
                    assert isinstance(fut, Future)
                    with pop_lock:
                        popped.append(fut)
                        seen = len(popped)
                        if seen >= N_WORKERS * N_PER_WORKER:
                            return

    threads = [threading.Thread(target=producer, args=(w,)) for w in range(N_WORKERS)]
    consumer_t = threading.Thread(target=consumer)
    for t in threads:
        t.start()
    consumer_t.start()
    for t in threads:
        t.join()
    consumer_t.join(timeout=10)

    assert len(popped) == N_WORKERS * N_PER_WORKER


# ---------- Module-level singleton sanity ----------

def test_pending_orders_singleton_is_registry_instance():
    """PENDING_ORDERS is the shared registry used by the strategy thread."""
    assert isinstance(PENDING_ORDERS, PendingOrderRegistry)


def test_pending_orders_singleton_does_not_leak_between_tests():
    """Each test owns its own PendingOrderRegistry(); the singleton must be
    left empty after we touch it so other tests are not affected.
    """
    PENDING_ORDERS.register("singleton-test", Future())
    assert PENDING_ORDERS.get("singleton-test") is not None
    PENDING_ORDERS.clear()
    assert PENDING_ORDERS.get("singleton-test") is None
