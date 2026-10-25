import unittest

from core.risk_levels import label_for, risk_bands
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

    def test_level_description_is_derived_from_the_threshold(self):
        self.assertEqual(describe_levels(75), "bajo <40; observación desde 40 y <75; alto desde 75")
        self.assertEqual(describe_levels(90), "bajo <40; observación desde 40 y <90; alto desde 90")
        self.assertEqual(describe_levels(82.5), "bajo <40; observación desde 40 y <82.5; alto desde 82.5")
        self.assertEqual(describe_levels(30), "bajo <30; alto desde 30")


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
