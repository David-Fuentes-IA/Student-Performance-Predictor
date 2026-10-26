"""System: what happens when the AI module or its configuration is unusable at startup.

Each case starts the real application in a fresh process (`import main_api`) - exactly what
`python web_app.py` does first - and checks that it stops with a message that tells the
operator what to fix, instead of serving wrong predictions.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from learning_module.model_store import MODEL_FILENAME
from learning_module.training_pipeline import run_training

ROOT = Path(__file__).resolve().parents[2]


def start_app(**env_overrides):
    env = dict(os.environ, MONGODB_URI="")
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", "import main_api"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)


class StartupFailureTests(unittest.TestCase):
    def test_missing_model_stops_the_app_and_names_the_fix(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            result = start_app(MODEL_DIR=empty_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ModelLoadError", result.stderr)
        self.assertIn("scripts/train_model.py", result.stderr)

    def test_corrupted_model_file_stops_the_app(self):
        with tempfile.TemporaryDirectory() as model_dir:
            run_training(Path(model_dir))
            (Path(model_dir) / MODEL_FILENAME).write_bytes(b"this is not a model")
            result = start_app(MODEL_DIR=model_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ModelLoadError", result.stderr)

    def test_invalid_risk_threshold_stops_the_app_and_names_the_variable(self):
        for bad in ("abc", "-5", "250"):
            with self.subTest(bad):
                result = start_app(RISK_THRESHOLD=bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RISK_THRESHOLD", result.stderr)

    def test_invalid_passing_grade_stops_the_app_and_names_the_variable(self):
        result = start_app(PASSING_GRADE="seis")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PASSING_GRADE", result.stderr)

    def test_a_configured_but_unreachable_database_stops_the_app_instead_of_serving_fake_data(self):
        # Found in Docker: the container restarted while MongoDB was down, fell back to demo data
        # and kept serving fake students for good, even after MongoDB came back.
        result = start_app(MONGODB_URI="mongodb://127.0.0.1:1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DataAccessError", result.stderr)
        self.assertIn("ALLOW_DEMO_FALLBACK", result.stderr)

    def test_demo_fallback_must_be_requested_explicitly(self):
        result = start_app(MONGODB_URI="mongodb://127.0.0.1:1", ALLOW_DEMO_FALLBACK="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOT the real ones", result.stdout + result.stderr)

    def test_a_valid_configuration_starts_normally(self):
        result = start_app()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
