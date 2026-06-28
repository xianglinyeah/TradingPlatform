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
        #
        # PnL is no longer a fixed baseline: §1 MarketDataCache makes the
        # execution price depend on which bar the execution-service Kafka
        # consumer has cached when the gRPC order arrives. At 10000x replay
        # the consumer can race ahead of strategy-engine by 1+ bars, so PnL
        # floats in roughly [-26, -17] across runs.
        #
        # Strategy: structural fields (trade count, sides, round trip,
        # commission) are deterministic and asserted strictly. PnL is
        # asserted as a range loose enough to absorb the cache race but
        # tight enough to catch real bugs (e.g. slippage disabled,
        # commission skipped, wrong-side fills).

        total = result["total_trades"]
        buys = result.get("buy_trades", 0)
        sells = result.get("sell_trades", 0)
        final_position = result.get("final_position", 0)
        commission = result.get("total_commission", 0.0)
        pnl = result.get("pnl", 0.0)

        # Structural (deterministic) assertions.
        if total == 0:
            print("[FAIL] No trades in database — pipeline produced no output")
            return False
        if total != 4:
            print(f"[FAIL] Expected 4 trades, got {total} — strategy signal pattern changed")
            return False
        if buys != 2 or sells != 2:
            print(f"[FAIL] Expected 2 buys + 2 sells, got buys={buys} sells={sells}")
            return False
        if final_position != 0:
            print(f"[FAIL] Expected flat final position (round trip), got {final_position}")
            return False
        # Commission: 4 trades × min 5 yuan = 20. Strict window to catch
        # rate / min-cap regressions; allows small rounding.
        if not (19.0 <= commission <= 22.0):
            print(f"[FAIL] Total commission {commission:.2f} outside expected [19, 22] "
                  "— commission rate or min-cap may be wrong")
            return False

        # Numerical (range) assertions.
        if result.get("avg_buy_price", 0) <= 0:
            print("[FAIL] Abnormal buy price — data may be corrupted")
            return False
        # Observed PnL across multiple runs: -17.88, -22.88, -25.88. Window
        # [-30, -10] absorbs cache-race variance but catches slippage /
        # commission skips / wrong-side fills (each shifts PnL by >10).
        if not (-30.0 <= pnl <= -10.0):
            print(f"[FAIL] PnL {pnl:.2f} outside expected [-30, -10] "
                  "— slippage model or fill direction may be wrong")
            return False

        print(f"[PASS] Smoke test passed!")
        print(f"  - Trades:      {total} (buys={buys}, sells={sells})")
        print(f"  - Final pos:   {final_position}")
        print(f"  - Commission:  {commission:.2f}")
        print(f"  - PnL:         {pnl:.2f}  (range [-30, -10])")
        print(f"  - Buy px:      {result.get('avg_buy_price', 0):.2f}")
        return True

    except Exception as e:
        print(f"[FAIL] Smoke test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
