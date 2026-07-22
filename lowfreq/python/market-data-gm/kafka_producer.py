"""Kafka producer wrapper (confluent-kafka).

Singleton-style module-level producer. Mirrors the C# DI-registered
`IProducer<Null, string>` with `EnableIdempotence = true`.
"""
from __future__ import annotations

import logging
from typing import Optional

from confluent_kafka import Producer

logger = logging.getLogger(__name__)

_producer: Optional[Producer] = None


def init(bootstrap_servers: str, client_id: str) -> None:
    global _producer
    if _producer is not None:
        return
    _producer = Producer(
        {
            "bootstrap.servers": bootstrap_servers,
            "client.id": client_id,
            "enable.idempotence": True,
            "acks": "all",
            "linger.ms": 0,
        }
    )
    logger.info(
        "Kafka producer initialized: bootstrap=%s client_id=%s",
        bootstrap_servers,
        client_id,
    )


def _delivery_callback(err, msg) -> None:
    if err is not None:
        logger.error("Kafka delivery failed: %s (topic=%s)", err, msg.topic())


def publish(topic: str, value: str) -> None:
    """Produce a single string message. Triggers poll for delivery callbacks."""
    if _producer is None:
        raise RuntimeError("kafka_producer.init() must be called before publish()")
    _producer.produce(topic, value=value.encode("utf-8"), callback=_delivery_callback)
    # Service delivery callbacks promptly (non-blocking).
    _producer.poll(0)


def flush(timeout: float = 5.0) -> None:
    """Flush pending messages to the Kafka broker."""
    if _producer is not None:
        _producer.flush(timeout)


def close() -> None:
    global _producer
    if _producer is not None:
        try:
            _producer.flush(5.0)
        finally:
            _producer = None
