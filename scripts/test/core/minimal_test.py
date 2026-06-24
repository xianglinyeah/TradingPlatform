"""
Minimal test - only verify environment health (30 seconds)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from helpers import BacktestTestHelper

def run_minimal_test():
    """Minimal test: only check whether services are available"""
    print("[MINIMAL] Minimal test starting...")

    helper = BacktestTestHelper()

    # 1. Check service health
    print("[1/3] Checking service health...")
    health = helper.check_service_health()

    if not health["replay_api"]:
        print("[FAIL] MarketData.Replay API unavailable")
        return False

    if not health["database"]:
        print("[FAIL] Database unavailable")
        return False

    print("[OK] Service health check passed")

    # 2. Check API response
    print("[2/3] Checking API response...")
    try:
        import requests
        response = requests.get("http://localhost:5000/api/Replay/status/test", timeout=2)
        print("[OK] API response normal")
    except:
        print("[WARN] API call failed (test session may not exist)")

    # 3. Check database connection
    print("[3/3] Checking database connection...")
    try:
        import psycopg2
        conn = psycopg2.connect(**helper.db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        conn.close()
        print("[OK] Database connection normal")
    except Exception as e:
        print(f"[FAIL] Database connection failed: {e}")
        return False

    print("[PASS] [OK] Minimal test passed! Environment is ready to use")
    return True

if __name__ == "__main__":
    success = run_minimal_test()
    sys.exit(0 if success else 1)
