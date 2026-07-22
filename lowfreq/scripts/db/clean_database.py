#!/usr/bin/env python3
"""
One-click cleanup of ExecutionService database

Features:
1. Clean all trade data
2. Clean specific session data
3. Clean expired data
4. Keep data from the last N days
"""
import subprocess
import sys
import argparse
from datetime import datetime, timedelta

class DatabaseCleaner:
    def __init__(self):
        self.db_name = "execution_service"
        self.docker_container = "dev-postgres"  # Docker container name

    def check_container_running(self):
        """Check if database container is running"""
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={self.docker_container}"],
                capture_output=True,
                text=True
            )
            return self.docker_container in result.stdout
        except:
            return False

    def clean_all_trades(self):
        """Clean all trade data"""
        print("[CLEAN] Cleaning all trade data...")

        if not self.check_container_running():
            print("[WARN] Database container is not running")
            return False

        try:
            # Use docker exec to run SQL
            sql = "TRUNCATE TABLE trades;"

            result = subprocess.run([
                "docker", "exec", "-i", self.docker_container,
                "psql", "-U", "dev_user", "-d", "execution_service",
                "-c", sql
            ], capture_output=True, text=True)

            if result.returncode == 0:
                print("[OK] All trade data cleaned")
                return True
            else:
                print(f"[FAIL] Cleanup failed: {result.stderr}")
                return False

        except Exception as e:
            print(f"[ERROR] Cleanup failed: {e}")
            return False

    def clean_test_sessions(self, days=7):
        """Clean test session data"""
        print(f"[CLEAN] Cleaning E2E test sessions older than {days} days...")

        if not self.check_container_running():
            print("[WARN] Database container is not running")
            return False

        try:
            # Use docker exec to run SQL
            sql = f"""
            DELETE FROM trades
            WHERE session_id LIKE 'e2e-test-%'
            AND trade_time < NOW() - INTERVAL '{days} days';
            """

            result = subprocess.run([
                "docker", "exec", "-i", self.docker_container,
                "psql", "-U", "dev_user", "-d", "execution_service",
                "-c", sql
            ], capture_output=True, text=True)

            if result.returncode == 0:
                print(f"[OK] Test sessions older than {days} days cleaned")
                return True
            else:
                print(f"[FAIL] Cleanup failed: {result.stderr}")
                return False

        except Exception as e:
            print(f"[ERROR] Cleanup failed: {e}")
            return False

    def clean_specific_session(self, session_id):
        """Clean a specific session"""
        print(f"[CLEAN] Cleaning session: {session_id}...")

        if not self.check_container_running():
            print("[WARN] Database container is not running")
            return False

        try:
            sql = f"DELETE FROM trades WHERE session_id = '{session_id}';"

            result = subprocess.run([
                "docker", "exec", "-i", self.docker_container,
                "psql", "-U", "dev_user", "-d", "execution_service",
                "-c", sql
            ], capture_output=True, text=True)

            if result.returncode == 0:
                print(f"[OK] Session cleaned: {session_id}")
                return True
            else:
                print(f"[FAIL] Cleanup failed: {result.stderr}")
                return False

        except Exception as e:
            print(f"[ERROR] Cleanup failed: {e}")
            return False

    def show_database_stats(self):
        """Show database statistics"""
        print("[STATS] Database statistics:")

        if not self.check_container_running():
            print("[WARN] Database container is not running")
            return

        try:
            # Total trade count
            sql = "SELECT COUNT(*) FROM trades;"
            result = subprocess.run([
                "docker", "exec", "-i", self.docker_container,
                "psql", "-U", "dev_user", "-d", "execution_service",
                "-c", sql
            ], capture_output=True, text=True)

            if result.returncode == 0:
                total = result.stdout.strip().split('\n')[-1]
                print(f"  Total trades: {total}")

            # Session count
            sql = "SELECT COUNT(DISTINCT session_id) FROM trades;"
            result = subprocess.run([
                "docker", "exec", "-i", self.docker_container,
                "psql", "-U", "dev_user", "-d", "execution_service",
                "-c", sql
            ], capture_output=True, text=True)

            if result.returncode == 0:
                sessions = result.stdout.strip().split('\n')[-1]
                print(f"  Total sessions: {sessions}")

            # Latest trade time
            sql = "SELECT MAX(trade_time) FROM trades;"
            result = subprocess.run([
                "docker", "exec", "-i", self.docker_container,
                "psql", "-U", "dev_user", "-d", "execution_service",
                "-c", sql
            ], capture_output=True, text=True)

            if result.returncode == 0:
                latest = result.stdout.strip().split('\n')[-1]
                print(f"  Latest trade: {latest}")

        except Exception as e:
            print(f"[WARN] Could not get statistics: {e}")

def main():
    parser = argparse.ArgumentParser(description="Clean ExecutionService database")
    parser.add_argument("--test", action="store_true", help="Clean test session data (older than 7 days)")
    parser.add_argument("--session", help="Clean a specific session")
    parser.add_argument("--days", type=int, default=7, help="Clean data older than N days (default 7)")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")

    args = parser.parse_args()

    cleaner = DatabaseCleaner()

    # Show statistics
    if args.stats:
        cleaner.show_database_stats()
        return 0

    # Cleanup operations
    if args.test:
        success = cleaner.clean_test_sessions(args.days)
        return 0 if success else 1

    elif args.session:
        success = cleaner.clean_specific_session(args.session)
        return 0 if success else 1

    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())
