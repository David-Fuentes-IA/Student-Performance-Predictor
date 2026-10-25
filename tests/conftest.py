"""Test environment, set up BEFORE any test module imports main_api.

- Demo (in-memory) mode: an explicit empty MONGODB_URI wins over the developer's
  .env (see core/config.py). Mongo integration tests use MONGODB_TEST_URI instead.
- A freshly trained model in a temp dir: the app never trains at startup, so the
  suite generates its own artifacts (and never touches ./models).
"""
import atexit
import os
import shutil
import tempfile

os.environ["MONGODB_URI"] = ""
os.environ.pop("RISK_THRESHOLD", None)

_MODEL_DIR = tempfile.mkdtemp(prefix="spp_test_models_")
atexit.register(shutil.rmtree, _MODEL_DIR, ignore_errors=True)
os.environ["MODEL_DIR"] = _MODEL_DIR

from learning_module.training_pipeline import run_training  # noqa: E402

run_training(_MODEL_DIR)
