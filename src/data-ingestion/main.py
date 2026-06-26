"""data_ingestion CLI.

Usage: python main.py <config.yaml> --mode=<mode>

Modes:
    kline                     Full K-line back-fill (minute + daily → Parquet + ClickHouse)
    kline_incremental         Daily K-line incremental (minute + daily)
    fundamentals              Full fundamentals back-fill (8 tables)
    fundamentals_incremental  Pt multi-symbol incremental (8 tables)
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from config import load_config


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_mode(args) -> Optional[str]:
    """Extract --mode=<value> from argv. Mirrors the C# parser."""
    for a in args:
        if a.startswith("--mode="):
            return a.split("=", 1)[1]
    return None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _setup_logging()
    log = logging.getLogger("data_ingestion")

    parser = argparse.ArgumentParser(prog="data_ingestion")
    parser.add_argument("config_path", nargs="?", default="config.yaml")
    # Accept --mode=... as a single token (argparse would otherwise choke on the = form).
    parsed, remaining = parser.parse_known_args(argv)
    mode = _parse_mode(remaining) or _parse_mode(argv)

    log.info("=== data-ingestion (Python) — config=%s, mode=%s ===",
             parsed.config_path, mode or "(interactive)")

    cfg = load_config(parsed.config_path)

    # Always initialize GM SDK up front; cheap and exposes bad tokens early.
    from sources import gm_api
    gm_api.initialize(cfg.gm.token, cfg.gm.address or None)

    if mode is None:
        log.error("Interactive menu not implemented. Use --mode=<mode>.")
        return 2

    mode_l = mode.lower()
    try:
        if mode_l == "kline":
            from pipelines.kline.full import run_kline_full
            run_kline_full(cfg.market_scope, cfg.data, cfg.processing,
                           cfg.kline_incremental, cfg.storage.connection_string)
        elif mode_l == "kline_incremental":
            from pipelines.kline.incremental import load_symbols, run_incremental
            kcfg = cfg.kline_incremental
            symbols = load_symbols(kcfg)
            run_incremental(kcfg, cfg.storage.connection_string, symbols)
        elif mode_l == "fundamentals":
            from pipelines.fundamentals.full import run_fundamentals_full
            run_fundamentals_full(cfg, cfg.fundamentals)
        elif mode_l in ("fundamentals_incremental", "incremental", "incremental_pt"):
            from pipelines.fundamentals.incremental import run_fundamentals_incremental_pt
            run_fundamentals_incremental_pt(cfg, cfg.fundamentals_incremental)
        else:
            log.error(
                "Unknown --mode=%s. Valid: kline | kline_incremental | "
                "fundamentals | fundamentals_incremental",
                mode,
            )
            return 2
    except Exception as ex:
        log.exception("Program exception: %s", ex)
        return 1

    log.info("[Completed] Program execution finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
