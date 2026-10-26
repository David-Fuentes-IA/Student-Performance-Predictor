"""
core/risk_levels.py

Single definition of the risk levels (low / medium / high) so the prediction
engines, the alerts, the dashboard legend and the PDF reports always agree.

    high    : the student's average grade is below the passing grade (as a school would say:
              "reprobando", below 6.0 = 60/100)  OR  the model's risk score >= threshold
    medium  : risk score >= min(MEDIUM_FLOOR, threshold)
    low     : everything else

Why both conditions: a student who is already failing is at risk by definition, whatever the
model says; the model adds the students who are still passing but are likely to end the term
with low performance (falling grades, low attendance or participation). On the independent
evaluation set this combined rule catches 71.9 % of the students who end up at risk, against
43.8 % for the model score alone at 75 (docs/evidence/model/README.md).

The threshold comes from RISK_THRESHOLD (default 75) and the passing grade from PASSING_GRADE
(default 60), both in core/config.py.
"""

from core.config import DEFAULT_PASSING_GRADE

MEDIUM_FLOOR = 40.0

FAILING_AVERAGE = "failing_average"
HIGH_PREDICTED_RISK = "high_predicted_risk"


def risk_bands(threshold: float) -> tuple[float, float]:
    """Return (medium_floor, high_floor) of the model score for the given alert threshold."""
    return min(MEDIUM_FLOOR, threshold), threshold


def is_failing(average_grade: float | None, passing_grade: float = DEFAULT_PASSING_GRADE) -> bool:
    return average_grade is not None and average_grade < passing_grade


def alert_reasons(score: float, threshold: float, average_grade: float | None = None,
                  passing_grade: float = DEFAULT_PASSING_GRADE) -> list[str]:
    """Why a student is high risk (empty list = not high risk)."""
    reasons = []
    if is_failing(average_grade, passing_grade):
        reasons.append(FAILING_AVERAGE)
    if score >= threshold:
        reasons.append(HIGH_PREDICTED_RISK)
    return reasons


def label_for(score: float, threshold: float, average_grade: float | None = None,
              passing_grade: float = DEFAULT_PASSING_GRADE) -> str:
    if alert_reasons(score, threshold, average_grade, passing_grade):
        return "high"
    medium_floor, _ = risk_bands(threshold)
    if score >= medium_floor:
        return "medium"
    return "low"
