"""
Paper Trading end-to-end test
Tests the full trading chain: strategy_engine -> ExecutionService -> GM Adapter
"""
import subprocess
import time
import sys
from pathlib import Path

def check_services():
    """Check whether all services are running"""
    print("Checking service status...")

    services = {
        "GM Adapter": False,
        "ExecutionService": False,
        "strategy_engine": False
    }

    # Check GM Adapter
    try:
        result = subprocess.run(
            ['tasklist'],
            capture_output=True,
            text=True,
            encoding='gbk',
            errors='ignore'
        )
        if 'execution_adapter_gm' in result.stdout:
            services["GM Adapter"] = True
            print("  [OK] GM Adapter running")
        else:
            print("  [FAIL] GM Adapter not running")
    except Exception as e:
        print(f"  [ERROR] Failed to check GM Adapter: {e}")

    # Check ExecutionService (Docker container)
    try:
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'name=execution-service', '--format', '{{.Names}}'],
            capture_output=True,
            text=True
        )
        if 'execution-service' in result.stdout:
            services["ExecutionService"] = True
            print("  [OK] ExecutionService running (Docker container)")
        else:
            print("  [FAIL] ExecutionService not running")
    except Exception as e:
        print(f"  [ERROR] Failed to check ExecutionService: {e}")

    # Check strategy_engine (Docker container)
    try:
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'name=strategy-engine', '--format', '{{.Names}}'],
            capture_output=True,
            text=True
        )
        if 'strategy-engine' in result.stdout:
            services["strategy_engine"] = True
            print("  [OK] strategy_engine running (Docker container)")
        else:
            print("  [INFO] strategy_engine not running (live/hot mode required for paper-trading tests)")
    except Exception as e:
        print(f"  [INFO] strategy_engine check failed: {e}")

    return services

def check_gm_adapter_logs():
    """Check GM Adapter logs"""
    print("\nChecking GM Adapter logs...")

    log_file = "D:/TradingPlatform/logs/execution-adapter-gm/execution-adapter-gm-realtime.log"

    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            if lines:
                print(f"  [OK] Found {len(lines)} log lines")
                print("  Last 5 log lines:")
                for line in lines[-5:]:
                    print(f"    {line.strip()}")
            else:
                print("  [WARN] Log file is empty")
    except FileNotFoundError:
        print("  [INFO] Log file does not exist, service may have just started")

def run_smoke_test():
    """Run smoke test"""
    print("\nRunning Smoke Test...")

    try:
        result = subprocess.run(
            ['python', 'D:/TradingPlatform/scripts/test/smart_e2e.py', '--smoke'],
            capture_output=True,
            text=True,
            timeout=120,
            encoding='utf-8',
            errors='ignore'
        )

        if 'PASS' in result.stdout or 'OK' in result.stdout:
            print("  [OK] Smoke Test passed")
            return True
        else:
            print("  [FAIL] Smoke Test failed")
            print("  Output:", result.stdout[:500])
            return False
    except subprocess.TimeoutExpired:
        print("  [WARN] Smoke Test timed out")
        return False
    except Exception as e:
        print(f"  [ERROR] Smoke Test exception: {e}")
        return False

def check_execution_service_logs():
    """Check ExecutionService logs"""
    print("\nChecking ExecutionService logs (PAPER_BROKER mode)...")

    log_file = "D:/TradingPlatform/logs/execution-service/execution-service-realtime.log"

    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Find PAPER_BROKER related logs
        paper_logs = [line for line in lines if 'PAPER_ADAPTER' in line or 'PAPER_BROKER' in line]

        if paper_logs:
            print(f"  [OK] Found {len(paper_logs)} PAPER_BROKER related log entries")
            print("  Recent PAPER_BROKER logs:")
            for line in paper_logs[-5:]:
                print(f"    {line.strip()}")
        else:
            print("  [INFO] No PAPER_BROKER related logs found")

    except FileNotFoundError:
        print("  [INFO] ExecutionService log file does not exist")

def check_gm_adapter_activity():
    """Check GM Adapter activity logs"""
    print("\nChecking GM Adapter activity logs...")

    log_file = "D:/TradingPlatform/logs/execution-adapter-gm/execution-adapter-gm-realtime.log"

    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Find gRPC related logs
        grpc_logs = [line for line in lines if 'GRPC' in line or 'PlaceOrder' in line]

        if grpc_logs:
            print(f"  [OK] Found {len(grpc_logs)} gRPC related log entries")
            print("  Recent gRPC activity:")
            for line in grpc_logs[-5:]:
                print(f"    {line.strip()}")
            return True
        else:
            print("  [INFO] No gRPC activity logs found")
            return False

    except FileNotFoundError:
        print("  [INFO] GM Adapter log file does not exist")
        return False

def main():
    print("=" * 60)
    print("Paper Trading End-to-End Test")
    print("=" * 60)
    print("\nTest chain:")
    print("  strategy_engine -> (gRPC) -> ExecutionService -> (gRPC) -> GM Adapter")
    print("=" * 60)

    # 1. Check services
    services = check_services()

    if not services["GM Adapter"]:
        print("\n[ERROR] GM Adapter not running, please start it first:")
        print("  cd D:\\TradingPlatform\\lowfreq\\python\\execution-adapter-gm")
        print("  .\\start_gm_adapter.ps1")
        return

    if not services["ExecutionService"]:
        print("\n[ERROR] ExecutionService not running, please start Docker container first")
        return

    # 2. Check GM Adapter logs
    check_gm_adapter_logs()

    # 3. Run Smoke Test
    test_passed = run_smoke_test()

    # 4. Check ExecutionService logs
    check_execution_service_logs()

    # 5. Check GM Adapter activity
    gm_activity = check_gm_adapter_activity()

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    print(f"Service status:")
    print(f"  GM Adapter: {'[OK]' if services['GM Adapter'] else '[FAIL]'}")
    print(f"  ExecutionService: {'[OK]' if services['ExecutionService'] else '[FAIL]'}")

    print(f"\nTest results:")
    print(f"  Smoke Test: {'[OK]' if test_passed else '[FAIL]'}")
    print(f"  gRPC activity: {'[OK]' if gm_activity else '[INFO]'}")

    if test_passed and gm_activity:
        print("\n[SUCCESS] End-to-end test passed!")
        print("  Strategy signal -> ExecutionService -> GM Adapter chain is working")
    elif test_passed:
        print("\n[PASS] Basic test passed, but no gRPC activity detected")
        print("  This may be because:")
        print("  - Test used SIMULATION mode")
        print("  - Or no actual trading signal was triggered")
    else:
        print("\n[FAIL] Test failed, please check configuration and service status")

if __name__ == "__main__":
    main()
