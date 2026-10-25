"""
scripts/collect_test_evidence.py

One command that (re)generates every number quoted in the testing section of the
Milestone 3 report, so the evidence is reproducible and not hand-typed:

    python scripts/collect_test_evidence.py
    MONGODB_TEST_URI=mongodb://localhost:27018 python scripts/collect_test_evidence.py   # include real-DB tests

Writes to docs/evidence/testing/:
    pytest_<level>.txt     verbose pytest output for unit / integration / system / performance
    coverage.txt           coverage report with missing lines
    memory_profile.json    tracemalloc results (scripts/memory_profile.py)
    summary.json           tests per level, coverage per package, environment
"""

import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "evidence" / "testing"
LEVELS = ("unit", "integration", "system", "performance")


def run_pytest(args: list[str], output_file: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider"], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    output_file.write_text(result.stdout + result.stderr, encoding="utf-8")
    return result


def _count(summary_line: str, word: str) -> int:
    match = re.search(rf"(\d+) {word}", summary_line)
    return int(match.group(1)) if match else 0


def run_level(level: str) -> dict:
    """`tests` are test functions; `subtests` are the parametrised cases (subTest) inside them."""
    result = run_pytest([f"tests/{level}", "-v"], OUT / f"pytest_{level}.txt")
    lines = [ln for ln in result.stdout.splitlines() if ln.startswith("=") and " in " in ln]
    summary_line = lines[-1]
    seconds = re.search(r" in ([\d.]+)s", summary_line)
    return {
        "tests": _count(summary_line, "passed") + _count(summary_line, "failed") + _count(summary_line, "error")
                 + _count(summary_line, "skipped"),
        "passed": _count(summary_line, "passed"),
        "failed": _count(summary_line, "failed") + _count(summary_line, "error"),
        "skipped": _count(summary_line, "skipped"),
        "subtests_passed": _count(summary_line, "subtests passed"),
        "seconds": float(seconds.group(1)) if seconds else None,
        "exit_code": result.returncode,
    }


def run_coverage() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "coverage.json"
        run_pytest(["tests", "-q", "--cov", "--cov-report=term-missing", f"--cov-report=json:{data}"],
                   OUT / "coverage.txt")
        report = json.loads(data.read_text(encoding="utf-8"))

    packages = defaultdict(lambda: [0, 0])
    for filename, info in report["files"].items():
        package = Path(filename).parts[0] if len(Path(filename).parts) > 1 else Path(filename).stem
        packages[package][0] += info["summary"]["num_statements"]
        packages[package][1] += info["summary"]["covered_lines"]
    return {
        "total_percent": round(report["totals"]["percent_covered"], 1),
        "by_package": {p: round(100 * c / s, 1) if s else 100.0 for p, (s, c) in sorted(packages.items())},
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mongo = bool(os.environ.get("MONGODB_TEST_URI"))
    if not mongo:
        print("WARNING: MONGODB_TEST_URI is not set - tests that need a real MongoDB will be skipped.")

    import sklearn

    from scripts.memory_profile import run_all

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "sklearn": sklearn.__version__,
        "platform": platform.platform(),
        "real_mongodb_tests_included": mongo,
        "levels": {level: run_level(level) for level in LEVELS},
    }
    summary["coverage"] = run_coverage()

    (OUT / "memory_profile.json").write_text(json.dumps(run_all(), indent=2) + "\n", encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
