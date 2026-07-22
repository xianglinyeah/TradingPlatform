"""Unit test for market rules in MockExecutor"""
import sys
import os
from pathlib import Path
from datetime import date, datetime

# Add project path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from execution.mock_executor import MockExecutor
from execution.common import Signal


class BarData:
    """Mock bar data"""
    def __init__(self, symbol: str, timestamp: datetime, close: float):
        self.symbol = symbol
        self.timestamp = timestamp
        self.close = close
        self.open = close
        self.high = close
        self.low = close
        self.volume = 1000


def test_no_naked_short():
    """Test: Cannot sell without position"""
    print("\n=== Test 1: No Naked Short Rule ===")

    executor = MockExecutor(initial_capital=1_000_000, commission_rate=0.0003)
    test_date = datetime(2024, 1, 10, 10, 0, 0)

    # Try to sell without position
    sell_signal = Signal(
        symbol="600000.SH",
        signal_type="sell",
        quantity=100,
        price=10.0,
        strategy_id="test_strategy"
    )

    bar = BarData("600000.SH", test_date, 10.0)
    orders = executor.execute_signals([sell_signal], bar)

    print(f"  Sell without position: {len(orders)} orders executed")
    print(f"  Expected: 0 orders (rejected by no naked short rule)")

    assert len(orders) == 0, "Should reject sell without position"
    print("  [PASS] No naked short rule works correctly")


def test_t1_rule():
    """Test: Cannot sell stocks bought today"""
    print("\n=== Test 2: T+1 Rule ===")

    executor = MockExecutor(initial_capital=1_000_000, commission_rate=0.0003)
    day1 = datetime(2024, 1, 10, 10, 0, 0)
    day1_evening = datetime(2024, 1, 10, 15, 0, 0)

    # Buy on day1
    buy_signal = Signal(
        symbol="600000.SH",
        signal_type="buy",
        quantity=100,
        price=10.0,
        strategy_id="test_strategy"
    )

    bar1 = BarData("600000.SH", day1, 10.0)
    buy_orders = executor.execute_signals([buy_signal], bar1)

    print(f"  Buy order executed: {len(buy_orders)} orders")
    assert len(buy_orders) == 1, "Buy should execute"

    # Try to sell on same day (should be rejected)
    sell_signal = Signal(
        symbol="600000.SH",
        signal_type="sell",
        quantity=50,
        price=12.0,
        strategy_id="test_strategy"
    )

    bar1_evening = BarData("600000.SH", day1_evening, 12.0)
    sell_orders = executor.execute_signals([sell_signal], bar1_evening)

    print(f"  Sell same day: {len(sell_orders)} orders executed")
    print(f"  Expected: 0 orders (rejected by T+1 rule)")

    assert len(sell_orders) == 0, "Should reject sell on same day"
    print("  [PASS] T+1 rule works correctly")


def test_sell_next_day():
    """Test: Can sell stocks bought yesterday"""
    print("\n=== Test 3: Sell Previous Day Purchase ===")

    executor = MockExecutor(initial_capital=1_000_000, commission_rate=0.0003)
    day1 = datetime(2024, 1, 10, 10, 0, 0)
    day2 = datetime(2024, 1, 11, 10, 0, 0)

    # Buy on day1
    buy_signal = Signal(
        symbol="600000.SH",
        signal_type="buy",
        quantity=100,
        price=10.0,
        strategy_id="test_strategy"
    )

    bar1 = BarData("600000.SH", day1, 10.0)
    executor.execute_signals([buy_signal], bar1)

    # Sell on day2 (should succeed)
    sell_signal = Signal(
        symbol="600000.SH",
        signal_type="sell",
        quantity=50,
        price=12.0,
        strategy_id="test_strategy"
    )

    bar2 = BarData("600000.SH", day2, 12.0)
    sell_orders = executor.execute_signals([sell_signal], bar2)

    print(f"  Sell next day: {len(sell_orders)} orders executed")
    print(f"  Expected: 1 order (allowed by T+1 rule)")

    assert len(sell_orders) == 1, "Should allow sell on next day"
    print("  [PASS] Previous day purchase can be sold")


def test_partial_sell_t1():
    """Test: Partial sell with T+1 constraint"""
    print("\n=== Test 4: Partial Sell with T+1 ===")

    executor = MockExecutor(initial_capital=1_000_000, commission_rate=0.0003)
    day1 = datetime(2024, 1, 10, 10, 0, 0)
    day2 = datetime(2024, 1, 11, 10, 0, 0)

    # Day1: Buy 100 shares
    buy1 = Signal(symbol="600000.SH", signal_type="buy", quantity=100,
                  price=10.0, strategy_id="test")
    bar1 = BarData("600000.SH", day1, 10.0)
    executor.execute_signals([buy1], bar1)

    # Day2: Buy another 100 shares
    buy2 = Signal(symbol="600000.SH", signal_type="buy", quantity=100,
                  price=11.0, strategy_id="test")
    bar2 = BarData("600000.SH", day2, 11.0)
    executor.execute_signals([buy2], bar2)

    # Day2 evening: Try to sell 150 shares (should only sell 100 from day1)
    sell = Signal(symbol="600000.SH", signal_type="sell", quantity=150,
                 price=12.0, strategy_id="test")
    bar2_evening = BarData("600000.SH", day2, 12.0)
    sell_orders = executor.execute_signals([sell], bar2_evening)

    print(f"  Sell 150 (100 from day1 + 50 from day2): {len(sell_orders)} orders")
    print(f"  Expected: 0 orders (cannot sell day2's purchase)")

    assert len(sell_orders) == 0, "Should reject selling day2's purchase"
    print("  [PASS] T+1 rule prevents selling today's purchase")


if __name__ == "__main__":
    print("=" * 60)
    print("Market Rules MockExecutor Unit Tests")
    print("=" * 60)

    try:
        test_no_naked_short()
        test_t1_rule()
        test_sell_next_day()
        test_partial_sell_t1()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
