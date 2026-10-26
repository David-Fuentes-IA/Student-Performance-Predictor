"""
learning_module/model_validation.py

Model validation (lessons 18-19): does the model make reliable predictions on data it has
not seen? Everything here is a pure function over labels and predictions, so it is easy to
test and `scripts/evaluate_models.py` only has to orchestrate and write files.

Positive class = "student at risk". In this domain the costly mistake is the FALSE NEGATIVE
(a struggling student the system calls "on track": no tutoring, may fail or drop out), so
recall is the priority metric; precision only has to stay high enough for alerts to be
worth a teacher's time. F2 weighs recall twice as much as precision and is reported as the
balanced summary.

Models are compared with stratified cross-validation on the training data, and only the
winner is then measured once on the independent evaluation workbook. Choosing by the
independent set would leak it into the decision and make its numbers optimistic.
"""

import math
from collections.abc import Callable

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    fbeta_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold

METRICS = ("accuracy", "precision", "recall", "f1", "f2")
CV_FOLDS = 5
CV_SEED = 42

# Selection rule: highest mean CV recall among models whose mean CV precision is acceptable.
MIN_PRECISION_FOR_SELECTION = 0.60

# Quality gate (CI): a freshly trained model must clear these on the independent set.
# Set a little below what the current models reach, so noise does not break the build but a real
# regression does. A "too good" model is also suspicious (data leakage), hence the ceiling.
GATE_MIN_RECALL = 0.60
GATE_MIN_PRECISION = 0.60
GATE_MIN_F1 = 0.65
GATE_SUSPICIOUS_ABOVE = 0.99


def score_predictions(y_true, y_pred) -> dict:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "f2": float(fbeta_score(y_true, y_pred, beta=2, zero_division=0)),
    }


def confusion_counts(y_true, y_pred) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def cross_validate(build_model: Callable, X, y, folds: int = CV_FOLDS, seed: int = CV_SEED) -> dict:
    """Stratified k-fold. Returns mean/std per metric, per-fold values and the pooled out-of-fold confusion."""
    X, y = np.asarray(X, dtype=float), np.asarray(y)
    per_fold = {m: [] for m in METRICS}
    out_of_fold = np.zeros_like(y)
    for train_idx, test_idx in StratifiedKFold(folds, shuffle=True, random_state=seed).split(X, y):
        model = build_model().fit(X[train_idx], y[train_idx])
        predictions = model.predict(X[test_idx])
        out_of_fold[test_idx] = predictions
        for metric, value in score_predictions(y[test_idx], predictions).items():
            per_fold[metric].append(value)
    return {
        "folds": folds,
        "mean": {m: float(np.mean(v)) for m, v in per_fold.items()},
        "std": {m: float(np.std(v, ddof=1)) for m, v in per_fold.items()},
        "per_fold": {m: [round(x, 4) for x in v] for m, v in per_fold.items()},
        "confusion_out_of_fold": confusion_counts(y, out_of_fold),
    }


def out_of_fold_scores(build_model: Callable, X, y, folds: int = CV_FOLDS, seed: int = CV_SEED) -> np.ndarray:
    """Risk scores (0-100) for every student, each predicted by a model that never saw that student."""
    X, y = np.asarray(X, dtype=float), np.asarray(y)
    scores = np.zeros(len(y))
    for train_idx, test_idx in StratifiedKFold(folds, shuffle=True, random_state=seed).split(X, y):
        model = build_model().fit(X[train_idx], y[train_idx])
        scores[test_idx] = model.predict_proba(X[test_idx])[:, 1] * 100
    return scores


THRESHOLD_GRID = tuple(range(5, 100, 5))


def threshold_sweep(y_true, scores, thresholds=THRESHOLD_GRID) -> list[dict]:
    """What flagging every student with score >= t would achieve (recall = at-risk students caught)."""
    y_true, scores = np.asarray(y_true), np.asarray(scores)
    rows = []
    for t in thresholds:
        predictions = (scores >= t).astype(int)
        counts = confusion_counts(y_true, predictions)
        rows.append({"threshold": t, **{k: round(v, 4) for k, v in score_predictions(y_true, predictions).items()},
                     **counts, "flagged_share": round(float(predictions.mean()), 4)})
    return rows


# Policy assumption (changeable): at most ~3 of every 10 alerts may be false alarms.
ALERT_MIN_PRECISION = 0.70


def best_threshold(sweep: list[dict], metric: str = "f2") -> int:
    """Threshold that maximises `metric` (F2 by default: recall counts double)."""
    return max(sweep, key=lambda row: (row[metric], -row["threshold"]))["threshold"]


