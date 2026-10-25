"""
learning_module/model_trainer.py

Design note (traceability: §1 System Boundary Statement; §9 ML Pipeline
"Train or load model" stage):
    The architecture proposal is explicit that Milestone 1 was about the
    *design*, not about training a model, and that training only enters
    scope once the system is implemented (which is what this milestone
    is). This module is that "Train or load model" stage: it is
    deliberately simple (a single RandomForestClassifier over four
    features) because the point is to prove the pipeline end to end and
    to validate it honestly, not to produce a production-grade model.

    There is no real institutional dataset available yet, so
    `generate_synthetic_training_set` stands in for "Academic data" at
    the start of the pipeline (Figure 8). It draws students from the
    noisy simulator in data_access/synthetic_students.py (hidden traits,
    overlapping classes, unforeseeable events) and turns them into
    features with the SAME FeatureManager the running application uses,
    so training and serving cannot drift apart. Swapping it for a real,
    historical dataset later does not require touching ModelTrainer's
    public interface.
"""

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from core.logger import get_logger
from data_access.student_repository import StudentRecord
from data_access.synthetic_students import SimulatedStudent, simulate_students
from feature_store.feature_manager import FeatureManager

logger = get_logger(__name__)

_TEST_SIZE = 0.20   # 80/20 stratified split keeps the at-risk ratio in both halves
_SPLIT_SEED = 42


def split_dataset(
    X: list[list[float]], y: list[int]
) -> tuple[list, list, list, list]:
    """
    Split (X, y) 80/20 with stratification so the minority at-risk class
    (~27 %) is proportionally represented in both halves.
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


def students_to_dataset(students: list[SimulatedStudent]) -> tuple[list[list[float]], list[int]]:
    """Features (via the production FeatureManager) and ground-truth labels for labelled students."""
    records = [
        StudentRecord(s.student_id, s.name, s.grades, s.attendance_pct, s.participation_score)
        for s in students
    ]
    X = [vector.as_model_input() for vector in FeatureManager.extract_many(records)]
    return X, [s.at_risk for s in students]


def generate_synthetic_training_set(n_samples: int = 600, seed: int = 7):
    """
    Build a synthetic (X, y) dataset shaped like FeatureVector's
    `as_model_input()` output: [average_grade, grade_trend,
    attendance_pct, participation_score] -> label (1 = at risk).

    The classes overlap (see data_access/synthetic_students.py), so even a
    good model makes mistakes; that is what makes validation meaningful.
    """
    return students_to_dataset(simulate_students(n_samples, seed=seed))


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
