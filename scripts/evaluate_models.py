"""
scripts/evaluate_models.py

Model validation and error analysis (Milestone 3, criterion 3), reproducible with one command:

    python scripts/evaluate_models.py                 # writes docs/evidence/model/
    python scripts/evaluate_models.py --gate          # CI quality gate: exit 1 if the model is not good enough
    python scripts/evaluate_models.py --out some/dir

Protocol
    1. Both candidate models are compared with stratified 5-fold cross-validation on the training
       data (600 simulated students). The decision is taken here, never on the independent set.
    2. The winner is trained on all the training data and measured ONCE on data it has never seen:
       data/grupo_evaluacion.xlsx (240 students, different seed).
    3. Every false negative and false positive of that run is listed and described, and the error
       rates of the synthetic subgroups (evening / morning shift) are compared.

Software testing shows the software works. This shows whether the model's predictions are reliable.
"""

import argparse
import csv
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import sklearn  # noqa: E402

from core import config  # noqa: E402
from learning_module.evaluation_data import DEFAULT_PATH, load_evaluation_workbook  # noqa: E402
from learning_module.model_trainer import (  # noqa: E402
    MODEL_TYPES,
    ModelTrainer,
    generate_synthetic_training_set,
)
from learning_module.model_validation import (  # noqa: E402
    ALERT_MIN_PRECISION,
    CV_FOLDS,
    GATE_MIN_F1,
    GATE_MIN_PRECISION,
    GATE_MIN_RECALL,
    MIN_PRECISION_FOR_SELECTION,
    best_threshold,
    check_quality_gate,
    confusion_counts,
    cross_validate,
    fairness_report,
    lowest_threshold_with_precision,
    out_of_fold_scores,
    score_predictions,
    select_model,
    threshold_sweep,
    wilson_interval,
)
from learning_module.training_pipeline import DATA_SEED, N_SAMPLES  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "model"
BORDERLINE_BAND = 15.0   # a risk score within +-15 of the 50 % decision boundary counts as borderline
LABELS = {"random_forest": "Random Forest", "logistic_regression": "Logistic Regression"}


def describe_errors(records, scores, y_true, y_pred, shifts) -> tuple[list[dict], dict]:
    """One row per misclassified student plus group comparisons that look for patterns."""
    features = {}
    for record, score, truth, prediction, shift in zip(records, scores, y_true, y_pred, shifts, strict=True):
        grades = record.grades
        row = {
            "student_id": record.student_id,
            "outcome": ("TP", "FN", "FP", "TN")[(2 * (truth == 0) + (prediction == 0))],
            "true_at_risk": int(truth), "predicted_at_risk": int(prediction),
            "risk_score": round(float(score), 1), "shift": shift,
            "grades_count": len(grades), "average_grade": round(sum(grades) / len(grades), 1),
            "grade_trend": round(grades[-1] - grades[0], 1),
            "attendance_pct": record.attendance_pct, "participation_score": record.participation_score,
            "borderline": abs(float(score) - 50.0) <= BORDERLINE_BAND,
        }
        features[record.student_id] = row
    all_rows = list(features.values())
    errors = [r for r in all_rows if r["outcome"] in ("FN", "FP")]

    def profile(outcome):
        group = [r for r in all_rows if r["outcome"] == outcome]
        if not group:
            return None
        return {
            "n": len(group),
            "average_grade": round(float(np.mean([r["average_grade"] for r in group])), 1),
            "grade_trend": round(float(np.mean([r["grade_trend"] for r in group])), 1),
            "attendance_pct": round(float(np.mean([r["attendance_pct"] for r in group])), 1),
            "participation_score": round(float(np.mean([r["participation_score"] for r in group])), 1),
            "risk_score": round(float(np.mean([r["risk_score"] for r in group])), 1),
            "share_borderline": round(float(np.mean([r["borderline"] for r in group])), 3),
            "share_incomplete_grades": round(float(np.mean([r["grades_count"] < 4 for r in group])), 3),
            "share_evening_shift": round(float(np.mean([r["shift"] == "vespertino" for r in group])), 3),
        }

    analysis = {
        "profiles": {o: profile(o) for o in ("TP", "FN", "FP", "TN")},
        "errors_total": len(errors),
        "errors_borderline_share": round(float(np.mean([r["borderline"] for r in errors])), 3) if errors else None,
        "correct_borderline_share": round(float(np.mean(
            [r["borderline"] for r in all_rows if r["outcome"] in ("TP", "TN")])), 3),
        "borderline_band": BORDERLINE_BAND,
    }
    return sorted(errors, key=lambda r: (r["outcome"], -r["risk_score"])), analysis


FEATURE_NAMES = ["average_grade", "grade_trend", "attendance_pct", "participation_score"]
DECLINE_POINTS = -14.0    # a fall of 14+ points between the first and last partial exam counts as a sharp decline


