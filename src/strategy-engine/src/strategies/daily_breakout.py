"""
DailyBreakoutStrategy
=====================
Bottom-box breakout strategy with daily filtering + minute entry.

Logic:
  1. [Daily Filter] Past 60 days decline > 20% (downtrend)
  2. [Daily Filter] Recent 20 days range < 8% (consolidation box)
  3. [Minute Trigger] Current bar.close breaks 20-day high (box upper edge)
  4. [Minute Trigger] Current bar.close > 20-day low (stand above support)
  5. [Anti-duplicate] No order placed for this symbol today

Time-series safety:
  breakout_level uses daily_bars[-20:] which is data through yesterday,
  excluding today, avoiding look-ahead bias.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, Optional

import pandas as pd

from ..context import Context  # Context class from src/context/

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bar dataclass (interface with Kafka consumer layer)
# ---------------------------------------------------------------------------

@dataclass
class Bar:
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_time: pd.Timestamp   # bar end time


# ---------------------------------------------------------------------------
# Strategy parameters
# ---------------------------------------------------------------------------

@dataclass
class BreakoutParams:
    downtrend_days: int   = 60    # lookback days for judging downtrend
    downtrend_pct: float  = 0.20  # decline threshold (20%)
    consol_days: int      = 20    # consolidation box days
    consol_range: float   = 0.08  # box amplitude threshold (8%)
    min_daily_bars: int   = 65    # minimum number of daily bars required (with buffer)


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class DailyBreakoutStrategy:
    """
    Usage:
        strategy = DailyBreakoutStrategy(
            params=BreakoutParams(),
            send_order=my_order_func,
        )

        # In Kafka consumer loop:
        strategy.on_bar(bar, context)
    """

    def __init__(
        self,
        params: Optional[BreakoutParams] = None,
        send_order: Optional[Callable[[str, float], None]] = None,
    ) -> None:
        self.params = params or BreakoutParams()
        self._send_order = send_order or self._default_order_log

        # Track symbols ordered today to prevent duplicates
        self._ordered_today: Dict[str, date] = {}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar, context: Context) -> None:
        """Process a new minute bar and place an order if all conditions pass."""
        if not context.is_ready:
            return

        daily = context.get_daily_bars(bar.symbol)
        if daily.empty or len(daily) < self.params.min_daily_bars:
            return

        # ── Daily filtering (State) ────────────────────────────────────
        signal = self._daily_signal(daily)
        if signal is None:
            return

        breakout_level, support_level = signal

        # ── Prevent duplicate orders ───────────────────────────────────
        today = bar.bar_time.date()
        if self._ordered_today.get(bar.symbol) == today:
            return

        # ── Minute bar entry (Event) ─────────────────────────────────
        if not self._intraday_entry(bar, breakout_level, support_level):
            return

        # ── Place order ───────────────────────────────────────────────
        logger.info(
            f"BUY signal | {bar.symbol} | "
            f"close={bar.close:.2f} breakout_level={breakout_level:.2f} "
            f"support={support_level:.2f} | {bar.bar_time}"
        )
        self._ordered_today[bar.symbol] = today
        self._send_order(bar.symbol, bar.close)

    # ------------------------------------------------------------------
    # Daily filtering
    # ------------------------------------------------------------------

    def _daily_signal(
        self, daily: pd.DataFrame
    ) -> Optional[tuple[float, float]]:
        """
        Returns (breakout_level, support_level) if all daily conditions pass,
        else None.

        Note: Uses daily.iloc[-20:] which is data through yesterday, excluding today.
        """
        p = self.params

        # Past 60 days decline > 20%
        past_60 = daily.iloc[-p.downtrend_days:]
        start_close = past_60["close"].iloc[0]
        end_close   = past_60["close"].iloc[-1]
        if start_close <= 0 or end_close <= 0:
            return None
        downtrend = (start_close / end_close - 1) >= p.downtrend_pct
        if not downtrend:
            return None

        # Recent 20 days range < 8%
        last_20 = daily.iloc[-p.consol_days:]
        high_20  = last_20["high"].max()
        low_20   = last_20["low"].min()
        if low_20 <= 0:
            return None
        range_pct = (high_20 - low_20) / low_20
        if range_pct >= p.consol_range:
            return None

        breakout_level = high_20
        support_level  = low_20
        return breakout_level, support_level

    # ------------------------------------------------------------------
    # Minute bar entry
    # ------------------------------------------------------------------

    def _intraday_entry(
        self,
        bar: Bar,
        breakout_level: float,
        support_level: float,
    ) -> bool:
        """
        Break above box upper edge AND close stands above support.
        """
        above_breakout = bar.close > breakout_level
        above_support  = bar.close > support_level   # Prevent false breakout then pullback
        return above_breakout and above_support

    # ------------------------------------------------------------------
    # Default order handler (logs for testing)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_order_log(symbol: str, price: float) -> None:
        logger.info(f"[ORDER] BUY {symbol} @ {price:.2f}")

    # ------------------------------------------------------------------
    # Day switch (call before market open each day to clear ordered symbols)
    # ------------------------------------------------------------------

    def on_new_day(self) -> None:
        """Clear the ordered-today tracker (call before market open each day)."""
        self._ordered_today.clear()


# ---------------------------------------------------------------------------
# Quick validation (standalone, no Kafka dependency)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from ..context.history_store import HistoryStore, ClickHouseConfig
    from ..context.context import Context

    logging.basicConfig(level=logging.INFO)

    # Daily-bar warmup now comes from ClickHouse; pass an explicit
    # ClickHouseConfig or None to skip warmup.
    store = HistoryStore(daily_window=120)
    store.warmup(clickhouse=None)

    ctx = Context(store)
    strategy = DailyBreakoutStrategy()

    # Simulate one minute bar coming in
    test_bar = Bar(
        symbol="SZSE.301622",
        open=10.0, high=10.5, low=9.8, close=10.3,
        volume=1_000_000,
        bar_time=pd.Timestamp("2025-06-14 10:05:00"),
    )
    strategy.on_bar(test_bar, ctx)
