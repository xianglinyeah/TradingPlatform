"""GM Strategy callbacks for market_data_gm.

Python GM SDK uses module-level functions discovered by name from the file
pointed to by `run(filename=...)`. The required callbacks are:

  init(context)          — called once at startup, used to subscribe
  on_bar(context, bars)  — called when a new bar arrives (per frequency)
  on_error(context, code, msg)  — error callback (optional but recommended)

We attach runtime state (config, sequence counter) to the `context` object
so the callbacks can reach them without module-level globals.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

import kafka_producer
import market_event
import metrics
import symbol_converter

logger = logging.getLogger("gm_strategy")

# Module-level state; populated by `init_state()` before run() is called.
_state_lock = threading.Lock()
_state: dict = {
    "session_id": "",
    "topic": "",
    "sequence": 0,
}


def init_state(*, session_id: str, topic: str) -> None:
    """Inject runtime state before `run()` is invoked."""
    with _state_lock:
        _state["session_id"] = session_id
        _state["topic"] = topic
        _state["sequence"] = 0


def _next_sequence() -> int:
    with _state_lock:
        _state["sequence"] += 1
        return _state["sequence"]


def init(context):
    """GM SDK init callback: subscribe to all configured symbols.

    NOTE: The list of symbols and frequency are baked into the module before
    `run()` is invoked by calling `prepare_subscriptions()`. The GM Python SDK
    does not allow passing config through context, so we set module-level
    globals instead.
    """
    logger.info("GM real-time data service started (event-driven mode)")
    logger.info("Subscription frequency: %s", _SUBSCRIPTION["frequency"])

    from gm.api import subscribe

    symbols = _SUBSCRIPTION["symbols"]
    frequency = _SUBSCRIPTION["frequency"]
    # `subscribe` accepts a single symbol string or a list. We subscribe to
    # all symbols in one call (wait_group=True waits for full snapshot).
    try:
        subscribe(symbols=symbols, frequency=frequency, count=1)
        for s in symbols:
            logger.info("Subscribed to real-time bar (%s): %s", frequency, s)
    except Exception as ex:
        logger.exception("subscribe() failed: %s", ex)
        raise

    logger.info(
        "GM real-time data service startup completed, waiting for bar push..."
    )


# Module-level subscription config, set by `prepare_subscriptions()`.
_SUBSCRIPTION: dict = {"symbols": [], "frequency": "60s"}


def prepare_subscriptions(symbols: list[str], frequency: str) -> None:
    _SUBSCRIPTION["symbols"] = list(symbols)
    _SUBSCRIPTION["frequency"] = frequency


def on_bar(context, bars):
    """GM SDK on_bar callback: publish each bar to Kafka as a MarketDataEvent."""
    if bars is None:
        return
    for bar in bars:
        try:
            sequence = _next_sequence()
            event = market_event.from_gm_bar(
                bar,
                symbol_converter=symbol_converter.from_gm,
                session_id=_state["session_id"],
                sequence_number=sequence,
                replay_time=datetime.now(timezone.utc),
            )
            payload = event.to_json()
            kafka_producer.publish(_state["topic"], payload)

            logger.info(
                "Published real-time bar: %s %s O:%s H:%s L:%s C:%s V:%s",
                event.Symbol,
                event.EventTime,
                event.Open,
                event.High,
                event.Low,
                event.Close,
                event.Volume,
            )
            metrics.bars_published.labels(symbol=event.Symbol).inc()
        except Exception as ex:
            metrics.kafka_publish_errors.inc()
            logger.exception("Failed to process real-time bar: %s", ex)


def on_error(context, code, msg) -> None:
    """GM SDK error callback."""
    logger.error("GM SDK error: code=%s msg=%s", code, msg)
