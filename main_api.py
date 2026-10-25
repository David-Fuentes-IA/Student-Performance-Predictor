"""
main_api.py

This is the "Prediction Orchestrator" from the Business Logic layer
(Figure 1) and the entry point of the application (Technology Stack: Flask).
It is the only module that is allowed to know about every layer - every
other module only knows the layer directly below it.

Design note (traceability: §8 AI Workflow, Figure 7):
    `generate_group_risk_report` follows the exact steps of the workflow
    diagram, in the exact same order:
        1. Validate permissions and academic input   (Business Logic Fail-Fast)
        2. Authorize request                          (teacher check)
        3. Retrieve academic data                     (IAcademicDataRepository)
        4. Data quality check                         (ETLProcessor/FailFastValidator)
        5. Run the ML pipeline                         (ETLProcessor)
        6. Execute IRiskPredictionEngine               (Strategy + Decorator)
        7. Notify on threshold                         (Observer)
        8. Persist prediction result                   (save_prediction)
        9. Generate and display the report             (Presentation)
"""

from core import config
from core.audit_observer import (
    ModelMonitoringObserver,
    RiskAlertObserver,
    RiskEvent,
    RiskEventPublisher,
)
from core.exception_handler import ValidationError, handle_errors
from core.logger import get_logger
from data_access.repository_factory import build_repository
from data_pipeline.etl_processor import ETLProcessor
from inference_engine.cache_manager import AuditDecorator, CachingDecorator
from inference_engine.risk_predictor import create_risk_engine
from learning_module.model_evaluator import ModelEvaluator
from learning_module.model_store import load_model
from presentation.teacher_report_ui import TeacherReportUI

logger = get_logger(__name__)

# FR-7: RISK_THRESHOLD env var (default 75). It sets the alert line AND the "high" level
# (core/risk_levels.py), and is read once at startup.
RISK_THRESHOLD = config.risk_threshold()


# --------------------------------------------------------------------------
# Composition root: wire every layer together ONCE, at startup.
# This is the only place concrete classes are instantiated directly -
# everywhere else depends on the interfaces (DIP).
# --------------------------------------------------------------------------

def _bootstrap():
    repository = build_repository()  # MongoDB if MONGODB_URI is set, in-memory demo otherwise
    etl = ETLProcessor(repository)

    # "Train or load model" (§9): the model is trained offline by
    # scripts/train_model.py and only LOADED here. A missing or corrupt model
    # raises ModelLoadError with the command needed to generate it.
    trained_model, model_card = load_model()

    # Strategy (base engine) wrapped in two Decorators, matching Figure 5:
    # AuditDecorator innermost (so it only logs real inference calls),
    # CachingDecorator outermost (so a cache hit skips both the audit
    # write and the model entirely). The rest of the app only ever sees
    # an IRiskPredictionEngine, never these concrete classes.
    base_engine = create_risk_engine(model_card["engine_type"], trained_model=trained_model, risk_threshold=RISK_THRESHOLD)
    audited_engine = AuditDecorator(base_engine, model_version=model_card["model_version"])
    engine = CachingDecorator(audited_engine)

    publisher = RiskEventPublisher()
    monitoring_observer = ModelMonitoringObserver()
    publisher.attach(RiskAlertObserver())
    publisher.attach(monitoring_observer)

    return repository, etl, engine, publisher, monitoring_observer, trained_model


_repository, _etl, _engine, _publisher, _monitoring_observer, _trained_model = _bootstrap()


# Business Logic layer

def _validate_request(group_id: str, requesting_teacher: str) -> None:
    """
    Business-Logic-level Fail-Fast (step 1 of Figure 7): checks the
    *request*, not the academic data itself (that check happens later,
    per record, in FailFastValidator). Keeping these separate is exactly
    what the validation matrix in the design doc calls for.
    """
    if not group_id or not isinstance(group_id, str) or not group_id.strip():
        raise ValidationError(
            "generate_group_risk_report called with an empty group_id",
            user_message="Please select a valid group before requesting a report.",
        )
    if not requesting_teacher:
        raise ValidationError(
            "generate_group_risk_report called with no requesting_teacher",
            user_message="You must be logged in to request a risk report.",
        )
    # A real deployment checks requesting_teacher against an auth/roster
    # service here (NFR-2). Out of scope for this milestone.


