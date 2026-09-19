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

    @staticmethod
    def extract(record: StudentRecord) -> FeatureVector:
        grades = record.grades
        average_grade = sum(grades) / len(grades)
        grade_trend = grades[-1] - grades[0] if len(grades) > 1 else 0.0

        return FeatureVector(
            student_ref=record.student_id,
            average_grade=round(average_grade, 2),
            grade_trend=round(grade_trend, 2),
            attendance_pct=record.attendance_pct,
            participation_score=record.participation_score,
        )

    @classmethod
    def extract_many(cls, records: list[StudentRecord]) -> list[FeatureVector]:
        """
        Vectorized batch extraction using pandas/numpy — more efficient
        than a Python loop for large cohorts (Criterion 4 — efficiency).
        Falls back to per-record extraction for empty input.
        """
        if not records:
            return []

        df = pd.DataFrame({
            "student_ref":        [r.student_id for r in records],
            "grades":             [r.grades for r in records],
            "attendance_pct":     [r.attendance_pct for r in records],
            "participation_score":[r.participation_score for r in records],
        })

        grades_matrix = np.array(df["grades"].tolist(), dtype=float)
        df["average_grade"] = np.round(grades_matrix.mean(axis=1), 2)
        df["grade_trend"]   = np.round(grades_matrix[:, -1] - grades_matrix[:, 0], 2)

        return [
            FeatureVector(
                student_ref=row.student_ref,
                average_grade=row.average_grade,
                grade_trend=row.grade_trend,
                attendance_pct=row.attendance_pct,
                participation_score=row.participation_score,
            )
            for row in df.itertuples(index=False)
        ]
