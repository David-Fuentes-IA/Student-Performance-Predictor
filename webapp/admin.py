"""
webapp/admin.py

Database administration blueprint, mounted at /admin by create_app().
Groups, students, Excel import and demo data - all operating on the SAME
repository the dashboard analyses (main_api owns it), so changes here are
visible in the dashboard immediately.

Security (NFR-2): if ADMIN_PASSWORD is set, every /admin/api route except
health, auth-required and the empty Excel template requires the header
`X-Admin-Password`. MongoDB credentials come from MONGODB_URI (environment /
.env) and are never sent to the browser.
"""

import hmac
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, render_template, request

import main_api
from core import config, event_log
from core.exception_handler import DataAccessError, NotFoundError, ValidationError
from core.logger import get_logger
from data_access.mongo_connection import get_database
from data_access.mongo_repository import MongoAcademicRepository
from data_pipeline.excel_importer import build_template
from data_pipeline.group_import_service import GroupImportService
from data_pipeline.synthetic_seed import seed_database
from presentation.pdf_reports import build_error_log_report

admin_bp = Blueprint("admin", __name__)
logger = get_logger(__name__)

_PUBLIC_API = {"/admin/api/health", "/admin/api/auth-required", "/admin/api/template.xlsx"}


def repo() -> MongoAcademicRepository:
    repository = main_api.get_repository()
    if not isinstance(repository, MongoAcademicRepository):
        raise DataAccessError(
            "admin panel needs MongoDB but the active repository is in-memory",
            user_message="La administración requiere conexión a la base de datos (modo demo activo).",
        )
    return repository


def service() -> GroupImportService:
    return GroupImportService(repo())


# Brute-force guard: after MAX_FAILED wrong passwords from one address within WINDOW seconds, that address is refused
# (429) for LOCKOUT seconds, even with the right password. 3 minutes on purpose: long enough to make guessing useless
# (at most 10 tries every 3 minutes), short enough not to lock a teacher out for long after a few typos.
# Kept in memory per process: with gunicorn's 2 workers an address gets at most 2 x 10 tries per window (documented).
MAX_FAILED = 10
WINDOW = 5 * 60
LOCKOUT = 3 * 60
_failures: dict[str, deque] = {}
_locked_until: dict[str, float] = {}
_lock = threading.Lock()


def _seconds_locked(address: str) -> int:
    with _lock:
        until = _locked_until.get(address, 0)
        if until <= time.monotonic():
            _locked_until.pop(address, None)
            return 0
        return int(until - time.monotonic()) + 1


def _register_failure(address: str) -> bool:
    """Count a wrong password; True when this one locks the address."""
    now = time.monotonic()
    with _lock:
        attempts = _failures.setdefault(address, deque())
        attempts.append(now)
        while attempts and attempts[0] < now - WINDOW:
            attempts.popleft()
        if len(attempts) >= MAX_FAILED:
            _locked_until[address] = now + LOCKOUT
            attempts.clear()
            return True
    return False


def reset_lockouts() -> None:
    with _lock:
        _failures.clear()
        _locked_until.clear()


def _too_many_attempts(seconds: int):
    response = jsonify(error="Demasiados intentos fallidos. Espera 3 minutos e intenta de nuevo.")
    response.headers["Retry-After"] = str(seconds)
    return response, 429


@admin_bp.before_request
def _require_password():
    password = config.admin_password()
    if not password or not request.path.startswith("/admin/api/") or request.path in _PUBLIC_API:
        return None
    address = request.remote_addr or "?"
    seconds = _seconds_locked(address)
    if seconds:
        logger.warning("ADMIN AUTH LOCKED | %s %s from %s (%d s left)", request.method, request.path, address, seconds)
        return _too_many_attempts(seconds)
    supplied = request.headers.get("X-Admin-Password", "")
    if not hmac.compare_digest(supplied.encode(), password.encode()):
        # Audit trail of rejected attempts (never the supplied value): repeated lines reveal guessing.
        logger.warning("ADMIN AUTH FAILED | %s %s from %s (%s)", request.method, request.path,
                       address, "wrong password" if supplied else "no password")
        # Only wrong passwords count: the panel's first requests go out without one before the browser asks for it.
        if supplied and _register_failure(address):
            logger.warning("ADMIN AUTH LOCKOUT | %s blocked for %d s after %d wrong passwords",
                           address, LOCKOUT, MAX_FAILED)
            return _too_many_attempts(LOCKOUT)
        return jsonify(error="Contrasena de administrador requerida o incorrecta."), 401
    with _lock:
        _failures.pop(address, None)
    return None


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("body is not a JSON object", user_message="Se esperaba un JSON valido.")
    return data