def _run_risk_workflow(group_id: str, requesting_teacher: str):
    """
    Steps 1-8 of the Figure 7 workflow, shared by every consumer of a risk
    report (the text report below, the JSON API, and the dashboard). This
    exists so `generate_group_risk_report` and `get_group_dashboard_data`
    can't drift apart and produce different numbers for the same group -
    there is exactly one place this computation happens (SRP).

    Returns (results, name_lookup) - never a name is left inside the
    result objects themselves (DR-1).
    """
    # Steps 1-2: validate and authorize request.
    _validate_request(group_id, requesting_teacher)

    # Steps 3-5: retrieve data and run it through the ETL/Fail-Fast pipeline.
    feature_vectors = _etl.process_group(group_id)

    # Steps 6-8: execute IRiskPredictionEngine, notify observers, persist.
    results = []
    for feature_vector in feature_vectors:
        result = _engine.predict_risk(feature_vector)
        results.append(result)

        # Step 7: notify observers (RiskAlertObserver + ModelMonitoringObserver).
        _publisher.notify_all(
            RiskEvent(
                group_id=group_id,
                student_ref=result.student_ref,
                risk_score=result.risk_score,
                threshold=RISK_THRESHOLD,
            )
        )

        # Step 8: persist the prediction. Best effort (NFR-5): if the secondary
        # store fails, the report is still produced.
        try:
            _repository.save_prediction(result.student_ref, result.risk_score, result.risk_label)
        except Exception as exc:  # noqa: BLE001 - isolation boundary
            logger.warning("Prediction for %s could not be persisted: %s", result.student_ref, type(exc).__name__)

    group = _repository.get_group(group_id)
    name_lookup = {s.student_id: s.name for s in group.students}
    return results, name_lookup


@handle_errors
def generate_group_risk_report(
    group_id: str,
    requesting_teacher: str = "demo_teacher",
) -> str:
    """Run the full workflow in Figure 7 and return the rendered text report."""
    results, name_lookup = _run_risk_workflow(group_id, requesting_teacher)
    # Step 6: build the report. Names are looked up here, in the
    # Presentation layer's data source - the AI layer never saw them.
    return TeacherReportUI.render_group_report(group_id, results, name_lookup)


@handle_errors
def get_group_dashboard_data(
    group_id: str,
    requesting_teacher: str = "demo_teacher",
) -> list[dict]:
    """
    Same workflow as generate_group_risk_report, but returns structured
    data instead of rendered text - for a UI (like web_app.py) that wants
    to build its own layout instead of parsing a text report. Returns a
    list of plain dicts, sorted highest-risk-first, one per student:
    {"name", "risk_score", "risk_label"}.
    """
    results, name_lookup = _run_risk_workflow(group_id, requesting_teacher)
    records = {s.student_id: s for s in _repository.get_group(group_id).students}
    ordered = sorted(results, key=lambda r: r.risk_score, reverse=True)
    return [
        {
            "student_id": r.student_ref,
            "name": name_lookup.get(r.student_ref, r.student_ref),
            "grades": list(records[r.student_ref].grades),
            "average_grade": round(sum(records[r.student_ref].grades) / len(records[r.student_ref].grades), 2),
            "attendance_pct": records[r.student_ref].attendance_pct,
            "participation_score": records[r.student_ref].participation_score,
            "grade_trend": round(records[r.student_ref].grades[-1] - records[r.student_ref].grades[0], 2),
            "risk_score": r.risk_score,
            "risk_label": r.risk_label,  # "high" | "medium" | "low" - never guessed from text
        }
        for r in ordered
    ]


def get_repository():
    """The single repository shared by the dashboard and the admin panel."""
    return _repository


def get_runtime_status() -> dict:
    """Non-sensitive runtime facts for /health and the demo-mode banner."""
    return {"backend": _repository.backend, "model_loaded": _trained_model is not None}


# Runnable demo: exercises the whole pipeline without needing a Flask
# server running, so the workflow can be verified end to end directly.


if __name__ == "__main__":
    from learning_module.model_trainer import (
        generate_synthetic_training_set,
        split_dataset,
    )
    from learning_module.training_pipeline import DATA_SEED, N_SAMPLES

    available = _repository.list_groups()
    if not available:
        raise SystemExit("No groups available. Create one in /admin or run scripts/seed_demo_data.py.")
    print(generate_group_risk_report(available[0]["group_id"]))

    print()
    print("--- Model evaluation on the held-out test set (same split used at training time) ---")
    _X, _y = generate_synthetic_training_set(n_samples=N_SAMPLES, seed=DATA_SEED)
    _, _X_test, _, _y_test = split_dataset(_X, _y)
    print(ModelEvaluator.evaluate(_trained_model, _X_test, _y_test))

    print()
    print(f"Audit trail size after this run: {len(_monitoring_observer.history())} predictions recorded")
    if hasattr(_repository, "get_prediction_log"):
        print(f"Predictions persisted: {len(_repository.get_prediction_log())} records in log")