def feature_effects(model, X) -> dict:
    """What the selected model leans on. Coefficients of correlated features must not be read causally."""
    X = np.asarray(X, dtype=float)
    spread = X.std(axis=0)
    if hasattr(model, "coef_"):
        coefficients = model.coef_[0]
        return {"kind": "logistic regression coefficients (positive = raises risk)",
                "per_feature": {name: {"coefficient": round(float(c), 4), "std_of_feature": round(float(s), 2),
                                       "effect_per_std": round(float(c * s), 3)}
                                for name, c, s in zip(FEATURE_NAMES, coefficients, spread, strict=True)}}
    return {"kind": "random forest impurity importance (shares sum to 1)",
            "per_feature": {name: {"importance": round(float(i), 4)}
                            for name, i in zip(FEATURE_NAMES, model.feature_importances_, strict=True)}}


def decline_analysis(X_test, y_true, y_pred) -> dict:
    """Does the model catch at-risk students whose grades fall sharply? (the trend feature's job)"""
    X_test, y_true, y_pred = np.asarray(X_test, dtype=float), np.asarray(y_true), np.asarray(y_pred)
    at_risk = y_true == 1
    declining = at_risk & (X_test[:, 1] <= DECLINE_POINTS)
    missed = declining & (y_pred == 0)
    return {"sharp_decline_points": DECLINE_POINTS, "at_risk_students": int(at_risk.sum()),
            "at_risk_with_sharp_decline": int(declining.sum()), "of_which_missed": int(missed.sum()),
            "miss_rate_with_sharp_decline": round(float(missed.sum() / declining.sum()), 3) if declining.any() else None,
            "miss_rate_overall": round(float((at_risk & (y_pred == 0)).sum() / at_risk.sum()), 3)}


def evaluate_application_rule(avg_cv, scores_cv, y_cv, avg_test, scores_test, y_test) -> dict:
    """The rule the application actually uses for 'Alto riesgo' and alerts (core/risk_levels.py):
    failing average (below PASSING_GRADE) OR model score >= RISK_THRESHOLD. Measured on out-of-fold
    cross-validation scores and once on the independent set, next to its two halves alone."""
    passing, threshold = config.DEFAULT_PASSING_GRADE, config.DEFAULT_RISK_THRESHOLD

    def measure(predictions_cv, predictions_test):
        out = {}
        for name, truth, predictions in (("cross_validation", y_cv, predictions_cv), ("independent", y_test, predictions_test)):
            counts = confusion_counts(truth, predictions)
            out[name] = {**{k: round(v, 4) for k, v in score_predictions(truth, predictions).items()}, **counts,
                         "flagged_share": round(float(np.mean(predictions)), 4),
                         "recall_ci95": wilson_interval(counts["tp"], counts["tp"] + counts["fn"])}
        return out

    failing_cv, failing_test = np.asarray(avg_cv) < passing, np.asarray(avg_test) < passing
    high_cv, high_test = np.asarray(scores_cv) >= threshold, np.asarray(scores_test) >= threshold
    return {
        "rule": f"high risk = average grade < {passing:g} (failing) OR model risk score >= {threshold:g}",
        "passing_grade": passing,
        "risk_threshold": threshold,
        "combined_rule": measure((failing_cv | high_cv).astype(int), (failing_test | high_test).astype(int)),
        "failing_average_alone": measure(failing_cv.astype(int), failing_test.astype(int)),
        "model_score_alone": measure(high_cv.astype(int), high_test.astype(int)),
        "combined_rule_with_lower_model_threshold": {
            str(t): measure((failing_cv | (np.asarray(scores_cv) >= t)).astype(int),
                            (failing_test | (np.asarray(scores_test) >= t)).astype(int))
            for t in (60, 50)
        },
    }


