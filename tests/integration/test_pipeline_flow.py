"""Integration: repository -> ETL -> engine -> observers -> persistence -> report, and what happens
when one link of that chain fails (the lesson-17 "failures between components" cases)."""
import unittest
from dataclasses import replace
from unittest.mock import patch

import main_api
from core.audit_observer import RiskEventPublisher
from core.exception_handler import DataAccessError, PredictionEngineError
from data_access.student_repository import InMemoryAcademicRepository, StudentGroup
from data_pipeline.etl_processor import ETLProcessor
from tests.unit.test_observer_and_errors import ExplodingObserver
from webapp import create_app

ALERTS = "student_predictor.core.audit_observer"
GENERIC = "No se pudo generar la información del grupo. Inténtalo de nuevo."


class HappyPathTests(unittest.TestCase):
    def test_report_lists_every_student_by_name_with_a_risk_score(self):
        report = main_api.generate_group_risk_report("301-A")
        self.assertIn("Risk report - Group 301-A", report)
        for student in main_api._repository.get_group("301-A").students:
            self.assertIn(student.name, report)

    def test_every_prediction_is_persisted_and_every_observer_is_notified(self):
        persisted_before = len(main_api._repository.get_prediction_log())
        monitored_before = len(main_api._monitoring_observer.history())
        main_api.generate_group_risk_report("301-B")
        self.assertEqual(len(main_api._repository.get_prediction_log()) - persisted_before, 12)
        self.assertEqual(len(main_api._monitoring_observer.history()) - monitored_before, 12)

    def test_high_risk_students_raise_an_alert(self):
        with self.assertLogs(ALERTS, level="WARNING") as logs:
            main_api.generate_group_risk_report("301-A")
        self.assertTrue(any("RISK ALERT" in line for line in logs.output))

    def test_personal_names_never_reach_any_log_line(self):
        names = [s.name for s in main_api._repository.get_group("301-C").students]
        with self.assertLogs("student_predictor", level="DEBUG") as logs:
            main_api.get_group_dashboard_data("301-C")
        text = "\n".join(logs.output)
        self.assertTrue(text)  # something was logged
        for name in names:
            self.assertNotIn(name, text)


class DataQualityTests(unittest.TestCase):
    def test_invalid_records_are_skipped_and_the_rest_of_the_group_is_analysed(self):
        repo = InMemoryAcademicRepository()
        good = repo.get_group("301-A").students[:3]
        bad = [replace(good[0], student_id="BAD-1", grades=["90"]),      # wrong type
               replace(good[0], student_id="BAD-2", grades=[250.0]),     # out of range
               replace(good[0], student_id="BAD-3", grades=[])]          # missing
        repo._groups["301-A"] = StudentGroup("301-A", good + bad)
        with patch.object(main_api, "_repository", repo), patch.object(main_api, "_etl", ETLProcessor(repo)):
            rows = main_api.get_group_dashboard_data("301-A")
        self.assertEqual({r["student_id"] for r in rows}, {s.student_id for s in good})


class ComponentFailureTests(unittest.TestCase):
    """NFR-5: a failing secondary service must not stop the report."""

    def test_a_failing_observer_does_not_stop_the_report(self):
        publisher = RiskEventPublisher()
        publisher.attach(ExplodingObserver())
        with patch.object(main_api, "_publisher", publisher), self.assertLogs(ALERTS, level="ERROR"):
            rows = main_api.get_group_dashboard_data("301-A")
        self.assertEqual(len(rows), 12)

    def test_a_failing_prediction_store_does_not_stop_the_report(self):
        with patch.object(main_api._repository, "save_prediction", side_effect=RuntimeError("disk full")):
            rows = main_api.get_group_dashboard_data("301-A")
        self.assertEqual(len(rows), 12)


class FailureReachesTheUserSafelyTests(unittest.TestCase):
    """A critical dependency failing must give a clean HTTP error, never a traceback or internals."""

    def setUp(self):
        self.client = create_app().test_client()

    def assert_clean(self, response, status, message):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.get_json()["error"], message)
        for leak in ("Traceback", "db01.internal", "/opt/model", "RuntimeError"):
            self.assertNotIn(leak, response.get_data(as_text=True))

    def test_database_failure_returns_503_with_the_safe_message(self):
        failing = unittest.mock.Mock()
        failing.process_group.side_effect = DataAccessError(
            "connection refused by db01.internal:27017", user_message="La base de datos no respondio correctamente.")
        with patch.object(main_api, "_etl", failing):
            self.assert_clean(self.client.get("/api/groups/301-A"), 503, "La base de datos no respondio correctamente.")

    def test_model_failure_returns_503_with_a_generic_message(self):
        failing = unittest.mock.Mock()
        failing.predict_risk.side_effect = PredictionEngineError("model crashed at /opt/model/rf.bin")
        with patch.object(main_api, "_engine", failing):
            self.assert_clean(self.client.get("/api/groups/301-A"), 503, GENERIC)

    def test_unexpected_crash_returns_503_with_a_generic_message(self):
        failing = unittest.mock.Mock()
        failing.predict_risk.side_effect = RuntimeError("something unforeseen")
        with patch.object(main_api, "_engine", failing):
            self.assert_clean(self.client.get("/api/groups/301-A"), 503, GENERIC)

    def test_pdf_endpoints_fail_just_as_safely(self):
        failing = unittest.mock.Mock()
        failing.process_group.side_effect = DataAccessError("db01.internal down", user_message="Base de datos no disponible.")
        with patch.object(main_api, "_etl", failing):
            self.assert_clean(self.client.get("/reports/groups/301-A.pdf"), 503, "Base de datos no disponible.")


if __name__ == "__main__":
    unittest.main()
