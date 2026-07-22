#!/usr/bin/env python3
"""
Smart E2E test runner - supports multiple test modes

Usage:
  python smart_e2e.py --smoke      # Smoke test (1-2 minutes)
  python smart_e2e.py --full       # Full test (5-8 minutes)
  python smart_e2e.py --ci         # CI mode (auto-select)
  python smart_e2e.py --local      # Local development mode
"""
import sys
import os
import argparse
import subprocess
import time
from datetime import datetime

class SmartE2ERunner:
    """Smart E2E test runner"""

    def __init__(self, mode="auto"):
        self.mode = mode
        self.start_time = time.time()

    def detect_environment(self):
        """Detect running environment"""
        # Check if in CI environment
        if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
            return "ci"

        # Check if in PR environment
        if os.getenv('GITHUB_HEAD_REF'):
            return "pr"

        # Check if interactive terminal is available
        if sys.stdin.isatty():
            return "local"

        return "unknown"

    def choose_test_mode(self):
        """Auto-select test mode based on environment"""
        env = self.detect_environment()

        if self.mode != "auto":
            return self.mode

        # Auto-select based on environment
        if env == "ci":
            # CI environment: quick smoke test
            return "smoke"
        elif env == "pr":
            # PR environment: full test
            return "full"
        elif env == "local":
            # Local environment: ask user
            print("[AI] Local development environment detected")
            print("Please select test mode:")
            print("  1. smoke   - Quick smoke test (1-2 minutes)")
            print("  2. full    - Full E2E test (5-8 minutes)")
            print("  3. minimal - Minimal test (30 seconds)")
            print("  4. unit    - Unit tests (strategy/execution/replay)")

            try:
                choice = input("Enter choice (default: smoke): ").strip() or "1"
                return ["smoke", "full", "minimal", "unit"][int(choice) - 1]
            except (ValueError, IndexError, KeyboardInterrupt, EOFError):
                print("[CANCEL] Invalid input or cancelled, using default smoke test")
                return "smoke"
        else:
            # Other environments: default smoke test
            return "smoke"

    def run_smoke_test(self):
        """Smoke test - quickly verify core functionality"""
        print("[SMOKE] Running smoke test...")

        # Call smoke_test.py
        smoke_script = os.path.join(os.path.dirname(__file__), "core/smoke_test.py")
        result = subprocess.run([
            sys.executable, smoke_script
        ], capture_output=False, text=True)

        return result.returncode == 0

    def run_full_test(self):
        """Full E2E test"""
        print("[FULL] Running full E2E test...")

        # Call existing launch_e2e.py
        launch_script = os.path.join(os.path.dirname(__file__), "launch_e2e.py")
        result = subprocess.run([
            sys.executable, launch_script
        ], capture_output=False, text=True, cwd=os.path.dirname(__file__))

        return result.returncode == 0

    def run_minimal_test(self):
        """Minimal test - only verify environment"""
        print("[MINIMAL] Running minimal test...")

        # Call minimal_test.py
        minimal_script = os.path.join(os.path.dirname(__file__), "core/minimal_test.py")
        result = subprocess.run([
            sys.executable, minimal_script
        ], capture_output=False, text=True)

        return result.returncode == 0

    def run_unit_test(self):
        """Unit tests - test unit tests for each service"""
        print("[UNIT] Running unit tests...")

        # Call run_unit_tests.py
        unit_script = os.path.join(os.path.dirname(__file__), "run_unit_tests.py")
        result = subprocess.run([
            sys.executable, unit_script
        ], capture_output=False, text=True)

        return result.returncode == 0

    def run_tests(self):
        """Run selected tests"""
        mode = self.choose_test_mode()

        print(f"\n{'='*60}")
        print(f"[ROCKET] Smart E2E Test Runner")
        print(f"{'='*60}")
        print(f"Mode: {mode}")
        print(f"Environment: {self.detect_environment()}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        success = False

        if mode == "smoke":
            success = self.run_smoke_test()
        elif mode == "full":
            success = self.run_full_test()
        elif mode == "minimal":
            success = self.run_minimal_test()
        elif mode == "unit":
            success = self.run_unit_test()

        # Show results
        elapsed = time.time() - self.start_time
        print(f"\n{'='*60}")
        if success:
            print(f"[OK] Tests passed! (elapsed: {elapsed:.1f}s)")
        else:
            print(f"[FAIL] Tests failed! (elapsed: {elapsed:.1f}s)")
        print(f"{'='*60}\n")

        return success

def main():
    parser = argparse.ArgumentParser(description="Smart E2E test runner")
    parser.add_argument("--smoke", action="store_true", help="Smoke test")
    parser.add_argument("--full", action="store_true", help="Full test")
    parser.add_argument("--minimal", action="store_true", help="Minimal test")
    parser.add_argument("--unit", action="store_true", help="Unit tests")
    parser.add_argument("--ci", action="store_true", help="CI mode")
    parser.add_argument("--local", action="store_true", help="Local mode")

    args = parser.parse_args()

    # Determine mode
    if args.smoke:
        mode = "smoke"
    elif args.full:
        mode = "full"
    elif args.minimal:
        mode = "minimal"
    elif args.unit:
        mode = "unit"
    elif args.ci:
        mode = "smoke"  # CI defaults to smoke
    elif args.local:
        mode = "auto"   # Local auto-select
    else:
        mode = "auto"

    runner = SmartE2ERunner(mode)
    success = runner.run_tests()

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