def _text(body: dict, key: str) -> str:
    """A text field of the JSON body: missing or null -> "", number -> its digits, anything else -> 400.
    Without this, str(None) stored a group literally called "None" and lists/objects were stored as text."""
    value = body.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise ValidationError(f"field '{key}' is not text", user_message=f"El campo '{key}' debe ser texto.")


def _require_group(group_id: str) -> None:
    if not repo().group_exists(group_id):
        raise NotFoundError(f"group '{group_id}' not found",
                            user_message=f"El grupo '{group_id}' no existe.")


# --------------------------------------------------------------------------
# Pages and health
# --------------------------------------------------------------------------

@admin_bp.route("/")
def index():
    return render_template("admin.html")


@admin_bp.route("/api/health")
def health():
    """Always 200: reports whether the database answers, without leaking details."""
    try:
        db = get_database()
        return jsonify(status="ok", database=True, db_name=db.name)
    except DataAccessError as exc:
        return jsonify(status="degraded", database=False, message=exc.user_message)


@admin_bp.route("/api/auth-required")
def auth_required():
    return jsonify(required=bool(config.admin_password()))


@admin_bp.route("/api/stats")
def stats():
    return jsonify(repo().stats())


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------

@admin_bp.route("/api/groups", methods=["GET"])
def list_groups():
    return jsonify(groups=repo().list_groups())


@admin_bp.route("/api/groups", methods=["POST"])
def create_group():
    body = _json_body()
    group = service().create_group(
        _text(body, "group_id"),
        name=_text(body, "name"),
        period=_text(body, "period"),
        teacher=_text(body, "teacher"),
    )
    return jsonify(group), 201


@admin_bp.route("/api/groups/<group_id>", methods=["DELETE"])
def delete_group(group_id: str):
    _require_group(group_id)
    return jsonify(repo().delete_group(group_id))


# --------------------------------------------------------------------------
# Students of a group
# --------------------------------------------------------------------------

@admin_bp.route("/api/groups/<group_id>/students", methods=["GET"])
def list_students(group_id: str):
    _require_group(group_id)
    return jsonify(group_id=group_id, students=repo().list_group_records(group_id))


@admin_bp.route("/api/groups/<group_id>/students", methods=["POST"])
def add_student(group_id: str):
    body = _json_body()
    grades = body.get("grades")
    if not isinstance(grades, list) or not grades:
        raise ValidationError("grades missing", user_message="Indica al menos una calificacion.")
    outcome = service().add_student(
        group_id,
        student_id=_text(body, "student_id"),
        name=_text(body, "name"),
        grades=grades,
        attendance_pct=body.get("attendance_pct"),
        participation_score=body.get("participation_score"),
    )
    return jsonify(outcome), 201


@admin_bp.route("/api/groups/<group_id>/students", methods=["DELETE"])
def clear_students(group_id: str):
    _require_group(group_id)
    return jsonify(deleted=repo().clear_group_students(group_id))


@admin_bp.route("/api/groups/<group_id>/students/<path:student_id>/history", methods=["GET"])
def student_history(group_id: str, student_id: str):
    _require_group(group_id)
    return jsonify(history=repo().get_student_history(group_id, student_id))


@admin_bp.route("/api/groups/<group_id>/students/<path:student_id>", methods=["DELETE"])
def delete_student(group_id: str, student_id: str):
    _require_group(group_id)
    if not repo().delete_student_record(group_id, student_id):
        raise NotFoundError("student not found", user_message="El alumno no existe en este grupo.")
    return jsonify(deleted=True)


# --------------------------------------------------------------------------
# Excel import / template
# --------------------------------------------------------------------------

