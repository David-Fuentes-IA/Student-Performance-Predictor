"""
scripts/collect_docker_evidence.py

Reproduces, with one command, every number quoted in docs/evidence/docker/README.md:

    python scripts/collect_docker_evidence.py              # needs Docker Desktop running; takes ~5 minutes
    python scripts/collect_docker_evidence.py --skip-build # reuse the existing image

What it does (and records in docs/evidence/docker/):
    1. cold build of the image (no cache) and an inspection of it: size, user, health check, layers
    2. a fresh `docker compose up`: seconds until the application container is "healthy"
    3. the smoke test against the running container
    4. import of data/grupo_evaluacion.xlsx through the admin API, then `down` / `up` to prove persistence
    5. failure drill A: MongoDB stops while the application runs
    6. failure drill B: MongoDB is down while the application container (re)starts

WARNING: step 2 runs `docker compose down -v`, deleting the compose project's own database volume.
Your separate development database (spp-mongo-test) is not touched.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.smoke_test import fetch, run_checks, wait_until_ready  # noqa: E402

IMAGE = "student-performance-predictor:local"
BASE = "http://localhost:8000"
OUT = ROOT / "docs" / "evidence" / "docker"
EVALUATION_FILE = ROOT / "data" / "grupo_evaluacion.xlsx"


def run(command: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def compose(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return run(["docker", "compose", *args], timeout=timeout)


def app_container() -> str:
    return compose("ps", "-q", "app").stdout.strip()


def container_state() -> dict:
    status, health, failing, restarts = run(
        ["docker", "inspect", "--format",
         "{{.State.Status}}|{{.State.Health.Status}}|{{.State.Health.FailingStreak}}|{{.RestartCount}}",
         app_container()]).stdout.strip().split("|")
    return {"status": status, "health": health, "failing_streak": int(failing or 0), "restart_count": int(restarts)}


def wait_for(predicate, seconds: float, interval: float = 2.0) -> float | None:
    """Seconds until predicate() is true, or None when it never is."""
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            if predicate():
                return round(time.monotonic() - started, 1)
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, subprocess.SubprocessError):
            pass
        time.sleep(interval)
    return None


def probe(path: str, timeout: float = 30.0) -> dict:
    started = time.perf_counter()
    try:
        status, _, body = fetch(BASE, path, timeout)
        text = body.decode("utf-8", "replace")
    except (OSError, urllib.error.URLError) as exc:
        status, text = None, f"{type(exc).__name__}"
    return {"path": path, "status": status, "seconds": round(time.perf_counter() - started, 2), "body": text[:140]}


def is_healthy() -> bool:
    return container_state()["health"] == "healthy"


def ready_in_database_mode() -> bool:
    status, _, body = fetch(BASE, "/ready", 5)
    data = json.loads(body)
    return status == 200 and data["mode"] == "database" and data["database"] is True


def build_and_inspect(skip_build: bool) -> dict:
    result = {"cold_build_seconds": None}
    if not skip_build:
        started = time.monotonic()
        build = run(["docker", "build", "--no-cache", "--progress=plain", "-t", IMAGE, "."])
        result["cold_build_seconds"] = round(time.monotonic() - started, 1)
        if build.returncode != 0:
            raise SystemExit("docker build failed:\n" + (build.stdout + build.stderr)[-2000:])
    info = json.loads(run(["docker", "image", "inspect", IMAGE]).stdout)[0]
    config = info["Config"]
    history = run(["docker", "history", IMAGE, "--format", "{{.Size}}\t{{.CreatedBy}}"]).stdout.splitlines()
    (OUT / "image_layers.txt").write_text("\n".join(ln[:140] for ln in history) + "\n", encoding="utf-8")
    result.update({
        "image": IMAGE,
        "size_mb": round(info["Size"] / 1_000_000, 1),
        "architecture": f"{info['Os']}/{info['Architecture']}",
        "layers": len(info["RootFS"]["Layers"]),
        "user": config["User"],
        "exposed_ports": list(config["ExposedPorts"]),
        "entrypoint": config["Entrypoint"],
        "command": config["Cmd"],
        "healthcheck": config["Healthcheck"]["Test"][-1][:110],
    })
    probe_files = run(["docker", "run", "--rm", "--entrypoint", "sh", IMAGE, "-c",
                       "for f in .env .git venv tests docs; do test -e /app/$f && echo PRESENT:$f; done; "
                       "ls /app/models"]).stdout.split()
    result["leaked_files_in_image"] = [f for f in probe_files if f.startswith("PRESENT:")]
    result["model_files_in_image"] = [f for f in probe_files if not f.startswith("PRESENT:")]
    return result


def fresh_stack() -> dict:
    compose("down", "-v")
    started = time.monotonic()
    compose("up", "-d")
    seconds = wait_for(is_healthy, 180)
    (OUT / "compose_ps.txt").write_text(
        compose("ps", "--format", "table {{.Service}}\t{{.State}}\t{{.Health}}\t{{.Ports}}").stdout, encoding="utf-8")
    logs = compose("logs", "app", "--no-log-prefix").stdout.splitlines()
    (OUT / "startup_log.txt").write_text("\n".join(ln[:200] for ln in logs[:24]) + "\n", encoding="utf-8")
    return {"seconds_to_healthy": seconds, "total_seconds": round(time.monotonic() - started, 1)}


def smoke() -> dict:
    wait_until_ready(BASE, 60)
    checks = run_checks(BASE, expect_groups=3)
    (OUT / "smoke_test.txt").write_text("\n".join(
        f"{'PASS' if ok else 'FAIL'}  {name}  {detail}" for name, ok, detail in checks) + "\n", encoding="utf-8")
    return {"passed": sum(ok for _, ok, _ in checks), "total": len(checks),
            "failed": [name for name, ok, _ in checks if not ok]}


def import_and_persist() -> dict:
    upload = run(["curl", "-s", "-F", f"file=@{EVALUATION_FILE}", "-F", "create_group=true",
                  f"{BASE}/admin/api/groups/EVAL-240/import"])
    imported = json.loads(upload.stdout)
    analysed = json.loads(fetch(BASE, "/api/groups/EVAL-240", 30)[2])
    compose("down")                      # containers go away, the named volume stays
    compose("up", "-d")
    seconds = wait_for(is_healthy, 180)
    groups = {g["group_id"]: g["student_count"] for g in json.loads(fetch(BASE, "/api/groups", 30)[2])["groups"]}
    return {"imported": {k: imported[k] for k in ("total_rows", "created", "updated")} | {"rejected": len(imported["rejected"])},
            "students_analysed": len(analysed["students"]), "levels": analysed["summary"]["counts"],
            "seconds_to_healthy_after_restart": seconds, "groups_after_restart": groups,
            "persisted": groups.get("EVAL-240") == 240}


def drill_runtime_outage(watch_seconds: int) -> dict:
    """MongoDB stops while the application is running."""
    result = {"baseline": [probe("/health"), probe("/ready")]}
    compose("stop", "mongo")
    time.sleep(1)
    result["right_after_stop"] = {"health": [probe("/health") for _ in range(4)]}
    time.sleep(7)                                       # let the 5 s readiness cache expire in every worker
    result["after_cache_expiry"] = {"ready": [probe("/ready") for _ in range(4)],
                                    "groups_api": probe("/api/groups")}
    watched, started = [], time.monotonic()
    while time.monotonic() - started < watch_seconds:
        watched.append({"t": round(time.monotonic() - started), **container_state()})
        time.sleep(10)
    result["container_health_while_database_is_down"] = watched
    compose("start", "mongo")
    result["seconds_until_ready_again"] = wait_for(ready_in_database_mode, 120)
    result["groups_api_after_recovery"] = probe("/api/groups")
    return result


def drill_boot_with_database_down() -> dict:
    """The container (re)starts while MongoDB is down: it must NOT fall back to fake demo data."""
    compose("stop", "mongo")
    restart_started = time.monotonic()
    compose("restart", "app", timeout=120)
    time.sleep(30)                                      # several boot attempts, each waits for the database
    during = container_state()
    log = compose("logs", "app", "--no-log-prefix", "--since", "2m").stdout
    result = {
        "container_during_outage": during,
        "log_shows_fail_fast_error": "MONGODB_URI is set but the database is unreachable" in log,
        "log_shows_demo_fallback": "falling back to the in-memory demo repository" in log,
        "serving_requests_with_fake_data": any(p["status"] == 200 and '"mode":"demo"' in p["body"].replace(" ", "")
                                              for p in [probe("/ready", 5)]),
    }
    compose("start", "mongo")
    result["seconds_until_serving_real_data"] = wait_for(ready_in_database_mode, 180)
    result["seconds_since_restart_until_serving_real_data"] = (
        round(time.monotonic() - restart_started, 1) if result["seconds_until_serving_real_data"] is not None else None)
    result["final_container"] = container_state()
    result["smoke_after_recovery"] = smoke()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect the Docker evidence.")
    parser.add_argument("--skip-build", action="store_true", help="reuse the existing image")
    parser.add_argument("--watch-seconds", type=int, default=100, help="how long drill A watches the container")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    summary = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "docker": run(["docker", "version", "--format", "{{.Server.Version}}"]).stdout.strip()}
    for name, step in (("image", lambda: build_and_inspect(args.skip_build)), ("fresh_stack", fresh_stack),
                       ("smoke_test", smoke), ("import_and_persistence", import_and_persist),
                       ("drill_runtime_outage", lambda: drill_runtime_outage(args.watch_seconds)),
                       ("drill_boot_with_database_down", drill_boot_with_database_down)):
        print(f"== {name} ...", flush=True)
        summary[name] = step()
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
