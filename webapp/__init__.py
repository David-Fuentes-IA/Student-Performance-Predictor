"""
webapp/__init__.py

Application factory: ONE Flask app serves the teacher dashboard (/) and the
database administration panel (/admin). Both blueprints use the same
repository and the same prediction engine owned by main_api (the composition
root), so a group created or imported in /admin is the very group the
dashboard analyses - same process, same data source, no restart.
"""

import json
import uuid
from datetime import date, datetime

from flask import Flask, g, jsonify, request
from markupsafe import escape
from werkzeug.exceptions import HTTPException

from core import config, event_log
from core.exception_handler import (
    AppError,
    DataAccessError,
    NotFoundError,
    ValidationError,
)
from core.logger import get_logger

logger = get_logger(__name__)

_JSON_PREFIXES = ("/api/", "/admin/api/", "/reports/", "/health", "/ready")

_GENERIC_MESSAGE = "No se pudo generar la información del grupo. Inténtalo de nuevo."

# Sent with every response. Only this server may provide content; no framing (clickjacking); no MIME sniffing; no
# referrer leaving the site. 'unsafe-inline' is still needed because the administration page keeps its script, styles
# and event handlers inside admin.html; moving them to static files would let it go (documented limitation).
SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                                "form-action 'self'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}

# What a user sees for an HTTP error raised by Flask itself (wrong URL, wrong method, oversized upload...).
_HTTP_MESSAGES = {
    400: "La solicitud no es valida.",
    404: "La pagina o ruta solicitada no existe.",
    405: "Esta ruta no admite ese tipo de solicitud.",
    413: "El archivo es demasiado grande (maximo 4 MB).",
    414: "La direccion es demasiado larga.",
    415: "Tipo de contenido no admitido.",
}


def _json_default(value):
    if isinstance(value, (datetime, date)):
        text = value.isoformat()
        return text + "Z" if isinstance(value, datetime) and value.tzinfo is None else text
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _wants_json() -> bool:
    return request.path.startswith(_JSON_PREFIXES)


# Rejected requests that are not worth an entry in the error log: the browser's automatic icon request, and wrong
# admin passwords (already logged as "ADMIN AUTH FAILED" with more detail).
_NOT_LOGGED_PATHS = ("/favicon.ico",)


def _install_event_log() -> None:
    """Errors go to MongoDB when the application uses it (kept for all time), otherwise to memory."""
    import main_api
    from data_access.mongo_repository import MongoAcademicRepository

    repository = main_api.get_repository()
    if isinstance(repository, MongoAcademicRepository):
        event_log.install(event_log.MongoEventLogStore(repository.db))
    else:
        event_log.install(event_log.InMemoryEventLogStore())


def _with_reference(response):
    """Every error answer carries the request's reference code, so a user can report it and an administrator can
    find the exact entry in the error log. The message itself stays short and never technical."""
    if response.status_code < 400 or not response.is_json:
        return response
    body = response.get_json(silent=True)
    if isinstance(body, dict) and "error" in body and "ref" not in body:
        body["ref"] = g.get("request_id")
        response.set_data(json.dumps(body, ensure_ascii=False))
    return response


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # Vercel rejects bodies > 4.5 MB anyway
    app.json.default = _json_default
    app.json.sort_keys = False

    from webapp.admin import admin_bp
    from webapp.dashboard import dashboard_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    if config.mongodb_uri() and not config.admin_password():
        logger.warning("ADMIN_PASSWORD is empty: anyone who can reach /admin can change or delete the groups. "
                       "Set it whenever another machine can reach this application.")

    _install_event_log()

    @app.before_request
    def _assign_reference():
        g.request_id = uuid.uuid4().hex[:8].upper()

    @app.after_request
    def _security_headers(response):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        response.headers["X-Request-ID"] = g.get("request_id", "")
        return response

    @app.after_request
    def _log_rejected_requests(response):
        status = response.status_code
        if 400 <= status < 500 and status != 401 and request.path not in _NOT_LOGGED_PATHS:
            body = response.get_json(silent=True) if response.is_json else None
            shown = body.get("error") if isinstance(body, dict) else None
            logger.warning("REQUEST REJECTED | %s %s %s | %s", status, request.method, request.path,
                           shown or "-", extra={"http_status": status})
        return _with_reference(response)

    @app.errorhandler(AppError)
    def _app_error(exc: AppError):
        if isinstance(exc, NotFoundError):
            return jsonify(error=exc.user_message), 404
        if isinstance(exc, ValidationError):
            return jsonify(error=exc.user_message), 400
        if isinstance(exc, DataAccessError):
            logger.warning("Data access failed: %s", exc, extra={"http_status": 503})
            return jsonify(error=exc.user_message), 503
        # Other AppErrors may carry internal detail: never echo it to the client.
        logger.warning("Academic workflow failed: %s", exc, extra={"http_status": 503})
        return jsonify(error=_GENERIC_MESSAGE), 503

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        if exc.code is None or exc.code < 400:
            return exc
        message = _HTTP_MESSAGES.get(exc.code, "La solicitud no se pudo procesar.")
        if not _wants_json():
            # A browser typing a wrong URL gets a short Spanish page with a way back, not Werkzeug's English one.
            page = (f'<!doctype html><html lang="es"><meta charset="utf-8"><title>{exc.code}</title>'
                    f'<p>{escape(message)}</p><p>Codigo de referencia: {escape(g.get("request_id", ""))}</p>'
                    f'<p><a href="/">Volver al panel</a></p></html>')
            return page, exc.code, {"Content-Type": "text/html; charset=utf-8"}
        return jsonify(error=message), exc.code

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        logger.error("Unexpected error: %s", exc, exc_info=True, extra={"http_status": 500})
        return jsonify(error="No se pudo completar la operación. Inténtalo de nuevo."), 500

    return app
