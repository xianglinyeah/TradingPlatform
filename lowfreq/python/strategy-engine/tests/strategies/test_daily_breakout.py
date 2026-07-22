"""Unit tests for DailyBreakoutStrategy.

Focus on the two failure modes unique to this strategy:

  1. **Look-ahead bias** — daily filter MUST compute on data through
     yesterday only. If the rolling window ever includes the current
     bar's daily value, today's signal becomes correlated with today's
     outcome and the backtest produces inflated returns.

  2. **Per-day duplicate-order guard** — `_ordered_today` must be
     cleared by `on_new_day()`. Without the day-boundary hook firing,
     the guard prevents legitimate orders on subsequent days.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from src.strategies.daily_breakout import (
    Bar,
    BreakoutParams,
    DailyBreakoutStrategy,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

class StubContext:
    """Minimal stand-in for Context — returns a canned daily DataFrame.

    Avoids pulling in HistoryStore / ClickHouse for these unit tests.
    """

    def __init__(self, daily: pd.DataFrame):
        self._daily = daily
        self.calls: list[str] = []

    @property
    def is_ready(self) -> bool:
        return True

    def get_daily_bars(self, symbol: str) -> pd.DataFrame:
        self.calls.append(symbol)
        return self._daily


def _build_daily(
    n_days: int,
    *,
    start_close: float = 100.0,
    end_close: float = 70.0,
    high_pct: float = 0.03,
    low_pct: float = 0.03,
    start: str = "2024-01-01",
    flat_tail_days: int = 25,
) -> pd.DataFrame:
    """Build a synthetic daily-bar DataFrame.

    Two-segment curve so the daily filter (20% decline over 60d, <8% range
    over the last 20d) actually passes with realistic per-bar noise:

      * First (n_days - flat_tail_days) bars: linear ramp from start_close
        down to end_close — supplies the >20% downtrend.
      * Last `flat_tail_days` bars: flat at end_close — supplies the tight
        consolidation box for the last-20-day window.

    Per-bar high/low are within +/-high_pct/-low_pct of close.
    """
    ramp_days = max(n_days - flat_tail_days, 1)
    ramp = np.linspace(start_close, end_close, ramp_days)
    flat = np.full(n_days - ramp_days, end_close)
    closes = np.concatenate([ramp, flat])
    dates = pd.bdate_range(start=start, periods=n_days)
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": closes * (1 + high_pct),
        "low": closes * (1 - low_pct),
        "close": closes,
        "volume": 1_000_000,
    })


def _bar(close: float, *, bar_time: str = "2024-03-15 10:30:00",
         symbol: str = "SHSE.600000") -> Bar:
    return Bar(
        symbol=symbol,
        open=close, high=close * 1.005, low=close * 0.995, close=close,
        volume=500_000,
        bar_time=pd.Timestamp(bar_time),
    )


# Capture orders without hitting gRPC / Kafka.
class OrderRecorder:
    def __init__(self) -> None:
        self.orders: list[tuple[str, float]] = []

    def __call__(self, symbol: str, price: float) -> None:
        self.orders.append((symbol, price))


# ---------------------------------------------------------------------------
# Daily filter — look-ahead bias
# ---------------------------------------------------------------------------

class TestDailyFilter:
    def test_passes_when_downtrend_and_consolidation_both_met(self):
        """Sanity check: the canonical shape (60d decline 30%, tight 20d box)
        produces a non-None signal."""
        daily = _build_daily(80, start_close=100.0, end_close=70.0,
                             high_pct=0.01, low_pct=0.01)
        strategy = DailyBreakoutStrategy()
        signal = strategy._daily_signal(daily)
        assert signal is not None
        breakout_level, support_level = signal
        assert breakout_level > support_level

    def test_rejects_when_downtrend_below_threshold(self):
        """If 60-day decline is < 20%, no signal."""
        daily = _build_daily(80, start_close=100.0, end_close=95.0,
                             high_pct=0.01, low_pct=0.01)
        strategy = DailyBreakoutStrategy()
        assert strategy._daily_signal(daily) is None

    def test_rejects_when_range_exceeds_consolidation_threshold(self):
        """If 20-day high-low range >= 8%, no signal."""
        daily = _build_daily(80, start_close=100.0, end_close=70.0,
                             high_pct=0.06, low_pct=0.06)
        strategy = DailyBreakoutStrategy()
        assert strategy._daily_signal(daily) is None

    def test_does_not_use_future_data(self):
        """The breakout/support levels must be derived ONLY from the last
        20 daily rows of the input — prepending older history must not
        change the result, since the rolling window is tail-anchored.

        This guards against an off-by-one regression where the window
        silently expands to iloc[:-20] (head-anchored) or otherwise drifts;
        preventing today's bar from leaking in is the responsibility of the
        caller (Context.get_daily_bars returns completed daily bars only),
        not the strategy.
        """
        daily = _build_daily(80, start_close=100.0, end_close=70.0,
                             high_pct=0.01, low_pct=0.01)
        baseline = strategy_signal(daily)

        # Prepend 30 extra older rows. The last 20 / 60 windows are
        # unchanged, so the breakout/support levels must be identical.
        older = _build_daily(30, start_close=130.0, end_close=100.0,
                             high_pct=0.01, low_pct=0.01,
                             start="2023-01-01")
        daily_with_prefix = pd.concat([older, daily], ignore_index=True)
        assert strategy_signal(daily_with_prefix) == baseline

    def test_handles_insufficient_history_gracefully(self):
        """Fewer than min_daily_bars (default 65) — on_bar() short-circuits
        without raising and without placing an order.

        The length gate lives in on_bar(), not in _daily_signal() (which
        assumes the caller has already validated history depth).
        """
        daily = _build_daily(40)
        ctx = StubContext(daily)
        recorder = OrderRecorder()
        strategy = DailyBreakoutStrategy(send_order=recorder)

        # Should not raise, should not place any order.
        strategy.on_bar(_bar(close=200.0), ctx)
        assert recorder.orders == []


def strategy_signal(daily: pd.DataFrame) -> Optional[tuple[float, float]]:
    s = DailyBreakoutStrategy()
    return s._daily_signal(daily)


# ---------------------------------------------------------------------------
# Intraday entry
# ---------------------------------------------------------------------------

class TestIntradayEntry:
    def setup_method(self):
        self.strategy = DailyBreakoutStrategy()

    def test_breakout_above_box_upper_triggers(self):
        assert self.strategy._intraday_entry(
            _bar(close=50.0), breakout_level=45.0, support_level=40.0
        ) is True

    def test_close_equal_to_breakout_does_not_trigger(self):
        """Strict inequality: close > breakout_level. Equality must fail —
        otherwise we trade exactly at the prior high with no confirmation."""
        assert self.strategy._intraday_entry(
            _bar(close=45.0), breakout_level=45.0, support_level=40.0
        ) is False

    def test_close_below_breakout_does_not_trigger(self):
        assert self.strategy._intraday_entry(
            _bar(close=44.9), breakout_level=45.0, support_level=40.0
        ) is False

    def test_pullback_below_support_blocks_entry(self):
        """Even if close > breakout, close must also stay above support to
        filter false breakouts."""
        assert self.strategy._intraday_entry(
            _bar(close=46.0), breakout_level=45.0, support_level=47.0
        ) is False


# ---------------------------------------------------------------------------
# Per-day duplicate guard + on_new_day lifecycle
# ---------------------------------------------------------------------------

class TestOnNewDay:
    def _make_strategy_with_signal(self) -> tuple[
        DailyBreakoutStrategy, StubContext, OrderRecorder, Bar
    ]:
        """Wire up a strategy that will fire exactly one BUY for the given
        bar so we can test the duplicate-order guard."""
        daily = _build_daily(80, start_close=100.0, end_close=70.0,
                             high_pct=0.01, low_pct=0.01)
        ctx = StubContext(daily)
        recorder = OrderRecorder()
        strategy = DailyBreakoutStrategy(send_order=recorder)
        # Pick a close well above the 20-day high to guarantee a breakout.
        last_high = daily["high"].iloc[-20:].max()
        bar = _bar(close=float(last_high) + 5.0)
        return strategy, ctx, recorder, bar

    def test_second_bar_same_day_is_blocked(self):
        """Two consecutive bars on the same trade date — only the first
        places an order; the duplicate guard rejects the second."""
        strategy, ctx, recorder, bar = self._make_strategy_with_signal()
        strategy.on_bar(bar, ctx)
        strategy.on_bar(bar, ctx)
        assert len(recorder.orders) == 1

    def test_on_new_day_clears_duplicate_guard(self):
        """After on_new_day(), the same trade can fire again — this is the
        bug the DAY_BOUNDARY message exists to fix."""
        strategy, ctx, recorder, bar = self._make_strategy_with_signal()
        strategy.on_bar(bar, ctx)
        assert len(recorder.orders) == 1

        strategy.on_new_day()
        strategy.on_bar(bar, ctx)
        assert len(recorder.orders) == 2

    def test_on_new_day_handles_iso_string(self):
        """on_new_day() accepts an ISO date string (the wire format
        emitted by market-data-replay) without raising."""
        strategy, ctx, recorder, bar = self._make_strategy_with_signal()
        strategy.on_bar(bar, ctx)
        # Should not raise even though we pass a string.
        strategy.on_new_day(trade_date="2024-03-16")
        strategy.on_bar(bar, ctx)
        assert len(recorder.orders) == 2

    def test_on_new_day_is_idempotent(self):
        """Calling on_new_day() without any prior orders is a no-op."""
        strategy, _, _, _ = self._make_strategy_with_signal()
        strategy.on_new_day()
        strategy.on_new_day()
        assert strategy._ordered_today == {}
