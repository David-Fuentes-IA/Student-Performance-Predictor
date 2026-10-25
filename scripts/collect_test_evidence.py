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


def _size(kib: float) -> str:
    return f"{kib / 1024:.2f} MiB" if kib >= 100 else f"{kib:.1f} KiB"


def render_results(summary: dict) -> str:
    levels = summary["levels"]
    names = {"performance": "Memory profiling"}
    rows = [f"| {names.get(level, level.capitalize())} | {v['tests']} | {v['subtests_passed']} | {v['failed']} "
            f"| {v['skipped']} | {v['seconds']:.1f} s |" for level, v in levels.items()]
    tests = sum(v["tests"] for v in levels.values())
    subs = sum(v["subtests_passed"] for v in levels.values())
    failed = sum(v["failed"] for v in levels.values())
    skipped = sum(v["skipped"] for v in levels.values())
    packages = summary["coverage"]["by_package"]
    weakest = min(packages, key=packages.get)
    verdict = "all passing" if not failed else f"{failed} FAILING"
    return "\n".join([
        "| Level | Tests | Parametrised sub-cases | Failed | Skipped | Time |",
        "|---|---|---|---|---|---|",
        *rows,
        f"| **Total** | **{tests}** | **{subs}** | **{failed}** | **{skipped}** | |",
        "",
        f"{tests} test functions, plus {subs} parametrised cases (`subTest`) executed inside them: "
        f"{tests + subs} checks, {verdict}.",
        "",
        f"Statement coverage: **{summary['coverage']['total_percent']} %** overall "
        f"(lowest: `{weakest}`, {packages[weakest]} %).",
        "",
        "| Package | Coverage |",
        "|---|---|",
        *[f"| `{name}` | {value} % |" for name, value in sorted(packages.items(), key=lambda kv: -kv[1])],
    ])


def render_memory(memory: dict) -> str:
    lines = ["| Measurement | Result |", "|---|---|"]
    for row in memory["feature_extraction"]:
        loop, batch = row["pure_python_loop"], row["extract_many_pandas_numpy"]
        lines.append(f"| Feature extraction, {row['students']:,} students | pure Python loop {_size(loop['peak_kib'])} / "
                     f"{loop['seconds'] * 1000:.0f} ms; `extract_many` (pandas + numpy) {_size(batch['peak_kib'])} / "
                     f"{batch['seconds'] * 1000:.0f} ms |")
    m, e, c = memory["model_load"], memory["excel_parse"], memory["cache_growth"]
    lines += [
        f"| Model load | {m['model_file_kib']} KiB file, {_size(m['peak_kib'])} peak, "
        f"{_size(m['retained_kib'])} retained, {m['seconds'] * 1000:.0f} ms |",
        f"| Largest allowed Excel ({e['rows']:,} rows, {e['file_kib']} KiB) | {_size(e['peak_kib'])} peak, {e['seconds']:.1f} s |",
        f"| Prediction cache, {c['distinct_predictions']:,} distinct predictions | "
        f"{'bounded' if c['bounded'] else 'UNBOUNDED'}: {c['cache_entries']:,} entries kept "
        f"(limit {c['max_entries']:,}), {_size(c['peak_kib'])} peak |",
    ]
    return "\n".join(lines)


def replace_block(text: str, name: str, content: str) -> str:
    begin = text.index(f"<!-- BEGIN:{name}")
    header_end = text.index("-->", begin) + 3
    end = text.index(f"<!-- END:{name} -->", header_end)
    return text[:header_end] + "\n" + content + "\n" + text[end:]


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

    memory = run_all()
    (OUT / "memory_profile.json").write_text(json.dumps(memory, indent=2) + "\n", encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    readme = OUT / "README.md"
    if readme.exists():                      # keep the numbers in the report in sync with the files above
        text = readme.read_text(encoding="utf-8")
        text = replace_block(text, "results", render_results(summary))
        text = replace_block(text, "memory", render_memory(memory))
        readme.write_text(text, encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
