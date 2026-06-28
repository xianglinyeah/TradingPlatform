"""
E2E test helper functions

Provides local backtest, ReplayService operations, database query and other features
"""
import subprocess
import sys
import requests
import time
import psycopg2
import re
import json
from typing import Dict, List, Tuple
from datetime import datetime

class BacktestTestHelper:
    """Backtest test helper class"""

    def __init__(self):
        self.replay_api_url = "http://localhost:8081/api/Replay"
        self.db_config = {
            "host": "localhost",
            "port": 5432,
            "database": "dev",
            "user": "dev_user",
            "password": "dev_pass",
            "options": "-c search_path=execution_service,public"
        }
        self.strategy_path = "./src/strategy-engine"

    def run_local_backtest(self, start_date: str, end_date: str) -> Dict:
        """
        Deprecated: the event-driven BacktestEngine was removed when daily-
        frequency alpha research moved to vectorized pandas under
        ``scripts/research/``. The old ``research`` CLI mode and
        ``research.yaml`` no longer exist.

        This stub raises immediately so callers fail loudly instead of
        hunting for a missing config file. For local alpha validation use::

            python -m scripts.research.volume_breakout_alpha

        from the project root.
        """
        raise NotImplementedError(
            "run_local_backtest is deprecated: BacktestEngine and the "
            "'research' CLI mode have been removed. For daily-frequency "
            "alpha research, use scripts/research/ (e.g. "
            "`python -m scripts.research.volume_breakout_alpha`)."
        )

    def _parse_backtest_output(self, output: str) -> Dict:
        """Parse local backtest output"""
        result = {
            "total_trades": 0,
            "total_pnl": 0.0,
            "realized_pnl": 0.0,
            "commission": 0.0,
            "signals": 0,
            "bars_processed": 0
        }

        # Parse key metrics - use regex to handle lines containing timestamps
        import re
        for line in output.split('\n'):
            if 'Total Trades:' in line:
                match = re.search(r'Total Trades:\s*(\d+)', line)
                if match:
                    result["total_trades"] = int(match.group(1))
            elif 'Total PnL:' in line:
                match = re.search(r'Total PnL:\s*CNY\s*([-\d.]+)', line)
                if match:
                    result["total_pnl"] = float(match.group(1))
            elif 'Realized PnL:' in line:
                match = re.search(r'Realized PnL:\s*CNY\s*([-\d.]+)', line)
                if match:
                    result["realized_pnl"] = float(match.group(1))
            elif 'Total Commission:' in line:
                match = re.search(r'Total Commission:\s*CNY\s*([-\d.]+)', line)
                if match:
                    result["commission"] = float(match.group(1))
            elif 'Signals Generated:' in line:
                match = re.search(r'Signals Generated:\s*(\d+)', line)
                if match:
                    result["signals"] = int(match.group(1))
            elif 'Bars Processed:' in line:
                match = re.search(r'Bars Processed:\s*(\d+)', line)
                if match:
                    result["bars_processed"] = int(match.group(1))

        print(f"[OK] Local backtest completed: {result['total_trades']} trades, PnL={result['total_pnl']:.2f}")
        return result

    def start_replay_session(self, start_date: str, end_date: str,
                           symbols: List[str], speed: int = 10000) -> str:
        """
        Start ReplayService replay session

        Args:
            start_date: Start date (format: YYYY-MM-DD)
            end_date: End date (format: YYYY-MM-DD)
            symbols: List of stock codes
            speed: Replay speed multiplier

        Returns:
            Session ID (with e2e-test prefix)
        """
        print(f"[REPLAY] Starting ReplayService: {start_date} ~ {end_date}, {speed}x speed")

        response = requests.post(
            f"{self.replay_api_url}/start",
            json={
                "startTime": f"{start_date}T09:30:00",
                "endTime": f"{end_date}T16:00:00",
                "symbols": symbols,
                "speedFactor": speed
            },
            timeout=10
        )

        if response.status_code not in (200, 201):
            raise RuntimeError(f"Failed to start replay (HTTP {response.status_code}): {response.text}")

        data = response.json()
        replay_session_id = data["sessionId"]

        # Return ID with e2e-test prefix, but do not update database yet
        e2e_session_id = f"e2e-test-{replay_session_id}"

        print(f"[OK] Replay started: {e2e_session_id}")
        return e2e_session_id, replay_session_id

    def wait_for_session_complete(self, e2e_session_id: str, replay_session_id: str, timeout: int = 120):
        """
        Wait for replay session to complete

        Args:
            e2e_session_id: E2E test session ID (for display)
            replay_session_id: ReplayService session ID (for status check)
            timeout: Timeout (seconds)
        """
        print(f"[WAIT] Waiting for session to complete: {e2e_session_id}")

        start_time = time.time()
        last_progress = 0

        while time.time() - start_time < timeout:
            try:
                response = requests.get(
                    f"{self.replay_api_url}/status/{replay_session_id}",  # use replay_session_id
                    timeout=5
                )

                if response.status_code != 200:
                    time.sleep(2)
                    continue

                data = response.json()
                status = data["status"]  # 0=Created, 1=Running, 2=Paused, 3=Stopped, 4=Completed
                progress = data.get("progressPercentage", 0)

                # Display progress
                if progress > last_progress + 5:  # Show once every 5%
                    print(f"   Progress: {progress:.0f}%")
                    last_progress = progress

                # 3 = Completed
                if status == 3:
                    print(f"[OK] Session completed: {e2e_session_id}")
                    # After session completes, update session_id in database
                    self._update_session_id(replay_session_id, e2e_session_id)
                    return

                # Display error message
                if data.get("errorMessage"):
                    print(f"[ERROR] Error: {data['errorMessage']}")
                    raise RuntimeError(f"Session failed: {data['errorMessage']}")

                time.sleep(2)

            except requests.exceptions.RequestException as e:
                print(f"[WARN] Request error, retrying: {e}")
                time.sleep(2)

        raise TimeoutError(f"Session {e2e_session_id} did not complete within {timeout} seconds")

    def _update_session_id(self, old_session_id: str, new_session_id: str):
        """Update session_id in database, add e2e-test prefix"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()

        try:
            # Update trades table
            cursor.execute("""
                UPDATE trades
                SET session_id = %s
                WHERE session_id = %s
            """, (new_session_id, old_session_id))

            # Update orders table
            cursor.execute("""
                UPDATE orders
                SET session_id = %s
                WHERE session_id = %s
            """, (new_session_id, old_session_id))

            # No error raised if there is no data yet
            conn.commit()
            print(f"[UPDATE] Session ID updated: {old_session_id} -> {new_session_id}")

        except Exception as e:
            print(f"[WARN] Could not update session ID: {e}")
            conn.rollback()

        finally:
            cursor.close()
            conn.close()

    def get_database_results(self, session_id: str) -> Dict:
        """
        Get backtest results from database

        Args:
            session_id: Session ID

        Returns:
            Dictionary containing trade data, PnL and other information
        """
        print(f"[DATABASE] Getting results from database: {session_id}")

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()

        try:
            # Get trade statistics
            cursor.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    COUNT(CASE WHEN side = 'buy' THEN 1 END) as buy_trades,
                    COUNT(CASE WHEN side = 'sell' THEN 1 END) as sell_trades,
                    SUM(CASE WHEN side = 'buy' THEN quantity ELSE 0 END) as buy_quantity,
                    ROUND(AVG(CASE WHEN side = 'buy' THEN price END)::numeric, 2) as avg_buy_price,
                    ROUND(AVG(CASE WHEN side = 'sell' THEN price END)::numeric, 2) as avg_sell_price,
                    COALESCE(SUM(commission), 0) as total_commission,
                    COALESCE(SUM(CASE WHEN side = 'buy' THEN quantity ELSE 0 END)
                           - SUM(CASE WHEN side = 'sell' THEN quantity ELSE 0 END), 0) as final_position
                FROM trades
                WHERE session_id = %s
            """, (session_id,))

            row = cursor.fetchone()
            if not row:
                return {"total_trades": 0, "pnl": 0.0}

            stats = {
                "total_trades": row[0],
                "buy_trades": row[1],
                "sell_trades": row[2],
                "buy_quantity": row[3],
                "avg_buy_price": float(row[4]) if row[4] else 0.0,
                "avg_sell_price": float(row[5]) if row[5] else 0.0,
                # Deterministic structural fields (added 2026-06-28 after §1
                # cache race made PnL non-deterministic in 10000x replay).
                "total_commission": float(row[6]) if row[6] is not None else 0.0,
                "final_position": float(row[7]) if row[7] is not None else 0.0,
            }

            # Calculate PnL
            cursor.execute("""
                WITH paired_trades AS (
                    SELECT
                        t1.price as sell_price,
                        t2.price as buy_price,
                        t1.quantity,
                        t1.commission as sell_commission,
                        t2.commission as buy_commission
                    FROM trades t1
                    JOIN trades t2 ON t1.session_id = t2.session_id
                        AND t2.side = 'buy'
                    WHERE t1.side = 'sell'
                        AND t1.session_id = %s
                        AND t2.trade_time = (
                            SELECT MAX(trade_time) FROM trades t3
                            WHERE t3.side = 'buy'
                                AND t3.trade_time < t1.trade_time
                                AND t3.session_id = t1.session_id
                        )
                )
                SELECT COALESCE(SUM(
                    (sell_price - buy_price) * quantity - sell_commission - buy_commission
                ), 0)
                FROM paired_trades
            """, (session_id,))

            pnl_row = cursor.fetchone()
            stats["pnl"] = float(pnl_row[0]) if pnl_row else 0.0

            print(f"[DATA] Database results: {stats['total_trades']} trades, PnL={stats['pnl']:.2f}")
            return stats

        finally:
            cursor.close()
            conn.close()

    def get_all_test_sessions(self) -> List[str]:
        """Get all E2E test sessions"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT DISTINCT session_id
                FROM trades
                WHERE session_id LIKE 'e2e-test-%'
                ORDER BY session_id DESC
            """)

            sessions = [row[0] for row in cursor.fetchall()]
            return sessions

        finally:
            cursor.close()
            conn.close()

    def compare_results(self, local: Dict, db: Dict,
                       tolerance_pnl: float = 1.0,
                       tolerance_trades: int = 0,
                       check_prices: bool = True) -> Tuple[bool, str]:
        """
        Compare local backtest and database results

        Args:
            local: Local backtest results
            db: Database results
            tolerance_pnl: PnL tolerance
            tolerance_trades: Trade count tolerance
            check_prices: Whether to check prices

        Returns:
            (whether passed, error message)
        """
        errors = []

        # Compare trade count
        if abs(local["total_trades"] - db["total_trades"]) > tolerance_trades:
            errors.append(
                f"Trade count mismatch: local={local['total_trades']}, database={db['total_trades']}"
            )

        # Compare PnL
        if abs(local["total_pnl"] - db["pnl"]) > tolerance_pnl:
            errors.append(
                f"PnL mismatch: local={local['total_pnl']:.2f}, database={db['pnl']:.2f}"
            )

        # Compare buy/sell prices (if data available)
        if check_prices and db.get("avg_buy_price", 0) > 0:
            if "avg_buy_price" in db and "avg_sell_price" in db:
                # Simple price range check
                if db["avg_buy_price"] <= 0 or db["avg_sell_price"] <= 0:
                    errors.append(f"Abnormal price: buy price={db['avg_buy_price']}, sell price={db['avg_sell_price']}")

        if errors:
            return False, "; ".join(errors)

        return True, "[OK] Test passed"

    def cleanup_old_test_sessions(self, keep_days: int = 7):
        """Clean up old E2E test sessions (optional)"""
        print(f"[CLEANUP] Cleaning up E2E test sessions older than {keep_days} days")

        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM trades
                WHERE session_id LIKE 'e2e-test-%'
                AND trade_time < NOW() - INTERVAL '%s days'
            """, (keep_days,))

            deleted_count = cursor.rowcount
            conn.commit()

            if deleted_count > 0:
                print(f"[DELETE] Cleaned up {deleted_count} old test records")
            else:
                print(f"[INFO] No old test records to clean up")

        finally:
            cursor.close()
            conn.close()

    def check_service_health(self) -> Dict[str, bool]:
        """Check health status of each service"""
        health = {
            "replay_api": False,
            "database": False
        }

        # Check MarketData.Replay API - use root path
        try:
            response = requests.get("http://localhost:5000/", timeout=5)
            health["replay_api"] = response.status_code == 200
        except:
            pass

        # Check database
        try:
            conn = psycopg2.connect(**self.db_config)
            conn.close()
            health["database"] = True
        except:
            pass

        return health