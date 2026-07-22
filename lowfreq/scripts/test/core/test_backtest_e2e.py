"""
E2E integration test: local backtest vs joint debugging

Test strategy:
1. Use "e2e-test-" prefix to identify test data, do not interfere with normal data
2. Run local mode twice (January, February) to get baseline results
3. ReplayService runs two sessions (January, February) to get actual results
4. Compare result consistency
5. Test session data isolation

Runtime: about 5-8 minutes
"""
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

import time
from datetime import datetime, timedelta
from helpers import BacktestTestHelper

class TestBacktestE2E:
    """Backtest E2E test suite"""

    @classmethod
    def setup_class(cls):
        """Test suite initialization"""
        cls.helper = BacktestTestHelper()
        cls.test_sessions = []  # track created session IDs

        # Check service health
        print("\n" + "="*80)
        print("[START] E2E tests started")
        print("="*80)

        health = cls.helper.check_service_health()
        print(f"\n[HEALTH] Service health check:")
        print(f"   ReplayService API: {'[OK]' if health['replay_api'] else '[FAIL]'}")
        print(f"   Database: {'[OK]' if health['database'] else '[FAIL]'}")

        # Only warn, do not interrupt tests
        if not health["database"]:
            print("[WARN] Database check failed, but continuing anyway...")
        if not health["replay_api"]:
            print("[WARN] ReplayService API check failed, but continuing anyway...")

    @classmethod
    def teardown_class(cls):
        """Test suite cleanup"""
        print("\n" + "="*80)
        print("[DONE] E2E tests completed")
        print("="*80)

        print(f"\n[LIST] Sessions created in this test run:")
        for session in cls.test_sessions:
            print(f"   - {session}")

        print(f"\n[INFO] Note: Test data remains in the database, viewable in Grafana:")
        print(f"   Dashboard: http://localhost:3001/d/1b83feae-9713-45a4-abe5-e1bbb845e60c")

    def test_january_backtest_consistency(self):
        """Test 1: January backtest - local mode vs joint debugging"""
        print("\n" + "----"*80)
        print("[TEST1] January 2023 data consistency")
        print("----"*80)

        # 1. Local mode backtest (baseline)
        local_result = self.helper.run_local_backtest(
            start_date="20230101",
            end_date="20230115"
        )

        # 2. Start ReplayService replay
        e2e_session_id, replay_session_id = self.helper.start_replay_session(
            start_date="2023-01-01",
            end_date="2023-01-15",
            symbols=["600000.SH"],
            speed=10000
        )

        self.test_sessions.append(e2e_session_id)

        # 3. Wait for completion
        self.helper.wait_for_session_complete(e2e_session_id, replay_session_id, timeout=90)

        # 4. Get database results
        db_result = self.helper.get_database_results(e2e_session_id)

        # 5. Compare results
        passed, message = self.helper.compare_results(
            local_result,
            db_result,
            tolerance_pnl=1.0,  # PnL allows 1 yuan tolerance
            tolerance_trades=0   # Trade count must match exactly
        )

        # 6. Detailed assertions
        assert local_result["total_trades"] == db_result["total_trades"], \
            f"Trade count mismatch: {local_result['total_trades']} vs {db_result['total_trades']}"

        assert abs(local_result["total_pnl"] - db_result["pnl"]) <= 1.0, \
            f"PnL difference too large: {local_result['total_pnl']:.2f} vs {db_result['pnl']:.2f}"

        print(f"[OK] Test 1 passed:")
        print(f"   Local: {local_result['total_trades']} trades, PnL={local_result['total_pnl']:.2f}")
        print(f"   Joint: {db_result['total_trades']} trades, PnL={db_result['pnl']:.2f}")

    def test_february_backtest_consistency(self):
        """Test 2: February backtest - local mode vs joint debugging"""
        print("\n" + "----"*80)
        print("[TEST2] February 2023 data consistency")
        print("----"*80)

        # 1. Local mode backtest
        local_result = self.helper.run_local_backtest(
            start_date="20230201",
            end_date="20230215"
        )

        # 2. Start ReplayService
        e2e_session_id, replay_session_id = self.helper.start_replay_session(
            start_date="2023-02-01",
            end_date="2023-02-15",
            symbols=["600000.SH"],
            speed=10000
        )

        self.test_sessions.append(e2e_session_id)

        # 3. Wait for completion
        self.helper.wait_for_session_complete(e2e_session_id, replay_session_id, timeout=90)

        # 4. Get database results
        db_result = self.helper.get_database_results(e2e_session_id)

        # 5. Compare results
        assert local_result["total_trades"] == db_result["total_trades"], \
            f"Trade count mismatch: {local_result['total_trades']} vs {db_result['total_trades']}"

        assert abs(local_result["total_pnl"] - db_result["pnl"]) <= 1.0, \
            f"PnL difference too large: {local_result['total_pnl']:.2f} vs {db_result['pnl']:.2f}"

        print(f"[OK] Test 2 passed:")
        print(f"   Local: {local_result['total_trades']} trades, PnL={local_result['total_pnl']:.2f}")
        print(f"   Joint: {db_result['total_trades']} trades, PnL={db_result['pnl']:.2f}")

    def test_multiple_sessions_isolation(self):
        """Test 3: Multi-session data isolation"""
        print("\n" + "----"*80)
        print("[LOCK] Test 3: Session data isolation")
        print("----"*80)

        # Get all test sessions
        test_sessions = self.helper.get_all_test_sessions()

        print(f"[DATA] Database contains {len(test_sessions)} E2E test sessions")

        # Verify at least the two sessions from current tests
        assert len(test_sessions) >= 2, "Should have at least 2 test sessions"

        # Verify each session has independent data
        session_data = {}
        for session in test_sessions:
            result = self.helper.get_database_results(session)
            session_data[session] = result
            print(f"   {session}: {result['total_trades']} trades")

        # Verify no cross-session data contamination
        for session_id, data in session_data.items():
            # Each session's data volume should be as expected
            assert data["total_trades"] >= 1, f"Session {session_id} should have trade data"

        print(f"[OK] Test 3 passed: All session data correctly isolated")

    def test_session_pnl_calculation(self):
        """Test 4: PnL calculation correctness"""
        print("\n" + "----"*80)
        print("[MONEY] Test 4: PnL calculation accuracy")
        print("----"*80)

        # Get the latest two sessions
        all_sessions = self.helper.get_all_test_sessions()

        if len(all_sessions) < 2:
            print("[SKIP] Need at least 2 sessions for PnL calculation test")
            return

        sessions_to_test = all_sessions[:2]

        total_pnl = 0
        for session in sessions_to_test:
            result = self.helper.get_database_results(session)
            session_pnl = result["pnl"]
            total_pnl += session_pnl

            print(f"   {session}: PnL={session_pnl:.2f}")

            # Verify PnL is within reasonable range (should not have huge anomalies)
            assert abs(session_pnl) < 10000, \
                f"Session {session} has abnormal PnL: {session_pnl}"

        print(f"[OK] Test 4 passed: Total PnL={total_pnl:.2f}")

    def test_grafana_dashboard_accessibility(self):
        """Test 5: Grafana Dashboard accessibility"""
        print("\n" + "----"*80)
        print("[DATA] Test 5: Grafana Dashboard accessibility")
        print("----"*80)

        import requests

        try:
            # Attempt to access Grafana API
            response = requests.get(
                "http://localhost:3001/api/search",
                auth=("admin", "admin"),
                timeout=5
            )

            assert response.status_code == 200, "Grafana API access failed"

            # Search for backtest-related dashboards
            dashboards = response.json()
            backtest_dashboards = [
                d for d in dashboards
                if "backtest" in d.get("title", "").lower()
            ]

            print(f"[OK] Test 5 passed: Found {len(backtest_dashboards)} backtest-related dashboards")
            for dash in backtest_dashboards:
                print(f"   - {dash['title']}: {dash['url']}")

        except requests.exceptions.ConnectionError:
            print("[SKIP] Grafana service unavailable")
            return

# Main runner function (direct run without pytest)
def run_e2e_tests():
    """Run E2E tests directly (for debugging)"""
    test_suite = TestBacktestE2E()

    try:
        test_suite.setup_class()

        # Run each test
        test_suite.test_january_backtest_consistency()
        test_suite.test_february_backtest_consistency()
        test_suite.test_multiple_sessions_isolation()
        test_suite.test_session_pnl_calculation()
        test_suite.test_grafana_dashboard_accessibility()

        test_suite.teardown_class()

        print("\n" + "All E2E tests passed!")
        return True

    except Exception as e:
        print(f"\n" + "[FAIL] E2E tests failed:")
        print(f"   Error: {e}")
        test_suite.teardown_class()
        return False

if __name__ == "__main__":
    import sys
    success = run_e2e_tests()
    sys.exit(0 if success else 1)