def plot_confusions(results: dict, path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(8, 7))
    panels = [(m, kind) for m in MODEL_TYPES for kind in ("cv", "test")]
    for ax, (model, kind) in zip(axes.flat, panels, strict=True):
        c = (results["cross_validation"][model]["confusion_out_of_fold"] if kind == "cv"
             else results["independent_test"][model]["confusion"])
        matrix = np.array([[c["tn"], c["fp"]], [c["fn"], c["tp"]]])
        ax.imshow(matrix, cmap="Blues")
        for (i, j), value in np.ndenumerate(matrix):
            ax.text(j, i, str(value), ha="center", va="center", fontsize=15,
                    color="white" if value > matrix.max() / 2 else "black")
        ax.set_xticks([0, 1], ["not at risk", "at risk"])
        ax.set_yticks([0, 1], ["not at risk", "at risk"])
        ax.set_xlabel("predicted")
        ax.set_ylabel("actual")
        ax.set_title(f"{LABELS[model]}\n" + ("cross-validation (out of fold, n=600)" if kind == "cv"
                                             else "independent set (n=240)"), fontsize=10)
    fig.suptitle("Confusion matrices (bottom-left = false negatives, top-right = false positives)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_cv_metrics(results: dict, path: Path) -> None:
    metrics = ["precision", "recall", "f1", "f2", "accuracy"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.38
    for k, model in enumerate(MODEL_TYPES):
        cv = results["cross_validation"][model]
        means = [cv["mean"][m] for m in metrics]
        errors = [cv["std"][m] for m in metrics]
        ax.bar(np.arange(len(metrics)) + (k - 0.5) * width, means, width, yerr=errors, capsize=4,
               label=LABELS[model])
    ax.set_xticks(range(len(metrics)), metrics)
    ax.set_ylim(0.5, 1.0)
    ax.set_ylabel("5-fold cross-validation, mean ± std")
    recalls = [results["cross_validation"][m]["mean"]["recall"] for m in MODEL_TYPES]
    spread = min(results["cross_validation"][m]["std"]["recall"] for m in MODEL_TYPES)
    gap = abs(recalls[0] - recalls[1])
    verdict = ("recall difference is smaller than the fold-to-fold variation: no clear winner" if gap <= spread
               else "recall difference is larger than the fold-to-fold variation")
    ax.set_title(f"Recall gap {gap:.3f} vs fold std {spread:.3f}: {verdict}", fontsize=9)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_operating_points(results: dict, path: Path) -> None:
    op = results["operating_points"]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for name, style, label in (("cross_validation", "-", "cross-validation"), ("independent", "--", "independent set")):
        rows = op[name]
        ax.plot([r["threshold"] for r in rows], [r["recall"] for r in rows], style, color="tab:red", label=f"recall ({label})")
        ax.plot([r["threshold"] for r in rows], [r["precision"] for r in rows], style, color="tab:blue",
                label=f"precision ({label})")
    for t, text, color in ((50, "default cut 50", "gray"), (op["application_alert_threshold"], "alert threshold (app)", "black"),
                           (op["recommended_alert_threshold_from_cv"], "recommended (from CV)", "tab:green")):
        ax.axvline(t, color=color, linestyle=":")
        ax.text(t + 0.8, 0.07, text, rotation=90, fontsize=8, color=color)
    ax.set_xlabel("flag a student when risk score >= threshold")
    ax.set_ylabel("metric")
    ax.set_ylim(0, 1.02)
    ax.set_title(f"{LABELS[op['selected_model']]}: raising the threshold trades recall (missed students) for precision",
                 fontsize=9)
    ax.legend(fontsize=8, loc="lower left", bbox_to_anchor=(0.0, 0.18))
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def comparison_markdown(results: dict) -> str:
    lines = ["| Model | Accuracy | Precision | Recall | F1 | F2 |", "|---|---|---|---|---|---|"]
    for model in MODEL_TYPES:
        cv = results["cross_validation"][model]
        lines.append(f"| {LABELS[model]} (5-fold CV) | " + " | ".join(
            f"{cv['mean'][m]:.3f} ± {cv['std'][m]:.3f}" for m in ("accuracy", "precision", "recall", "f1", "f2")) + " |")
    for model in MODEL_TYPES:
        t = results["independent_test"][model]["metrics"]
        lines.append(f"| {LABELS[model]} (independent set) | " + " | ".join(
            f"{t[m]:.3f}" for m in ("accuracy", "precision", "recall", "f1", "f2")) + " |")
    return "\n".join(lines) + "\n"


def evaluate(selected_override: str | None = None) -> dict:
    X, y = generate_synthetic_training_set(N_SAMPLES, DATA_SEED)
    evaluation = load_evaluation_workbook(DEFAULT_PATH)
    X_test, y_test, shifts = evaluation.dataset()

    cross_validation = {m: cross_validate(lambda m=m: ModelTrainer.build(m), X, y) for m in MODEL_TYPES}
    decision = select_model(cross_validation)
    selected = selected_override or decision["selected"]

    independent, fitted = {}, {}
    for model_type in MODEL_TYPES:
        fitted[model_type] = ModelTrainer.fit(model_type, X, y)
        predictions = fitted[model_type].predict(X_test)
        independent[model_type] = {"metrics": score_predictions(y_test, predictions),
                                   "confusion": confusion_counts(y_test, predictions)}

    chosen = fitted[selected]
    predictions = chosen.predict(X_test)
    scores = chosen.predict_proba(X_test)[:, 1] * 100

    # Operating points: the metrics above cut at score 50, but the application alerts at RISK_THRESHOLD (75).
    scores_cv = out_of_fold_scores(lambda: ModelTrainer.build(selected), X, y)
    sweep_cv = threshold_sweep(y, scores_cv)
    sweep_independent = threshold_sweep(y_test, scores)
    application_rule = evaluate_application_rule(np.asarray(X)[:, 0], scores_cv, y,
                                                 np.asarray(X_test)[:, 0], scores, y_test)
    chosen_threshold = lowest_threshold_with_precision(sweep_cv)   # decided on cross-validation only
    f2_threshold = best_threshold(sweep_cv, "f2")
    pick = lambda sweep, t: next(r for r in sweep if r["threshold"] == t)  # noqa: E731
    error_rows, error_analysis = describe_errors(evaluation.records, scores, y_test, predictions, shifts)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {"python": platform.python_version(), "scikit_learn": sklearn.__version__},
        "data": {"training": {"students": len(X), "seed": DATA_SEED, "share_at_risk": round(float(np.mean(y)), 3)},
                 "independent": {"students": len(X_test), "file": "data/grupo_evaluacion.xlsx",
                                 "share_at_risk": round(float(np.mean(y_test)), 3)}},
        "protocol": {"cross_validation": f"stratified {CV_FOLDS}-fold, shuffled", "positive_class": "student at risk",
                     "priority_metric": "recall", "min_precision_for_selection": MIN_PRECISION_FOR_SELECTION},
        "cross_validation": cross_validation,
        "decision": {**decision, "selected": selected, "configured_default": config.DEFAULT_MODEL_TYPE},
        "independent_test": independent,
        "operating_points": {
            "selected_model": selected,
            "cross_validation": sweep_cv,
            "independent": sweep_independent,
            "recommended_alert_threshold_from_cv": chosen_threshold,
            "recommendation_rule": (f"lowest threshold whose cross-validated precision is >= {ALERT_MIN_PRECISION} "
                                    "(policy assumption: at most ~3 in 10 alerts may be false alarms)"),
            "independent_at_recommended_threshold": pick(sweep_independent, chosen_threshold),
            "f2_optimal_threshold_from_cv": f2_threshold,
            "independent_at_f2_optimal_threshold": pick(sweep_independent, f2_threshold),
            "independent_at_default_cut_50": pick(sweep_independent, 50),
            "independent_at_application_alert_threshold": pick(sweep_independent, int(config.DEFAULT_RISK_THRESHOLD)),
            "application_alert_threshold": config.DEFAULT_RISK_THRESHOLD,
        },
        "application_rule": application_rule,
        "feature_effects": feature_effects(chosen, X),
        "error_analysis": {**error_analysis, "sharp_decline": decline_analysis(X_test, y_test, predictions)},
        "fairness": {"selected_model": selected, "subgroup": "turno (synthetic, see data/README.md)",
                     **fairness_report(y_test, predictions, shifts)},
        "quality_gate": {"min_recall": GATE_MIN_RECALL, "min_precision": GATE_MIN_PRECISION, "min_f1": GATE_MIN_F1,
                         "violations": check_quality_gate(independent[selected]["metrics"])},
        "_error_rows": error_rows,
    }


def write_evidence(results: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    error_rows = results.pop("_error_rows")
    (out / "metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (out / "comparison.md").write_text(comparison_markdown(results), encoding="utf-8")
    with (out / "errors.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(error_rows[0]))
        writer.writeheader()
        writer.writerows(error_rows)
    plot_confusions(results, out / "confusion_matrices.png")
    plot_cv_metrics(results, out / "cv_metrics.png")
    plot_operating_points(results, out / "operating_points.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the risk models and analyse their errors.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", choices=MODEL_TYPES, default=None, help="evaluate this model as 'selected'")
    parser.add_argument("--gate", action="store_true", help="CI quality gate: exit 1 when the model fails it")
    args = parser.parse_args()

    results = evaluate(args.model)
    selected = results["decision"]["selected"]
    violations = results["quality_gate"]["violations"]
    metrics = results["independent_test"][selected]["metrics"]
    if args.gate:
        print(f"quality gate for {selected}: " + ", ".join(f"{m}={metrics[m]:.3f}" for m in ("recall", "precision", "f1")))
        if violations:
            raise SystemExit("QUALITY GATE FAILED: " + "; ".join(violations))
        print("quality gate passed")
        return

    write_evidence(results, args.out)
    print(f"selected model: {selected} ({results['decision']['rule']})")
    print(f"configured default (core/config.py): {config.DEFAULT_MODEL_TYPE}")
    print(comparison_markdown(results))
    print(f"errors on the independent set: {results['error_analysis']['errors_total']} -> {args.out}")
    if violations:
        print("WARNING quality gate violations:", "; ".join(violations))


if __name__ == "__main__":
    main()
