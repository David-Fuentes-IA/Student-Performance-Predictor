"""
core/audit_observer.py

Observer pattern implementation.

Design note (traceability: Observer, §5; FR-5; §5.1 Observer Instances table):
    The design doc defines exactly TWO canonical Observer instances, and
    this file keeps that distinction instead of collapsing them into one:

    1. RiskAlertObserver        -> "Risk Alert" instance. Fires ONLY when a
       student's score crosses the configured threshold. Notifies the
       teacher and academic tutor. This is a decision-support alert, not
       an automatic action (DR-2, Academic Sovereignty / human-in-the-loop):
       the observer never changes a grade or flags the student itself, it
       only surfaces the alert for a human to act on.

    2. ModelMonitoringObserver  -> "Model Monitoring" instance. Accumulates
       every prediction (regardless of risk level) into an in-memory
       history used for the semiannual retraining/drift review described
       in the Risks section.

    Note this is NOT the same job as AuditDecorator
    (inference_engine/cache_manager.py), even though both involve
    "recording" something - AuditDecorator writes the per-call technical
    audit trail (one log line per actual inference, as the call happens).
    ModelMonitoringObserver reacts to the RiskEvent published AFTER a
    prediction, and its job is to accumulate that history for a later,
    periodic analysis job (drift/fairness), not to log each call. Keeping
    them separate is SRP (§4) applied to two things that sound similar but
    answer different questions: "what happened on this call?" (Decorator)
    vs. "what has been happening over time?" (Observer).

    The RiskEvent payload never carries the student's name - only the
    pseudonymous student_ref used throughout the AI layer (DR-1).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RiskEvent:
    """Payload passed to every observer when a prediction is made."""
    group_id: str
    student_ref: str        # pseudonymous identifier, never a name
    risk_score: float       # 0-100
    threshold: float        # threshold that was in effect at prediction time
    timestamp: str = None   # set automatically if not provided

    def __post_init__(self):
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", datetime.now(timezone.utc).isoformat())

    @property
    def exceeds_threshold(self) -> bool:
        return self.risk_score >= self.threshold


class RiskObserver(ABC):
    """Observer interface. Any class that wants to react to a prediction
    implements `update`."""

    @abstractmethod
    def update(self, event: RiskEvent) -> None:
        raise NotImplementedError


class RiskEventPublisher:
    """
    The Subject/Observable. The inference engine (or the orchestrator)
    holds one of these and calls `notify_all` after every prediction -
    it does not need to know which observers exist or what they do.
    """

    def __init__(self) -> None:
        self._observers: list[RiskObserver] = []

    def attach(self, observer: RiskObserver) -> None:
        self._observers.append(observer)

    def detach(self, observer: RiskObserver) -> None:
        self._observers.remove(observer)

    def notify_all(self, event: RiskEvent) -> None:
        for observer in self._observers:
            observer.update(event)


class RiskAlertObserver(RiskObserver):
    """
    'Risk Alert' instance (FR-5). Only acts when the event crosses the
    threshold, and only *notifies* - the actual intervention is always a
    human decision (DR-2).
    """

    def update(self, event: RiskEvent) -> None:
        if not event.exceeds_threshold:
            return
        # In production this would call the Notification Service (email/
        # SMS/push to the teacher and academic tutor). For this milestone
        # we log the alert so the workflow is visible end to end.
        logger.warning(
            "RISK ALERT | group=%s student_ref=%s score=%.1f (threshold=%.1f) "
            "-> teacher and academic tutor notified for review",
            event.group_id, event.student_ref, event.risk_score, event.threshold,
        )


class ModelMonitoringObserver(RiskObserver):
    """
    'Model Monitoring' instance. Accumulates every prediction (regardless
    of risk level) into an in-memory history for the semiannual
    retraining/drift review described in the Risks section.

    This does NOT write a per-call log line - AuditDecorator already owns
    that (inference_engine/cache_manager.py). Logging the same event twice
    from two different patterns would be duplicated responsibility, not
    two patterns working together.
    """

    def __init__(self) -> None:
        self._history: list[RiskEvent] = []

    def update(self, event: RiskEvent) -> None:
        self._history.append(event)

    def history(self) -> list[RiskEvent]:
        """Expose recorded events, e.g. for a future bias-audit job (DR-3)."""
        return list(self._history)
