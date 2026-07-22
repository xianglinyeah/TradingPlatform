"""
Test strategy trigger - analyze minimum data days required
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from core.helpers import BacktestTestHelper

def test_strategy_trigger():
    """Test whether different numbers of days can trigger the strategy"""
    helper = BacktestTestHelper()

    test_periods = [
        ("3 days", "20230101", "20230103"),
        ("5 days", "20230101", "20230105"),
        ("7 days", "20230101", "20230107"),
        ("10 days", "20230101", "20230110"),
        ("15 days", "20230101", "20230115"),
    ]

    print("Analyzing strategy trigger with different data day counts:")
    print("=" * 60)

    for period_name, start_date, end_date in test_periods:
        print(f"\n{period_name} data ({start_date} ~ {end_date}):")

        try:
            result = helper.run_local_backtest(start_date, end_date)

            trades = result["total_trades"]
            signals = result.get("signals", 0)
            bars = result.get("bars_processed", 0)

            print(f"  - K-lines processed: {bars}")
            print(f"  - Signals generated: {signals}")
            print(f"  - Trades executed: {trades}")

            if trades > 0:
                print(f"  - [OK] Strategy triggered!")
            else:
                print(f"  - [WARN] Strategy not triggered")

        except Exception as e:
            print(f"  - [ERROR] Test failed: {e}")

    print("\n" + "=" * 60)
    print("Recommendation: Based on EMA period 10, use at least 10-15 days of data")

if __name__ == "__main__":
    test_strategy_trigger()