def lowest_threshold_with_precision(sweep: list[dict], min_precision: float = ALERT_MIN_PRECISION) -> int | None:
    """Lowest alert threshold (= most students caught) whose precision still meets `min_precision`."""
    eligible = [row["threshold"] for row in sweep if row["precision"] >= min_precision]
    return min(eligible) if eligible else None


def select_model(cv_results: dict[str, dict]) -> dict:
    """Apply the selection rule to {model name: cross_validate() result}. Returns the decision and why."""
    eligible = {n: r for n, r in cv_results.items() if r["mean"]["precision"] >= MIN_PRECISION_FOR_SELECTION}
    pool = eligible or cv_results
    # Highest mean recall; a near tie (within one fold-to-fold standard deviation) goes to the better F2.
    best_recall = max(r["mean"]["recall"] for r in pool.values())
    contenders = {n: r for n, r in pool.items()
                  if best_recall - r["mean"]["recall"] <= min(r["std"]["recall"] for r in pool.values())}
    winner = max(contenders, key=lambda n: (contenders[n]["mean"]["f2"], contenders[n]["mean"]["recall"]))
    return {
        "selected": winner,
        "rule": (f"highest mean cross-validated recall among models with mean precision >= "
                 f"{MIN_PRECISION_FOR_SELECTION}; ties within one standard deviation of recall go to the higher F2"),
        "recall_gap_between_models": round(best_recall - min(r["mean"]["recall"] for r in cv_results.values()), 4),
        "decided_on": "cross-validation of the training data (the independent set is not used to choose)",
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """95 % Wilson score interval for a proportion; None when there are no observations."""
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)


def fairness_report(y_true, y_pred, groups) -> dict:
    """Error rates per subgroup (DR-3), with 95 % intervals, plus the gaps between groups.

    false_positive_rate: share of students who did NOT end at risk that were flagged anyway
                         (extra review, possible stigma).
    false_negative_rate: share of students who DID end at risk that were missed
                         (no support when it was needed).
    flag_rate:           share of the group flagged, whatever the truth (demographic parity).
    """
    y_true, y_pred, groups = np.asarray(y_true), np.asarray(y_pred), np.asarray(groups)
    report = {}
    for group in sorted(set(groups)):
        mask = groups == group
        negatives, positives = int(np.sum(mask & (y_true == 0))), int(np.sum(mask & (y_true == 1)))
        false_positives = int(np.sum(mask & (y_true == 0) & (y_pred == 1)))
        false_negatives = int(np.sum(mask & (y_true == 1) & (y_pred == 0)))
        report[str(group)] = {
            "students": int(mask.sum()),
            "negatives": negatives,
            "positives": positives,
            "false_positive_rate": round(false_positives / negatives, 4) if negatives else None,
            "false_positive_rate_ci95": wilson_interval(false_positives, negatives),
            "false_negative_rate": round(false_negatives / positives, 4) if positives else None,
            "false_negative_rate_ci95": wilson_interval(false_negatives, positives),
            "flag_rate": round(float(np.mean(y_pred[mask] == 1)), 4),
        }

    def gap(key):
        values = [g[key] for g in report.values() if g[key] is not None]
        return round(max(values) - min(values), 4) if len(values) > 1 else None

    def overlap(key):
        intervals = [g[key] for g in report.values() if g[key] is not None]
        return all(a[0] <= b[1] and b[0] <= a[1] for a in intervals for b in intervals)

    return {
        "by_group": report,
        "gap": {k: gap(k) for k in ("false_positive_rate", "false_negative_rate", "flag_rate")},
        "intervals_overlap": {"false_positive_rate": overlap("false_positive_rate_ci95"),
                              "false_negative_rate": overlap("false_negative_rate_ci95")},
    }


def check_quality_gate(metrics: dict) -> list[str]:
    """Return the violated conditions (empty list = the model passes)."""
    problems = []
    if metrics["recall"] < GATE_MIN_RECALL:
        problems.append(f"recall {metrics['recall']:.3f} < {GATE_MIN_RECALL}")
    if metrics["precision"] < GATE_MIN_PRECISION:
        problems.append(f"precision {metrics['precision']:.3f} < {GATE_MIN_PRECISION}")
    if metrics["f1"] < GATE_MIN_F1:
        problems.append(f"f1 {metrics['f1']:.3f} < {GATE_MIN_F1}")
    suspicious = [m for m in ("accuracy", "precision", "recall") if metrics[m] > GATE_SUSPICIOUS_ABOVE]
    if suspicious:
        problems.append(f"{', '.join(suspicious)} above {GATE_SUSPICIOUS_ABOVE}: perfect scores usually mean "
                        "data leakage or a dataset with no overlap between classes")
    return problems
