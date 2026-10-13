"""
data_access/repository_factory.py

Factory (section 5): picks the concrete IAcademicDataRepository.

    - MONGODB_URI configured  -> MongoAcademicRepository (Atlas / local Mongo)
    - not configured          -> InMemoryAcademicRepository (zero-setup demo)

The composition root (main_api.py) calls `build_repository()` and keeps
depending only on the interface, so nothing else in the system changes
when the data source does (FR-8, NFR-3).
"""

from core import config
from core.exception_handler import DataAccessError
from core.logger import get_logger
from data_access.student_repository import IAcademicDataRepository, InMemoryAcademicRepository

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
        logger.warning(
            "MongoDB unavailable (%s) - falling back to the in-memory demo repository.", exc
        )
        return InMemoryAcademicRepository()
