"""
learning_module/model_store.py

Persists the trained model and its model card, and loads them back.

Design note (traceability: §11.1 model loading; "Train or load model", §9):
    The application never trains at startup. `scripts/train_model.py`
    produces `risk_model.joblib` (the model, NOT versioned in git) and
    `model_card.json` (how it was trained and how it scored, versioned).
    If either file is missing or unreadable the app fails fast with a clear
    ModelLoadError instead of silently retraining or serving bad scores.
    Only files produced by our own training script are ever loaded
    (joblib uses pickle).
"""

import json
from pathlib import Path

import joblib

from core import config
from core.exception_handler import ModelLoadError
from core.logger import get_logger

logger = get_logger(__name__)

MODEL_FILENAME = "risk_model.joblib"
CARD_FILENAME = "model_card.json"
_TRAIN_HINT = "Run `python scripts/train_model.py` to generate it."


def save_model(model, card: dict, directory: Path | None = None) -> Path:
    directory = Path(directory) if directory else config.model_dir()
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, directory / MODEL_FILENAME)
    (directory / CARD_FILENAME).write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    logger.info("Model saved to %s (version %s)", directory, card.get("model_version"))
    return directory


def load_model(directory: Path | None = None):
    """Return (model, model_card). Raises ModelLoadError with an actionable message."""
    directory = Path(directory) if directory else config.model_dir()
    model_path, card_path = directory / MODEL_FILENAME, directory / CARD_FILENAME

    for path in (model_path, card_path):
        if not path.is_file():
            raise ModelLoadError(
                f"required model artifact not found: {path}. {_TRAIN_HINT}",
                user_message=f"The prediction model is not available ({path.name} is missing). {_TRAIN_HINT}",
            )
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
        model = joblib.load(model_path)
    except Exception as exc:  # noqa: BLE001 - any unreadable artifact means "cannot serve predictions"
        raise ModelLoadError(
            f"could not read model artifacts in {directory}: {type(exc).__name__}: {exc}. {_TRAIN_HINT}",
            user_message=f"The prediction model could not be loaded (corrupt files). {_TRAIN_HINT}",
        ) from exc

    if not hasattr(model, "predict_proba") or "model_version" not in card or "engine_type" not in card:
        raise ModelLoadError(
            f"model artifacts in {directory} are not a valid classifier + card. {_TRAIN_HINT}",
            user_message=f"The prediction model files are invalid. {_TRAIN_HINT}",
        )
    logger.info("Model loaded from %s (version %s)", directory, card["model_version"])
    return model, card
