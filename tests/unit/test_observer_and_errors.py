import dataclasses
import unittest

from core.audit_observer import (
    ModelMonitoringObserver,
    RiskAlertObserver,
    RiskEvent,
    RiskEventPublisher,
    RiskObserver,
)
from core.exception_handler import (
    AppError,
    DataAccessError,
    GroupNotFoundError,
    NotFoundError,
    ValidationError,
    handle_errors,
)
from core.logger import sanitize

ALERTS = "student_predictor.core.audit_observer"


def event(score, threshold=75.0):
    return RiskEvent(group_id="G1", student_ref="S1", risk_score=score, threshold=threshold)


class RecordingObserver(RiskObserver):
    def __init__(self):
        self.events = []

    def update(self, event):
        self.events.append(event)


class ExplodingObserver(RiskObserver):
    def update(self, event):
        raise RuntimeError("notification service is down")


class RiskEventTests(unittest.TestCase):
    def test_threshold_comparison_is_inclusive(self):
        self.assertFalse(event(74.9).exceeds_threshold)
        self.assertTrue(event(75.0).exceeds_threshold)
        self.assertTrue(event(100).exceeds_threshold)

    def test_timestamp_is_set_automatically(self):
        self.assertTrue(event(10).timestamp)

    def test_event_carries_no_personal_name_field(self):
        names = {f.name for f in dataclasses.fields(RiskEvent)}
        self.assertEqual(names, {"group_id", "student_ref", "risk_score", "threshold", "timestamp"})


class PublisherTests(unittest.TestCase):
    def test_notifies_every_attached_observer_and_supports_detach(self):
        publisher, first, second = RiskEventPublisher(), RecordingObserver(), RecordingObserver()
        publisher.attach(first)
        publisher.attach(second)
        publisher.notify_all(event(50))
        publisher.detach(second)
        publisher.notify_all(event(60))
        self.assertEqual(len(first.events), 2)
        self.assertEqual(len(second.events), 1)

    def test_a_failing_observer_does_not_stop_the_others_nor_raise(self):
        publisher, healthy = RiskEventPublisher(), RecordingObserver()
        publisher.attach(ExplodingObserver())
        publisher.attach(healthy)
        with self.assertLogs(ALERTS, level="ERROR") as logs:
            publisher.notify_all(event(90))
        self.assertEqual(len(healthy.events), 1)
        self.assertIn("ExplodingObserver", "\n".join(logs.output))


class ObserverBehaviourTests(unittest.TestCase):
    def test_risk_alert_logs_only_when_the_threshold_is_reached(self):
        observer = RiskAlertObserver()
        with self.assertNoLogs(ALERTS, level="WARNING"):
            observer.update(event(40))
        with self.assertLogs(ALERTS, level="WARNING") as logs:
            observer.update(event(80))
        line = logs.output[0]
        self.assertIn("RISK ALERT", line)
        self.assertIn("student_ref=S1", line)

    def test_monitoring_observer_records_every_prediction_and_returns_a_copy(self):
        observer = ModelMonitoringObserver()
        for score in (5, 50, 99):
            observer.update(event(score))
        history = observer.history()
        self.assertEqual([e.risk_score for e in history], [5, 50, 99])
        history.clear()
        self.assertEqual(len(observer.history()), 3)


class ExceptionHandlingTests(unittest.TestCase):
    def test_hierarchy_supports_specific_catching(self):
        self.assertTrue(issubclass(GroupNotFoundError, NotFoundError))
        self.assertTrue(issubclass(NotFoundError, DataAccessError))
        self.assertTrue(issubclass(DataAccessError, AppError))
        self.assertTrue(issubclass(ValidationError, AppError))

    def test_user_message_defaults_to_the_message(self):
        self.assertEqual(AppError("boom").user_message, "boom")
        self.assertEqual(AppError("boom", user_message="Try again").user_message, "Try again")

    def test_handle_errors_returns_the_value_untouched(self):
        @handle_errors
        def ok():
            return 42
        self.assertEqual(ok(), 42)

    def test_handle_errors_reraises_known_errors_unchanged(self):
        @handle_errors
        def fail():
            raise ValidationError("bad input", user_message="Please check the data.")
        with self.assertRaises(ValidationError) as ctx:
            fail()
        self.assertEqual(ctx.exception.user_message, "Please check the data.")

    def test_handle_errors_hides_unexpected_error_details_from_the_user(self):
        @handle_errors
        def crash():
            raise RuntimeError("password=hunter2 at /srv/app/secret.py")
        with self.assertRaises(AppError) as ctx:
            crash()
        self.assertNotIn("hunter2", ctx.exception.user_message)
        self.assertNotIn("/srv/app", ctx.exception.user_message)
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)


class LogSanitizerTests(unittest.TestCase):
    def test_sensitive_keys_are_redacted_case_insensitively_without_mutating_input(self):
        original = {"Name": "Ana Perez", "EMAIL": "a@b.mx", "student_ref": "S1", "score": 80}
        clean = sanitize(original)
        self.assertEqual(clean["Name"], "[REDACTED]")
        self.assertEqual(clean["EMAIL"], "[REDACTED]")
        self.assertEqual((clean["student_ref"], clean["score"]), ("S1", 80))
        self.assertEqual(original["Name"], "Ana Perez")


if __name__ == "__main__":
    unittest.main()
