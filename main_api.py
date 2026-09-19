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

from flask import Flask, jsonify

from core.exception_handler import handle_errors, ValidationError, AppError
from core.logger import get_logger
from core.audit_observer import RiskEventPublisher, RiskAlertObserver, ModelMonitoringObserver, RiskEvent

from data_access.student_repository import InMemoryAcademicRepository
from data_pipeline.etl_processor import ETLProcessor

from learning_module.model_trainer import ModelTrainer, generate_synthetic_training_set, split_dataset
from learning_module.model_evaluator import ModelEvaluator

from inference_engine.risk_predictor import create_risk_engine
from inference_engine.cache_manager import AuditDecorator, CachingDecorator

from presentation.teacher_report_ui import TeacherReportUI

logger = get_logger(__name__)

DEFAULT_RISK_THRESHOLD = 75.0  # NFR-1 / FR-7: admin-configurable in a real deployment


# --------------------------------------------------------------------------
# Composition root: wire every layer together ONCE, at startup.
# This is the only place concrete classes are instantiated directly -
# everywhere else depends on the interfaces (DIP).
# --------------------------------------------------------------------------

def _bootstrap():
    repository = InMemoryAcademicRepository()
    etl = ETLProcessor(repository)

    # "Train or load model" (§9): proper 80/20 stratified split so the
    # held-out test set evaluates generalisation, not training-set fit.
    X, y = generate_synthetic_training_set()
    X_train, X_test, y_train, y_test = split_dataset(X, y)
    trained_model = ModelTrainer.train(X_train, y_train)

    # Strategy (base engine) wrapped in two Decorators, matching Figure 5:
    # AuditDecorator innermost (so it only logs real inference calls),
    # CachingDecorator outermost (so a cache hit skips both the audit
    # write and the model entirely). The rest of the app only ever sees
    # an IRiskPredictionEngine, never these concrete classes.
    base_engine = create_risk_engine("random_forest", trained_model=trained_model)
    audited_engine = AuditDecorator(base_engine)
    engine = CachingDecorator(audited_engine)

    publisher = RiskEventPublisher()
    monitoring_observer = ModelMonitoringObserver()
    publisher.attach(RiskAlertObserver())
    publisher.attach(monitoring_observer)

    return repository, etl, engine, publisher, monitoring_observer, trained_model, X_test, y_test


_repository, _etl, _engine, _publisher, _monitoring_observer, _trained_model, _X_test, _y_test = _bootstrap()


# --------------------------------------------------------------------------
# Business Logic layer
# --------------------------------------------------------------------------

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


def _run_risk_workflow(group_id: str, requesting_teacher: str, threshold: float):
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
                threshold=threshold,
            )
        )

        # Step 8: persist prediction (IAcademicDataRepository.save_prediction).
        _repository.save_prediction(result.student_ref, result.risk_score, result.risk_label)

    group = _repository.get_group(group_id)
    name_lookup = {s.student_id: s.name for s in group.students}
    return results, name_lookup


@handle_errors
def generate_group_risk_report(
    group_id: str,
    requesting_teacher: str = "demo_teacher",
    threshold: float = DEFAULT_RISK_THRESHOLD,
) -> str:
    """Run the full workflow in Figure 7 and return the rendered text report."""
    results, name_lookup = _run_risk_workflow(group_id, requesting_teacher, threshold)
    # Step 6: build the report. Names are looked up here, in the
    # Presentation layer's data source - the AI layer never saw them.
    return TeacherReportUI.render_group_report(group_id, results, name_lookup)


@handle_errors
def get_group_dashboard_data(
    group_id: str,
    requesting_teacher: str = "demo_teacher",
    threshold: float = DEFAULT_RISK_THRESHOLD,
) -> list[dict]:
    """
    Same workflow as generate_group_risk_report, but returns structured
    data instead of rendered text - for a UI (like web_app.py) that wants
    to build its own layout instead of parsing a text report. Returns a
    list of plain dicts, sorted highest-risk-first, one per student:
    {"name", "risk_score", "risk_label"}.
    """
    results, name_lookup = _run_risk_workflow(group_id, requesting_teacher, threshold)
    ordered = sorted(results, key=lambda r: r.risk_score, reverse=True)
    return [
        {
            "name": name_lookup.get(r.student_ref, r.student_ref),
            "risk_score": r.risk_score,
            "risk_label": r.risk_label,  # "high" | "medium" | "low" - never guessed from text
        }
        for r in ordered
    ]


# --------------------------------------------------------------------------
# Thin Flask API (Technology Stack, §6.5)
# --------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/api/v1/groups/<group_id>/risk-report", methods=["GET"])
def get_group_risk_report(group_id: str):
    try:
        report_text = generate_group_risk_report(group_id)
        return jsonify({"group_id": group_id, "report": report_text})
    except AppError as exc:
        # user_message is always safe to return to the client (core/exception_handler.py).
        return jsonify({"error": exc.user_message}), 400


# --------------------------------------------------------------------------
# Runnable demo: exercises the whole pipeline without needing a Flask
# server running, so the workflow can be verified end to end directly.
# --------------------------------------------------------------------------

if __name__ == "__main__":
    print(generate_group_risk_report("301-A"))

    print("\n--- Model evaluation on held-out test set (80/20 stratified split) ---")
    print(ModelEvaluator.evaluate(_trained_model, _X_test, _y_test))

    print(f"\nAudit trail size after this run: {len(_monitoring_observer.history())} predictions recorded")
    print(f"Predictions persisted: {len(_repository.get_prediction_log())} records in log")
