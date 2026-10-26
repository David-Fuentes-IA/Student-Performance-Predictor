import unittest

from core.risk_levels import (
    FAILING_AVERAGE,
    HIGH_PREDICTED_RISK,
    alert_reasons,
    is_failing,
    label_for,
    risk_bands,
)
from feature_store.feature_manager import FeatureVector
from inference_engine.risk_predictor import (
    LogisticRegressionRiskEngine,
    RandomForestRiskEngine,
    create_risk_engine,
)
from presentation.report_data import describe_levels


class FixedProbabilityModel:
    def __init__(self, probability):
        self._probability = probability

    def predict_proba(self, rows):
        return [[1 - self._probability, self._probability] for _ in rows]


VECTOR = FeatureVector("S1", 60.0, 0.0, 70.0, 60.0)



class LabelTests(unittest.TestCase):
    def test_default_threshold_keeps_the_original_cutoffs(self):
        for score, expected in ((0, "low"), (39.9, "low"), (40, "medium"), (74.9, "medium"), (75, "high"), (100, "high")):
            self.assertEqual(label_for(score, 75), expected, score)

    def test_high_level_follows_the_threshold(self):
        self.assertEqual(label_for(80, 90), "medium")
        self.assertEqual(label_for(90, 90), "high")
        self.assertEqual(label_for(55, 50), "high")
        self.assertEqual(label_for(45, 50), "medium")
        self.assertEqual(label_for(39, 50), "low")

    def test_threshold_at_or_below_medium_floor_has_no_medium_band(self):
        self.assertEqual(risk_bands(30), (30, 30))
        self.assertEqual([label_for(s, 30) for s in (10, 29.9, 30, 90)], ["low", "low", "high", "high"])

    def test_level_description_is_derived_from_the_threshold_and_passing_grade(self):
        self.assertEqual(describe_levels(75), "alto: promedio menor a 6.0 (60/100) o riesgo estimado desde 75; "
                                              "observación: riesgo estimado desde 40; bajo: el resto")
        self.assertIn("riesgo estimado desde 82.5", describe_levels(82.5))
        self.assertEqual(describe_levels(30), "alto: promedio menor a 6.0 (60/100) o riesgo estimado desde 30; "
                                              "bajo: el resto")
        self.assertIn("promedio menor a 7.0 (70/100)", describe_levels(75, 70))


class SchoolRuleTests(unittest.TestCase):
    """High risk also means 'failing average', as a school would say (below 6.0 = 60/100)."""

    def test_a_failing_average_is_high_risk_whatever_the_model_says(self):
        self.assertEqual(label_for(3.0, 75, average_grade=59.9), "high")
        self.assertEqual(label_for(3.0, 75, average_grade=0), "high")

    def test_the_passing_grade_itself_is_not_failing(self):
        self.assertEqual(label_for(3.0, 75, average_grade=60.0), "low")
        self.assertEqual(label_for(50.0, 75, average_grade=60.0), "medium")

    def test_without_an_average_only_the_model_score_counts(self):
        self.assertEqual(label_for(3.0, 75), "low")
        self.assertEqual(label_for(80.0, 75), "high")

    def test_the_passing_grade_is_configurable(self):
        self.assertEqual(label_for(3.0, 75, average_grade=65, passing_grade=70), "high")
        self.assertEqual(label_for(3.0, 75, average_grade=65, passing_grade=60), "low")

    def test_alert_reasons_say_why(self):
        self.assertEqual(alert_reasons(10, 75, 55), [FAILING_AVERAGE])
        self.assertEqual(alert_reasons(90, 75, 80), [HIGH_PREDICTED_RISK])
        self.assertEqual(alert_reasons(90, 75, 40), [FAILING_AVERAGE, HIGH_PREDICTED_RISK])
        self.assertEqual(alert_reasons(10, 75, 80), [])
        self.assertTrue(is_failing(59.99) and not is_failing(60) and not is_failing(None))

    def test_engines_apply_the_school_rule_through_the_factory(self):
        failing = FeatureVector("S9", 45.0, 0.0, 90.0, 80.0)
        low_score_model = FixedProbabilityModel(0.05)
        self.assertEqual(create_risk_engine("logistic_regression", trained_model=low_score_model)
                         .predict_risk(failing).risk_label, "high")
        lenient = create_risk_engine("logistic_regression", trained_model=low_score_model, passing_grade=40)
        self.assertEqual(lenient.predict_risk(failing).risk_label, "low")


class EngineThresholdTests(unittest.TestCase):
    def test_same_score_gets_a_different_label_per_threshold(self):
        model = FixedProbabilityModel(0.55)  # score 55
        for engine_class in (RandomForestRiskEngine, LogisticRegressionRiskEngine):
            self.assertEqual(engine_class(model, risk_threshold=50).predict_risk(VECTOR).risk_label, "high")
            self.assertEqual(engine_class(model, risk_threshold=90).predict_risk(VECTOR).risk_label, "medium")

    def test_factory_passes_the_threshold_to_the_engine(self):
        engine = create_risk_engine("random_forest", trained_model=FixedProbabilityModel(0.55), risk_threshold=50)
        self.assertEqual(engine.predict_risk(VECTOR).risk_label, "high")


if __name__ == "__main__":
    unittest.main()
