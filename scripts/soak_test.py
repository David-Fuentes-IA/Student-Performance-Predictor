"""
scripts/soak_test.py

Prolonged-operation (soak) test of the running container (Milestone 3 feedback, criterion 5: "no evidence of prolonged
operation"). It keeps a steady, realistic load on the application for a long time and records whether it stays healthy:

    docker compose up -d --build
    python scripts/soak_test.py --minutes 120          # writes docs/evidence/docker/soak_test.json

Every few seconds a teacher-like request (open a group's dashboard data, sometimes a PDF); every minute the container's
health, restart count, CPU and memory (`docker stats`). Per 10-minute window: requests, errors, latency p50/p95/max,
memory. A leak would show as memory that keeps growing; instability as errors, restarts or a container that is not healthy.

It is not a production run: one machine, one container, synthetic data, a few hours.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "docker"
CONTAINER = "student_predictor_project-app-1"
PATHS = ["/api/groups/301-A", "/api/groups/301-B", "/api/groups/301-C", "/api/groups", "/reports/groups/301-A.pdf"]


def request(base: str, path: str) -> tuple[bool, float]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(base + path, timeout=30) as response:
            response.read()
            ok = response.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        ok = False
    return ok, (time.perf_counter() - started) * 1000


def container_state() -> dict:
    fmt = "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.RestartCount}}|{{.State.StartedAt}}"
    state = subprocess.run(["docker", "inspect", "--format", fmt, CONTAINER], capture_output=True, text=True)
    stats = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}", CONTAINER],
                           capture_output=True, text=True)
    status, health, restarts, started = (state.stdout.strip().split("|") + ["", "", "", ""])[:4]
    cpu, memory = (stats.stdout.strip().split("|") + ["", ""])[:2]
    return {"status": status, "health": health, "restarts": int(restarts or -1), "started_at": started,
            "cpu": cpu, "memory": memory.split("/")[0].strip()}


def mib(text: str) -> float | None:
    for unit, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024)):
        if text.endswith(unit):
            return round(float(text[: -len(unit)]) * factor, 1)
    return None


def window_summary(start: float, latencies: list[float], errors: int, samples: list[dict]) -> dict:
    ordered = sorted(latencies)
    memories = [m for m in (mib(s["memory"]) for s in samples) if m is not None]
    return {
        "minute_from": round(start / 60), "requests": len(latencies) + errors, "errors": errors,
        "p50_ms": round(statistics.median(ordered), 1) if ordered else None,
        "p95_ms": round(ordered[min(len(ordered) - 1, round(0.95 * len(ordered)) - 1)], 1) if ordered else None,
        "max_ms": round(ordered[-1], 1) if ordered else None,
        "memory_mib_last": memories[-1] if memories else None,
        "unhealthy_samples": sum(1 for s in samples if s["health"] != "healthy"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prolonged-operation test of the running container.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--minutes", type=float, default=120)
    parser.add_argument("--interval", type=float, default=3.0, help="seconds between requests")
    args = parser.parse_args()

    began, first = time.time(), container_state()
    windows, samples, latencies, errors, all_latencies = [], [], [], 0, []
    window_start, next_sample, i = 0.0, 0.0, 0
    while (elapsed := time.time() - began) < args.minutes * 60:
        if elapsed >= next_sample:
            samples.append({**container_state(), "minute": round(elapsed / 60, 1)})
            next_sample += 60
        ok, ms = request(args.base_url, PATHS[i % len(PATHS)])
        i += 1
        if ok:
            latencies.append(ms)
            all_latencies.append(ms)
        else:
            errors += 1
        if elapsed - window_start >= 600:
            windows.append(window_summary(window_start, latencies,
                                          errors, [s for s in samples if s["minute"] * 60 >= window_start]))
            print(json.dumps(windows[-1]), flush=True)
            window_start, latencies, errors = elapsed, [], 0
        time.sleep(args.interval)
    windows.append(window_summary(window_start, latencies, errors,
                                  [s for s in samples if s["minute"] * 60 >= window_start]))
    last = container_state()

    memories = [m for m in (mib(s["memory"]) for s in samples) if m is not None]
    total_errors = sum(w["errors"] for w in windows)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_minutes": round((time.time() - began) / 60, 1),
        "load": f"one request every {args.interval:g} s, rotating over {PATHS}",
        "requests": sum(w["requests"] for w in windows),
        "errors": total_errors,
        "availability_pct": round(100 * (1 - total_errors / max(1, sum(w["requests"] for w in windows))), 3),
        "latency_overall_ms": {"p50": round(statistics.median(all_latencies), 1),
                               "p95": round(sorted(all_latencies)[round(0.95 * len(all_latencies)) - 1], 1)}
        if all_latencies else None,
        "memory_mib": {"first": memories[0] if memories else None, "last": memories[-1] if memories else None,
                       "max": max(memories) if memories else None},
        "container": {"before": first, "after": last,
                      "restarts_during_test": last["restarts"] - first["restarts"],
                      "same_process": first["started_at"] == last["started_at"]},
        "unhealthy_samples": sum(1 for s in samples if s["health"] != "healthy"),
        "windows_of_10_minutes": windows,
        "samples_every_minute": samples,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "soak_test.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("windows_of_10_minutes", "samples_every_minute")},
                     indent=2))
    sys.exit(0 if total_errors == 0 and result["container"]["restarts_during_test"] == 0 else 1)


if __name__ == "__main__":
    main()
