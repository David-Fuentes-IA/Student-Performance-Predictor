"""
core/logger.py

Centralized logging for the whole project.

Design note (traceability: DR-1, NFR-2):
    The project brief requires that Personally Identifiable Information (PII)
    never gets written to logs. Every module in this project is expected to
    import `get_logger()` from here instead of configuring its own logging,
    and to pass log data through `sanitize(...)` before writing anything that
    could contain student-identifying fields (name, raw student_id, etc.).

    This is intentionally the ONLY place logging is configured, so the whole
    application has one consistent log format (Single Responsibility: this
    module's one job is "how do we log").
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

_LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

# Fields that must never appear in a log line. Anything with one of these
# keys gets replaced with a redaction marker before it is logged.
_SENSITIVE_KEYS = {"name", "student_name", "full_name", "email", "curp"}

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _configure_root_logger(level: int = logging.DEBUG) -> None:
    """Configure the root logger exactly once (idempotent)."""
    global _configured
    if _configured:
        return

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    log_file = _LOGS_DIR / f"spp_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root = logging.getLogger("student_predictor")
    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)
    root.propagate = False

    _configured = True


def get_logger(module_name: str) -> logging.Logger:
    """
    Return a namespaced logger for a module, e.g. get_logger(__name__).

    All loggers are children of "student_predictor" so log level and
    formatting stay consistent across the whole codebase.
    """
    _configure_root_logger()
    return logging.getLogger(f"student_predictor.{module_name}")


def sanitize(data: dict) -> dict:
    """
    Return a copy of `data` with any sensitive keys redacted.

    Use this before logging any dict that might carry student-identifying
    fields. This does NOT try to be a full PII scrubber (that's a much
    bigger problem) - it enforces the specific fields this project knows
    about, which is what DR-1 asks for at the architecture level.
    """
    clean = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            clean[key] = "[REDACTED]"
        else:
            clean[key] = value
    return clean
