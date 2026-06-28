"""A-share symbol pool loader.

The pool is built from the symbols that have actually traded recently in
ClickHouse ``market_data.kline_daily`` (last 30 days). Previously this
scanned ``daily_dir/*.parquet`` filenames; reads have consolidated on
ClickHouse, so Parquet is no longer a read source. Parquet writes continue
in data-ingestion as a backup and would still produce the same filename
shape, so a fallback to filename scanning is kept for environments where
ClickHouse is unreachable (e.g. local dev without a CH port-forward).

Result is cached to a text file.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# Default ClickHouse connection for symbol discovery. Override per call via
# the ``clickhouse`` arg, or globally via env vars (matches the conventions
# used by other services).
_DEFAULT_CH_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse.infrastructure")
_DEFAULT_CH_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
_DEFAULT_CH_DB = os.getenv("CLICKHOUSE_DATABASE", "market_data")
_DEFAULT_CH_USER = os.getenv("CLICKHOUSE_USER", "dev_user")
_DEFAULT_CH_PWD = os.getenv("CLICKHOUSE_PASSWORD", "dev_pass")


def to_gm_symbol(raw_name: str) -> Optional[str]:
    """``600000.SH`` → ``SHSE.600000``. Returns None for unknown suffixes.

    Also accepts bare exchange codes (``SH``/``SZ``) for parity with the
    legacy filename-scan path.
    """
    if not raw_name:
        return None
    dot = raw_name.rfind(".")
    if dot <= 0 or dot == len(raw_name) - 1:
        return None
    code = raw_name[:dot]
    suffix = raw_name[dot + 1:].upper()
    if suffix == "SH":
        return f"SHSE.{code}"
    if suffix == "SZ":
        return f"SZSE.{code}"
    return None


def _query_clickhouse_symbols(clickhouse: Optional[dict]) -> list[str]:
    """Query distinct ts_codes from ClickHouse kline_daily (last 30 days).

    Accepts a dict with host/port/database/username/password keys. Missing
    keys fall back to module-level env-default constants. Returns symbols
    in GM format (``SHSE.600000``) for direct use with the GM SDK.
    """
    import clickhouse_connect

    cfg = clickhouse or {}
    host = cfg.get("host", _DEFAULT_CH_HOST)
    port = int(cfg.get("port", _DEFAULT_CH_PORT))
    database = cfg.get("database", _DEFAULT_CH_DB)
    user = cfg.get("user") or cfg.get("username") or _DEFAULT_CH_USER
    pwd = cfg.get("password") or _DEFAULT_CH_PWD

    client = clickhouse_connect.get_client(
        host=host, port=port,
        username=user, password=pwd,
        database=database,
    )
    try:
        res = client.query(
            f"SELECT DISTINCT ts_code FROM {database}.kline_daily "
            "WHERE trade_time >= now() - INTERVAL 30 DAY"
        )
    finally:
        client.close()

    symbols = [to_gm_symbol(row[0]) for row in res.result_rows]
    symbols = [s for s in symbols if s]
    symbols.sort()
    logger.info("ClickHouse symbol discovery: %d symbols", len(symbols))
    return symbols


def _scan_parquet_files(daily_dir: str) -> list[str]:
    """Legacy fallback: scan ``daily_dir/*.parquet`` filenames.

    Kept so symbol discovery still works when ClickHouse is not reachable
    (local dev without a CH port-forward). The Parquet daily files are
    still being written by data-ingestion as a backup.
    """
    if not os.path.isdir(daily_dir):
        raise FileNotFoundError(f"Daily parquet directory not found: {daily_dir}")

    files = [f for f in os.listdir(daily_dir) if f.endswith(".parquet")]
    logger.info("Scanning %d parquet files in %s (Parquet fallback)", len(files), daily_dir)

    symbols = []
    for fname in files:
        stem = os.path.splitext(fname)[0]
        gm = to_gm_symbol(stem)
        if gm:
            symbols.append(gm)
    symbols.sort()
    return symbols


def load(daily_dir: str, cache_file: str,
         clickhouse: Optional[dict] = None) -> list[str]:
    """Load symbols. Uses cache file if present; otherwise queries ClickHouse.

    Args:
        daily_dir: Parquet fallback directory (only scanned when CH fails).
        cache_file: Text-file cache for the resolved symbol list.
        clickhouse: Optional CH connection dict. When None, env defaults
            are used.
    """
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            syms = [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
        syms.sort()
        logger.info("Symbol pool loaded from cache %s: %d symbols", cache_file, len(syms))
        return syms

    try:
        symbols = _query_clickhouse_symbols(clickhouse)
    except Exception as ex:
        logger.warning("ClickHouse symbol discovery failed (%s); "
                       "falling back to Parquet scan of %s", ex, daily_dir)
        symbols = _scan_parquet_files(daily_dir)

    with open(cache_file, "w", encoding="utf-8") as f:
        f.write("\n".join(symbols))
    logger.info("Symbol pool cached to %s: %d symbols", cache_file, len(symbols))
    return symbols


def refresh(daily_dir: str, cache_file: str,
            clickhouse: Optional[dict] = None) -> list[str]:
    """Force-refresh by deleting cache then load. Idempotent if file is absent."""
    if cache_file and os.path.exists(cache_file):
        try:
            os.remove(cache_file)
            logger.info("Deleted symbol cache %s to force refresh", cache_file)
        except OSError as ex:
            logger.warning("Failed to delete symbol cache %s; continuing with stale pool: %s",
                           cache_file, ex)
    return load(daily_dir, cache_file, clickhouse=clickhouse)
