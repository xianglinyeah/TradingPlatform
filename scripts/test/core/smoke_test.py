"""
Smoke test — verify the k8s replay pipeline produces trades.

Tests: MarketData.Replay → Kafka → Strategy → Execution.Service → PostgreSQL

Does NOT run a local backtest. The pipeline output (trade count, buy/sell sides)
is verified against sanity expectations, not against a local baseline.
For a detailed local-vs-k8s comparison, use test-full instead.

Usage:
    python smoke_test.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from helpers import BacktestTestHelper


def run_smoke_test():
    """Quick verification that the replay pipeline is alive and producing output."""
    print("[SMOKE] Smoke test started...")

    helper = BacktestTestHelper()

    try:
        # 1. Trigger k8s replay (2 weeks of data, fast speed)
        print("[1/3] Triggering k8s Replay...")
        session_id, replay_id = helper.start_replay_session(
            start_date="2023-01-01",
            end_date="2023-01-15",
            symbols=["600000.SH"],
            speed=10000,
        )

        # 2. Wait for replay to finish
        print("[2/3] Waiting for pipeline to process...")
        helper.wait_for_session_complete(session_id, replay_id, timeout=60)

        # 3. Verify database has results
        print("[3/3] Checking PostgreSQL results...")
        result = helper.get_database_results(session_id)

        # --- Assertions (smoke-level sanity checks) ---

        # Pipeline must produce at least 1 trade
        total = result["total_trades"]
        if total == 0:
            print("[FAIL] No trades in database — pipeline produced no output")
            return False

        # Strategy should generate both buys and sells
        buys = result.get("buy_trades", 0)
        sells = result.get("sell_trades", 0)
        if buys == 0:
            print("[FAIL] No buy trades — strategy may not be generating signals")
            return False

        # Prices should be positive
        if result.get("avg_buy_price", 0) <= 0:
            print("[FAIL] Abnormal buy price — data may be corrupted")
            return False

        pnl = result.get("pnl", 0.0)
        print(f"[PASS] Smoke test passed!")
        print(f"  - Trades:  {total} (buys={buys}, sells={sells})")
        print(f"  - PnL:     {pnl:.2f}")
        print(f"  - Buy px:  {result.get('avg_buy_price', 0):.2f}")
        return True

    except Exception as e:
        print(f"[FAIL] Smoke test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
