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

DEFAULT_DB_NAME = "student_predictor"


def mongodb_uri() -> str:
    """MongoDB connection string. Empty string means 'not configured'."""
    return os.environ.get("MONGODB_URI", "").strip()


def mongodb_db_name() -> str:
    return os.environ.get("MONGODB_DB", "").strip() or DEFAULT_DB_NAME


def admin_password() -> str:
    """Optional shared password for the admin web interface ('' = open)."""
    return os.environ.get("ADMIN_PASSWORD", "").strip()


def running_on_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))
