"""
data_pipeline/fail_fast_validator.py

Design note (traceability: Fail-Fast, §4; FR-2; validation matrix, §8.0):
    This is the ML-pipeline-level validation gate: it checks the data
    itself (ranges, missing values) before it becomes a feature vector.
    It is deliberately a different responsibility from the input checks
    that happen in main_api.py (which validate the *request*, e.g. "is
    this a real group id") and in the Business Logic layer - each layer
    validates a different thing, per the validation matrix in the design
    doc. This module only validates records that have already been
    retrieved from the repository.
"""

from data_access.student_repository import StudentRecord
from core.exception_handler import ValidationError

_GRADE_RANGE = (0, 100)
_ATTENDANCE_RANGE = (0, 100)
_PARTICIPATION_RANGE = (0, 100)


class FailFastValidator:
    """Stateless validator - one method, one job (SRP)."""

    @staticmethod
    def validate(record: StudentRecord) -> None:
        """
        Raise ValidationError on the FIRST problem found. This function
        never tries to "fix" bad data (e.g. clamping an out-of-range
        grade) - Fail-Fast means reject and flag for review, not silently
        guess what the correct value should have been.
        """
        if not record.grades:
            raise ValidationError(
                f"student '{record.student_id}' has no grades recorded",
                user_message=f"Record for {record.student_id} is incomplete (no grades) and was skipped.",
            )

        low, high = _GRADE_RANGE
        for grade in record.grades:
            if grade is None or not (low <= grade <= high):
                raise ValidationError(
                    f"student '{record.student_id}' has an invalid grade: {grade}",
                    user_message=f"Record for {record.student_id} has an invalid grade and was skipped.",
                )

        a_low, a_high = _ATTENDANCE_RANGE
        if record.attendance_pct is None or not (a_low <= record.attendance_pct <= a_high):
            raise ValidationError(
                f"student '{record.student_id}' has invalid attendance: {record.attendance_pct}",
                user_message=f"Record for {record.student_id} has invalid attendance and was skipped.",
            )

        p_low, p_high = _PARTICIPATION_RANGE
        if record.participation_score is None or not (p_low <= record.participation_score <= p_high):
            raise ValidationError(
                f"student '{record.student_id}' has invalid participation score: {record.participation_score}",
                user_message=f"Record for {record.student_id} has an invalid participation score and was skipped.",
            )
