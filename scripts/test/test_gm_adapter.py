"""
GM Adapter verification script (simplified)
Tests whether execution_adapter_gm service is running normally
"""
import subprocess
import socket
import sys

def check_gm_adapter_process():
    """Check whether GM Adapter process is running"""
    try:
        result = subprocess.run(
            ['tasklist'],
            capture_output=True,
            text=True,
            encoding='gbk',
            errors='ignore'
        )
        return 'execution_adapter_gm' in result.stdout
    except Exception as e:
        print(f"[ERROR] Failed to check process: {e}")
        return False

def check_grpc_port():
    """Check whether gRPC port 5005 is accessible"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('localhost', 5005))
        sock.close()

        if result == 0:
            print("[OK] gRPC port 5005 is accessible")
            return True
        else:
            print("[FAIL] gRPC port 5005 is not accessible")
            return False
    except Exception as e:
        print(f"[ERROR] Port check failed: {e}")
        return False

def check_gm_logs():
    """Check GM Adapter logs"""
    try:
        log_file = "D:/TradingPlatform/logs/execution-adapter-gm/gm-trading-adaptor-realtime.log"
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            # Read last few lines
            lines = f.readlines()[-10:]
            print("\nRecent logs:")
            for line in lines[-5:]:  # Show last 5 lines
                print(f"  {line.strip()}")
    except Exception as e:
        print(f"[INFO] Unable to read logs: {e}")

def main():
    print("=" * 60)
    print("GM Adapter Verification Test (Simplified)")
    print("=" * 60)

    # 1. Check process
    print("\n[1/3] Checking GM Adapter process...")
    if check_gm_adapter_process():
        print("[OK] GM Adapter process is running")
    else:
        print("[FAIL] GM Adapter process is not running")
        print("\nSteps to start GM Adapter:")
        print("1. cd D:\\BackTesting\\BackTesting\\execution_adapter_gm")
        print("2. .\\start_gm_adapter.ps1")
        return

    # 2. Check port
    print("\n[2/3] Checking gRPC port...")
    if not check_grpc_port():
        print("\nService process is running but port is not accessible, may still be starting")
        print("Wait a few seconds and retest, or check logs to troubleshoot")
        return

    # 3. Check logs
    print("\n[3/3] Checking service logs...")
    check_gm_logs()

    print("\n" + "=" * 60)
    print("Verification completed")
    print("=" * 60)
    print("\nTo run detailed GM SDK tests, please ensure:")
    print("1. GM SDK is correctly installed")
    print("2. GM server is running (during trading hours)")
    print("3. Correct GM Token is configured")

if __name__ == "__main__":
    main()
