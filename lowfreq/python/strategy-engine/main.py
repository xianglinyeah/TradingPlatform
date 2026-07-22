"""Main Entry Point - strategy_engine"""
import sys
import os
import logging
import threading
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config import settings
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


def start_api_server(host: str = "0.0.0.0", port: int = 8080) -> threading.Thread:
    """Run the run-control FastAPI app in a daemon thread.

    The Kafka consumer blocks the main thread, so the HTTP server must
    run on a side thread. uvicorn.run() blocks until the server stops,
    hence the daemon thread - process exit will kill it.
    """
    import uvicorn
    from src.run import build_app

    app = build_app()

    def _serve():
        uvicorn.run(app, host=host, port=port, log_level="info")

    thread = threading.Thread(target=_serve, name="strategy-engine-api", daemon=True)
    thread.start()
    return thread


def main() -> None:
    """Main entry point: parse args and dispatch to the appropriate engine."""
    import argparse

    parser = argparse.ArgumentParser(description="Strategy Service")
    parser.add_argument(
        'mode',
        choices=['live', 'hot'],
        help='Running mode: live (Kafka+gRPC) '
             'or hot (live + run-control HTTP API for Dashboard.Service)',
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config file (default: config/{mode}.yaml)'
    )
    parser.add_argument(
        '--api-host',
        type=str,
        default='0.0.0.0',
        help='Host for the run-control HTTP API (default: 0.0.0.0)',
    )
    parser.add_argument(
        '--api-port',
        type=int,
        default=8080,
        help='Port for the run-control HTTP API (default: 8080)',
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)

    # Start Prometheus metrics server on :8000
    from src import metrics
    metrics.start(8000)
    logger.info("Prometheus metrics server started on :8000")

    # `hot` is an alias for live mode that also serves the run-control API
    # on :8080. This is the mode Dashboard.Service expects.
    if args.mode == 'hot':
        logger.info("Starting run-control HTTP API (hot mode) on %s:%d",
                    args.api_host, args.api_port)
        start_api_server(args.api_host, args.api_port)
        run_mode = 'live'
        config_mode = 'live'
    else:
        run_mode = args.mode
        config_mode = args.mode

    # Determine config file
    if args.config is None:
        config_file = Path(__file__).parent / "config" / f"{config_mode}.yaml"
    else:
        config_file = Path(args.config)

    logger.info(f"Loading config from: {config_file}")

    # Run appropriate engine (live is the only supported mode; `hot` is
    # promoted to `live` above before we reach here).
    if run_mode == 'live':
        engine = LiveEngine(str(config_file))
        engine.run()


if __name__ == "__main__":
    main()
