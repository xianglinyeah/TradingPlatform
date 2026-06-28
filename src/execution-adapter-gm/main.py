"""execution_adapter_gm entry point. Runs the GM Strategy event loop on a
daemon thread and a gRPC server (port 5005) on the main thread.

The gRPC servicer hands orders to the strategy thread via REQUEST_QUEUE,
because the Python GM SDK only permits trading calls from the strategy thread.

Our own `gm_trading_pb2.py` is now generated with grpcio-tools 1.48.2 and
loads cleanly under protobuf 3.20.3 without any workaround. The
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python env var below is kept as a
DEFENSE-IN-DEPTH measure: the `gm` SDK ships its own internal _pb2.py files
whose protoc version we do not control, and the pure-Python parser tolerates
mixed protoc generations more gracefully than the upb/C++ parser.
"""
from __future__ import annotations

import os
# Must be set before any protobuf import. See module docstring.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import logging
import sys
import threading

import grpc
from concurrent import futures

from config import load_config
# GM SDK discovers strategy callbacks by name in the module referenced by
# `run(filename=...)`. Since `run(filename=__file__)` points here, these
# symbols must be importable from this module's namespace.
from broker.strategy import (  # noqa: F401
    init,
    on_schedule,
    on_order_status,
    on_execution_report,
    on_error,
    on_backtest_finished,
)


def _make_proto_importable() -> None:
    proto_dir = os.path.join(os.path.dirname(__file__), "protos")
    if proto_dir not in sys.path:
        sys.path.insert(0, proto_dir)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = argv[0] if argv else "config.yaml"
    cfg = load_config(config_path)

    from utils import logger as logger_setup
    logger_setup.setup_logging(cfg.logging.dir, cfg.logging.level)
    log = logging.getLogger("execution_adapter_gm")

    log.info("=== execution-adapter-gm (Python) — config=%s ===", config_path)
    if not cfg.gm.token:
        log.error("GM_TOKEN not configured! Set gm.token in %s", config_path)
        return 1

    log.info("GM_TOKEN configured: %s***",
             cfg.gm.token[: min(10, len(cfg.gm.token))])
    log.info("Paper account: %s", cfg.gm.paper_account_id or "(none)")
    log.info("Live account: %s", cfg.gm.live_account_id or "(none)")
    log.info("gRPC listen: %s", cfg.grpc.listen)

    _make_proto_importable()

    # ---- Wire up GM strategy on a background thread ----
    from gm.api import set_token, set_serv_addr, run, MODE_LIVE
    from broker import strategy as gm_strategy

    # The Python SDK must be told which account is the "default" for trades
    # that don't pass account explicitly.
    try:
        from gm.api import set_account_id
        default_account = cfg.gm.paper_account_id or cfg.gm.live_account_id
        if default_account:
            set_account_id(default_account)
            log.info("GM default account set: %s", default_account)
    except Exception as ex:
        log.warning("set_account_id not available or failed: %s", ex)

    set_token(cfg.gm.token)
    if cfg.gm.address:
        try:
            set_serv_addr(cfg.gm.address)
        except Exception as ex:
            log.warning("set_serv_addr failed (using default): %s", ex)

    gm_strategy.prepare(
        account=cfg.gm.paper_account_id or cfg.gm.live_account_id,
        strategy_id=cfg.gm.strategy_id,
        poll_frequency_ms=cfg.schedule.poll_frequency_ms,
        session_start=cfg.schedule.session_start,
        session_end=cfg.schedule.session_end,
    )

    gm_error = {}

    def _run_gm():
        # GM SDK calls signal.signal() internally, which raises on non-main
        # threads in Linux. Patch the *module attribute* only for the duration
        # of run() and restore it afterward — previously the patch was
        # permanent and silenced every subsequent signal.signal() call across
        # the whole process (including grpc / futures libraries that use
        # signals for interrupt handling).
        import signal as _signal
        _orig_signal = _signal.signal
        _signal.signal = lambda *a, **kw: None
        try:
            log.info("Starting GM trading service event loop")
            run(
                strategy_id=cfg.gm.strategy_id,
                filename=__file__,
                mode=MODE_LIVE,
                token=cfg.gm.token,
            )
        except Exception as ex:
            log.exception("GM trading service event loop exception: %s", ex)
            gm_error["err"] = ex
        finally:
            # Restore the real signal handler so gRPC / shutdown handlers
            # that need signals still work after the GM loop exits.
            _signal.signal = _orig_signal

    gm_thread = threading.Thread(target=_run_gm, name="gm-strategy", daemon=True)
    gm_thread.start()

    # Wait briefly so init() failures surface before the gRPC server binds.
    if not gm_strategy._initialized.wait(timeout=5.0):
        log.warning("GM strategy init() did not signal within 5s; continuing")

    if gm_error:
        log.error("Aborting: GM strategy thread exited during startup")
        return 1

    # ---- Start gRPC server on the main thread ----
    from gm_grpc.servicer import GMTradingServicer

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=cfg.grpc.workers),
        options=[
            ("grpc.so_reuseport", 0),
            ("grpc.max_send_message_length", 4 * 1024 * 1024),
            ("grpc.max_receive_message_length", 4 * 1024 * 1024),
        ],
    )
    pb_grpc = __import__("gm_trading_pb2_grpc")
    pb_grpc.add_GMTradingServicer_to_server(
        GMTradingServicer(default_timeout_seconds=cfg.order.default_timeout_seconds),
        server,
    )

    server.add_insecure_port(cfg.grpc.listen)
    server.start()
    log.info("gRPC server listening on %s", cfg.grpc.listen)

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        log.info("Interrupted by user, shutting down")
        server.stop(grace=2.0)
    finally:
        # Cooperative shutdown of the order-poll thread so we don't cut an
        # order placement in half. The GM SDK's own event loop has no clean
        # stop API and stays daemon=True; it will be killed on process exit.
        try:
            gm_strategy.shutdown(timeout_seconds=5.0)
        except Exception as ex:
            log.warning("gm_strategy.shutdown failed: %s", ex)
        log.info("execution_adapter_gm stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
