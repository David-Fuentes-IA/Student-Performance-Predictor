"""
learning_module/training_pipeline.py

Train -> evaluate on held-out data -> persist (model + model card).
Used by `scripts/train_model.py`, Docker/CI builds and the test suite, so
there is exactly one definition of "how the model is trained".
"""

from datetime import datetime, timezone
from pathlib import Path

import sklearn

from core.logger import get_logger
from learning_module.model_evaluator import ModelEvaluator
from learning_module.model_store import save_model
from learning_module.model_trainer import (
    _SPLIT_SEED,
    _TEST_SIZE,
    ModelTrainer,
    generate_synthetic_training_set,
    split_dataset,
)

logger = get_logger(__name__)

DATA_SEED = 7
N_SAMPLES = 600
FEATURES = ["average_grade", "grade_trend", "attendance_pct", "participation_score"]


def run_training(directory: Path | None = None) -> dict:
    """Train the Random Forest, evaluate it on the held-out split, save it. Returns the card."""
    X, y = generate_synthetic_training_set(n_samples=N_SAMPLES, seed=DATA_SEED)
    X_train, X_test, y_train, y_test = split_dataset(X, y)
    model = ModelTrainer.train(X_train, y_train)
    metrics = ModelEvaluator.evaluate(model, X_test, y_test)

    card = {
        "model_version": f"random_forest-seed{DATA_SEED}-n{N_SAMPLES}",
        "algorithm": "RandomForestClassifier",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "hyperparameters": {k: model.get_params()[k] for k in ("n_estimators", "max_depth", "random_state")},
        "features": FEATURES,
        "data": {
            "source": "synthetic",
            "n_samples": N_SAMPLES,
            "data_seed": DATA_SEED,
            "n_train": len(X_train),
            "n_test": len(X_test),
            "test_size": _TEST_SIZE,
            "split_seed": _SPLIT_SEED,
        },
        "metrics_on_holdout": metrics,
    }
    save_model(model, card, directory)
    return card
