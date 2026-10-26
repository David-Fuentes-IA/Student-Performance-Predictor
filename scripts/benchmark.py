"""
scripts/benchmark.py

Performance and scalability measurements (lessons 21-22): measure first, optimise second.

    python scripts/benchmark.py                          # both parts, writes docs/evidence/performance/
    python scripts/benchmark.py --label after            # store as a second run, to compare before/after
    python scripts/benchmark.py --skip-http              # only the in-process part

Part 1, in process (needs a MongoDB; default mongodb://localhost:27018, database `spp_benchmark`, dropped at the end):
    - time spent in every stage of ONE real dashboard request (main_api.get_group_dashboard_data, instrumented),
      for groups of 50 and 240 students, with a cold and a warm prediction cache
    - start-up: training the model at start-up (before this milestone) vs loading it (now)
    - inference one student at a time vs one batch call

Part 2, over HTTP against a running instance (default http://localhost:8000, e.g. `docker compose up`):
    - latency p50/p95/max and throughput with 1 and 10 concurrent users (NFR-1: <= 10 s for a group of 50,
      <= 3 s per student, 10 concurrent sessions), PDF reports, and the container's CPU and memory under load
"""

import argparse
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "evidence" / "performance"

GROUPS = {"BENCH-50": 50, "BENCH-240": 240}


def stats(samples_ms: list[float]) -> dict:
    ordered = sorted(samples_ms)
    p95 = ordered[min(len(ordered) - 1, max(0, round(0.95 * len(ordered)) - 1))]
    return {"n": len(ordered), "p50_ms": round(statistics.median(ordered), 2), "p95_ms": round(p95, 2),
            "max_ms": round(ordered[-1], 2), "mean_ms": round(statistics.fmean(ordered), 2)}


# --------------------------------------------------------------------------------------------------
# Part 1: in process
# --------------------------------------------------------------------------------------------------

class StageTimer:
    """Wraps callables so every call adds its duration to a named stage."""

    def __init__(self):
        self.totals: dict[str, float] = {}
        self.calls: dict[str, int] = {}

    def reset(self):
        self.totals.clear()
        self.calls.clear()

    def wrap(self, stage: str, fn):
        def timed(*args, **kwargs):
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.totals[stage] = self.totals.get(stage, 0.0) + (time.perf_counter() - started)
                self.calls[stage] = self.calls.get(stage, 0) + 1
        return timed


