#!/usr/bin/env python3
"""Run unit tests for all services.

Python modules: pytest (each service uses its own venv at src/<svc>/venv)
C# modules:     dotnet test
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def resolve_venv_python(service_dir: Path) -> str:
    """Return the python.exe path for the service's own venv.

    Each Python service must have its own venv (Python 3.12, matching the
    Dockerfile base image). This isolation mirrors the K8s deployment where
    every service ships in its own image with its own dependency tree.
    """
    candidate = service_dir / "venv" / "Scripts" / "python.exe"
    if not candidate.exists():
        raise FileNotFoundError(
            f"venv missing for {service_dir.name}: expected {candidate}\n"
            f"Create it with:\n"
            f"  cd {service_dir}\n"
            f"  py -3.12 -m venv venv\n"
            f"  venv/Scripts/python.exe -m pip install -r requirements.txt "
            f"--index-url https://pypi.tuna.tsinghua.edu.cn/simple"
        )
    return str(candidate)


def run_pytest(name: str, src_dir: str) -> bool:
    """Run pytest in a src directory using that service's own venv."""
    path = PROJECT_ROOT / src_dir
    tests = path / "tests"
    if not tests.exists():
        print(f"[{name}] no tests/ directory, SKIP")
        return True

    try:
        python_exe = resolve_venv_python(path)
    except FileNotFoundError as e:
        print(f"[{name}] SKIP - {e}")
        return False

    print(f"[{name}] Running pytest in {src_dir}/tests/ ...")
    print(f"[{name}] venv python: {python_exe}")
    r = subprocess.run(
        [python_exe, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=str(path),
        timeout=120,
    )
    ok = r.returncode == 0
    print(f"[{name}] {'PASS' if ok else 'FAIL'}")
    return ok


def run_dotnet(name: str) -> bool:
    """Run dotnet test for the entire solution."""
    sln = PROJECT_ROOT / "lowfreq" / "dotnet" / "TradingPlatform.sln"
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
    results["strategy-engine"] = run_pytest("strategy-engine", "lowfreq/python/strategy-engine")
    print()
    results["data-ingestion"] = run_pytest("data-ingestion", "lowfreq/python/data-ingestion")
    print()
    results["execution-adapter-gm"] = run_pytest("execution-adapter-gm", "lowfreq/python/execution-adapter-gm")
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
