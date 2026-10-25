"""System: the model quality gate (what CI runs) and the consistency of the model evidence.

The gate trains the configured model from scratch and measures it on the independent
evaluation workbook. If a change makes the model worse (or suspiciously perfect) it fails.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core import config
from learning_module.model_validation import check_quality_gate

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "model"


def run_script(*args):
    return subprocess.run([sys.executable, "scripts/evaluate_models.py", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=300)


class QualityGateTests(unittest.TestCase):
    def test_the_configured_model_passes_the_gate_on_unseen_data(self):
        result = run_script("--gate")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("quality gate passed", result.stdout)

    def test_the_gate_really_fails_for_a_degraded_model(self):
        self.assertNotEqual(check_quality_gate({"accuracy": 0.6, "precision": 0.5, "recall": 0.3, "f1": 0.37, "f2": 0.3}), [])


class EvidenceReproducibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.result = run_script("--out", cls.tmp.name)
        cls.out = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_script_writes_every_deliverable(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        for name in ("metrics.json", "comparison.md", "errors.csv", "confusion_matrices.png", "cv_metrics.png",
                     "operating_points.png"):
            self.assertTrue((self.out / name).stat().st_size > 0, name)

    def test_the_results_are_internally_consistent(self):
        metrics = json.loads((self.out / "metrics.json").read_text(encoding="utf-8"))
        selected = metrics["decision"]["selected"]
        confusion = metrics["independent_test"][selected]["confusion"]
        self.assertEqual(sum(confusion.values()), metrics["data"]["independent"]["students"])
        self.assertEqual(metrics["error_analysis"]["errors_total"], confusion["fn"] + confusion["fp"])
        errors = (self.out / "errors.csv").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(errors) - 1, confusion["fn"] + confusion["fp"])  # every error is listed
        self.assertEqual(metrics["quality_gate"]["violations"], [])

    def test_the_perfect_score_problem_is_gone(self):
        metrics = json.loads((self.out / "metrics.json").read_text(encoding="utf-8"))
        for model in metrics["independent_test"].values():
            self.assertLess(model["metrics"]["recall"], 0.99)
            self.assertGreater(model["confusion"]["fn"], 0)


class CommittedEvidenceMatchesTheCodeTests(unittest.TestCase):
    """The documents must not claim a model the application does not use."""

    def test_the_validated_model_is_the_configured_default(self):
        metrics = json.loads((EVIDENCE / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["decision"]["selected"], config.DEFAULT_MODEL_TYPE)

    def test_the_committed_model_card_names_the_same_model(self):
        card = json.loads((ROOT / "models" / "model_card.json").read_text(encoding="utf-8"))
        self.assertEqual(card["engine_type"], config.DEFAULT_MODEL_TYPE)


if __name__ == "__main__":
    unittest.main()
