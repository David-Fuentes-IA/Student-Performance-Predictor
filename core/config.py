"""
core/config.py

Single place where environment-based configuration is read (Single
Responsibility: "where do settings come from").

Design note (traceability: NFR-2 Security, DIP):
    Credentials (the MongoDB Atlas connection string, the optional admin
    password) are NEVER written in source code or committed to Git. They
    come from environment variables:
      - locally: a `.env` file in the project root (listed in .gitignore)
      - on Vercel: Project Settings -> Environment Variables
    Real environment variables always win over `.env`, so a deployment
    can never be silently overridden by a stale local file.
"""

import os
from pathlib import Path

try:  # python-dotenv is only a convenience for local development
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover - dotenv is listed in requirements.txt
    pass

from core.exception_handler import ValidationError

DEFAULT_DB_NAME = "student_predictor"
DEFAULT_RISK_THRESHOLD = 75.0


def mongodb_uri() -> str:
    """MongoDB connection string. Empty string means 'not configured'."""
    return os.environ.get("MONGODB_URI", "").strip()


def mongodb_db_name() -> str:
    return os.environ.get("MONGODB_DB", "").strip() or DEFAULT_DB_NAME


def admin_password() -> str:
    """Optional shared password for the admin web interface ('' = open)."""
    return os.environ.get("ADMIN_PASSWORD", "").strip()


def model_dir() -> Path:
    """Folder holding risk_model.joblib and model_card.json (MODEL_DIR overrides)."""
    configured = os.environ.get("MODEL_DIR", "").strip()
    return Path(configured) if configured else Path(__file__).resolve().parent.parent / "models"


def risk_threshold() -> float:
    """Score (0-100) at or above which a Risk Alert fires (FR-7). RISK_THRESHOLD overrides 75."""
    raw = os.environ.get("RISK_THRESHOLD", "").strip()
    if not raw:
        return DEFAULT_RISK_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not 0.0 <= value <= 100.0:  # NaN fails this comparison too
        raise ValidationError(
            f"RISK_THRESHOLD={raw!r} is not a number between 0 and 100",
            user_message="RISK_THRESHOLD must be a number between 0 and 100.",
        )
    return value


def running_on_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))
