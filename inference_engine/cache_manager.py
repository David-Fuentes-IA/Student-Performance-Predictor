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

from core.logger import get_logger
from feature_store.feature_manager import FeatureVector
from inference_engine.risk_predictor import IRiskPredictionEngine, RiskResult

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
        return self.predict_many([feature_vector])[0]

    def predict_many(self, feature_vectors: list[FeatureVector]) -> list[RiskResult]:
        return self._wrappee.predict_many(feature_vectors)


class AuditDecorator(RiskPredictionDecoratorBase):
    """
    Wraps an IRiskPredictionEngine to record the audit history - exactly
    the responsibility Figure 5 assigns to AuditDecorator. Every time the
    wrapped engine actually runs, this writes one audit-trail line per
    student before returning the results, independent of the Observer side.
    `latency_ms` is the duration of the engine call that produced the score
    (one call for the whole batch).
    """

    def __init__(self, wrappee: IRiskPredictionEngine, model_version: str = "unknown") -> None:
        super().__init__(wrappee)
        self._model_version = model_version

    def predict_many(self, feature_vectors: list[FeatureVector]) -> list[RiskResult]:
        started = time.perf_counter()
        results = self._wrappee.predict_many(feature_vectors)
        latency_ms = (time.perf_counter() - started) * 1000
        engine, at = type(self._wrappee).__name__, datetime.now(timezone.utc).isoformat()
        for result in results:
            logger.info(
                "AUDIT-TRAIL | engine=%s model_version=%s student_ref=%s score=%.1f latency_ms=%.2f batch=%d at=%s",
                engine, self._model_version, result.student_ref, result.risk_score, latency_ms, len(results), at,
            )
        return results


class CachingDecorator(RiskPredictionDecoratorBase):
    """
    Caches predictions for 60 s (NFR-1, §3) so an identical repeated request
    (e.g. a teacher reopening the same report) does not re-run inference.

    The key is the whole FeatureVector (student_ref + grades-derived features,
    attendance, participation), not just the student id: if an Excel import or
    an admin edit changes a student's data, the key changes and a fresh
    prediction is computed immediately instead of serving a stale score.
    For a group, only the students missing from the cache reach the engine,
    in a single batch.
    """

    _MAX_ENTRIES = 10_000

    def __init__(self, wrappee: IRiskPredictionEngine) -> None:
        super().__init__(wrappee)
        self._cache: dict[FeatureVector, tuple[RiskResult, float]] = {}

    def predict_many(self, feature_vectors: list[FeatureVector]) -> list[RiskResult]:
        results: list[RiskResult | None] = [None] * len(feature_vectors)
        misses = []
        for position, vector in enumerate(feature_vectors):
            entry = self._cache.get(vector)
            if entry is not None and time.monotonic() - entry[1] < _TTL_SECONDS:
                results[position] = entry[0]
            else:
                misses.append(position)

        hits = len(feature_vectors) - len(misses)
        if hits:
            logger.info("Cache hit for %d of %d students (TTL=%ds)", hits, len(feature_vectors), _TTL_SECONDS)
        if misses:
            fresh = self._wrappee.predict_many([feature_vectors[p] for p in misses])
            stored_at = time.monotonic()
            for position, result in zip(misses, fresh, strict=True):
                results[position] = result
                self._evict_if_full()
                self._cache[feature_vectors[position]] = (result, stored_at)
        return results

    def _evict_if_full(self) -> None:
        if len(self._cache) < self._MAX_ENTRIES:
            return
        now = time.monotonic()
        self._cache = {k: v for k, v in self._cache.items() if now - v[1] < _TTL_SECONDS}
        if len(self._cache) >= self._MAX_ENTRIES:
            self._cache.clear()

    def clear_cache(self) -> None:
        self._cache.clear()
