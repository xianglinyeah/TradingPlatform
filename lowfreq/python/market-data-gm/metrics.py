"""Prometheus metrics for market-data-gm.

Exposes on :8000/metrics. Scraped by Prometheus job 'market-data-gm'.
"""
from prometheus_client import Counter, start_http_server

bars_published = Counter(
    "marketdata_bars_published_total",
    "Total bars published to Kafka",
    ["symbol"],
)

kafka_publish_errors = Counter(
    "marketdata_kafka_publish_errors_total",
    "Total Kafka publish errors",
)


def start(port: int = 8000) -> None:
    """Start the Prometheus metrics HTTP server."""
    start_http_server(port)
