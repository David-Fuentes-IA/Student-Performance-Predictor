"""
data_pipeline/etl_processor.py

Design note (traceability: Pipeline, §5; §9 Machine-Learning Pipeline):
    This is the "Academic data -> Validate and clean -> Feature
    engineering" portion of the ML pipeline diagram (Figure 8). It is
    built by assembling three independent stages (repository, validator,
    feature manager) rather than one big function, so any stage can be
    swapped or reordered without rewriting the others (Composition over
    Inheritance, §4).

    Records that fail Fail-Fast validation are skipped, not fatal to the
    whole batch: one bad record for one student should not prevent the
    teacher from getting a report for the rest of the group (NFR-5,
    Reliability - applied here at the record level, not just the service
    level).
"""

from data_access.student_repository import IAcademicDataRepository, StudentGroup
from data_pipeline.fail_fast_validator import FailFastValidator
from feature_store.feature_manager import FeatureManager, FeatureVector
from core.exception_handler import ValidationError
from core.logger import get_logger

logger = get_logger(__name__)


class ETLProcessor:
    """Coordinates the load -> validate -> feature-extract stages."""

    def __init__(self, repository: IAcademicDataRepository) -> None:
        # Depends on the IAcademicDataRepository abstraction, not a
        # concrete class (DIP) - any repository implementation works here.
        self._repository = repository
        self._validator = FailFastValidator()

    def process_group(self, group_id: str) -> list[FeatureVector]:
        """
        Extract a group's raw records, validate each one (Fail-Fast),
        and return feature vectors only for the records that passed.
        """
        group: StudentGroup = self._repository.get_group(group_id)

        feature_vectors: list[FeatureVector] = []
        skipped = 0

        for record in group.students:
            try:
                self._validator.validate(record)
            except ValidationError as exc:
                # Log and skip - do not let one bad record block the group.
                logger.warning("Skipping invalid record: %s", exc)
                skipped += 1
                continue

            feature_vectors.append(FeatureManager.extract(record))

        logger.info(
            "ETL complete for group '%s': %d valid, %d skipped",
            group_id, len(feature_vectors), skipped,
        )
        return feature_vectors
