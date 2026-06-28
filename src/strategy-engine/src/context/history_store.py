"""
HistoryStore + Context
======================
Unified data access layer for strategies. Strategies are agnostic to data
sources (ClickHouse / Kafka / DB).

Daily bars are loaded from ClickHouse ``market_data.kline_daily`` during
startup via ``warmup()``; minute bars are appended at runtime from Kafka.

Symbol format:
  - Internal / strategy-facing: GM format (``SZSE.301622``).
  - ClickHouse: TS format (``301622.SZ``).
  Conversion happens at the read boundary.
"""

from __future__ import annotations

import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Symbol format conversion (TS ↔ GM)
# ---------------------------------------------------------------------------

_TS_TO_GM_EXCHANGE = {"SH": "SHSE", "SZ": "SZSE"}
_GM_TO_TS_EXCHANGE = {v: k for k, v in _TS_TO_GM_EXCHANGE.items()}


def ts_to_gm_symbol(ts_symbol: str) -> str:
    """``301622.SZ`` → ``SZSE.301622``. Falls through unchanged on failure."""
    if "." not in ts_symbol:
        return ts_symbol
    code, suffix = ts_symbol.rsplit(".", 1)
    gm_exchange = _TS_TO_GM_EXCHANGE.get(suffix.upper())
    if gm_exchange is None:
        return ts_symbol
    return f"{gm_exchange}.{code}"


def gm_to_ts_symbol(gm_symbol: str) -> str:
    """``SZSE.301622`` → ``301622.SZ``. Falls through unchanged on failure."""
    if "." not in gm_symbol:
        return gm_symbol
    exchange, code = gm_symbol.split(".", 1)
    ts_suffix = _GM_TO_TS_EXCHANGE.get(exchange.upper())
    if ts_suffix is None:
        return gm_symbol
    return f"{code}.{ts_suffix}"


# ---------------------------------------------------------------------------
# ClickHouse connection config
# ---------------------------------------------------------------------------

@dataclass
class ClickHouseConfig:
    host: str = "clickhouse.infrastructure"
    port: int = 8123
    database: str = "market_data"
    username: str = "dev_user"
    password: str = "dev_pass"


# ---------------------------------------------------------------------------
# HistoryStore
# ---------------------------------------------------------------------------

@dataclass
class HistoryStore:
    """
    Stores rolling windows for daily and minute bars.

    - Loads daily bars from ClickHouse during startup via ``warmup()``
    - Receives Kafka minute bars during runtime via ``append_minute_bar()``
    """

    daily_window: int = 120    # Keep last N daily bars
    minute_window: int = 240   # Keep last N minute bars

    # symbol (GM format) → deque of dict (each dict is one bar's fields)
    daily_bars: Dict[str, deque] = field(default_factory=dict)
    minute_bars: Dict[str, deque] = field(default_factory=dict)

    _warmup_done: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    def warmup(self,
               clickhouse: Optional[ClickHouseConfig] = None,
               symbols: Optional[List[str]] = None,
               max_workers: int = 8) -> None:
        """Load recent daily bars from ClickHouse ``market_data.kline_daily``.

        Args:
            clickhouse: connection config. When None, the call is a no-op
                (matches the legacy graceful-degradation contract when no
                ``parquet_data_dir`` was set).
            symbols: GM-format symbols to warm up (``SZSE.301622``). When
                None, every symbol with bars in the last 30 days is loaded.
            max_workers: parallel fetch fan-out (IO-bound, 8 is plenty).
        """
        if clickhouse is None:
            logger.info("HistoryStore.warmup: no ClickHouse config, skipping")
            self._warmup_done = True
            return

        if symbols is None or len(symbols) == 0:
            symbols = self._discover_symbols(clickhouse)
            if not symbols:
                logger.warning("HistoryStore.warmup: 0 symbols discovered; daily context will be empty")
                self._warmup_done = True
                return

        logger.info("HistoryStore warmup starting: %d symbols from ClickHouse %s:%d/%s",
                    len(symbols), clickhouse.host, clickhouse.port, clickhouse.database)

        errors: List[str] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._load_daily_bars, clickhouse, sym): sym
                for sym in symbols
            }
            for future in as_completed(futures):
                exc = future.exception()
                if exc:
                    errors.append(f"{futures[future]}: {exc}")

        if errors:
            logger.warning("HistoryStore warmup completed with %d errors (first %d shown):\n%s",
                           len(errors), min(len(errors), 10),
                           "\n".join(errors[:10]))

        self._warmup_done = True
        logger.info("HistoryStore warmup done: %d symbols loaded",
                    len(self.daily_bars))

    def _discover_symbols(self, ch: ClickHouseConfig) -> List[str]:
        """Discover GM-format symbols that have traded in the last 30 days."""
        import clickhouse_connect  # lazy: keeps module import dep-free

        sql = (
            "SELECT DISTINCT ts_code "
            f"FROM {ch.database}.kline_daily "
            "WHERE trade_time >= now() - INTERVAL 30 DAY"
        )
        client = self._client(ch)
        try:
            res = client.query(sql)
        finally:
            client.close()
        ts_codes = [row[0] for row in res.result_rows]
        return [ts_to_gm_symbol(ts) for ts in ts_codes]

    def _load_daily_bars(self, ch: ClickHouseConfig, gm_symbol: str) -> None:
        """Load up to ``daily_window`` most recent daily bars for one symbol.

        ``gm_symbol`` is accepted in either GM (``SZSE.301622``) or TS
        (``301622.SZ``) form; ``gm_to_ts_symbol`` is idempotent on TS input.
        The dict is keyed by TS format so lookups from
        ``context.get_daily_bars(bar.symbol)`` (which carries TS-format
        symbols straight off Kafka) match.
        """
        ts_code = gm_to_ts_symbol(gm_symbol)
        sql = (
            "SELECT trade_time, open, high, low, close, volume "
            f"FROM {ch.database}.kline_daily "
            "WHERE ts_code = %(ts)s "
            "ORDER BY trade_time DESC "
            "LIMIT %(limit)s"
        )
        client = self._client(ch)
        try:
            res = client.query(sql, parameters={"ts": ts_code, "limit": self.daily_window})
        finally:
            client.close()

        if not res.result_rows:
            return

        # chronological order for the rolling window
        records = []
        for row in reversed(res.result_rows):
            trade_time = row[0]
            if hasattr(trade_time, "to_pydatetime"):
                trade_time = trade_time.to_pydatetime()
            records.append({
                "date": trade_time,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })

        self.daily_bars[ts_code] = deque(records, maxlen=self.daily_window)

    @staticmethod
    def _client(ch: ClickHouseConfig):
        import clickhouse_connect  # lazy: keeps module import dep-free

        return clickhouse_connect.get_client(
            host=ch.host, port=ch.port,
            username=ch.username, password=ch.password,
            database=ch.database,
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
