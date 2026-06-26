"""Prometheus metrics for strategy-engine.

Exposes on :8000/metrics. Scraped by Prometheus job 'strategy-engine'.
"""
from prometheus_client import Counter, Histogram, start_http_server

bars_processed = Counter(
    "strategy_bars_processed_total",
    "Total market data bars processed",
    ["symbol"],
)

signals_generated = Counter(
    "strategy_signals_generated_total",
    "Total trading signals generated",
    ["strategy_name", "symbol", "side"],
)

bar_processing_duration = Histogram(
    "strategy_bar_processing_duration_seconds",
    "Time spent processing one bar (per strategy)",
    ["strategy_name"],
    buckets=(0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)

orders_placed = Counter(
    "strategy_orders_placed_total",
    "Total orders submitted to execution service",
    ["strategy_name", "symbol", "side"],
)

orders_filled = Counter(
    "strategy_orders_filled_total",
    "Total orders that were filled",
    ["strategy_name", "symbol", "side"],
)

orders_rejected = Counter(
    "strategy_orders_rejected_total",
    "Total orders rejected by execution service",
    ["strategy_name", "symbol"],
)


def start(port: int = 8000) -> None:
    """Start the Prometheus metrics HTTP server."""
    start_http_server(port)
