import json
import os
import subprocess
import sys
import unittest
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

import main_api
from core.risk_levels import label_for, risk_bands
from feature_store.feature_manager import FeatureVector
from inference_engine.risk_predictor import (
    LogisticRegressionRiskEngine,
    RandomForestRiskEngine,
    create_risk_engine,
)
from presentation.pdf_reports import build_group_report, build_student_report
from presentation.report_data import describe_levels, summarize
from webapp import create_app

ROOT = Path(__file__).resolve().parent.parent


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


class DashboardAndReportsTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_api_exposes_threshold_and_labels_are_consistent_with_it(self):
        data = self.client.get("/api/groups/301-A").get_json()
        self.assertEqual(data["risk_threshold"], main_api.RISK_THRESHOLD)
        self.assertIn(f"alto desde {main_api.RISK_THRESHOLD:g}", data["risk_levels"])
        for student in data["students"]:
            self.assertEqual(student["risk_label"], label_for(student["risk_score"], main_api.RISK_THRESHOLD))

    def test_page_has_the_threshold_tag_and_legend_placeholders(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="threshold-tag"', html)
        self.assertIn('id="risk-legend"', html)

    def test_pdfs_print_the_configured_levels(self):
        students = main_api.get_group_dashboard_data("301-A")
        group_text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(build_group_report("301-A", students, 90))).pages)
        student_text = "\n".join(p.extract_text() for p in PdfReader(
            BytesIO(build_student_report("301-A", students[0], summarize(students), 90))).pages)
        for text in (group_text, student_text):
            self.assertIn("alto desde 90", " ".join(text.split()))


class EndToEndThresholdTests(unittest.TestCase):
    def labels_with(self, threshold):
        script = ("import json, collections, main_api;"
                  "print(json.dumps(collections.Counter(s['risk_label'] for s in main_api.get_group_dashboard_data('301-A'))))")
        env = dict(os.environ, MONGODB_URI="")
        if threshold is None:
            env.pop("RISK_THRESHOLD", None)
        else:
            env["RISK_THRESHOLD"] = str(threshold)
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_lowering_the_threshold_turns_more_students_high_risk(self):
        default, lowered = self.labels_with(None), self.labels_with(1)
        self.assertGreater(lowered.get("high", 0), default.get("high", 0))


if __name__ == "__main__":
    unittest.main()
