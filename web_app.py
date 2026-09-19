"""
web_app.py

Presentation-layer entry point for the dashboard (Figure 1, Report Viewer).

This calls main_api.get_group_dashboard_data(...) directly instead of
spawning main_api.py as a subprocess and parsing its printed report:
- Calling the function in-process means the model trains once, when this
  process starts, not on every page load (Code Efficiency, NFR-1).
- Reading structured data (name, risk_score, risk_label) instead of
  parsing text means the "Monitor" (medium-risk) tier is handled
  correctly - the previous string-parsing version only recognized
  "HIGH RISK" and silently miscounted every medium-risk student as
  "on track".
"""

from flask import Flask, render_template

from core.exception_handler import AppError
from core.logger import get_logger
from main_api import get_group_dashboard_data

logger = get_logger(__name__)

app = Flask(__name__)

DEFAULT_GROUP_ID = "301-A"

# Spanish display labels for the three risk tiers used throughout the
# rest of the codebase ("high" | "medium" | "low" - see risk_predictor.py).
_STATUS_LABELS = {
    "high": "Alto Riesgo",
    "medium": "En Observacion",
    "low": "Buen Camino",
}
_BADGE_CLASS = {
    "high": "bg-red",
    "medium": "bg-yellow",
    "low": "bg-green",
}


@app.route("/")
def index():
    try:
        students_data = get_group_dashboard_data(DEFAULT_GROUP_ID)
    except AppError as exc:
        # Never show a raw traceback to the teacher - render the page
        # with an empty roster and a clear, safe error message instead.
        logger.warning("Dashboard could not load group %s: %s", DEFAULT_GROUP_ID, exc)
        return render_template(
            "index.html",
            group_id=DEFAULT_GROUP_ID,
            error_message=exc.user_message,
            students=[],
            total=0,
            high_risk=0,
            monitor=0,
            on_track=0,
        )

    students = [
        {
            "name": s["name"],
            "score": s["risk_score"],
            "status": _STATUS_LABELS[s["risk_label"]],
            "badge_class": _BADGE_CLASS[s["risk_label"]],
        }
        for s in students_data
    ]

    return render_template(
        "index.html",
        group_id=DEFAULT_GROUP_ID,
        error_message=None,
        students=students,
        total=len(students),
        high_risk=sum(1 for s in students_data if s["risk_label"] == "high"),
        monitor=sum(1 for s in students_data if s["risk_label"] == "medium"),
        on_track=sum(1 for s in students_data if s["risk_label"] == "low"),
    )


if __name__ == "__main__":
    app.run(debug=True)
