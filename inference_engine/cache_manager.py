"""
inference_engine/cache_manager.py

Design note (traceability: Decorator, §5; Figure 5 structural diagram; NFR-1):
    This is the code behind the `RiskPredictionDecorator` / `AuditDecorator`
    / `CachingDecorator` classes in Figure 5 of the architecture document.
    `RiskPredictionDecoratorBase` implements IRiskPredictionEngine and
    wraps another IRiskPredictionEngine (the `wrappee` in the diagram) -
    that is what lets us stack behavior around the real engine without
    ever modifying RandomForestRiskEngine itself.

    Division of labor between AuditDecorator (here) and AuditLogObserver
    (core/audit_observer.py), so the two do NOT overlap:
      - AuditDecorator wraps the engine call itself. It writes one audit
        record per ACTUAL inference call (student_ref, engine used, score,
        timestamp) - this is the per-call technical audit trail Figure 5
        asks for. Wrapping it around the engine (not the cache) means a
        cache hit is never logged as a new prediction.
      - AuditLogObserver reacts to the RiskEvent the orchestrator publishes
        AFTER a prediction is produced. It does not log per call - it
        accumulates events for the periodic drift/fairness review (the
        "Model Monitoring" Observer instance, §5.1). One writes the audit
        trail as the call happens (Decorator); the other watches the
        resulting business event over time (Observer).
"""

import time
from abc import ABC
from datetime import datetime, timezone

from inference_engine.risk_predictor import IRiskPredictionEngine, RiskResult
from feature_store.feature_manager import FeatureVector
from core.logger import get_logger

logger = get_logger(__name__)

_TTL_SECONDS = 60  # NFR-1, §3: cached entries expire after 60 s


class RiskPredictionDecoratorBase(IRiskPredictionEngine, ABC):
    """
    Common base for every decorator. Holds the wrapped engine and, by
    default, just delegates to it - concrete decorators only override
    what they actually need to change.
    """

    def __init__(self, wrappee: IRiskPredictionEngine) -> None:
        self._wrappee = wrappee

    def predict_risk(self, feature_vector: FeatureVector) -> RiskResult:
        return self._wrappee.predict_risk(feature_vector)


class AuditDecorator(RiskPredictionDecoratorBase):
    """
    Wraps an IRiskPredictionEngine to record the audit history - exactly
    the responsibility Figure 5 assigns to AuditDecorator. Every time the
    wrapped engine actually runs, this writes one audit-trail line before
    returning the result, independent of anything the Observer side does.
    """

    def predict_risk(self, feature_vector: FeatureVector) -> RiskResult:
        result = self._wrappee.predict_risk(feature_vector)

        logger.info(
            "AUDIT-TRAIL | engine=%s student_ref=%s score=%.1f at=%s",
            type(self._wrappee).__name__,
            result.student_ref,
            result.risk_score,
            datetime.now(timezone.utc).isoformat(),
        )
        return result


class CachingDecorator(RiskPredictionDecoratorBase):
    """
    Caches predictions per student_ref with a 60-second TTL so an
    identical repeated request (e.g. a teacher reopening the same report)
    does not re-run inference, while guaranteeing a fresh score once the
    TTL expires (NFR-1, §3).
    """

    def __init__(self, wrappee: IRiskPredictionEngine) -> None:
        super().__init__(wrappee)
        self._cache: dict[str, tuple[RiskResult, float]] = {}

    def predict_risk(self, feature_vector: FeatureVector) -> RiskResult:
        entry = self._cache.get(feature_vector.student_ref)
        if entry is not None:
            result, cached_at = entry
            age = time.monotonic() - cached_at
            if age < _TTL_SECONDS:
                logger.info(
                    "Cache hit for %s (age=%.1fs / TTL=%ds)",
                    feature_vector.student_ref, age, _TTL_SECONDS,
                )
                return result
            logger.debug("Cache expired for %s (age=%.1fs)", feature_vector.student_ref, age)

        result = self._wrappee.predict_risk(feature_vector)
        self._cache[feature_vector.student_ref] = (result, time.monotonic())
        return result

    def clear_cache(self) -> None:
        self._cache.clear()
