"""
core/risk_levels.py

Single definition of the risk levels (low / medium / high) so the prediction
engines, the dashboard legend and the PDF reports always agree.

    high    : score >= threshold                  (the same line that fires the Risk Alert, FR-7)
    medium  : score >= min(MEDIUM_FLOOR, threshold) and below the threshold
    low     : everything below the medium floor

The threshold comes from RISK_THRESHOLD (core/config.py, default 75). When the
threshold is at or below MEDIUM_FLOOR there is no "medium" band.
"""

MEDIUM_FLOOR = 40.0


def risk_bands(threshold: float) -> tuple[float, float]:
    """Return (medium_floor, high_floor) for the given alert threshold."""
    return min(MEDIUM_FLOOR, threshold), threshold


def label_for(score: float, threshold: float) -> str:
    medium_floor, high_floor = risk_bands(threshold)
    if score >= high_floor:
        return "high"
    if score >= medium_floor:
        return "medium"
    return "low"
