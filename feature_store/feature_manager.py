"""
feature_store/feature_manager.py

Design note (traceability: DR-1 Anonymization; Feature Pipeline, §6):
    This is the boundary where identifiable data stops and anonymized
    data starts. `FeatureVector` intentionally has NO `name` field - only
    `student_ref`, which is the same student_id used elsewhere but is
    treated as an opaque token from this point forward. The AI/Prediction
    layer only ever sees FeatureVectors, never a StudentRecord.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from data_access.student_repository import StudentRecord


@dataclass(frozen=True)
class FeatureVector:
    """Numeric, model-ready representation of one student. No PII."""
    student_ref: str
    average_grade: float       # 0-100
    grade_trend: float         # last grade minus first grade; negative = declining
    attendance_pct: float      # 0-100
    participation_score: float  # 0-100

    def as_model_input(self) -> list[float]:
        """Ordered numeric list, the shape scikit-learn models expect."""
        return [self.average_grade, self.grade_trend, self.attendance_pct, self.participation_score]


class FeatureManager:
    """Turns validated StudentRecords into FeatureVectors (one job: SRP)."""

    @classmethod
    def extract(cls, record: StudentRecord) -> FeatureVector:
        """Single-record extraction; shares the batch implementation so both always agree."""
        return cls.extract_many([record])[0]

    @classmethod
    def extract_many(cls, records: list[StudentRecord]) -> list[FeatureVector]:
        """
        Vectorized feature extraction for any number of records (the single
        source of truth: `extract` delegates here).

        Students may have a different number of grades (Excel imports), so the
        grades are flattened into one array and reduced per student with
        `np.add.reduceat` instead of building a rectangular matrix. Records
        must already be validated (at least one grade each).
        """
        if not records:
            return []

        lengths = np.fromiter((len(r.grades) for r in records), dtype=np.int64, count=len(records))
        if (lengths == 0).any():
            raise ValueError("extract_many requires validated records with at least one grade")

        flat = np.concatenate([np.asarray(r.grades, dtype=float) for r in records])
        starts = np.concatenate(([0], np.cumsum(lengths)[:-1]))
        averages = np.add.reduceat(flat, starts) / lengths
        trends = flat[starts + lengths - 1] - flat[starts]

        frame = pd.DataFrame({
            "student_ref": [r.student_id for r in records],
            "average_grade": averages,
            "grade_trend": trends,
            "attendance_pct": [r.attendance_pct for r in records],
            "participation_score": [r.participation_score for r in records],
        })

        # Python's round() keeps the results identical to `extract`.
        return [
            FeatureVector(
                student_ref=row.student_ref,
                average_grade=round(float(row.average_grade), 2),
                grade_trend=round(float(row.grade_trend), 2),
                attendance_pct=row.attendance_pct,
                participation_score=row.participation_score,
            )
            for row in frame.itertuples(index=False)
        ]
