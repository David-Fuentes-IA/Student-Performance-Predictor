"""
scripts/memory_profile.py

Memory profiling (lesson 17) with `tracemalloc`.

`sys.getsizeof` only measures the container itself, not what it references, so
it understates real usage. `tracemalloc` traces every Python allocation made
while a function runs and reports the peak, which is what matters for
"is it efficient at scale?".

    python scripts/memory_profile.py            # writes docs/evidence/testing/memory_profile.json
    python scripts/memory_profile.py --quick    # smaller sizes
"""

import argparse
import io
import json
import platform
import random
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402

from data_access.student_repository import StudentRecord  # noqa: E402
from data_pipeline.excel_importer import MAX_ROWS, TEMPLATE_COLUMNS, parse_workbook  # noqa: E402
from feature_store.feature_manager import FeatureManager, FeatureVector  # noqa: E402
from inference_engine.cache_manager import CachingDecorator  # noqa: E402
from inference_engine.risk_predictor import IRiskPredictionEngine, RiskResult  # noqa: E402
from learning_module.model_store import MODEL_FILENAME, load_model  # noqa: E402
from learning_module.training_pipeline import run_training  # noqa: E402

OUTPUT = ROOT / "docs" / "evidence" / "testing" / "memory_profile.json"


def measure(fn):
    """Run fn() under tracemalloc. Returns (result, {peak_kib, retained_kib, seconds})."""
    tracemalloc.start()
    started = time.perf_counter()
    result = fn()
    seconds = time.perf_counter() - started
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, {
        "peak_kib": round(peak / 1024, 1),
        "retained_kib": round(retained / 1024, 1),
        "seconds": round(seconds, 4),
    }


def synthetic_records(n: int, seed: int = 3) -> list[StudentRecord]:
    rng = random.Random(seed)
    return [
        StudentRecord(
            student_id=f"P{i:06d}", name=f"Alumno {i}",
            grades=[round(rng.uniform(0, 100), 1) for _ in range(rng.randint(1, 4))],
            attendance_pct=round(rng.uniform(0, 100), 1),
            participation_score=round(rng.uniform(0, 100), 1),
        )
        for i in range(n)
    ]


def pure_python_baseline(records: list[StudentRecord]) -> list[FeatureVector]:
    """The original per-record implementation, kept as the 'before' reference."""
    vectors = []
    for r in records:
        grades = r.grades
        vectors.append(FeatureVector(
            student_ref=r.student_id,
            average_grade=round(sum(grades) / len(grades), 2),
            grade_trend=round(grades[-1] - grades[0] if len(grades) > 1 else 0.0, 2),
            attendance_pct=r.attendance_pct,
            participation_score=r.participation_score,
        ))
    return vectors


def profile_feature_extraction(sizes=(1_000, 10_000)) -> list[dict]:
    rows = []
    for n in sizes:
        records = synthetic_records(n)
        _, baseline = measure(lambda recs=records: pure_python_baseline(recs))
        _, batch = measure(lambda recs=records: FeatureManager.extract_many(recs))
        rows.append({"students": n, "pure_python_loop": baseline, "extract_many_pandas_numpy": batch})
    return rows


def profile_model_load() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        run_training(Path(tmp))
        size_kib = round((Path(tmp) / MODEL_FILENAME).stat().st_size / 1024, 1)
        _, stats = measure(lambda: load_model(Path(tmp)))
    return {"model_file_kib": size_kib, **stats}


def build_workbook(rows: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Calificaciones"
    ws.append(TEMPLATE_COLUMNS)
    for i in range(rows):
        ws.append([f"M{i:05d}", f"Alumno {i}", 70 + i % 30, 75, 80, 85, 90, 88])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def profile_excel_parse(rows: int = MAX_ROWS) -> dict:
    content = build_workbook(rows)
    parsed, stats = measure(lambda: parse_workbook(content))
    return {"rows": rows, "file_kib": round(len(content) / 1024, 1), "records_parsed": len(parsed.records), **stats}


class _StubEngine(IRiskPredictionEngine):
    def predict_risk(self, feature_vector):
        return RiskResult(feature_vector.student_ref, 10.0, "low")


def profile_cache_growth(predictions: int = 15_000) -> dict:
    cache = CachingDecorator(_StubEngine())

    def fill():
        for i in range(predictions):
            cache.predict_risk(FeatureVector(f"C{i:06d}", 70.0 + i % 30, 0.0, 90.0, 80.0))

    _, stats = measure(fill)
    return {
        "distinct_predictions": predictions,
        "cache_entries": len(cache._cache),
        "max_entries": CachingDecorator._MAX_ENTRIES,
        "bounded": len(cache._cache) <= CachingDecorator._MAX_ENTRIES,
        **stats,
    }


def run_all(quick: bool = False) -> dict:
    sizes = (500, 2_000) if quick else (1_000, 10_000)
    return {
        "tool": "tracemalloc",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "feature_extraction": profile_feature_extraction(sizes),
        "model_load": profile_model_load(),
        "excel_parse": profile_excel_parse(),
        "cache_growth": profile_cache_growth(3_000 if quick else 15_000),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Memory profiling with tracemalloc.")
    parser.add_argument("--quick", action="store_true", help="smaller sizes")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()

    report = run_all(args.quick)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWritten to {args.out}")


if __name__ == "__main__":
    main()
