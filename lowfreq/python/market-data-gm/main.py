"""market_data_gm entry point. Subscribes to GM real-time bars and publishes
them to Kafka. Blocks on gm.api.run(); the SDK dispatches on_bar() each minute.

The `gm` SDK ships _pb2.py files generated with protoc 3.x, which require
either protobuf<4 at runtime or the pure-Python parser. We set the env var
unconditionally so the process loads cleanly under modern protobuf runtimes.
"""
from __future__ import annotations

import os
# Must be set before any gm/protobuf import (gm SDK ships old _pb2 files).
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import logging
import logging.handlers
import sys
from datetime import datetime

from config import load_config
# GM SDK discovers `init`, `on_bar`, and `on_error` by name in the module
# referenced by `run(filename=...)`. Since `run(filename=__file__)` points
# here, these symbols must be importable from this module's namespace.
from gm_strategy import init, on_bar, on_error  # noqa: F401


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


def _resolve_symbols(cfg, log) -> list[str]:
    """Resolve subscription symbols. universe_id wins over explicit symbols list.

    Reads from market_ref.universe_member via UNIVERSE_PG_CONN env var
    (Npgsql-style connection string). Returns GM-format symbols.
    """
    if not cfg.gm.universe_id:
        return list(cfg.gm.symbols)

    conn_str = os.getenv("UNIVERSE_PG_CONN")
    if not conn_str:
        log.error(
            "gm.universe_id=%s set but UNIVERSE_PG_CONN env var is not configured; "
            "falling back to explicit symbols list",
            cfg.gm.universe_id,
        )
        return list(cfg.gm.symbols)

    import psycopg2
    # Parse Npgsql-style 'Host=...;Port=...;Username=...;Password=...;Database=...'
    parts: dict[str, str] = {}
    for token in conn_str.split(";"):
        token = token.strip()
        if "=" in token:
            k, v = token.split("=", 1)
            parts[k.strip().lower()] = v.strip()
    pg_kwargs = {
        "host": parts.get("host", "localhost"),
        "port": int(parts.get("port", "5432")),
        "user": parts.get("username") or parts.get("user", ""),
        "password": parts.get("password", ""),
        "dbname": parts.get("database") or parts.get("dbname", ""),
    }
    with psycopg2.connect(**pg_kwargs) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol FROM market_ref.universe_member "
                "WHERE universe_id = %s AND effective_to IS NULL "
                "ORDER BY symbol",
                (cfg.gm.universe_id,),
            )
            ts_symbols = [r[0] for r in cur.fetchall()]

    # Convert TS format (600000.SH) -> GM format (SHSE.600000) for the SDK.
    from symbol_converter import to_gm
    gm_symbols = [to_gm(s) for s in ts_symbols]
    log.info(
        "Resolved universe_id=%s -> %d GM-format symbols",
        cfg.gm.universe_id, len(gm_symbols),
    )
    return gm_symbols


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = argv[0] if argv else "config.yaml"

    cfg = load_config(config_path)

    _setup_logging(cfg.logging.dir, cfg.logging.level)
    log = logging.getLogger("market_data_gm")

    if not cfg.gm.token:
        log.error("GM_TOKEN not configured! Set gm.token in %s", config_path)
        return 1

    # Resolve subscription symbols (universe_id from PG if configured).
    symbols = _resolve_symbols(cfg, log)
    if not symbols:
        log.error("No symbols to subscribe (neither gm.symbols nor universe_id resolved any)")
        return 1
    cfg.gm.symbols = symbols  # propagate resolved list for downstream logging

    log.info("=== market-data-gm (Python) — config=%s ===", config_path)
    log.info("Subscribed symbols: %d total (%s...)",
             len(symbols), symbols[0] if symbols else "")
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

    # Start Prometheus metrics server
    import metrics
    metrics.start(8000)
    log.info("Prometheus metrics server started on :8000")

    # Inject runtime state into gm_strategy module before run()
    import gm_strategy
    session_id = f"{cfg.session_id_prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    gm_strategy.init_state(session_id=session_id, topic=cfg.kafka.market_data_topic)
    gm_strategy.prepare_subscriptions(cfg.gm.symbols, cfg.gm.frequency)

    # Init GM SDK
    from gm.api import set_token, set_serv_addr, run, MODE_LIVE

    set_token(cfg.gm.token)
    if cfg.gm.address:
        # set_serv_addr is the entry point to the GM terminal. If it fails
        # (wrong host/port, terminal not running, firewall), every subsequent
        # run() / on_bar() call will fail with a misleading downstream error
        # (timeouts, "no data", SDK internal errors). Fail fast at startup so
        # the failure mode is obvious and k8s restarts the pod with a clear
        # signal instead of dragging the bad state into the event loop.
        try:
            set_serv_addr(cfg.gm.address)
        except Exception as ex:
            log.error(
                "set_serv_addr failed for address=%s: %s. "
                "Aborting — check GM_SERV_ADDR / gm.address and that the "
                "Futu/GM terminal on the host is actually running.",
                cfg.gm.address, ex,
            )
            return 1

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
