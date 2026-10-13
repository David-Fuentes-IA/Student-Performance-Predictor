"""
admin_app.py

Minimal database administration interface + REST API (Presentation layer).

This is intentionally NOT the teacher's risk dashboard (that is web_app.py,
owned by another part of the team). It only exposes the database so it can
be seen and managed once deployed (Vercel) - groups, students, Excel import,
demo data - and gives the final UI a documented API to build on.

Run locally:        python admin_app.py          -> http://127.0.0.1:5001
On Vercel:          api/index.py exposes `app`

Security (NFR-2): if ADMIN_PASSWORD is set, every /api route except
/api/health, /api/auth-required and the empty Excel template requires the
header `X-Admin-Password`. Credentials for MongoDB come from MONGODB_URI
(environment / .env) and are never sent to the browser.
"""

import hmac
from datetime import date, datetime

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from core import config
from core.exception_handler import AppError, DataAccessError, ValidationError
from core.logger import get_logger
from data_access.mongo_connection import get_database
from data_access.mongo_repository import MongoAcademicRepository
from data_pipeline.excel_importer import build_template
from data_pipeline.group_import_service import GroupImportService
from data_pipeline.synthetic_seed import seed_database

logger = get_logger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # Vercel rejects bodies > 4.5 MB anyway


def _json_default(value):
    if isinstance(value, (datetime, date)):
        text = value.isoformat()
        return text + "Z" if isinstance(value, datetime) and value.tzinfo is None else text
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


app.json.default = _json_default
app.json.sort_keys = False


class NotFoundError(AppError):
    """Requested group/student does not exist (HTTP 404)."""


# --------------------------------------------------------------------------
# Lazy singletons: one repository per warm serverless instance.
# --------------------------------------------------------------------------

_repository: MongoAcademicRepository | None = None


def repo() -> MongoAcademicRepository:
    global _repository
    if _repository is None:
        _repository = MongoAcademicRepository()
    return _repository


def service() -> GroupImportService:
    return GroupImportService(repo())


# --------------------------------------------------------------------------
# Security + error handling
# --------------------------------------------------------------------------

_PUBLIC_API = {"/api/health", "/api/auth-required", "/api/template.xlsx"}


@app.before_request
def _require_password():
    password = config.admin_password()
    if not password or not request.path.startswith("/api/") or request.path in _PUBLIC_API:
        return None
    supplied = request.headers.get("X-Admin-Password", "")
    if not hmac.compare_digest(supplied.encode(), password.encode()):
        return jsonify(error="Contrasena de administrador requerida o incorrecta."), 401
    return None


@app.errorhandler(AppError)
def _handle_app_error(exc: AppError):
    if isinstance(exc, NotFoundError):
        status = 404
    elif isinstance(exc, ValidationError):
        status = 400
    elif isinstance(exc, DataAccessError):
        status = 503
    else:
        status = 400
    return jsonify(error=exc.user_message), status


@app.errorhandler(HTTPException)
def _handle_http_error(exc: HTTPException):
    if exc.code == 413:
        return jsonify(error="El archivo es demasiado grande (maximo 4 MB)."), 413
    return jsonify(error=exc.description), exc.code


@app.errorhandler(Exception)
def _handle_unexpected(exc: Exception):
    logger.error("Unexpected error: %s", exc, exc_info=True)
    return jsonify(error="Ocurrio un error inesperado. Intenta de nuevo."), 500


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("body is not a JSON object", user_message="Se esperaba un JSON valido.")
    return data


def _require_group(group_id: str) -> None:
    if not repo().group_exists(group_id):
        raise NotFoundError(f"group '{group_id}' not found",
                            user_message=f"El grupo '{group_id}' no existe.")


# --------------------------------------------------------------------------
# Pages and health
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("admin.html")


@app.route("/api/health")
def health():
    """Always 200: reports whether the database answers, without leaking details."""
    try:
        db = get_database()
        return jsonify(status="ok", database=True, db_name=db.name)
    except DataAccessError as exc:
        return jsonify(status="degraded", database=False, message=exc.user_message)


@app.route("/api/auth-required")
def auth_required():
    return jsonify(required=bool(config.admin_password()))


@app.route("/api/stats")
def stats():
    return jsonify(repo().stats())


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------

