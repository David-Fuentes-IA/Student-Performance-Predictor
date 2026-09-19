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

from feature_store.feature_manager import FeatureVector
from core.exception_handler import PredictionEngineError
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RiskResult:
    student_ref: str
    risk_score: float   # 0-100, higher = more at risk
    risk_label: str      # "low" | "medium" | "high"


def _label_for(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


class IRiskPredictionEngine(ABC):
    """Strategy interface every prediction engine (and every Decorator
    wrapping one) must implement."""

    @abstractmethod
    def predict_risk(self, feature_vector: FeatureVector) -> RiskResult:
        raise NotImplementedError


class RandomForestRiskEngine(IRiskPredictionEngine):
    """
    Concrete strategy backed by a scikit-learn RandomForestClassifier.

    The trained model is injected in the constructor rather than trained
    here - this class's one job is running inference, not training
    (SRP; training lives in learning_module.model_trainer).
    """

    def __init__(self, trained_model) -> None:
        if trained_model is None:
            raise PredictionEngineError(
                "RandomForestRiskEngine created without a trained model",
                user_message="The prediction model is not available right now.",
            )
        self._model = trained_model

    def predict_risk(self, feature_vector: FeatureVector) -> RiskResult:
        try:
            # predict_proba returns [P(not at risk), P(at risk)]; we report
            # the "at risk" probability as a 0-100 risk score.
            probability_at_risk = self._model.predict_proba(
                [feature_vector.as_model_input()]
            )[0][1]
        except Exception as exc:  # noqa: BLE001
            raise PredictionEngineError(
                f"model inference failed for {feature_vector.student_ref}: {exc}",
                user_message="Could not compute a risk score for one or more students.",
            ) from exc

        score = round(probability_at_risk * 100, 1)
        return RiskResult(
            student_ref=feature_vector.student_ref,
            risk_score=score,
            risk_label=_label_for(score),
        )


class LogisticRegressionRiskEngine(IRiskPredictionEngine):
    """
    Second concrete strategy backed by a scikit-learn LogisticRegression
    model. Injecting the trained model keeps SRP: this class only runs
    inference; training lives in learning_module.model_trainer.
    """

    def __init__(self, trained_model) -> None:
        if trained_model is None:
            raise PredictionEngineError(
                "LogisticRegressionRiskEngine created without a trained model",
                user_message="The prediction model is not available right now.",
            )
        self._model = trained_model

    def predict_risk(self, feature_vector: FeatureVector) -> RiskResult:
        try:
            probability_at_risk = self._model.predict_proba(
                [feature_vector.as_model_input()]
            )[0][1]
        except Exception as exc:  # noqa: BLE001
            raise PredictionEngineError(
                f"logistic regression inference failed for {feature_vector.student_ref}: {exc}",
                user_message="Could not compute a risk score for one or more students.",
            ) from exc

        score = round(probability_at_risk * 100, 1)
        return RiskResult(
            student_ref=feature_vector.student_ref,
            risk_score=score,
            risk_label=_label_for(score),
        )


def create_risk_engine(engine_type: str, **kwargs) -> IRiskPredictionEngine:
    """
    Factory function (§5, Factory pattern). The admin-configured model
    type (FR-8) is the single string that decides which class gets built;
    no if/else chains scattered around the rest of the application.
    """
    engine_type = engine_type.lower().strip()

    if engine_type == "random_forest":
        return RandomForestRiskEngine(trained_model=kwargs.get("trained_model"))

    if engine_type == "logistic_regression":
        return LogisticRegressionRiskEngine(trained_model=kwargs.get("trained_model"))

    raise PredictionEngineError(
        f"Unknown engine_type '{engine_type}' requested from create_risk_engine",
        user_message="The configured prediction model type is not supported.",
    )
