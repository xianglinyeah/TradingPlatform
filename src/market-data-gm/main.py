"""market_data_gm entry point.

Usage:
    python main.py [config.yaml]

Behaviour mirrors the C# `Program.cs`:
1. Load config (YAML replaces appsettings.json)
2. Init Kafka producer
3. Set GM token + module-level state
4. Block on gm.api.run() — SDK dispatches on_bar() each minute

Note: the `gm` SDK bundles _pb2.py files generated with protoc 3.x. They
require either protobuf<4 at runtime, or the pure-Python parser. We set the
env var here unconditionally so the process loads cleanly under modern
protobuf runtimes.
"""
from __future__ import annotations

import os
# MUST be set before any gm/protobuf import (gm SDK ships old _pb2 files).
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import logging
import logging.handlers
import sys
from datetime import datetime

from config import load_config


def _setup_logging(log_dir: str, level: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "marketdata-gm-realtime.log"),
        maxBytes=50 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    root.addHandler(console)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = argv[0] if argv else "config.yaml"

    cfg = load_config(config_path)

    _setup_logging(cfg.logging.dir, cfg.logging.level)
    log = logging.getLogger("market_data_gm")

    if not cfg.gm.token:
        log.error("GM_TOKEN not configured! Set gm.token in %s", config_path)
        return 1

    log.info("=== market-data-gm (Python) — config=%s ===", config_path)
    log.info("Subscribed symbols: %s", ", ".join(cfg.gm.symbols))
    log.info("Subscription frequency: %s", cfg.gm.frequency)
    log.info(
        "GM_TOKEN configured: %s***",
        cfg.gm.token[: min(10, len(cfg.gm.token))],
    )

    # Init Kafka producer (singleton)
    import kafka_producer
    kafka_producer.init(
        bootstrap_servers=cfg.kafka.bootstrap_servers,
        client_id=cfg.kafka.client_id,
    )

    # Inject runtime state into gm_strategy module before run()
    import gm_strategy
    session_id = f"{cfg.session_id_prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    gm_strategy.init_state(session_id=session_id, topic=cfg.kafka.market_data_topic)
    gm_strategy.prepare_subscriptions(cfg.gm.symbols, cfg.gm.frequency)

    # Init GM SDK
    from gm.api import set_token, set_serv_addr, run, MODE_LIVE

    set_token(cfg.gm.token)
    if cfg.gm.address:
        try:
            set_serv_addr(cfg.gm.address)
        except Exception as ex:
            log.warning("set_serv_addr failed (using default): %s", ex)

    log.info("Starting to receive real-time bar data (pushed every minute)...")
    try:
        # Blocks. The SDK discovers `init`, `on_bar`, `on_error` by name in
        # this file (filename=main.py).
        run(
            strategy_id=session_id,
            filename=__file__,
            mode=MODE_LIVE,
            token=cfg.gm.token,
        )
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as ex:
        log.exception("market_data_gm runtime failed: %s", ex)
        return 1
    finally:
        kafka_producer.close()
        log.info("market_data_gm stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
