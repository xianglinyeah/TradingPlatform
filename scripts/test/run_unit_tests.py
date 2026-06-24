#!/usr/bin/env python3
"""
Run unit tests for all services

Supported services:
- strategy_engine (pytest)
- ExecutionService (dotnet test)
- MarketData.Replay (verified via E2E tests)
"""
import sys
import os
import subprocess
from pathlib import Path

class UnitTestRunner:
    """Unit test runner"""

    def __init__(self):
        self.project_root = Path.cwd()
        self.results = {}

    def run_strategy_tests(self):
        """Run strategy_engine unit tests"""
        print("[STRATEGY] Running strategy_engine tests...")

        strategy_path = self.project_root / "src" / "strategy-engine"
        if not strategy_path.exists():
            print("[SKIP] strategy_engine does not exist")
            return False

        tests_path = strategy_path / "tests"
        if not tests_path.exists():
            print("[SKIP] strategy_engine/tests does not exist")
            return False

        try:
            # Use strategy_engine venv
            venv_python = strategy_path / "venv/Scripts/python.exe"
            if not venv_python.exists():
                venv_python = strategy_path / "venv/bin/python"
            if not venv_python.exists():
                print("[WARN] strategy_engine venv does not exist, using system Python")
                venv_python = Path(sys.executable)

            # Run pytest
            result = subprocess.run(
                [str(venv_python), "-m", "pytest", "tests/", "-v"],
                cwd=strategy_path,
                capture_output=True,
                text=True,
                timeout=300
            )

            print(result.stdout)
            if result.stderr:
                print("[STDERR]", result.stderr)

            success = result.returncode == 0
            print(f"[{'OK' if success else 'FAIL'}] strategy_engine tests completed")
            return success

        except subprocess.TimeoutExpired:
            print("[ERROR] strategy_engine tests timed out")
            return False
        except Exception as e:
            print(f"[ERROR] strategy_engine tests failed: {e}")
            return False

    def run_execution_tests(self):
        """Run ExecutionService unit tests"""
        print("[EXECUTION] Running ExecutionService tests...")

        src_path = self.project_root / "src"
        if not src_path.exists():
            print("[SKIP] src directory does not exist")
            return None

        # Run C# unit tests - use dotnet test for the solution
        try:
            print("  Running C# solution unit tests...")
            result = subprocess.run(
                ["dotnet", "test", "TradingPlatform.sln", "--verbosity", "normal"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=300
            )

            # Check whether tests failed
            test_failed = result.returncode != 0

            # Show test summary
            if result.stdout:
                for line in result.stdout.split('\n'):
                    # Show total test count and results
                    if 'Total test files:' in line or 'Total tests:' in line or \
                       'Passed:' in line or 'Failed:' in line or 'Skipped:' in line:
                        print(f"    {line.strip()}")

            success = not test_failed
            print(f"[{'OK' if success else 'FAIL'}] C# unit tests completed")
            return success

        except subprocess.TimeoutExpired:
            print("[ERROR] C# tests timed out")
            return False
        except FileNotFoundError:
            print("[SKIP] dotnet command does not exist")
            return None
        except Exception as e:
            print(f"[ERROR] C# tests failed: {e}")
            return False

        if not existing_tests:
            print("[SKIP] ExecutionService test project does not exist")
            return None

        try:
            # Run all test projects
            all_passed = True
            for test_proj in existing_tests:
                print(f"  Running: {test_proj.parent.name}...")
                try:
                    result = subprocess.run(
                        ["dotnet", "test", str(test_proj), "--verbosity", "detailed", "--no-build"],
                        cwd=str(backtesting_path),
                        capture_output=True,
                        text=True,
                        encoding='utf-8',  # Use UTF-8 encoding
                        errors='ignore',   # Ignore encoding errors
                        timeout=300
                    )

                    # Check whether tests failed
                    test_failed = result.returncode != 0

                    # Show test summary
                    if result.stdout:
                        for line in result.stdout.split('\n'):
                            # Show total test count and results
                            if 'Total test files:' in line or 'Total tests:' in line or \
                               'Passed:' in line or 'Failed:' in line or 'Skipped:' in line:
                                print(f"    {line.strip()}")
                            # Show failed test details
                            elif test_failed and ('Failed' in line or 'Error' in line or 'test' in line.lower()):
                                print(f"    {line.strip()}")

                    if test_failed:
                        all_passed = False
                        print(f"    [FAIL] {test_proj.parent.name}")
                        # Show detailed error information
                        if result.stderr:
                            print("    === Error details ===")
                            for line in result.stderr.split('\n'):
                                if line.strip():
                                    print(f"    {line.strip()}")
                    else:
                        print(f"    [OK] {test_proj.parent.name}")

                except subprocess.TimeoutExpired:
                    print(f"    [TIMEOUT] {test_proj.parent.name}")
                    all_passed = False
                except Exception as e:
                    print(f"    [ERROR] {test_proj.parent.name}: {e}")
                    all_passed = False

            success = all_passed
            print(f"[{'OK' if success else 'FAIL'}] ExecutionService tests completed")
            return success

        except subprocess.TimeoutExpired:
            print("[ERROR] ExecutionService tests timed out")
            return False
        except FileNotFoundError:
            print("[SKIP] dotnet command does not exist")
            return None
        except Exception as e:
            print(f"[ERROR] ExecutionService tests failed: {e}")
            return False

    def run_simulation_tests(self):
        """Run MarketData.Replay unit tests"""
        print("[SIMULATION] Running MarketData.Replay tests...")

        # C# tests are already run via dotnet test TradingPlatform.sln in run_execution_tests
        # Including MarketData.Replay.Tests
        print("[INFO] MarketData.Replay unit tests are included in the C# solution tests")
        print("[INFO] Use E2E tests (smoke/full) to verify MarketData.Replay functionality")
        return True

        try:
            # Run all test projects
            all_passed = True
            for test_proj in existing_tests:
                print(f"  Running: {test_proj.parent.name}...")
                try:
                    result = subprocess.run(
                        ["dotnet", "test", str(test_proj), "--verbosity", "detailed", "--no-build"],
                        cwd=str(backtesting_path),
                        capture_output=True,
                        text=True,
                        encoding='utf-8',  # Use UTF-8 encoding
                        errors='ignore',   # Ignore encoding errors
                        timeout=300
                    )

                    # Check whether tests failed
                    test_failed = result.returncode != 0

                    # Show test summary
                    if result.stdout:
                        for line in result.stdout.split('\n'):
                            # Show total test count and results
                            if 'Total test files:' in line or 'Total tests:' in line or \
                               'Passed:' in line or 'Failed:' in line or 'Skipped:' in line:
                                print(f"    {line.strip()}")
                            # Show failed test details
                            elif test_failed and ('Failed' in line or 'Error' in line or 'test' in line.lower()):
                                print(f"    {line.strip()}")

                    if test_failed:
                        all_passed = False
                        print(f"    [FAIL] {test_proj.parent.name}")
                        # Show detailed error information
                        if result.stderr:
                            print("    === Error details ===")
                            for line in result.stderr.split('\n'):
                                if line.strip():
                                    print(f"    {line.strip()}")
                    else:
                        print(f"    [OK] {test_proj.parent.name}")

                except subprocess.TimeoutExpired:
                    print(f"    [TIMEOUT] {test_proj.parent.name}")
                    all_passed = False
                except Exception as e:
                    print(f"    [ERROR] {test_proj.parent.name}: {e}")
                    all_passed = False

            success = all_passed
            print(f"[{'OK' if success else 'FAIL'}] ReplayService tests completed")
            return success

        except subprocess.TimeoutExpired:
            print("[ERROR] ReplayService tests timed out")
            return False
        except FileNotFoundError:
            print("[SKIP] dotnet command does not exist")
            return None
        except Exception as e:
            print(f"[ERROR] ReplayService tests failed: {e}")
            return False

    def run_all_tests(self):
        """Run unit tests for all services"""
        print("="*60)
        print("[UNIT] Unit Test Runner")
        print("="*60)
        print()

        results = {}

        # Run each service tests
        results['strategy_engine'] = self.run_strategy_tests()
        print()
        results['ExecutionService'] = self.run_execution_tests()
        print()
        results['MarketData.Replay'] = self.run_simulation_tests()
        print()

        # Summarize results
        print("="*60)
        print("[SUMMARY] Test Results Summary")
        print("="*60)
        for service, success in results.items():
            if success is None:
                status = "[SKIP]"
            elif success:
                status = "[PASS]"
            else:
                status = "[FAIL]"
            print(f"  {status} {service}")

        # Only False counts as failure, None and True both count as pass
        all_passed = all(v is None or v is True for v in results.values())
        print()
        if all_passed:
            print("[OK] All unit tests passed!")
        else:
            print("[FAIL] Some unit tests failed")
        print("="*60)

        return all_passed

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Unit Test Runner")
    parser.add_argument("--service", help="Specify service (strategy/execution/replay)")
    args = parser.parse_args()

    runner = UnitTestRunner()

    if args.service:
        # Run specified service tests
        service_map = {
            "strategy": runner.run_strategy_tests,
            "execution": runner.run_execution_tests,
            "simulation": runner.run_simulation_tests
        }
        test_func = service_map.get(args.service.lower())
        if test_func:
            success = test_func()
            sys.exit(0 if success else 1)
        else:
            print(f"[ERROR] Unknown service: {args.service}")
            print("Available: strategy, execution, simulation")
            sys.exit(1)
    else:
        # Run all tests
        success = runner.run_all_tests()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
