"""A-share symbol pool loader. Builds the universe from `<daily_dir>/*.parquet`
filenames (e.g. `600000.SH.parquet` → `SHSE.600000`); result cached to a text file.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def to_gm_symbol(raw_name: str) -> Optional[str]:
    """`600000.SH` → `SHSE.600000`. Returns None for unknown suffixes."""
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


def load(daily_dir: str, cache_file: str) -> list[str]:
    """Load symbols. Uses cache file if present; otherwise scans daily_dir."""
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

    if not os.path.isdir(daily_dir):
        raise FileNotFoundError(f"Daily parquet directory not found: {daily_dir}")

    files = [f for f in os.listdir(daily_dir) if f.endswith(".parquet")]
    logger.info("Scanning %d parquet files in %s", len(files), daily_dir)

    symbols = []
    for fname in files:
        stem = os.path.splitext(fname)[0]
        gm = to_gm_symbol(stem)
        if gm:
            symbols.append(gm)

    symbols.sort()
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write("\n".join(symbols))
    logger.info("Symbol pool cached to %s: %d symbols", cache_file, len(symbols))
    return symbols


def refresh(daily_dir: str, cache_file: str) -> list[str]:
    """Force-refresh by deleting cache then load. Idempotent if file is absent."""
    if cache_file and os.path.exists(cache_file):
        try:
            os.remove(cache_file)
            logger.info("Deleted symbol cache %s to force refresh", cache_file)
        except OSError as ex:
            logger.warning("Failed to delete symbol cache %s; continuing with stale pool: %s",
                           cache_file, ex)
    return load(daily_dir, cache_file)
