#!/usr/bin/env python3
"""
TradingPlatform - Unified Development Entry Point

Usage:
  py dev.py help      # Recommended on Windows (no setup needed)
  python dev.py help  # If Python is on PATH
"""
import sys
import subprocess
import argparse
import time
from pathlib import Path

class DevCommand:
    def __init__(self):
        self.project_root = Path.cwd()

    # ------------------------------------------------------------------
    # Environment switching (Production / E2E) via env-selector ConfigMap.
    # Drives ASPNETCORE_ENVIRONMENT (execution-service) and STRATEGY_CONFIG
    # (strategy-engine). See infra/k8s/apps/env-selector.yaml.
    # ------------------------------------------------------------------

    NAMESPACE = "trading-platform"
    SERVICES = {
        "execution-service":      {"src": "src/execution-service",    "dotnet": True},
        "market-data-replay":     {"src": "src/market-data-replay",   "dotnet": True},
        "strategy-engine":        {"src": "src/strategy-engine",      "dotnet": False},
        "market-data-gm":         {"src": "src/market-data-gm",       "dotnet": False},
        "execution-adapter-gm":   {"src": "src/execution-adapter-gm", "dotnet": False},
        "data-ingestion":         {"src": "src/data-ingestion",       "dotnet": False},
    }

    def _switch_env(self, mode: str) -> bool:
        """Patch env-selector ConfigMap. mode ∈ {'Production', 'E2E'}."""
        if mode not in ("Production", "E2E"):
            print(f"[ERROR] unknown mode: {mode!r}")
            return False
        strategy_config = "live.yaml" if mode == "Production" else "e2e.yaml"
        patch = (
            f'{{"data":{{"mode":"{mode}",'
            f'"strategy_config":"{strategy_config}"}}}}'
        )
        try:
            r = subprocess.run(
                ["kubectl", "patch", "configmap", "env-selector",
                 "-n", self.NAMESPACE, "-p", patch],
                cwd=self.project_root, capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                print(f"[ENV] env-selector -> {mode} (strategy_config={strategy_config})")
                return True
            print(f"[FAIL] patch failed: {r.stderr}")
            return False
        except Exception as e:
            print(f"[ERROR] patch exception: {e}")
            return False

    def _build_service(self, service: str) -> bool:
        """Build a service's Docker image (and dotnet publish if needed)."""
        cfg = self.SERVICES.get(service)
        if cfg is None:
            print(f"[ERROR] unknown service: {service!r}")
            return False
        src = cfg["src"]
        print(f"[BUILD] {service} ({src})")
        try:
            if cfg["dotnet"]:
                r = subprocess.run(
                    ["dotnet", "publish", src, "-c", "Release",
                     "-o", f"{src}/bin/Release/net8.0/publish"],
                    cwd=self.project_root,
                )
                if r.returncode != 0:
                    print(f"[FAIL] dotnet publish for {service}")
                    return False
            r = subprocess.run(
                ["docker", "build", "-t", f"docker-{service}:latest", src],
                cwd=self.project_root,
            )
            return r.returncode == 0
        except Exception as e:
            print(f"[ERROR] build exception: {e}")
            return False

    def _restart_deployments(self, *deployments: str) -> bool:
        """Rollout restart and wait for each deployment."""
        for d in deployments:
            subprocess.run(
                ["kubectl", "rollout", "restart", f"deployment/{d}",
                 "-n", self.NAMESPACE],
                cwd=self.project_root,
            )
        ok = True
        for d in deployments:
            print(f"[ROLL] waiting for {d}...")
            r = subprocess.run(
                ["kubectl", "rollout", "status", f"deployment/{d}",
                 "-n", self.NAMESPACE, "--timeout=180s"],
                cwd=self.project_root,
            )
            if r.returncode != 0:
                print(f"[FAIL] {d} rollout failed")
                ok = False
        return ok

    def _clear_kafka_topic(self, topic: str) -> bool:
        """Delete and recreate a Kafka topic to clear all messages."""
        print(f"[KAFKA] Clearing topic '{topic}'...")
        try:
            # Delete (async in Kafka, takes a few seconds)
            subprocess.run(
                ["kubectl", "exec", "-n", "infrastructure", "kafka-0", "--",
                 "bash", "-c",
                 f"/opt/kafka/bin/kafka-topics.sh --bootstrap-server "
                 f"kafka.infrastructure:9092 --delete --topic {topic}"],
                cwd=self.project_root, capture_output=True, text=True, timeout=30,
            )
            time.sleep(3)
            # Recreate with 1 partition (auto-create would also work but
            # this is explicit)
            subprocess.run(
                ["kubectl", "exec", "-n", "infrastructure", "kafka-0", "--",
                 "bash", "-c",
                 f"/opt/kafka/bin/kafka-topics.sh --bootstrap-server "
                 f"kafka.infrastructure:9092 --create --topic {topic} "
                 f"--partitions 1 --replication-factor 1"],
                cwd=self.project_root, capture_output=True, text=True, timeout=30,
            )
            print(f"[KAFKA] topic '{topic}' cleared.")
            return True
        except Exception as e:
            print(f"[KAFKA] clear failed (non-fatal): {e}")
            return False

    def switch_env(self, mode: str) -> bool:
        """Top-level: switch env-selector and restart the affected services."""
        target = "Production" if mode == "prod" else "E2E" if mode == "e2e" else mode
        if not self._switch_env(target):
            return False
        return self._restart_deployments("strategy-engine", "execution-service")

    def build_one(self, service: str) -> bool:
        return self._build_service(service)

    def build_all(self) -> bool:
        ok = True
        for svc in self.SERVICES:
            if not self._build_service(svc):
                ok = False
        return ok

    def deploy_one(self, service: str) -> bool:
        if service not in self.SERVICES:
            print(f"[ERROR] unknown service: {service!r}")
            return False
        self._build_service(service)
        return self._restart_deployments(service)

    def deploy_all(self) -> bool:
        """Build all images, then restart all deployments."""
        if not self.build_all():
            print("[WARN] some builds failed, continuing with deploy anyway")
        return self._restart_deployments(*self.SERVICES.keys())

    def print_help(self):
        """Show help information"""
        print("="*60)
        print("TradingPlatform - Unified Development Commands")
        print("="*60)
        print()
        print("[START] Development environment:")
        print("  py dev.py start-all  - Start all services (infrastructure + apps)")
        print("  py dev.py start      - Start K8s application services")
        print("  py dev.py stop       - Stop K8s application services (keep infrastructure)")
        print("  py dev.py stop-all   - Stop all services (including infrastructure)")
        print("  py dev.py restart    - Restart application services")
        print()
        print("[MARKET DATA] Market data services:")
        print("  py dev.py start-market-data   - Start market data services (GM + Simulation)")
        print("  py dev.py stop-market-data    - Stop market data services")
        print("  py dev.py start-gm            - Start market_data_gm (live GM API)")
        print("  py dev.py stop-gm             - Stop market_data_gm")
        print("  py dev.py start-simulation    - Start MarketData.Replay (historical replay)")
        print("  py dev.py stop-simulation     - Stop MarketData.Replay")
        print()
        print("[EXECUTION] Trade execution:")
        print("  py dev.py start-gm-exec       - Start execution_adapter_gm (GM trading)")
        print("  py dev.py stop-gm-exec        - Stop execution_adapter_gm")
        print()
        print("[TEST] Testing:")
        print("  py dev.py test       - Quick test (30 seconds)")
        print("  py dev.py test-smoke - Full E2E: switch E2E -> build -> deploy -> smoke test -> restore")
        print("  py dev.py test-full  - Full test (5-8 minutes)")
        print("  py dev.py test-unit  - Unit tests (strategy/execution/replay)")
        print()
        print("[ENV] Environment switching (Production / E2E):")
        print("  py dev.py switch prod  - Switch env-selector to Production")
        print("  py dev.py switch e2e   - Switch env-selector to E2E")
        print("  py dev.py build        - Build ALL service Docker images")
        print("  py dev.py build <svc>  - Build one service Docker image")
        print("  py dev.py deploy       - Build all + restart all deployments")
        print("  py dev.py deploy <svc> - Build one + restart one deployment")
        print()
        print("[LOG] Log management:")
        print("  py dev.py watch-logs      - Tail all service logs in real time")
        print()
        print("[DB] Database:")
        print("  py dev.py db-stats   - Show database statistics")
        print("  py dev.py db-clean   - Clean up test data")
        print("  py dev.py db-reset   - Reset database")
        print()
        print("[DEPLOY] Deployment:")
        # deploy command removed — use scripts/deploy/ for k8s deployment
        print()
        print("[K8S] Advanced options:")
        print("  py dev.py k8s-services    - Show K8s services and Pod status")
        print("  py dev.py k8s-scale       - Scale service replicas")
        print()
        print("[OTHER] Other:")
        print("  py dev.py check      - Check environment status")
        print("  py dev.py logs       - Show log locations")
        print()
        print("="*60)

    def run_script(self, script_name, *args):
        """Run a script"""
        # Prefer strategy-engine's Python
        python_exe = Path("src/strategy-engine/venv/Scripts/python.exe")
        if not python_exe.exists():
            python_exe = Path("venv/Scripts/python.exe")

        if python_exe.exists():
            exe = str(python_exe)
        else:
            exe = sys.executable

        script = Path(script_name)
        if not script.is_absolute():
            script = self.project_root / script

        if not script.exists():
            print(f"[ERROR] Script not found: {script}")
            return False

        try:
            cmd = [exe, str(script)] + list(args)
            print(f"[CMD] {Path(exe).name} {script} {' '.join(args) if args else ''}")
            subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"[FAIL] Execution failed: {e}")
            return False
        except Exception as e:
            print(f"[ERROR] Exception: {e}")
            return False

    def start_k8s_services(self):
        """Start K8s application services"""
        print("[K8S] Starting application services...")

        # K8s service list
        services = ["execution-service", "market-data-replay", "strategy-engine"]
        k8s_dir = self.project_root / "infra" / "k8s"
        started = []

        if not k8s_dir.exists():
            print(f"[ERROR] K8s config directory not found: {k8s_dir}")
            return False

        for service in services:
            try:
                # Find the corresponding yaml file (supports multiple naming conventions)
                patterns = [
                    f"{service}-deployment.yaml",           # standard format
                    f"{service.replace('-', '_')}.yaml",    # underscore format
                    f"*{service}*.yaml",                    # wildcard match
                ]

                yaml_file = None
                for pattern in patterns:
                    matches = list(k8s_dir.rglob(pattern))
                    if matches:
                        # Prefer deployment files
                        deployment_files = [f for f in matches if "deployment" in f.name.lower()]
                        yaml_file = deployment_files[0] if deployment_files else matches[0]
                        break

                if not yaml_file:
                    print(f"[WARN] {service} config file not found, skipping")
                    continue

                # Check if service already exists
                result = subprocess.run(
                    ["kubectl", "get", "deployment", service],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    # Service already exists, no need to recreate
                    print(f"[INFO] {service} already running")
                    started.append(service)
                else:
                    # Service does not exist, apply config
                    print(f"[INFO] {service} not running, applying config...")
                    apply_result = subprocess.run(
                        ["kubectl", "apply", "-f", str(yaml_file)],
                        cwd=self.project_root,
                        timeout=60,
                        capture_output=True,
                        text=True
                    )

                    if apply_result.returncode == 0:
                        started.append(service)
                        print(f"[OK] {service} started")
                    else:
                        print(f"[WARN] {service} failed to start")

            except Exception as e:
                print(f"[ERROR] Failed to start {service}: {e}")

        if started:
            print(f"[OK] Started: {', '.join(started)}")

        return len(started) > 0

    def stop_k8s_services(self):
        """Stop K8s application services"""
        print("[K8S] Stopping application services...")

        # K8s service list
        services = ["execution-service", "market-data-replay", "strategy-engine"]
        stopped = []

        for service in services:
            try:
                # Delete deployment to stop the service
                result = subprocess.run(
                    ["kubectl", "delete", "deployment", service],
                    cwd=self.project_root,
                    timeout=30,
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    stopped.append(service)
                    print(f"[OK] {service} stopped")
                else:
                    # Service may not have been running
                    if "not found" in result.stderr.lower():
                        print(f"[INFO] {service} was not running")
                    else:
                        print(f"[WARN] {service} failed to stop")

            except Exception as e:
                print(f"[ERROR] Failed to stop {service}: {e}")

        if stopped:
            print(f"[OK] Stopped: {', '.join(stopped)}")
        return len(stopped) > 0

    def start_services(self):
        """Start application services"""
        print("[START] Starting application services...")
        print("[INFO] Current architecture: Full K8s (Infrastructure + Services)")

        # Start K8s application services
        return self.start_k8s_services()

    def stop_services(self):
        """Stop application services"""
        print("[STOP] Stopping application services...")
        print("[INFO] Current architecture: Full K8s (Infrastructure + Services)")

        # Stop K8s application services
        return self.stop_k8s_services()

    def stop_all_services(self):
        """Stop all services (including infrastructure)"""
        print("[STOP-ALL] Stopping all services (including infrastructure)...")

        # Confirm the operation
        try:
            confirm = input("Confirm stopping all services (including database, message queue, etc.)? (yes/no): ")
            if confirm.lower() != "yes":
                print("[CANCEL] Cancelled")
                return False
        except (EOFError, KeyboardInterrupt):
            print("[CANCEL] Cancelled")
            return False

        # Stop application services first
        print("\n[1/2] Stopping application services...")
        self.stop_services()

        # Then stop infrastructure services
        print("\n[2/2] Stopping infrastructure services...")
        try:
            result = subprocess.run(
                ["kubectl", "delete", "namespace", "infrastructure", "--ignore-not-found=true"],
                cwd=self.project_root,
                timeout=120,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("[OK] Infrastructure services stopped")
            else:
                print(f"[WARN] Infrastructure stop failed: {result.stderr}")
        except Exception as e:
            print(f"[ERROR] Failed to stop infrastructure: {e}")

        print("\n[OK] All services stopped")
        print("[INFO] To restart, use: py dev.py start")
        return True

    def start_all_services(self):
        """Start all services (infrastructure + apps)"""
        print("[START-ALL] Starting all services (infrastructure + apps)...")
        print("[START-ALL] Use 'kubectl apply -f infra/k8s/' for infrastructure,")
        print("[START-ALL] then 'py dev.py start' for application services.")
        return self.start_k8s_services()

    def restart_services(self):
        """Restart all services"""
        print("[RESTART] Restarting application services...")
        self.stop_services()
        time.sleep(2)
        return self.start_services()

    def start_market_data_services(self):
        """Start market data services (GM + Simulation)"""
        print("[START] Starting market data services...")
        success = True

        # Start MarketData.Replay (Docker)
        print("\n[1/2] Starting MarketData.Replay...")
        try:
            result = subprocess.run(
                ["docker", "start", "market-data-replay"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print("[OK] MarketData.Replay started")
            else:
                print(f"[WARN] MarketData.Replay failed to start: {result.stderr}")
                success = False
        except Exception as e:
            print(f"[WARN] MarketData.Replay start exception: {e}")
            success = False

        # Start market_data_gm (Windows background process)
        print("\n[2/2] Starting market_data_gm...")
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                 "scripts/dev/start_market_data_gm.ps1"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30  # Returns immediately, 30 seconds is enough
            )
            if result.returncode == 0:
                print("[OK] market_data_gm started")
            else:
                print(f"[WARN] market_data_gm failed to start: {result.stderr}")
                success = False
        except Exception as e:
            print(f"[WARN] market_data_gm start exception: {e}")
            success = False

        return success

    def stop_market_data_services(self):
        """Stop market data services"""
        print("[STOP] Stopping market data services...")

        # Stop MarketData.Replay (Docker)
        print("\n[1/2] Stopping MarketData.Replay...")
        try:
            result = subprocess.run(
                ["docker", "stop", "market-data-replay"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print("[OK] MarketData.Replay stopped")
            else:
                print(f"[INFO] MarketData.Replay: {result.stderr}")
        except Exception as e:
            print(f"[INFO] MarketData.Replay: {e}")

        # Stop market_data_gm (Windows background process)
        print("\n[2/2] Stopping market_data_gm...")
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                 "scripts/dev/stop_market_data_gm.ps1"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print("[OK] market_data_gm stopped")
            else:
                print(f"[INFO] market_data_gm: {result.stderr}")
        except Exception as e:
            print(f"[INFO] market_data_gm: {e}")

        return True

    def start_gm_service(self):
        """Start market_data_gm"""
        print("[START] Starting market_data_gm...")
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                 "scripts/dev/start_market_data_gm.ps1"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30  # Returns immediately, 30 seconds is enough
            )
            print(result.stdout)
            return result.returncode == 0
        except Exception as e:
            print(f"[ERROR] Failed to start: {e}")
            return False

    def stop_gm_service(self):
        """Stop market_data_gm"""
        print("[STOP] Stopping market_data_gm...")
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                 "scripts/dev/stop_market_data_gm.ps1"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30
            )
            print(result.stdout)
            return result.returncode == 0
        except Exception as e:
            print(f"[ERROR] Failed to stop: {e}")
            return False

    def start_simulation_service(self):
        """Start MarketData.Replay"""
        print("[START] Starting MarketData.Replay...")
        try:
            result = subprocess.run(
                ["docker", "start", "market-data-replay"],
                capture_output=True,
                text=True,
                timeout=30
            )
            print(result.stdout)
            return result.returncode == 0
        except Exception as e:
            print(f"[ERROR] Failed to start: {e}")
            return False

    def stop_simulation_service(self):
        """Stop MarketData.Replay"""
        print("[STOP] Stopping MarketData.Replay...")
        try:
            result = subprocess.run(
                ["docker", "stop", "market-data-replay"],
                capture_output=True,
                text=True,
                timeout=30
            )
            print(result.stdout)
            return result.returncode == 0
        except Exception as e:
            print(f"[ERROR] Failed to stop: {e}")
            return False

    def start_gm_exec_service(self):
        """Start execution_adapter_gm"""
        print("[START] Starting execution_adapter_gm...")
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                 "scripts/dev/start_execution_adapter_gm.ps1"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30
            )
            print(result.stdout)
            return result.returncode == 0
        except Exception as e:
            print(f"[ERROR] Failed to start: {e}")
            return False

    def stop_gm_exec_service(self):
        """Stop execution_adapter_gm"""
        print("[STOP] Stopping execution_adapter_gm...")
        try:
            # Use taskkill directly to stop the process
            result = subprocess.run(
                ["taskkill", "/F", "/IM", "execution_adapter_gm.exe"],
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0:
                print("[OK] execution_adapter_gm stopped")
                return True
            else:
                # If the process does not exist, consider it successful
                print("[OK] execution_adapter_gm not running")
                return True
        except Exception as e:
            print(f"[INFO] Stop completed: {e}")
            return True

    def run_test(self, test_type=None):
        """Run tests.

        For test_type='smoke', runs the full E2E workflow: switch to E2E config,
        rebuild + redeploy strategy-engine & execution-service, run
        scripts/test/core/smoke_test.py, then restore Production config
        (always, even on failure). For other types, falls back to smart_e2e.py.
        """
        if test_type == "smoke":
            return self.run_smoke_e2e_workflow()

        if test_type:
            test_files = {
                "minimal": "--minimal",
                "full": "--full",
                "unit": "--unit",
            }
            print(f"[TEST] Running {test_type} test...")

            return self.run_script("scripts/test/smart_e2e.py", test_files[test_type])

        print("[TEST] Running tests...")
        return self.run_script("scripts/test/smart_e2e.py")

    def run_smoke_e2e_workflow(self) -> bool:
        """Full E2E workflow: switch -> build -> deploy -> smoke test -> restore.

        Always restores Production config in a finally block.
        """
        targets = ["strategy-engine", "execution-service"]
        success = False
        try:
            print("\n=== [1/5] Switching to E2E config ===")
            if not self._switch_env("E2E"):
                return False

            print("\n=== [2/5] Building images ===")
            for svc in targets:
                if not self._build_service(svc):
                    return False

            # Clear Kafka topic so strategy-engine starts from a clean slate.
            # Old messages (live GM bars + previous replay sessions) would
            # confuse the strategy (mixed-timeframe EMA input).
            #
            # NOTE: clear BEFORE restart. If we restart first, the new pod
            # subscribes to the topic, then sees "partition count changed
            # from 1 to 0" when the topic is deleted, and confluent-kafka's
            # metadata refresh is not always enough to recover — the consumer
            # sits idle while the smoke-test replay produces messages that
            # never get consumed. Clearing first means the new pod starts
            # against the recreated topic and consumes from earliest.
            print("\n=== [3/5] Clearing Kafka topic (market.data) ===")
            self._clear_kafka_topic("market.data")
            # Brief pause to let the topic recreation propagate through the
            # Kafka cluster before strategy-engine subscribes.
            print("  waiting 5s for topic recreation to settle...")
            time.sleep(5)

            print("\n=== [3.5/5] Deploying & waiting for rollout ===")
            if not self._restart_deployments(*targets):
                return False

            # Note: smoke_test.py connects via LoadBalancer (8080, 5432) directly.
            print("\n=== [4/5] Skipping port-forward (NodePort/LB used directly) ===")

            print("\n=== [5/5] Running smoke test ===")
            success = self.run_script("scripts/test/core/smoke_test.py")
            print("\n[SMOKE] PASSED" if success else "\n[SMOKE] FAILED")
            return success
        finally:
            print("\n=== Restoring Production config ===")
            self._switch_env("Production")
            self._restart_deployments(*targets)
            print("[RESTORE] back to Production mode.")

    def db_stats(self):
        """Show database statistics"""
        print("[DB] Database statistics:")
        return self.run_script("scripts/db/clean_database.py", "--stats")

    def db_clean(self):
        """Clean up database"""
        print("[DB] Cleaning up test data...")
        return self.run_script("scripts/db/clean_database.py", "--test", "--days", "7")

    def db_reset(self):
        """Reset database"""
        print("[DB] Resetting database...")
        try:
            confirm = input("Confirm resetting all trading data? (yes/no): ")
            if confirm.lower() != "yes":
                print("[CANCEL] Cancelled")
                return False
        except (EOFError, KeyboardInterrupt):
            print("[CANCEL] Cancelled")
            return False

        return self.run_script("scripts/db/clean_database.py", "--all")

    def check_status(self):
        """Check environment status"""
        print("[CHECK] Checking environment status...")
        try:
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True,
                text=True,
                timeout=10
            )
            print(result.stdout)
        except:
            print("[ERROR] Unable to connect to Docker")

    def show_logs(self):
        """Show log locations"""
        print("[LOGS] Log locations:")
        print("\nAvailable log directories:")
        print(f"  - {self.project_root}/logs/strategy-engine/")
        print(f"  - {self.project_root}/logs/execution-service/")
        print(f"  - {self.project_root}/logs/market-data-replay/")
        print(f"  - {self.project_root}/logs/marketdata-gm/")
        print(f"  - {self.project_root}/logs/execution-adapter-gm/")
        print("\nGrafana log aggregation: http://localhost:3001")
        print("\nView container logs with Docker:")
        print("  docker logs -f dev-postgres")
        print("  docker logs -f dev-kafka")
        print("\nView container logs with K8s:")
        print("  kubectl logs -f deployment/execution-service")
        print("  kubectl logs -f deployment/market-data-replay")
        print("  kubectl logs -f deployment/strategy-engine")
        print("\nView process logs on Windows:")
        print("  Get-Process execution_adapter_gm | Select-Object Path, Id")
        return True

    def watch_logs(self):
        """Tail all service logs in real time"""
        print("[LOG] Tailing all service logs in real time...")
        print("Tip: Press Ctrl+C to stop\n")

        # Get all running pods
        try:
            infra_pods = subprocess.run(
                ["kubectl", "get", "pods", "-n", "infrastructure",
                 "-o", "jsonpath={.items[*].metadata.name}"],
                capture_output=True, text=True, timeout=10
            )
            business_pods = subprocess.run(
                ["kubectl", "get", "pods", "-n", "trading-platform",
                 "-o", "jsonpath={.items[*].metadata.name}"],
                capture_output=True, text=True, timeout=10
            )

            all_pods = []
            if infra_pods.stdout.strip():
                all_pods.extend([f"infrastructure/{pod}" for pod in infra_pods.stdout.strip().split()])
            if business_pods.stdout.strip():
                all_pods.extend([f"trading-platform/{pod}" for pod in business_pods.stdout.strip().split()])

            if not all_pods:
                print("[WARN] No running pods found")
                return False

            print(f"Found {len(all_pods)} pods, starting real-time monitoring...\n")

            # Start log monitoring
            processes = []
            for pod_namespace in all_pods:
                namespace, pod = pod_namespace.split('/')
                try:
                    proc = subprocess.Popen(
                        ["kubectl", "logs", "-f", pod, "-n", namespace],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    processes.append((pod_namespace, proc))
                except:
                    print(f"[WARN] Failed to start log monitoring for {pod_namespace}")

            # Wait for user interrupt
            try:
                for pod_namespace, proc in processes:
                    print(f"[{pod_namespace}] log stream started...")
            except KeyboardInterrupt:
                print("\n[INTERRUPTED] Stopping log monitoring")
                for pod_namespace, proc in processes:
                    proc.terminate()
                return True

        except Exception as e:
            print(f"[ERROR] Real-time log monitoring failed: {e}")
            return False

    def k8s_scale(self, service=None, replicas=None):
        """Scale K8s service replicas"""
        if not service or not replicas:
            print("[K8S] Usage: py dev.py k8s-scale <service> <replicas>")
            print("Available services:")
            print("  - execution-service")
            print("  - market-data-replay")
            print("  - strategy-engine")
            return False

        print(f"[K8S] Scaling service {service} to {replicas} replicas...")
        try:
            result = subprocess.run(
                ["kubectl", "scale", "deployment/" + service, "--replicas=" + replicas],
                cwd=self.project_root,
                timeout=60,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"[OK] {service} scaled to {replicas} replicas")
                return True
            else:
                print(f"[FAIL] Scaling failed: {result.stderr}")
                return False
        except Exception as e:
            print(f"[ERROR] Scaling failed: {e}")
            return False

    def k8s_services(self):
        """Show K8s service status"""
        print("[K8S] Service status:")
        try:
            result = subprocess.run(
                ["kubectl", "get", "services"],
                cwd=self.project_root,
                timeout=30,
                capture_output=True,
                text=True
            )
            print(result.stdout)

            result2 = subprocess.run(
                ["kubectl", "get", "pods"],
                cwd=self.project_root,
                timeout=30,
                capture_output=True,
                text=True
            )
            print("\n[K8S] Pod status:")
            print(result2.stdout)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to get status: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(description="TradingPlatform unified development commands")
    parser.add_argument("command", nargs="?", help="command name")

    if len(sys.argv) == 1:
        cmd = DevCommand()
        cmd.print_help()
        return 0

    cmd = DevCommand()
    command = sys.argv[1].lower()

    commands = {
        "help": cmd.print_help,
        "start": cmd.start_services,
        "start-all": cmd.start_all_services,
        "stop": cmd.stop_services,
        "stop-all": cmd.stop_all_services,
        "restart": cmd.restart_services,
        "start-market-data": cmd.start_market_data_services,
        "stop-market-data": cmd.stop_market_data_services,
        "start-gm": cmd.start_gm_service,
        "stop-gm": cmd.stop_gm_service,
        "start-simulation": cmd.start_simulation_service,
        "stop-simulation": cmd.stop_simulation_service,
        "start-gm-exec": cmd.start_gm_exec_service,
        "stop-gm-exec": cmd.stop_gm_exec_service,
        "test": cmd.run_test,
        "test-smoke": lambda: cmd.run_test("smoke"),
        "test-full": lambda: cmd.run_test("full"),
        "test-unit": lambda: cmd.run_test("unit"),
        "db-stats": cmd.db_stats,
        "db-clean": cmd.db_clean,
        "db-reset": cmd.db_reset,
        "check": cmd.check_status,
        "logs": cmd.show_logs,
        "watch-logs": cmd.watch_logs,
        "k8s-scale": cmd.k8s_scale,
        "k8s-services": cmd.k8s_services,
        "k8s-start": cmd.start_k8s_services,
        "k8s-stop": cmd.stop_k8s_services,
        # Environment switching and per-service build/deploy
        "switch": lambda: cmd.switch_env(sys.argv[2] if len(sys.argv) > 2 else ""),
        "build":  lambda: cmd.build_one(sys.argv[2] if len(sys.argv) > 2 else "") if len(sys.argv) > 2 else cmd.build_all(),
        "deploy": lambda: cmd.deploy_one(sys.argv[2]) if len(sys.argv) > 2 else cmd.deploy_all(),
    }

    if command in commands:
        try:
            success = commands[command]()
            return 0 if success else 1
        except KeyboardInterrupt:
            print(f"\n[INTERRUPTED] Command interrupted")
            return 130
        except Exception as e:
            print(f"[ERROR] Command execution failed: {e}")
            return 1
    else:
        print(f"[ERROR] Unknown command: {command}")
        print("Run 'py dev.py help' to see available commands")
        return 1

if __name__ == "__main__":
    sys.exit(main())