@app.route("/api/groups", methods=["GET"])
def list_groups():
    return jsonify(groups=repo().list_groups())


@app.route("/api/groups", methods=["POST"])
def create_group():
    body = _json_body()
    group = service().create_group(
        str(body.get("group_id", "")),
        name=str(body.get("name", "")),
        period=str(body.get("period", "")),
        teacher=str(body.get("teacher", "")),
    )
    return jsonify(group), 201


@app.route("/api/groups/<group_id>", methods=["DELETE"])
def delete_group(group_id: str):
    _require_group(group_id)
    return jsonify(repo().delete_group(group_id))


# --------------------------------------------------------------------------
# Students of a group
# --------------------------------------------------------------------------

@app.route("/api/groups/<group_id>/students", methods=["GET"])
def list_students(group_id: str):
    _require_group(group_id)
    return jsonify(group_id=group_id, students=repo().list_group_records(group_id))


@app.route("/api/groups/<group_id>/students", methods=["POST"])
def add_student(group_id: str):
    body = _json_body()
    grades = body.get("grades")
    if not isinstance(grades, list) or not grades:
        raise ValidationError("grades missing", user_message="Indica al menos una calificacion.")
    outcome = service().add_student(
        group_id,
        student_id=str(body.get("student_id", "")),
        name=str(body.get("name", "")),
        grades=grades,
        attendance_pct=body.get("attendance_pct"),
        participation_score=body.get("participation_score"),
    )
    return jsonify(outcome), 201


@app.route("/api/groups/<group_id>/students", methods=["DELETE"])
def clear_students(group_id: str):
    _require_group(group_id)
    return jsonify(deleted=repo().clear_group_students(group_id))


@app.route("/api/groups/<group_id>/students/<path:student_id>/history", methods=["GET"])
def student_history(group_id: str, student_id: str):
    _require_group(group_id)
    return jsonify(history=repo().get_student_history(group_id, student_id))


@app.route("/api/groups/<group_id>/students/<path:student_id>", methods=["DELETE"])
def delete_student(group_id: str, student_id: str):
    _require_group(group_id)
    if not repo().delete_student_record(group_id, student_id):
        raise NotFoundError("student not found", user_message="El alumno no existe en este grupo.")
    return jsonify(deleted=True)


# --------------------------------------------------------------------------
# Excel import / template
# --------------------------------------------------------------------------

@app.route("/api/template.xlsx")
def template():
    return Response(
        build_template(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_calificaciones.xlsx"'},
    )


@app.route("/api/groups/<group_id>/import", methods=["POST"])
def import_excel(group_id: str):
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ValidationError("no file", user_message="Selecciona un archivo Excel (.xlsx).")
    if not upload.filename.lower().endswith(".xlsx"):
        raise ValidationError("bad extension", user_message="Solo se admiten archivos .xlsx.")

    result = service().import_excel(
        group_id,
        upload.read(),
        filename=upload.filename,
        mode=request.form.get("mode", "partial"),
        create_if_missing=request.form.get("create_group", "false").lower() == "true",
        group_info={
            "name": request.form.get("name", ""),
            "period": request.form.get("period", ""),
            "teacher": request.form.get("teacher", ""),
        },
    )
    return jsonify(result), 200


@app.route("/api/imports")
def recent_imports():
    return jsonify(imports=repo().recent_imports())


# --------------------------------------------------------------------------
# Demo data + raw database browser
# --------------------------------------------------------------------------

@app.route("/api/seed", methods=["POST"])
def seed():
    body = request.get_json(silent=True) or {}
    try:
        count = int(body.get("count", 100))
    except (TypeError, ValueError):
        raise ValidationError("bad count", user_message="La cantidad debe ser un numero.") from None
    if not 1 <= count <= 500:
        raise ValidationError("count out of range", user_message="La cantidad debe estar entre 1 y 500.")
    return jsonify(seed_database(repo(), count, reset=bool(body.get("reset", False))))


@app.route("/api/seed", methods=["DELETE"])
def purge_seed():
    return jsonify(repo().purge_synthetic())


@app.route("/api/collections/<name>")
def browse_collection(name: str):
    return jsonify(
        repo().browse(
            name,
            limit=request.args.get("limit", 50, type=int),
            skip=request.args.get("skip", 0, type=int),
        )
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
