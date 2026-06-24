"""
HistoryStore + Context
======================
Unified data access layer for strategies. Strategies are agnostic to data sources (Parquet / Kafka / DB).

Filename format: 301622.SZ.parquet  →  Internal symbol: SZSE.301622
"""

from __future__ import annotations

import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Symbol format conversion
# ---------------------------------------------------------------------------

_EXCHANGE_FILE_TO_GM = {"SH": "SHSE", "SZ": "SZSE"}
_EXCHANGE_GM_TO_FILE = {v: k for k, v in _EXCHANGE_FILE_TO_GM.items()}


def filename_stem_to_symbol(stem: str) -> str:
    """301622.SZ  →  SZSE.301622"""
    code, exchange = stem.rsplit(".", 1)
    gm_exchange = _EXCHANGE_FILE_TO_GM.get(exchange.upper())
    if gm_exchange is None:
        raise ValueError(f"Unknown exchange suffix: {exchange!r} in {stem!r}")
    return f"{gm_exchange}.{code}"


def symbol_to_filename_stem(symbol: str) -> str:
    """SZSE.301622  →  301622.SZ"""
    gm_exchange, code = symbol.split(".", 1)
    file_exchange = _EXCHANGE_GM_TO_FILE.get(gm_exchange)
    if file_exchange is None:
        raise ValueError(f"Unknown GM exchange: {gm_exchange!r} in {symbol!r}")
    return f"{code}.{file_exchange}"


# ---------------------------------------------------------------------------
# HistoryStore
# ---------------------------------------------------------------------------

@dataclass
class HistoryStore:
    """
    Stores rolling windows for daily and minute bars.

    - Loads daily bars from Parquet during startup via warmup()
    - Receives Kafka minute bars during runtime via append_minute_bar()
    """

    daily_window: int = 120    # Keep last N daily bars
    minute_window: int = 240   # Keep last N minute bars

    # symbol → deque of dict (each dict is one bar's fields)
    daily_bars: Dict[str, deque] = field(default_factory=dict)
    minute_bars: Dict[str, deque] = field(default_factory=dict)

    _warmup_done: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    def warmup(self, parquet_dir: str, max_workers: int = 8) -> None:
        """
        Load all market daily bars from Parquet directory in parallel.
        Each filename format: {code}.{SH|SZ}.parquet

        Args:
            parquet_dir: Parquet files directory
            max_workers: Parallel thread count (IO-bound, 8 is sufficient)
        """
        files = list(Path(parquet_dir).glob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"No parquet files found in {parquet_dir}")

        logger.info(f"Warmup starting: {len(files)} files from {parquet_dir}")

        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._load_daily_file, f): f for f in files}
            for future in as_completed(futures):
                exc = future.exception()
                if exc:
                    errors.append(f"{futures[future].name}: {exc}")

        if errors:
            logger.warning(f"Warmup completed with {len(errors)} errors:\n" + "\n".join(errors))

        self._warmup_done = True
        logger.info(f"Warmup done: {len(self.daily_bars)} symbols loaded")

    def _load_daily_file(self, path: Path) -> None:
        """Load a single Parquet file (executed in thread pool)."""
        symbol = filename_stem_to_symbol(path.stem)

        df = pd.read_parquet(
            path,
            columns=["date", "open", "high", "low", "close", "volume"],
        )
        df = df.sort_values("date").tail(self.daily_window)

        self.daily_bars[symbol] = deque(
            df.to_dict("records"),
            maxlen=self.daily_window,
        )

    # ------------------------------------------------------------------
    # Daily bars access
    # ------------------------------------------------------------------

    def get_daily_bars(self, symbol: str) -> list[dict]:
        return list(self.daily_bars.get(symbol, []))

    def append_daily_bar(self, symbol: str, bar: dict) -> None:
        """Append new daily bar after market close (for future use)."""
        if symbol not in self.daily_bars:
            self.daily_bars[symbol] = deque(maxlen=self.daily_window)
        self.daily_bars[symbol].append(bar)

    # ------------------------------------------------------------------
    # Minute bars access
    # ------------------------------------------------------------------

    def get_minute_bars(self, symbol: str) -> list[dict]:
        return list(self.minute_bars.get(symbol, []))

    def append_minute_bar(self, symbol: str, bar: dict) -> None:
        """Called when new minute bar is consumed from Kafka."""
        if symbol not in self.minute_bars:
            self.minute_bars[symbol] = deque(maxlen=self.minute_window)
        self.minute_bars[symbol].append(bar)

    # ------------------------------------------------------------------
    # Status check
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._warmup_done
