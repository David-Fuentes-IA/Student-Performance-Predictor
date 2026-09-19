"""
core/exception_handler.py

Custom exception hierarchy for the whole project, plus a decorator that
turns any of these exceptions into a clean, teacher-facing message instead
of a raw Python traceback.

Design note (traceability: Fail-Fast, §4; FR-2):
    Every layer raises the MOST SPECIFIC exception below as soon as it
    finds a problem, instead of letting bad data travel further into the
    pipeline. That is the Fail-Fast principle in code, not just in prose.
"""

import functools
from core.logger import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for every error this application raises on purpose."""

    def __init__(self, message: str, *, user_message: str | None = None):
        super().__init__(message)
        # `user_message` is what the Presentation layer is allowed to show.
        # It never leaks internal details (file paths, stack traces, etc.).
        self.user_message = user_message or message


class ValidationError(AppError):
    """
    Raised by data_pipeline.fail_fast_validator when academic data fails a
    sanity check (out-of-range grade, negative attendance, missing field).
    This is the exception behind FR-2.
    """


class DataAccessError(AppError):
    """Raised when the repository layer cannot read/find academic data."""


class PredictionEngineError(AppError):
    """Raised when the AI/Prediction layer fails to produce a risk score."""


def handle_errors(func):
    """
    Decorator for orchestration-level functions (e.g. main_api.py).

    - Known AppError subclasses are logged with their real message and
      re-raised with only `user_message` intended for display.
    - Anything unexpected is logged with full detail internally, but the
      caller only ever sees a generic, safe message - we never want a
      stack trace leaking into a teacher-facing report.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AppError as exc:
            logger.warning("%s raised %s: %s", func.__name__, type(exc).__name__, exc)
            raise
        except Exception as exc:  # noqa: BLE001 - intentional final safety net
            logger.error("Unexpected error in %s: %s", func.__name__, exc, exc_info=True)
            raise AppError(
                f"Unexpected error in {func.__name__}: {exc}",
                user_message="Something went wrong while processing this request. "
                "Please try again or contact IT support if it persists.",
            ) from exc

    return wrapper
