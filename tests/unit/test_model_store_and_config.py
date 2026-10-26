import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sklearn.linear_model import LogisticRegression

from core import config
from core.exception_handler import ModelLoadError, ValidationError
from feature_store.feature_manager import FeatureVector
from inference_engine.cache_manager import AuditDecorator
from inference_engine.risk_predictor import IRiskPredictionEngine, RiskResult
from learning_module.model_store import (
    CARD_FILENAME,
    MODEL_FILENAME,
    load_model,
    save_model,
)
from learning_module.training_pipeline import run_training


def tiny_model():
    return LogisticRegression().fit([[0, 0, 0, 0], [100, 10, 100, 100]], [1, 0])


class ModelStoreTests(unittest.TestCase):
    def test_round_trip_keeps_card_and_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = tiny_model()
            save_model(model, {"model_version": "v-test", "engine_type": "logistic_regression"}, Path(tmp))
            loaded, card = load_model(Path(tmp))
            self.assertEqual(card["model_version"], "v-test")
            self.assertEqual(loaded.predict([[0, 0, 0, 0]]).tolist(), model.predict([[0, 0, 0, 0]]).tolist())

    def test_missing_model_says_how_to_generate_it(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ModelLoadError) as ctx:
            load_model(Path(tmp))
        self.assertIn("scripts/train_model.py", ctx.exception.user_message)

    def test_corrupt_model_file_is_a_model_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_model(tiny_model(), {"model_version": "v"}, Path(tmp))
            (Path(tmp) / MODEL_FILENAME).write_bytes(b"not a joblib file")
            with self.assertRaises(ModelLoadError):
                load_model(Path(tmp))

    def test_card_without_engine_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_model(tiny_model(), {"model_version": "v"}, Path(tmp))
            with self.assertRaises(ModelLoadError):
                load_model(Path(tmp))

    def test_card_without_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_model(tiny_model(), {"algorithm": "x"}, Path(tmp))
            with self.assertRaises(ModelLoadError):
                load_model(Path(tmp))

    def test_training_pipeline_writes_a_complete_model_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = run_training(Path(tmp))
            self.assertTrue((Path(tmp) / CARD_FILENAME).is_file())
            self.assertEqual(card["engine_type"], config.model_type())
            self.assertEqual(card["algorithm"], type(load_model(Path(tmp))[0]).__name__)
            self.assertEqual(set(card["metrics_on_holdout"]), {"accuracy", "precision", "recall", "f1_score"})
            self.assertEqual(card["data"]["n_train"] + card["data"]["n_test"], card["data"]["n_samples"])


class RiskThresholdConfigTests(unittest.TestCase):
    def threshold(self, value):
        env = {} if value is None else {"RISK_THRESHOLD": value}
        with patch.dict(os.environ, env, clear=False):
            if value is None:
                os.environ.pop("RISK_THRESHOLD", None)
            return config.risk_threshold()

    def test_default_is_75(self):
        self.assertEqual(self.threshold(None), 75.0)

    def test_valid_values_including_bounds(self):
        for raw, expected in (("60", 60.0), ("0", 0.0), ("100", 100.0), (" 82.5 ", 82.5)):
            self.assertEqual(self.threshold(raw), expected)

    def test_invalid_values_fail_fast(self):
        for raw in ("abc", "-1", "100.1", "nan", "inf"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                self.threshold(raw)


class StubEngine(IRiskPredictionEngine):
    def predict_risk(self, feature_vector):
        return RiskResult(feature_vector.student_ref, 42.0, "medium")


class AuditDecoratorTests(unittest.TestCase):
    def test_audit_line_has_model_version_and_latency_but_no_name(self):
        engine = AuditDecorator(StubEngine(), model_version="rf-test-1")
        vector = FeatureVector("301-A-007", 70.0, 0.0, 90.0, 80.0)
        with self.assertLogs("student_predictor.inference_engine.cache_manager", level="INFO") as logs:
            engine.predict_risk(vector)
        line = "\n".join(logs.output)
        self.assertIn("AUDIT-TRAIL", line)
        self.assertIn("model_version=rf-test-1", line)
        self.assertIn("student_ref=301-A-007", line)
        self.assertRegex(line, r"latency_ms=\d+\.\d{2}")




class ModelTypeConfigTests(unittest.TestCase):
    def model_type(self, value):
        with patch.dict(os.environ, {} if value is None else {"RISK_MODEL": value}):
            if value is None:
                os.environ.pop("RISK_MODEL", None)
            return config.model_type()

    def test_default_is_the_validated_model(self):
        self.assertEqual(self.model_type(None), config.DEFAULT_MODEL_TYPE)
        self.assertEqual(self.model_type(""), config.DEFAULT_MODEL_TYPE)

    def test_valid_values_are_case_insensitive(self):
        self.assertEqual(self.model_type("Random_Forest"), "random_forest")
        self.assertEqual(self.model_type(" logistic_regression "), "logistic_regression")

    def test_unknown_model_fails_fast(self):
        for bad in ("xgboost", "svm", "random forest"):
            with self.subTest(bad), self.assertRaises(ValidationError):
                self.model_type(bad)


class ServingFollowsTheModelCardTests(unittest.TestCase):
    def test_each_trained_model_is_served_by_its_own_engine_through_the_factory(self):
        from inference_engine.risk_predictor import (
            LogisticRegressionRiskEngine,
            RandomForestRiskEngine,
            create_risk_engine,
        )

        for model_type, engine_class in (("random_forest", RandomForestRiskEngine),
                                         ("logistic_regression", LogisticRegressionRiskEngine)):
            with self.subTest(model_type), tempfile.TemporaryDirectory() as tmp:
                run_training(Path(tmp), model_type)
                model, card = load_model(Path(tmp))
                self.assertEqual(card["engine_type"], model_type)
                self.assertIsInstance(create_risk_engine(card["engine_type"], trained_model=model), engine_class)


class PassingGradeConfigTests(unittest.TestCase):
    def passing(self, value):
        with patch.dict(os.environ, {} if value is None else {"PASSING_GRADE": value}):
            if value is None:
                os.environ.pop("PASSING_GRADE", None)
            return config.passing_grade()

    def test_default_is_6_point_0(self):
        self.assertEqual(self.passing(None), 60.0)

    def test_valid_values(self):
        self.assertEqual(self.passing("70"), 70.0)
        self.assertEqual(self.passing(" 55.5 "), 55.5)

    def test_invalid_values_fail_fast(self):
        for raw in ("seis", "-1", "101", "nan"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                self.passing(raw)


if __name__ == "__main__":
    unittest.main()
