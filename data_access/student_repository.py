"""
data_access/student_repository.py

Design note (traceability: DIP, §4; FR-3; IAcademicDataRepository, §6):
    `IAcademicDataRepository` is the abstraction the rest of the system
    depends on. Nothing outside this file ever imports
    `InMemoryAcademicRepository` directly by name in business logic code -
    everything talks to the interface. That is how the database decision
    changed from the design document's PostgreSQL + SQLAlchemy to MongoDB:
    one new class (`MongoAcademicRepository`, data_access/mongo_repository.py)
    and the factory (repository_factory.py), with no change anywhere else.

    `InMemoryAcademicRepository` is the demo mode used when no database is
    configured. It holds three fixed groups of synthetic students - nothing
    here is a real student.
"""

import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.exception_handler import DataAccessError, GroupNotFoundError
from core.logger import get_logger
from data_access.synthetic_students import simulate_students

logger = get_logger(__name__)

# The only groups the in-memory demo repository knows about.
DEMO_GROUP_IDS = ("301-A", "301-B", "301-C")


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

    backend = "unknown"  # "mongodb" | "memory"; surfaced by /health and the demo banner

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

    def save_predictions(self, predictions: list[tuple[str, float, str]]) -> None:
        """Persist several (student_ref, risk_score, risk_label) at once. The default makes one call per
        prediction; repositories that can batch (MongoDB) override it with a single round trip."""
        for student_ref, risk_score, risk_label in predictions:
            self.save_prediction(student_ref, risk_score, risk_label)

    @abstractmethod
    def list_groups(self) -> list[dict]:
        """Groups available to analyse: [{"group_id", "name", "student_count"}, ...]."""
        raise NotImplementedError


class InMemoryAcademicRepository(IAcademicDataRepository):
    """
    Demo implementation of IAcademicDataRepository.

    Holds a small in-memory dataset of synthetic students per group, so the
    rest of the pipeline (validation -> features -> prediction -> report)
    can be exercised without a database. The real implementation of the same
    interface is `MongoAcademicRepository` (MongoDB, local or Atlas).
    """

    backend = "memory"

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._groups: dict[str, StudentGroup] = {}
        self._prediction_log: list[dict] = []

    def _generate_group(self, group_id: str, size: int = 12) -> StudentGroup:
        """Simulated class (noisy, see data_access/synthetic_students.py), same for the same seed."""
        simulated = simulate_students(size, seed=self._seed + zlib.crc32(group_id.encode()) % 10_000)
        students = [
            StudentRecord(
                student_id=f"{group_id}-{i:03d}",
                name=f"Demo Student {i + 1}",
                grades=s.grades,
                attendance_pct=s.attendance_pct,
                participation_score=s.participation_score,
            )
            for i, s in enumerate(simulated)
        ]
        return StudentGroup(group_id=group_id, students=students)

    def get_student(self, student_id: str) -> StudentRecord:
        group_id = student_id.rsplit("-", 1)[0] if "-" in student_id else student_id
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
        if group_id in self._groups:
            return self._groups[group_id]
        if group_id not in DEMO_GROUP_IDS:
            raise GroupNotFoundError(
                f"group '{group_id}' is not a demo group",
                user_message=f"El grupo '{group_id}' no existe.",
            )
        logger.info("Generating synthetic data for demo group '%s'", group_id)
        self._groups[group_id] = self._generate_group(group_id)
        return self._groups[group_id]

    def list_groups(self) -> list[dict]:
        return [
            {"group_id": g, "name": f"Grupo demo {g}", "student_count": len(self.get_group(g).students)}
            for g in DEMO_GROUP_IDS
        ]
