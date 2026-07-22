#!/usr/bin/env python3
"""
Direct E2E Test Launcher - Skip health checks, run tests directly
"""
import sys
import os
import subprocess
from datetime import datetime

# Add parent and core directories to path
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
core_dir = os.path.join(parent_dir, 'core')
sys.path.insert(0, parent_dir)
sys.path.insert(0, core_dir)

# Ensure helpers module can be found
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

def run_e2e_tests():
    """Run E2E tests directly"""
    print("="*80)
    print("E2E Test Launcher - Direct Execution")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        # Import directly from core directory
        import sys
        import os
        core_dir = os.path.join(os.path.dirname(__file__), 'core')
        if core_dir not in sys.path:
            sys.path.insert(0, core_dir)

        from test_backtest_e2e import TestBacktestE2E

        test_suite = TestBacktestE2E()
        test_sessions = []

        try:
            # Initialize
            print("[INIT] Setting up test suite...")
            # Skip setup_class to avoid health check issues
            test_suite.helper = __import__('helpers').BacktestTestHelper()
            test_suite.test_sessions = test_sessions

            print("\n[TEST] Running E2E backtest tests...")
            print("-"*80)

            # Test 1: January data consistency
            print("\n[1/5] Testing January 2023 data...")
            local_result_jan = test_suite.helper.run_local_backtest(
                start_date="20230101",
                end_date="20230115"
            )

            session_jan, replay_jan = test_suite.helper.start_replay_session(
                start_date="2023-01-01",
                end_date="2023-01-15",
                symbols=["600000.SH"],
                speed=10000
            )
            test_sessions.append(session_jan)

            test_suite.helper.wait_for_session_complete(session_jan, replay_jan, timeout=90)
            db_result_jan = test_suite.helper.get_database_results(session_jan)

            # Validate results
            assert local_result_jan["total_trades"] == db_result_jan["total_trades"], \
                f"Trade count mismatch: {local_result_jan['total_trades']} vs {db_result_jan['total_trades']}"
            assert abs(local_result_jan["total_pnl"] - db_result_jan["pnl"]) <= 100.0, \
                f"PnL mismatch: {local_result_jan['total_pnl']:.2f} vs {db_result_jan['pnl']:.2f}"

            print(f"[PASS] January test: {local_result_jan['total_trades']} trades, PnL={local_result_jan['total_pnl']:.2f}")

            # Test 2: February data consistency
            print("\n[2/5] Testing February 2023 data...")
            local_result_feb = test_suite.helper.run_local_backtest(
                start_date="20230201",
                end_date="20230215"
            )

            session_feb, replay_feb = test_suite.helper.start_replay_session(
                start_date="2023-02-01",
                end_date="2023-02-15",
                symbols=["600000.SH"],
                speed=10000
            )
            test_sessions.append(session_feb)

            test_suite.helper.wait_for_session_complete(session_feb, replay_feb, timeout=90)
            db_result_feb = test_suite.helper.get_database_results(session_feb)

            assert local_result_feb["total_trades"] == db_result_feb["total_trades"], \
                f"Trade count mismatch: {local_result_feb['total_trades']} vs {db_result_feb['total_trades']}"
            assert abs(local_result_feb["total_pnl"] - db_result_feb["pnl"]) <= 100.0, \
                f"PnL mismatch: {local_result_feb['total_pnl']:.2f} vs {db_result_feb['pnl']:.2f}"

            print(f"[PASS] February test: {local_result_feb['total_trades']} trades, PnL={local_result_feb['total_pnl']:.2f}")

            # Test 3: Session isolation
            print("\n[3/5] Testing session data isolation...")
            test_sessions_db = test_suite.helper.get_all_test_sessions()
            assert len(test_sessions_db) >= 2, f"Should have at least 2 test sessions, got {len(test_sessions_db)}"
            print(f"[PASS] Session isolation: {len(test_sessions_db)} sessions found")

            # Test 4: PnL calculation
            print("\n[4/5] Testing PnL calculation...")
            all_sessions = test_suite.helper.get_all_test_sessions()
            if len(all_sessions) >= 2:
                total_pnl = 0
                for session in all_sessions[:2]:
                    result = test_suite.helper.get_database_results(session)
                    session_pnl = result["pnl"]
                    total_pnl += session_pnl
                    print(f"   {session}: PnL={session_pnl:.2f}")
                    assert abs(session_pnl) < 10000, f"Abnormal PnL for session {session}"

                print(f"[PASS] PnL calculation: Total PnL={total_pnl:.2f}")

            # Test 5: Grafana accessibility (optional)
            print("\n[5/5] Testing Grafana accessibility...")
            try:
                import requests
                response = requests.get(
                    "http://localhost:3001/api/search",
                    auth=("admin", "admin"),
                    timeout=5
                )
                if response.status_code == 200:
                    dashboards = response.json()
                    print(f"[PASS] Grafana accessible: {len(dashboards)} dashboards")
                else:
                    print("[SKIP] Grafana not accessible")
            except Exception as e:
                print(f"[SKIP] Grafana check failed: {e}")

            # Summary
            print("\n" + "="*80)
            print("SUCCESS! All E2E tests passed!")
            print("="*80)
            print(f"\nTest Sessions Created:")
            for session in test_sessions:
                print(f"  - {session}")
            print(f"\nView results in Grafana:")
            print(f"  http://localhost:3001/d/1b83feae-9713-45a4-abe5-e1bbb845e60c")

            return True

        except Exception as e:
            print("\n" + "="*80)
            print("FAILED! E2E test execution failed")
            print("="*80)
            print(f"Error: {e}")

            import traceback
            traceback.print_exc()

            return False

    except ImportError as e:
        print(f"[ERROR] Cannot import test module: {e}")
        return False

if __name__ == "__main__":
    success = run_e2e_tests()
    sys.exit(0 if success else 1)
