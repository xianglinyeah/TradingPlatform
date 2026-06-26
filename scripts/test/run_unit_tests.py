#!/usr/bin/env python3
"""Run unit tests for all services.

Python modules: pytest
C# modules:     dotnet test
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def run_pytest(name: str, src_dir: str) -> bool:
    """Run pytest in a src directory using system Python."""
    path = PROJECT_ROOT / src_dir
    tests = path / "tests"
    if not tests.exists():
        print(f"[{name}] no tests/ directory, SKIP")
        return True

    print(f"[{name}] Running pytest in {src_dir}/tests/ ...")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=str(path),
        timeout=120,
    )
    ok = r.returncode == 0
    print(f"[{name}] {'PASS' if ok else 'FAIL'}")
    return ok


def run_dotnet(name: str) -> bool:
    """Run dotnet test for the entire solution."""
    sln = PROJECT_ROOT / "TradingPlatform.sln"
    if not sln.exists():
        print(f"[{name}] TradingPlatform.sln not found, SKIP")
        return True

    print(f"[{name}] Running dotnet test ...")
    r = subprocess.run(
        ["dotnet", "test", str(sln), "--verbosity", "normal"],
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
        timeout=300,
    )
    for line in r.stdout.splitlines():
        if any(k in line for k in ("Passed!", "Failed!", "Skipped", "Total tests")):
            print(f"  {line.strip()}")
    ok = r.returncode == 0
    print(f"[{name}] {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print("=" * 60)
    print("Unit Test Runner")
    print("=" * 60)

    results = {}
    results["strategy-engine"] = run_pytest("strategy-engine", "src/strategy-engine")
    print()
    results["data-ingestion"] = run_pytest("data-ingestion", "src/data-ingestion")
    print()
    results["execution-adapter-gm"] = run_pytest("execution-adapter-gm", "src/execution-adapter-gm")
    print()
    results["C# solution"] = run_dotnet("C# solution")
    print()

    print("=" * 60)
    print("Summary")
    all_ok = True
    for svc, ok in results.items():
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"  [{status}] {svc}")

    print(f"\n{'All tests passed!' if all_ok else 'Some tests FAILED'}")
    print("=" * 60)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
