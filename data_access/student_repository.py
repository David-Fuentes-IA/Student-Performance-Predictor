"""
data_access/student_repository.py

Design note (traceability: DIP, §4; FR-3; IAcademicDataRepository, §6):
    `IAcademicDataRepository` is the abstraction the rest of the system
    depends on. Nothing outside this file ever imports
    `InMemoryAcademicRepository` directly by name in business logic code -
    everything talks to the interface, so swapping this for a real
    SQLAlchemy + PostgreSQL implementation later (per the Technology Stack)
    means writing ONE new class here and changing zero lines anywhere else.

    `InMemoryAcademicRepository` exists so this project runs end to end
    without a real institutional database, which is out of scope for this
    milestone. It generates small, clearly-fake sample data - nothing here
    is a real student.
"""

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.exception_handler import DataAccessError
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class StudentRecord:
    """
    Raw academic record as it exists in the Data Access layer.

    NOTE: `name` and `student_id` are real identifiers and are allowed to
    exist here and in the Presentation layer. They are stripped out before
    the record reaches the AI/Prediction layer (see feature_store), which
    is where DR-1 actually applies.
    """
    student_id: str
    name: str
    grades: list[float]          # 0-100 scale
    attendance_pct: float        # 0-100
    participation_score: float   # 0-100


@dataclass(frozen=True)
class StudentGroup:
    group_id: str
    students: list[StudentRecord] = field(default_factory=list)


class IAcademicDataRepository(ABC):
    """Abstraction the Business Logic / Data Pipeline layers depend on."""

    @abstractmethod
    def get_student(self, student_id: str) -> StudentRecord:
        raise NotImplementedError

    @abstractmethod
    def get_group(self, group_id: str) -> StudentGroup:
        raise NotImplementedError

    @abstractmethod
    def save_prediction(self, student_ref: str, risk_score: float, risk_label: str) -> None:
        """Persist a prediction result (Step 8 of the AI Workflow, §8)."""
        raise NotImplementedError


class InMemoryAcademicRepository(IAcademicDataRepository):
    """
    Demo implementation of IAcademicDataRepository.

    Holds a small in-memory dataset of synthetic students per group, so the
    rest of the pipeline (validation -> features -> prediction -> report)
    can be exercised without a real academic database. A production
    implementation would replace this class with one built on SQLAlchemy
    over PostgreSQL, implementing the same interface.
    """

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._groups: dict[str, StudentGroup] = {}
        self._prediction_log: list[dict] = []

    def _generate_group(self, group_id: str, size: int = 12) -> StudentGroup:
        students = []
        for i in range(size):
            # A handful of students are deliberately generated as
            # "at risk" (low grades/attendance) so the demo run in
            # main_api.py actually triggers a Risk Alert.
            at_risk = i < max(1, size // 6)
            if at_risk:
                grades = [self._rng.uniform(30, 55) for _ in range(4)]
                attendance = self._rng.uniform(40, 65)
                participation = self._rng.uniform(20, 50)
            else:
                grades = [self._rng.uniform(65, 98) for _ in range(4)]
                attendance = self._rng.uniform(75, 100)
                participation = self._rng.uniform(60, 100)

            students.append(
                StudentRecord(
                    student_id=f"{group_id}-{i:03d}",
                    name=f"Demo Student {i + 1}",
                    grades=[round(g, 1) for g in grades],
                    attendance_pct=round(attendance, 1),
                    participation_score=round(participation, 1),
                )
            )
        return StudentGroup(group_id=group_id, students=students)

    def get_student(self, student_id: str) -> StudentRecord:
        group_id = student_id.split("-")[0] if "-" in student_id else student_id
        group = self.get_group(group_id)
        for student in group.students:
            if student.student_id == student_id:
                return student
        raise DataAccessError(
            f"student_id '{student_id}' not found in group '{group_id}'",
            user_message="That student could not be found.",
        )

    def save_prediction(self, student_ref: str, risk_score: float, risk_label: str) -> None:
        self._prediction_log.append({
            "student_ref": student_ref,
            "risk_score": risk_score,
            "risk_label": risk_label,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.debug("Prediction saved: %s → %.1f (%s)", student_ref, risk_score, risk_label)

    def get_prediction_log(self) -> list[dict]:
        return list(self._prediction_log)

    def get_group(self, group_id: str) -> StudentGroup:
        if not group_id or not isinstance(group_id, str):
            raise DataAccessError(
                "get_group called with an empty/invalid group_id",
                user_message="Please provide a valid group ID.",
            )
        if group_id not in self._groups:
            logger.info("Generating synthetic data for new group '%s'", group_id)
            self._groups[group_id] = self._generate_group(group_id)
        return self._groups[group_id]