def in_process(mongo_uri: str, iterations: int) -> dict:
    os.environ.setdefault("MONGODB_URI", "")          # bootstrap main_api in demo mode, then point it at the bench DB
    from pymongo import MongoClient

    import main_api
    from data_access.mongo_repository import MongoAcademicRepository
    from data_access.student_repository import StudentRecord
    from data_access.synthetic_students import simulate_students
    from data_pipeline.etl_processor import ETLProcessor
    from feature_store.feature_manager import FeatureManager
    from presentation.pdf_reports import build_group_report

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[f"spp_benchmark_{uuid.uuid4().hex[:6]}"]
    try:
        repo = MongoAcademicRepository(db=db)
        for group_id, size in GROUPS.items():
            repo.create_group(group_id, source="synthetic")
            students = simulate_students(size, seed=size, id_prefix=f"{group_id}-")
            repo.upsert_records(group_id, [StudentRecord(s.student_id, s.name, s.grades, s.attendance_pct,
                                                         s.participation_score) for s in students], source="synthetic")

        timer = StageTimer()
        etl = ETLProcessor(repo)
        repo.get_group = timer.wrap("load group from MongoDB", repo.get_group)
        # Both the per-student and the batch methods are timed, so the same script measures the code
        # before and after the Phase 8 optimisations.
        store, infer = "store predictions in MongoDB", "model inference (incl. cache, audit)"
        repo.save_prediction = timer.wrap(store, repo.save_prediction)
        if hasattr(repo, "save_predictions"):
            repo.save_predictions = timer.wrap(store, repo.save_predictions)
        etl._validator.validate = timer.wrap("validate records (Fail-Fast)", etl._validator.validate)
        original_extract = FeatureManager.extract_many
        FeatureManager.extract_many = timer.wrap("extract features", original_extract)
        engine, publisher = main_api._engine, main_api._publisher
        main_api._repository, main_api._etl = repo, etl
        timed_engine = {"predict_risk": staticmethod(timer.wrap(infer, engine.predict_risk))}
        if hasattr(engine, "predict_many"):
            timed_engine["predict_many"] = staticmethod(timer.wrap(infer, engine.predict_many))
        main_api._engine = type("Timed", (), timed_engine)()
        main_api._publisher = type("Timed", (), {"notify_all": staticmethod(timer.wrap("observers (alerts, monitoring)",
                                                                                       publisher.notify_all))})()
        try:
            breakdown = {}
            for group_id, size in GROUPS.items():
                for cache in ("cold", "warm"):
                    totals, per_stage = [], {}
                    for _ in range(iterations):
                        if cache == "cold":
                            engine.clear_cache()
                        timer.reset()
                        started = time.perf_counter()
                        rows = main_api.get_group_dashboard_data(group_id)
                        serialise_started = time.perf_counter()
                        json.dumps(rows)
                        timer.totals["serialise JSON"] = time.perf_counter() - serialise_started
                        total = time.perf_counter() - started
                        totals.append(total * 1000)
                        for stage, seconds in timer.totals.items():
                            per_stage.setdefault(stage, []).append(seconds * 1000)
                        other = total - sum(timer.totals.values())
                        per_stage.setdefault("other (orchestration, sorting, dict building)", []).append(other * 1000)
                    medians = {stage: round(statistics.median(v), 2) for stage, v in per_stage.items()}
                    total_median = statistics.median(totals)
                    breakdown[f"{group_id} / {cache} cache"] = {
                        "students": size,
                        "total": stats(totals),
                        "stages_median_ms": dict(sorted(medians.items(), key=lambda kv: -kv[1])),
                        "stages_share_pct": {s: round(100 * m / total_median, 1) for s, m in
                                             sorted(medians.items(), key=lambda kv: -kv[1])},
                        "calls_per_request": dict(timer.calls),
                    }
            pdf_times = []
            rows = main_api.get_group_dashboard_data("BENCH-50")
            for _ in range(max(3, iterations // 3)):
                started = time.perf_counter()
                build_group_report("BENCH-50", rows)
                pdf_times.append((time.perf_counter() - started) * 1000)
        finally:
            FeatureManager.extract_many = original_extract
            main_api._engine, main_api._publisher = engine, publisher
        return {"request_breakdown": breakdown, "group_pdf_50_students": stats(pdf_times),
                "startup": startup_costs(), "inference_batching": inference_batching()}
    finally:
        client.drop_database(db.name)
        client.close()


def startup_costs() -> dict:
    from learning_module.model_store import load_model
    from learning_module.training_pipeline import run_training

    result = {}
    with tempfile.TemporaryDirectory() as tmp:
        for model_type in ("logistic_regression", "random_forest"):
            times = []
            for _ in range(3):
                started = time.perf_counter()
                run_training(Path(tmp), model_type)
                times.append((time.perf_counter() - started) * 1000)
            result[f"train at start-up ({model_type})"] = stats(times)
            load_times = []
            for _ in range(10):
                started = time.perf_counter()
                load_model(Path(tmp))
                load_times.append((time.perf_counter() - started) * 1000)
            result[f"load trained model ({model_type})"] = stats(load_times)
    return result


def inference_batching() -> dict:
    from learning_module.evaluation_data import load_evaluation_workbook
    from learning_module.model_trainer import (
        ModelTrainer,
        generate_synthetic_training_set,
    )

    X, y = generate_synthetic_training_set()
    X_test, _, _ = load_evaluation_workbook().dataset()
    result = {}
    for model_type in ("logistic_regression", "random_forest"):
        model = ModelTrainer.fit(model_type, X, y)
        single, batch = [], []
        for _ in range(5):
            started = time.perf_counter()
            for row in X_test:
                model.predict_proba([row])
            single.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            model.predict_proba(X_test)
            batch.append((time.perf_counter() - started) * 1000)
        result[model_type] = {"students": len(X_test), "one_call_per_student": stats(single),
                              "one_batch_call": stats(batch),
                              "speed-up": round(statistics.median(single) / statistics.median(batch), 1)}
    return result


# --------------------------------------------------------------------------------------------------
# Part 2: HTTP against a running instance
# --------------------------------------------------------------------------------------------------

def http(base: str, path: str, method: str = "GET", body: bytes | None = None, headers=None, timeout: float = 60.0):
    request = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        payload, status = error.read(), error.code
    return status, (time.perf_counter() - started) * 1000, payload


def ensure_http_group(base: str, group_id: str, size: int) -> None:
    from openpyxl import Workbook

    from data_access.synthetic_students import simulate_students
    from data_pipeline.excel_importer import TEMPLATE_COLUMNS

    http(base, "/admin/api/groups", "POST", json.dumps({"group_id": group_id}).encode(),
         {"Content-Type": "application/json"})
    wb = Workbook()
    ws = wb.active
    ws.title = "Calificaciones"
    ws.append(TEMPLATE_COLUMNS)
    for s in simulate_students(size, seed=size, id_prefix=f"{group_id}-"):
        ws.append([s.student_id, s.name, *(s.grades + [None] * (4 - len(s.grades))), s.attendance_pct,
                   s.participation_score])
    buffer = io.BytesIO()
    wb.save(buffer)
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"bench.xlsx\"\r\n"
            f"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n").encode()
    body += buffer.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    status, _, payload = http(base, f"/admin/api/groups/{group_id}/import", "POST", body,
                              {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    if status != 200:
        raise SystemExit(f"could not prepare {group_id}: {status} {payload[:200]!r}")


def container_usage(stop: threading.Event, samples: list) -> None:
    container = subprocess.run(["docker", "compose", "ps", "-q", "app"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip()
    if not container:
        return
    while not stop.is_set():
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}", container],
                             capture_output=True, text=True).stdout.strip()
        if out:
            cpu, memory = out.split("|")
            samples.append({"cpu_pct": float(cpu.rstrip("%") or 0), "memory": memory.split("/")[0].strip()})


def load_test(base: str, path: str, users: int, requests: int) -> dict:
    def one(_):
        status, ms, _ = http(base, path)
        return status, ms

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=users) as pool:
        results = list(pool.map(one, range(requests)))
    elapsed = time.perf_counter() - started
    latencies = [ms for status, ms in results if status == 200]
    return {"path": path, "concurrent_users": users, "requests": requests,
            "errors": sum(1 for status, _ in results if status != 200),
            "latency": stats(latencies) if latencies else None,
            "throughput_rps": round(len(results) / elapsed, 1), "wall_seconds": round(elapsed, 2)}


def over_http(base: str, quick: bool) -> dict:
    for group_id, size in GROUPS.items():
        ensure_http_group(base, group_id, size)
    for _ in range(5):                                     # warm-up (both gunicorn workers, caches)
        http(base, "/api/groups/BENCH-50")
    n1, n10 = (30, 60) if quick else (100, 300)
    result = {"group_of_50_one_user": load_test(base, "/api/groups/BENCH-50", 1, n1)}
    samples, stop = [], threading.Event()
    watcher = threading.Thread(target=container_usage, args=(stop, samples), daemon=True)
    watcher.start()
    result["group_of_50_ten_users"] = load_test(base, "/api/groups/BENCH-50", 10, n10)
    stop.set()
    watcher.join(timeout=15)
    result["container_during_ten_users"] = {
        "samples": len(samples),
        "cpu_pct_max": max((s["cpu_pct"] for s in samples), default=None),
        "cpu_pct_mean": round(statistics.fmean(s["cpu_pct"] for s in samples), 1) if samples else None,
        "memory_last": samples[-1]["memory"] if samples else None,
        "note": "docker stats CPU % is relative to one core (100 % = one full core)",
    }
    result["group_of_240_one_user"] = load_test(base, "/api/groups/BENCH-240", 1, n1 // 2)
    result["group_pdf_50_one_user"] = load_test(base, "/reports/groups/BENCH-50.pdf", 1, 20)
    first_student = json.loads(http(base, "/api/groups/BENCH-50")[2])["students"][0]["student_id"]
    result["student_pdf_one_user"] = load_test(base, f"/reports/groups/BENCH-50/students/{first_student}.pdf", 1, 20)
    result["student_pdf_ten_users"] = load_test(base, f"/reports/groups/BENCH-50/students/{first_student}.pdf", 10, 60)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Performance benchmark.")
    parser.add_argument("--mongo-uri", default="mongodb://localhost:27018")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--label", default="baseline", help="name of this run (e.g. baseline, after)")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--skip-http", action="store_true")
    parser.add_argument("--skip-inprocess", action="store_true")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    report = {"label": args.label, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "python": platform.python_version(), "platform": platform.platform(),
              "cpus": os.cpu_count()}
    if not args.skip_inprocess:
        report["in_process"] = in_process(args.mongo_uri, 5 if args.quick else args.iterations)
    if not args.skip_http:
        report["http"] = over_http(args.base_url.rstrip("/"), args.quick)

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"benchmark_{args.label}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    main()