@admin_bp.route("/api/template.xlsx")
def template():
    return Response(
        build_template(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_calificaciones.xlsx"'},
    )


@admin_bp.route("/api/groups/<group_id>/import", methods=["POST"])
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


@admin_bp.route("/api/imports")
def recent_imports():
    return jsonify(imports=repo().recent_imports())


# --------------------------------------------------------------------------
# Demo data + raw database browser
# --------------------------------------------------------------------------

@admin_bp.route("/api/seed", methods=["POST"])
def seed():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ValidationError("body is not a JSON object", user_message="Se esperaba un JSON valido.")
    try:
        count = body.get("count", 100)
        if isinstance(count, bool):
            raise TypeError("bool is not a count")
        count = int(count)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError("bad count", user_message="La cantidad debe ser un numero.") from None
    if not 1 <= count <= 500:
        raise ValidationError("count out of range", user_message="La cantidad debe estar entre 1 y 500.")
    return jsonify(seed_database(repo(), count, reset=body.get("reset") is True))


@admin_bp.route("/api/seed", methods=["DELETE"])
def purge_seed():
    return jsonify(repo().purge_synthetic())


@admin_bp.route("/api/collections/<name>")
def browse_collection(name: str):
    return jsonify(
        repo().browse(
            name,
            limit=request.args.get("limit", 50, type=int),
            skip=request.args.get("skip", 0, type=int),
        )
    )


# --------------------------------------------------------------------------
# Error log ("bitacora de errores"): everything that went wrong, for all time
# --------------------------------------------------------------------------

_PDF_LIMIT = 2_000           # the most recent events (the viewer pages through all of them)


def _date(name: str, *, end_of_day: bool = False):
    text = request.args.get(name, "").strip()
    if not text:
        return None
    try:
        day = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"bad date {name}", user_message="Formato de fecha incorrecto (usa AAAA-MM-DD).") from None
    return day + timedelta(days=1) - timedelta(microseconds=1) if end_of_day else day


def _log_filters() -> dict:
    level = request.args.get("level", "").strip().upper() or None
    if level and level not in event_log.LEVELS:
        raise ValidationError("bad level", user_message="Nivel no valido.")
    kind = request.args.get("kind", "").strip() or None
    if kind and kind not in event_log.KINDS:
        raise ValidationError("bad kind", user_message="Tipo de evento no valido.")
    text = request.args.get("q", "").strip()[:100] or None
    since, until = _date("from"), _date("to", end_of_day=True)
    if since and until and since > until:
        raise ValidationError("from after to", user_message="La fecha inicial es posterior a la final.")
    return {"level": level, "kind": kind, "text": text, "since": since, "until": until}


def _query_log(filters: dict, limit: int, skip: int = 0):
    log = event_log.get_event_log()
    log.flush()                                   # include what this process logged a moment ago
    try:
        return log.store.query(**filters, limit=limit, skip=skip), log.store.counts(), log.store
    except Exception as exc:  # noqa: BLE001 - e.g. MongoDB down: a clean 503, never internals
        raise DataAccessError(f"reading the error log failed ({type(exc).__name__})",
                              user_message="No se pudo leer la bitacora de errores. Intenta de nuevo.") from exc


@admin_bp.route("/api/error-log")
def error_log():
    filters = _log_filters()
    limit = max(1, min(request.args.get("limit", 50, type=int) or 50, 200))
    skip = max(0, min(request.args.get("skip", 0, type=int) or 0, 1_000_000_000))
    (total, events), counts, store = _query_log(filters, limit, skip)
    return jsonify(total=total, skip=skip, limit=limit, events=events, counts=counts,
                   persistent=getattr(store, "persistent", False), kinds=list(event_log.KINDS),
                   levels=list(event_log.LEVELS))


@admin_bp.route("/api/error-log/export.pdf")
def export_error_log_pdf():
    filters = _log_filters()
    (total, events), counts, store = _query_log(filters, _PDF_LIMIT)
    pdf = build_error_log_report(events, total, counts, filters, persistent=getattr(store, "persistent", False))
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="bitacora_errores_{stamp}.pdf"',
                             "Cache-Control": "no-store"})
