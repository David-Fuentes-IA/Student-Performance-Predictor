"""
inference_engine/risk_predictor.py

Design note (traceability: Strategy + Factory, §5; DIP §6.3; FR-4, FR-8):
    `IRiskPredictionEngine` is the Strategy interface: the rest of the
    system calls `predict_risk(...)` and never knows or cares which
    concrete algorithm answered. `RandomForestRiskEngine` is one concrete
    strategy; adding a `LogisticRegressionRiskEngine` later means writing
    one new class here and registering it in `create_risk_engine`, with
    zero changes anywhere else in the codebase.

    `create_risk_engine` is the Factory: callers ask for an engine by
    name/config instead of importing and instantiating a concrete class
    directly, which is what lets an administrator change the configured
    model type (FR-8) without touching orchestration code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from core.config import DEFAULT_PASSING_GRADE, DEFAULT_RISK_THRESHOLD
from core.exception_handler import PredictionEngineError
from core.logger import get_logger
from core.risk_levels import label_for
from feature_store.feature_manager import FeatureVector

logger = get_logger(__name__)


@dataclass(frozen=True)
class RiskResult:
    student_ref: str
    risk_score: float   # 0-100, higher = more at risk
    risk_label: str      # "low" | "medium" | "high"


class IRiskPredictionEngine(ABC):
    """Strategy interface every prediction engine (and every Decorator
    wrapping one) must implement."""

    @abstractmethod
    def predict_risk(self, feature_vector: FeatureVector) -> RiskResult:
        raise NotImplementedError

    def predict_many(self, feature_vectors: list[FeatureVector]) -> list[RiskResult]:
        """Predictions for a whole group, in order. The default asks one student at a time;
        engines that can (scikit-learn models) override it with one batch call."""
        return [self.predict_risk(vector) for vector in feature_vectors]


class _ProbabilisticRiskEngine(IRiskPredictionEngine):
    """
    Shared implementation for engines backed by a scikit-learn classifier with predict_proba.

    The trained model is injected in the constructor rather than trained here - this class's one
    job is running inference, not training (SRP; training lives in learning_module.model_trainer).
    """

    def __init__(self, trained_model, risk_threshold: float = DEFAULT_RISK_THRESHOLD,
                 passing_grade: float = DEFAULT_PASSING_GRADE) -> None:
        if trained_model is None:
            raise PredictionEngineError(
                f"{type(self).__name__} created without a trained model",
                user_message="The prediction model is not available right now.",
            )
        self._model = trained_model
        self._risk_threshold = risk_threshold
        self._passing_grade = passing_grade

    def predict_risk(self, feature_vector: FeatureVector) -> RiskResult:
        return self.predict_many([feature_vector])[0]

    def predict_many(self, feature_vectors: list[FeatureVector]) -> list[RiskResult]:
        if not feature_vectors:
            return []
        try:
            # predict_proba returns [P(not at risk), P(at risk)] per row; one call for the whole group
            # is ~100x faster than one call per student (docs/evidence/performance).
            rows = [v.as_model_input() for v in feature_vectors]
            probabilities = np.asarray(self._model.predict_proba(rows), dtype=float)[:, 1]
        except Exception as exc:  # noqa: BLE001
            refs = ", ".join(v.student_ref for v in feature_vectors[:5])
            raise PredictionEngineError(
                f"{type(self).__name__} inference failed for {refs}: {exc}",
                user_message="Could not compute a risk score for one or more students.",
            ) from exc

        results = []
        for vector, probability in zip(feature_vectors, probabilities, strict=True):
            score = round(float(probability) * 100, 1)
            results.append(RiskResult(
                student_ref=vector.student_ref,
                risk_score=score,
                risk_label=label_for(score, self._risk_threshold, vector.average_grade, self._passing_grade),
            ))
        return results


class RandomForestRiskEngine(_ProbabilisticRiskEngine):
    """Concrete strategy backed by a scikit-learn RandomForestClassifier."""


class LogisticRegressionRiskEngine(_ProbabilisticRiskEngine):
    """Concrete strategy backed by a scikit-learn LogisticRegression (the validated default)."""


def create_risk_engine(engine_type: str, **kwargs) -> IRiskPredictionEngine:
    """
    Factory function (§5, Factory pattern). The admin-configured model
    type (FR-8) is the single string that decides which class gets built;
    no if/else chains scattered around the rest of the application.
    """
    engine_type = engine_type.lower().strip()
    risk_threshold = kwargs.get("risk_threshold", DEFAULT_RISK_THRESHOLD)
    passing_grade = kwargs.get("passing_grade", DEFAULT_PASSING_GRADE)

    if engine_type == "random_forest":
        return RandomForestRiskEngine(trained_model=kwargs.get("trained_model"), risk_threshold=risk_threshold,
                                      passing_grade=passing_grade)

    if engine_type == "logistic_regression":
        return LogisticRegressionRiskEngine(trained_model=kwargs.get("trained_model"), risk_threshold=risk_threshold,
                                            passing_grade=passing_grade)

    raise PredictionEngineError(
        f"Unknown engine_type '{engine_type}' requested from create_risk_engine",
        user_message="The configured prediction model type is not supported.",
    )
