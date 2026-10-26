"""
scripts/smoke_test.py

Quick end-to-end check of a RUNNING instance of the application (local, Docker or deployed).
Standard library only, so it runs anywhere:

    python scripts/smoke_test.py                       # http://localhost:8000
    python scripts/smoke_test.py http://localhost:8000 --expect-groups 3
    python scripts/smoke_test.py http://localhost:5000 --timeout 10

Exit code 0 when every check passes, 1 otherwise. CI runs it against the freshly built image.
"""

import argparse
import json
import time
import urllib.error
import urllib.request


def fetch(base: str, path: str, timeout: float = 15.0):
    """Return (status, content_type, body_bytes); HTTP errors are returned, not raised."""
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()


def wait_until_ready(base: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if fetch(base, "/health", timeout=3)[0] == 200:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def run_checks(base: str, expect_groups: int | None) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    status, _, body = fetch(base, "/health")
    health = json.loads(body) if status == 200 else {}
    check("health answers 200", status == 200, f"status={status}")
    check("model is loaded", health.get("model_loaded") is True, f"model_loaded={health.get('model_loaded')}")
    check("health reports a mode", health.get("mode") in ("database", "demo"),
          f"mode={health.get('mode')} database={health.get('database')} status={health.get('status')}")
    status, _, body = fetch(base, "/ready")
    check("readiness answers 200", status == 200, f"status={status}")

    status, content_type, body = fetch(base, "/")
    check("dashboard page loads", status == 200 and b"Student Predictor" in body, f"status={status}")
    check("static assets are served", fetch(base, "/static/dashboard.js")[0] == 200)
    check("admin page loads", fetch(base, "/admin/")[0] == 200)

    status, _, body = fetch(base, "/api/groups")
    groups = json.loads(body).get("groups", []) if status == 200 else []
    check("group list is available", status == 200, f"{len(groups)} groups")
    if expect_groups is not None:
        check(f"at least {expect_groups} groups exist", len(groups) >= expect_groups, f"{len(groups)} groups")

    with_students = next((g for g in groups if g.get("student_count", 0) > 0), None)
    if with_students:
        group_id = with_students["group_id"]
        status, _, body = fetch(base, f"/api/groups/{group_id}")
        data = json.loads(body) if status == 200 else {}
        students = data.get("students", [])
        check(f"predictions for group {group_id}", status == 200 and len(students) == with_students["student_count"],
              f"{len(students)} students")
        check("risk scores are within 0-100", bool(students) and all(0 <= s["risk_score"] <= 100 for s in students))
        check("risk levels are valid", all(s["risk_label"] in ("low", "medium", "high") for s in students))
        status, content_type, body = fetch(base, f"/reports/groups/{group_id}.pdf")
        check("group PDF report downloads", status == 200 and "application/pdf" in content_type
              and body.startswith(b"%PDF"), f"{len(body)} bytes")

    status, content_type, body = fetch(base, "/api/groups/NO-SUCH-GROUP")
    check("unknown group returns a clean 404", status == 404 and b"Traceback" not in body and "json" in content_type,
          f"status={status}")
    status, _, body = fetch(base, "/api/groups/bad!id")
    check("malformed group id is rejected (400)", status == 400, f"status={status}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test of a running Student Performance Predictor.")
    parser.add_argument("base_url", nargs="?", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=60, help="seconds to wait for /health (default 60)")
    parser.add_argument("--expect-groups", type=int, default=None, help="fail if fewer groups exist")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"Smoke test against {base}")
    if not wait_until_ready(base, args.timeout):
        raise SystemExit(f"FAIL: {base}/health did not answer 200 within {args.timeout:.0f} s")

    results = run_checks(base, args.expect_groups)
    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        raise SystemExit("FAILED: " + ", ".join(failed))


if __name__ == "__main__":
    main()
