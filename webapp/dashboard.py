"""
webapp/dashboard.py

Teacher dashboard blueprint: HTML page, JSON data, PDF reports and /health.
Group data comes from main_api, which reads the same repository the admin
panel writes to.
"""

import re
from io import BytesIO

from flask import Blueprint, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

import main_api
from main_api import generate_group_risk_report, get_group_dashboard_data
from presentation.pdf_reports import build_group_report, build_student_report
from presentation.report_data import summarize

dashboard_bp = Blueprint("dashboard", __name__)

_GROUP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
_DEMO_NOTICE = "Modo demo: sin conexión a la base de datos"


def valid_group(group_id: str) -> bool:
    return bool(_GROUP_ID.fullmatch(group_id))


def load_group(group_id: str):
    if not valid_group(group_id):
        return None
    return get_group_dashboard_data(group_id)


def _mode() -> str:
    return "demo" if main_api.get_runtime_status()["backend"] == "memory" else "database"


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def pdf_response(data: bytes, filename: str):
    response = send_file(BytesIO(data), mimetype="application/pdf", as_attachment=True,
                         download_name=filename, max_age=0)
    return _no_store(response)


@dashboard_bp.get("/")
def index():
    group_id = request.args.get("group", "")
    if group_id and not valid_group(group_id):
        return render_template("index.html", group_id="", initial_error="Identificador de grupo inválido."), 400
    return render_template("index.html", group_id=group_id, initial_error=None)


@dashboard_bp.get("/health")
def health():
    """Liveness + readiness without leaking details (used by Docker/Kubernetes)."""
    status = main_api.get_runtime_status()
    database = False
    if status["backend"] == "mongodb":
        try:
            main_api.get_repository().db.command("ping")
            database = True
        except Exception:  # noqa: BLE001 - any failure just means "not reachable"
            database = False
    healthy = status["model_loaded"] and database
    return _no_store(jsonify(
        status="ok" if healthy else "degraded",
        mode=_mode(),
        model_loaded=status["model_loaded"],
        database=database,
    ))


@dashboard_bp.get("/api/groups")
def list_groups():
    return _no_store(jsonify(groups=main_api.get_repository().list_groups(), mode=_mode(),
                             notice=_DEMO_NOTICE if _mode() == "demo" else None))


@dashboard_bp.get("/api/groups/<group_id>")
def group_data(group_id):
    students = load_group(group_id)
    if students is None:
        return jsonify(error="Identificador de grupo inválido."), 400
    return _no_store(jsonify(group_id=group_id, students=students, summary=summarize(students),
                             model_demo=True, mode=_mode()))


@dashboard_bp.get("/api/v1/groups/<group_id>/risk-report")
def text_report(group_id):
    if not valid_group(group_id):
        return jsonify(error="Identificador de grupo inválido."), 400
    return jsonify(group_id=group_id, report=generate_group_risk_report(group_id))


@dashboard_bp.get("/reports/groups/<group_id>.pdf")
def group_pdf(group_id):
    students = load_group(group_id)
    if students is None:
        return jsonify(error="Identificador de grupo inválido."), 400
    return pdf_response(build_group_report(group_id, students), f"reporte_grupo_{group_id}.pdf")


@dashboard_bp.get("/reports/groups/<group_id>/students/<path:student_id>.pdf")
def student_pdf(group_id, student_id):
    if not valid_group(group_id) or not student_id or len(student_id) > 128:
        return jsonify(error="Identificador inválido."), 400
    students = load_group(group_id)
    student = next((s for s in students if s["student_id"] == student_id), None)
    if student is None:
        return jsonify(error="El alumno no pertenece a este grupo."), 404
    return pdf_response(build_student_report(group_id, student, summarize(students)),
                        f"reporte_alumno_{secure_filename(student_id)}.pdf")
