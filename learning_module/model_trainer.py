"""
learning_module/model_trainer.py

Design note (traceability: §1 System Boundary Statement; §9 ML Pipeline
"Train or load model" stage):
    The architecture proposal is explicit that Milestone 1 was about the
    *design*, not about training a model, and that training only enters
    scope once the system is implemented (which is what this milestone
    is). This module is that "Train or load model" stage: it is
    deliberately simple (a single RandomForestClassifier over a handful
    of features) because the point of this milestone is to prove the
    pipeline end to end, not to produce a production-grade model.

    There is no real institutional dataset available yet, so
    `generate_synthetic_training_set` stands in for "Academic data" at
    the start of the pipeline (Figure 8). Swapping this for a real,
    historical dataset later does not require touching ModelTrainer's
    public interface.
"""

import random

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from core.logger import get_logger

logger = get_logger(__name__)

_TEST_SIZE = 0.20   # 80/20 stratified split preserves ~30% at-risk ratio
_SPLIT_SEED = 42


def split_dataset(
    X: list[list[float]], y: list[int]
) -> tuple[list, list, list, list]:
    """
    Split (X, y) 80/20 with stratification so the minority at-risk class
    (~30%) is proportionally represented in both halves.
    Returns (X_train, X_test, y_train, y_test).
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=_TEST_SIZE, random_state=_SPLIT_SEED, stratify=y
    )
    logger.info(
        "Dataset split: %d train / %d test (stratified, test_size=%.0f%%)",
        len(X_train), len(X_test), _TEST_SIZE * 100,
    )
    return X_train, X_test, y_train, y_test


def generate_synthetic_training_set(n_samples: int = 300, seed: int = 7):
    """
    Build a small synthetic (X, y) dataset shaped like FeatureVector's
    `as_model_input()` output: [average_grade, grade_trend,
    attendance_pct, participation_score] -> label (1 = at risk).

    This is a stand-in for historical academic records and is only meant
    to make the pipeline runnable end to end for this milestone.
    """
    rng = random.Random(seed)
    X, y = [], []

    for _ in range(n_samples):
        is_at_risk = rng.random() < 0.3
        if is_at_risk:
            average_grade = rng.uniform(30, 60)
            grade_trend = rng.uniform(-15, 0)
            attendance = rng.uniform(40, 70)
            participation = rng.uniform(20, 55)
        else:
            average_grade = rng.uniform(60, 100)
            grade_trend = rng.uniform(-5, 15)
            attendance = rng.uniform(70, 100)
            participation = rng.uniform(50, 100)

        X.append([average_grade, grade_trend, attendance, participation])
        y.append(1 if is_at_risk else 0)

    return X, y


class ModelTrainer:
    """One job: fit models on features and labels (SRP)."""

    @staticmethod
    def train(X: list[list[float]], y: list[int]) -> RandomForestClassifier:
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=6,
            random_state=42,
        )
        model.fit(X, y)
        logger.info("Trained RandomForestClassifier on %d samples", len(X))
        return model

    @staticmethod
    def train_logistic_regression(X: list[list[float]], y: list[int]) -> LogisticRegression:
        model = LogisticRegression(max_iter=500, random_state=42)
        model.fit(X, y)
        logger.info("Trained LogisticRegression on %d samples", len(X))
        return model
