import os
import unittest
from unittest.mock import MagicMock, patch

from pymongo.errors import ServerSelectionTimeoutError

from core import config
from core.exception_handler import DataAccessError
from data_access import mongo_connection
from data_access.repository_factory import build_repository
from data_access.student_repository import InMemoryAcademicRepository
from learning_module.model_evaluator import ModelEvaluator


class StubClassifier:
    def __init__(self, predictions):
        self._predictions = predictions

    def predict(self, X):
        return self._predictions


class EvaluatorTests(unittest.TestCase):
    def test_metrics_for_a_known_confusion_matrix(self):
        # TP=1, FN=1, FP=1, TN=1  ->  every metric is 0.5
        metrics = ModelEvaluator.evaluate(StubClassifier([1, 0, 0, 1]), [[0]] * 4, [1, 1, 0, 0])
        self.assertEqual(metrics, {"accuracy": 0.5, "precision": 0.5, "recall": 0.5, "f1_score": 0.5})

    def test_perfect_and_worst_cases(self):
        self.assertEqual(ModelEvaluator.evaluate(StubClassifier([1, 0]), [[0]] * 2, [1, 0])["f1_score"], 1.0)
        worst = ModelEvaluator.evaluate(StubClassifier([0, 1]), [[0]] * 2, [1, 0])
        self.assertEqual((worst["accuracy"], worst["recall"]), (0.0, 0.0))

    def test_a_model_that_never_flags_anyone_has_zero_precision_not_a_crash(self):
        metrics = ModelEvaluator.evaluate(StubClassifier([0, 0, 0]), [[0]] * 3, [1, 0, 1])
        self.assertEqual((metrics["precision"], metrics["recall"]), (0.0, 0.0))


class FairnessAuditTests(unittest.TestCase):
    def test_false_positive_rate_is_computed_per_group(self):
        predictions = [1, 0, 1,  0, 0,  1]
        labels =      [0, 0, 1,  0, 0,  1]
        groups = ["A", "A", "A", "B", "B", "C"]
        rates = ModelEvaluator.audit_fairness(StubClassifier(predictions), [[0]] * 6, labels, groups)
        self.assertEqual(rates["A"], 0.5)    # 1 of 2 real negatives flagged
        self.assertEqual(rates["B"], 0.0)
        self.assertIsNone(rates["C"])        # no negatives -> rate undefined, not zero

    def test_mismatched_lengths_fail_loudly(self):
        with self.assertRaises(ValueError):
            ModelEvaluator.audit_fairness(StubClassifier([1, 0]), [[0]] * 2, [1, 0], ["A"])


class MongoConnectionTests(unittest.TestCase):
    def test_passwords_are_redacted_for_logs(self):
        uri = "mongodb+srv://gabo:SuperSecret123@cluster0.mongodb.net/db?appName=x"
        safe = mongo_connection.redact_uri(uri)
        self.assertNotIn("SuperSecret123", safe)
        self.assertIn("gabo:****@cluster0.mongodb.net", safe)
        self.assertEqual(mongo_connection.redact_uri("mongodb://localhost:27017"), "mongodb://localhost:27017")

    def test_missing_configuration_is_a_clear_error(self):
        with self.assertRaises(DataAccessError) as ctx:
            mongo_connection.get_client("")
        self.assertIn("MONGODB_URI", ctx.exception.user_message)

    def test_unreachable_server_gives_a_safe_message_without_internals(self):
        client = MagicMock()
        client.admin.command.side_effect = ServerSelectionTimeoutError("db01.internal:27017 timed out")
        with patch.object(mongo_connection, "get_client", return_value=client), self.assertRaises(DataAccessError) as ctx:
            mongo_connection.get_database("mongodb://whatever")
        self.assertNotIn("db01.internal", ctx.exception.user_message)
        self.assertIn("No se pudo conectar", ctx.exception.user_message)


class RepositoryFactoryTests(unittest.TestCase):
    def test_without_configuration_the_in_memory_demo_repository_is_used(self):
        self.assertIsInstance(build_repository(), InMemoryAcademicRepository)

    def configured_but_down(self):
        return (patch("data_access.repository_factory.config.mongodb_uri", return_value="mongodb://configured"),
                patch("data_access.mongo_repository.MongoAcademicRepository",
                      side_effect=DataAccessError("down", user_message="down")))

    def test_a_configured_database_that_is_down_stops_the_application(self):
        uri, repo = self.configured_but_down()
        with uri, repo, self.assertLogs("student_predictor.data_access.repository_factory", level="ERROR"),                 self.assertRaises(DataAccessError) as ctx:
            build_repository()
        self.assertIn("ALLOW_DEMO_FALLBACK", ctx.exception.user_message)

    def test_demo_fallback_is_an_explicit_development_opt_in_and_warns_loudly(self):
        uri, repo = self.configured_but_down()
        with uri, repo, patch.dict(os.environ, {"ALLOW_DEMO_FALLBACK": "true"}),                 self.assertLogs("student_predictor.data_access.repository_factory", level="WARNING") as logs:
            repository = build_repository()
        self.assertIsInstance(repository, InMemoryAcademicRepository)
        self.assertIn("NOT the real ones", " ".join(logs.output))

    def test_the_fallback_switch_is_off_by_default_and_parses_common_spellings(self):
        for value, expected in ((None, False), ("", False), ("false", False), ("true", True), ("TRUE", True),
                                ("1", True), ("yes", True)):
            with self.subTest(value), patch.dict(os.environ, {} if value is None else {"ALLOW_DEMO_FALLBACK": value}):
                if value is None:
                    os.environ.pop("ALLOW_DEMO_FALLBACK", None)
                self.assertEqual(config.allow_demo_fallback(), expected)


if __name__ == "__main__":
    unittest.main()
