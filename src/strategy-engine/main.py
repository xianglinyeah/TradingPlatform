"""Main Entry Point - strategy_engine"""
import sys
import os
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config import settings
from src.engines.backtest_engine import BacktestEngine
from src.engines.live_engine import LiveEngine


def setup_logging():
    """Setup logging configuration - Console only, let K8s automatically collect to /var/log/pods/"""
    # Unified log format
    log_format = '[%(levelname).3s] %(message)s'

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Keep console output only - INFO level and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(log_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)


def main() -> None:
    """Main entry point: parse args and dispatch to the appropriate engine."""
    import argparse

    parser = argparse.ArgumentParser(description="Strategy Service")
    parser.add_argument(
        'mode',
        choices=['research', 'live'],
        help='Running mode: research (local development) or live (microservices with Kafka+gRPC)'
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config file (default: config/{mode}.yaml)'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)

    # Start Prometheus metrics server on :8000
    from src import metrics
    metrics.start(8000)
    logger.info("Prometheus metrics server started on :8000")

    # Determine config file
    if args.config is None:
        config_file = Path(__file__).parent / "config" / f"{args.mode}.yaml"
    else:
        config_file = Path(args.config)

    logger.info(f"Loading config from: {config_file}")

    # Run appropriate engine
    if args.mode == 'research':
        engine = BacktestEngine(str(config_file))
        results = engine.run()
        logger.info(f"\nResearch completed. Return: {results['return_pct']:.2f}%")

    elif args.mode == 'live':
        engine = LiveEngine(str(config_file))
        engine.run()


if __name__ == "__main__":
    main()
