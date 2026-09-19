"""
learning_module/model_evaluator.py

Design note (traceability: §9 ML Pipeline "Evaluate performance" stage;
DR-3 Algorithmic Fairness and Bias Auditing):
    `evaluate` covers the standard accuracy/precision/recall numbers used
    to decide whether a trained model is good enough to deploy (feeds the
    "Model evaluation" step in the Gantt chart, Figure 9). `audit_fairness`
    is a minimal, working version of the recurring bias audit DR-3
    requires: it is intentionally simple (a per-group false-positive-rate
    comparison) because a full fairness audit is out of scope for this
    milestone, but the architecture needs to demonstrably *support* one -
    this is that hook, not a placeholder comment.
"""

from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from core.logger import get_logger

logger = get_logger(__name__)


class ModelEvaluator:
    @staticmethod
    def evaluate(model, X_test: list[list[float]], y_test: list[int]) -> dict:
        """Return standard classification metrics for a held-out test set."""
        predictions = model.predict(X_test)
        metrics = {
            "accuracy": round(accuracy_score(y_test, predictions), 3),
            "precision": round(precision_score(y_test, predictions, zero_division=0), 3),
            "recall": round(recall_score(y_test, predictions, zero_division=0), 3),
            "f1_score": round(f1_score(y_test, predictions, zero_division=0), 3),
        }
        logger.info("Model evaluation: %s", metrics)
        return metrics

    @staticmethod
    def audit_fairness(model, X_test: list[list[float]], y_test: list[int],
                        group_labels: list[str]) -> dict:
        """
        Compare the false-positive rate (a student incorrectly flagged as
        at-risk) across the given subgroup labels (DR-3). A large gap
        between groups is what a real audit would flag for review; this
        method only computes the numbers, a human still interprets them
        (consistent with DR-2, human-in-the-loop).
        """
        predictions = model.predict(X_test)
        rates_by_group: dict[str, dict[str, int]] = {}

        for true_label, predicted_label, group in zip(y_test, predictions, group_labels):
            bucket = rates_by_group.setdefault(group, {"false_positives": 0, "negatives": 0})
            if true_label == 0:
                bucket["negatives"] += 1
                if predicted_label == 1:
                    bucket["false_positives"] += 1

        result = {}
        for group, counts in rates_by_group.items():
            negatives = counts["negatives"]
            result[group] = round(counts["false_positives"] / negatives, 3) if negatives else None

        logger.info("Fairness audit (false-positive rate by group): %s", result)
        return result
