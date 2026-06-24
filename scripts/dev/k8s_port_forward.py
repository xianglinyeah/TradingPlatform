#!/usr/bin/env python3
"""
Kubernetes Port-Forward Management Script

Automatically manages port forwarding for K8s services in the development environment,
making the K8s environment usage experience similar to Docker Compose.

Usage:
  python k8s_port_forward.py start      # Start all port-forwards
  python k8s_port_forward.py stop       # Stop all port-forwards
  python k8s_port_forward.py status     # View status
  python k8s_port_forward.py restart    # Restart all port-forwards
"""

import subprocess
import time
import sys
import os
from pathlib import Path
import signal
import atexit

# Port mapping configuration
# Format: "service_name:local_port:service_port"
PORT_MAPPINGS = {
    "market-data-replay": "5000:8080",
    "execution-service": "8084:8084",
    "strategy-engine": "8081:8080",
}

PID_FILE = Path(__file__).parent / ".k8s_port_forward_pids"


class PortForwardManager:
    def __init__(self):
        self.pids = {}
        self.load_pids()

    def load_pids(self):
        """Load running port-forward PIDs from file"""
        if PID_FILE.exists():
            with open(PID_FILE, 'r') as f:
                for line in f:
                    if line.strip():
                        service, pid = line.strip().split(':')
                        self.pids[service] = int(pid)

    def save_pids(self):
        """Save currently running port-forward PIDs"""
        with open(PID_FILE, 'w') as f:
            for service, pid in self.pids.items():
                f.write(f"{service}:{pid}\n")

    def check_k8s_available(self):
        """Check whether K8s is available"""
        try:
            result = subprocess.run(
                ["kubectl", "cluster-info"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True
            else:
                print(f"[ERROR] K8s cluster unavailable: {result.stderr}")
                return False
        except Exception as e:
            print(f"[ERROR] Unable to connect to K8s: {e}")
            return False

    def check_service_exists(self, service_name):
        """Check whether service exists"""
        try:
            result = subprocess.run(
                ["kubectl", "get", "service", service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            print(f"[ERROR] Failed to check service: {e}")
            return False

    def is_process_running(self, pid):
        """Check whether process is still running"""
        if not pid:
            return False
        try:
            result = subprocess.run(
                ["tasklist"],  # Windows
                capture_output=True,
                text=True,
                timeout=5
            )
            return str(pid) in result.stdout
        except Exception:
            return False

    def start_port_forward(self, service_name, port_mapping):
        """Start port-forward for a single service"""
        local_port, service_port = port_mapping.split(':')

        # Check whether service exists
        if not self.check_service_exists(service_name):
            print(f"[WARN] Service {service_name} does not exist, skipping")
            return False

        # Check whether port is already occupied
        try:
            result = subprocess.run(
                ["netstat", "-ano"],  # Windows
                capture_output=True,
                text=True,
                timeout=5
            )
            if f":{local_port} " in result.stdout and "LISTENING" in result.stdout:
                print(f"[WARN] Port {local_port} is already occupied, skipping {service_name}")
                return False
        except Exception:
            pass

        # Start port-forward
        print(f"[START] {service_name}: localhost:{local_port} -> {service_name}:{service_port}")

        try:
            # Use CREATE_NEW_PROCESS_GROUP to start in background
            # Use STARTUPINFO on Windows to hide window
            if sys.platform == "win32":
                CREATE_NO_WINDOW = 0x08000000
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                DETACHED_PROCESS = 0x00000008

                process = subprocess.Popen(
                    ["kubectl", "port-forward",
                     f"service/{service_name}", f"{local_port}:{service_port}"],
                    creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:  # Linux/Mac
                process = subprocess.Popen(
                    ["kubectl", "port-forward",
                     f"service/{service_name}", f"{local_port}:{service_port}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

            # Wait briefly to ensure successful startup
            time.sleep(2)

            if process.poll() is None:  # Process is still running
                self.pids[service_name] = process.pid
                print(f"[OK] {service_name} started (PID: {process.pid})")
                return True
            else:
                print(f"[FAIL] {service_name} failed to start")
                return False

        except Exception as e:
            print(f"[ERROR] Failed to start {service_name}: {e}")
            return False

    def stop_port_forward(self, service_name):
        """Stop port-forward for a single service"""
        if service_name not in self.pids:
            print(f"[INFO] {service_name} is not running")
            return True

        pid = self.pids[service_name]

        if not self.is_process_running(pid):
            print(f"[INFO] {service_name} process no longer exists")
            del self.pids[service_name]
            return True

        try:
            # Use taskkill on Windows
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=5
            )
            print(f"[OK] {service_name} stopped")
            del self.pids[service_name]
            return True
        except Exception as e:
            print(f"[WARN] Failed to stop {service_name}: {e}")
            return False

    def start_all(self):
        """Start all port-forwards"""
        if not self.check_k8s_available():
            return False

        print("[K8S] Starting Port-Forward mappings...")

        success_count = 0
        for service_name, port_mapping in PORT_MAPPINGS.items():
            if self.start_port_forward(service_name, port_mapping):
                success_count += 1
                time.sleep(1)  # Avoid starting too many processes at once

        self.save_pids()

        print(f"\n[SUMMARY] Successfully started {success_count}/{len(PORT_MAPPINGS)} services")
        return success_count > 0

    def stop_all(self):
        """Stop all port-forwards"""
        print("[K8S] Stopping all Port-Forward mappings...")

        stopped_count = 0
        for service_name in list(self.pids.keys()):
            if self.stop_port_forward(service_name):
                stopped_count += 1

        # Clear PID file
        if PID_FILE.exists():
            PID_FILE.unlink()

        print(f"\n[SUMMARY] Successfully stopped {stopped_count} services")
        return True

    def show_status(self):
        """Show current status"""
        print("[K8S] Port-Forward Status:")
        print("=" * 60)

        if not self.check_k8s_available():
            print("[ERROR] K8s cluster unavailable")
            return

        running_count = 0
        for service_name, port_mapping in PORT_MAPPINGS.items():
            local_port, service_port = port_mapping.split(':')
            is_running = service_name in self.pids and self.is_process_running(self.pids[service_name])

            status = "[RUNNING]" if is_running else "[STOPPED]"
            pid_info = f"(PID: {self.pids[service_name]})" if service_name in self.pids else ""

            print(f"{service_name:25} localhost:{local_port:5} -> {service_port:5} {status} {pid_info}")
            if is_running:
                running_count += 1

        print("=" * 60)
        print(f"Total: {running_count}/{len(PORT_MAPPINGS)} services running")

    def restart_all(self):
        """Restart all port-forwards"""
        print("[K8S] Restarting Port-Forward mappings...")
        self.stop_all()
        time.sleep(2)
        return self.start_all()


def cleanup_on_exit():
    """Clean up all port-forwards on program exit"""
    manager = PortForwardManager()
    if manager.pids:
        print("\n[CLEANUP] Cleaning up Port-Forward processes...")
        manager.stop_all()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python k8s_port_forward.py start   - Start all port-forwards")
        print("  python k8s_port_forward.py stop    - Stop all port-forwards")
        print("  python k8s_port_forward.py status  - View status")
        print("  python k8s_port_forward.py restart - Restart all port-forwards")
        sys.exit(1)

    command = sys.argv[1].lower()
    manager = PortForwardManager()

    if command == "start":
        success = manager.start_all()
        sys.exit(0 if success else 1)

    elif command == "stop":
        success = manager.stop_all()
        sys.exit(0 if success else 1)

    elif command == "status":
        manager.show_status()
        sys.exit(0)

    elif command == "restart":
        success = manager.restart_all()
        sys.exit(0 if success else 1)

    else:
        print(f"[ERROR] Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
