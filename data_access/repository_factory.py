"""
data_access/repository_factory.py

Factory (section 5): picks the concrete IAcademicDataRepository.

    - MONGODB_URI configured, reachable      -> MongoAcademicRepository (Atlas / local Mongo)
    - MONGODB_URI configured, NOT reachable  -> start-up fails (Fail-Fast), unless ALLOW_DEMO_FALLBACK=true
    - MONGODB_URI not configured             -> InMemoryAcademicRepository (zero-setup demo)

The composition root (main_api.py) calls `build_repository()` and keeps
depending only on the interface, so nothing else in the system changes
when the data source does (FR-8, NFR-3).
"""

from core import config
from core.exception_handler import DataAccessError
from core.logger import get_logger
from data_access.student_repository import (
    IAcademicDataRepository,
    InMemoryAcademicRepository,
)

logger = get_logger(__name__)


def build_repository() -> IAcademicDataRepository:
    if not config.mongodb_uri():
        logger.info("MONGODB_URI not set - using the in-memory demo repository.")
        return InMemoryAcademicRepository()

    # Imported lazily so the in-memory path does not need pymongo at all.
    from data_access.mongo_repository import MongoAcademicRepository

    try:
        repository = MongoAcademicRepository()
        logger.info("Using MongoDB repository (database '%s').", config.mongodb_db_name())
        return repository
    except DataAccessError as exc:
        if config.allow_demo_fallback():
            logger.warning(
                "MongoDB unavailable (%s) - falling back to the in-memory demo repository "
                "(ALLOW_DEMO_FALLBACK=true). The data shown are NOT the real ones.", exc
            )
            return InMemoryAcademicRepository()
        # Fail fast: a configured database that does not answer must stop the application, not be
        # replaced by fake students for the whole life of the process. The container restarts and retries.
        logger.error("MongoDB is configured but unreachable: %s", exc)
        raise DataAccessError(
            f"MONGODB_URI is set but the database is unreachable at start-up: {exc}. Start MongoDB or fix "
            "MONGODB_URI; for development only, ALLOW_DEMO_FALLBACK=true runs on demo data instead.",
            user_message=(
                "The database is configured but not reachable. Start MongoDB or fix MONGODB_URI; "
                "to run on demo data anyway (development only) set ALLOW_DEMO_FALLBACK=true."
            ),
        ) from exc
