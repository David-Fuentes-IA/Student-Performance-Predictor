"""
webapp/__init__.py

Application factory: ONE Flask app serves the teacher dashboard (/) and the
database administration panel (/admin). Both blueprints use the same
repository and the same prediction engine owned by main_api (the composition
root), so a group created or imported in /admin is the very group the
dashboard analyses - same process, same data source, no restart.
"""

from datetime import date, datetime

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

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


def _json_default(value):
    if isinstance(value, (datetime, date)):
        text = value.isoformat()
        return text + "Z" if isinstance(value, datetime) and value.tzinfo is None else text
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _wants_json() -> bool:
    return request.path.startswith(_JSON_PREFIXES)


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # Vercel rejects bodies > 4.5 MB anyway
    app.json.default = _json_default
    app.json.sort_keys = False

    from webapp.admin import admin_bp
    from webapp.dashboard import dashboard_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.errorhandler(AppError)
    def _app_error(exc: AppError):
        if isinstance(exc, NotFoundError):
            return jsonify(error=exc.user_message), 404
        if isinstance(exc, ValidationError):
            return jsonify(error=exc.user_message), 400
        if isinstance(exc, DataAccessError):
            logger.warning("Data access failed: %s", exc)
            return jsonify(error=exc.user_message), 503
        # Other AppErrors may carry internal detail: never echo it to the client.
        logger.warning("Academic workflow failed: %s", exc)
        return jsonify(error=_GENERIC_MESSAGE), 503

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        if not _wants_json():
            return exc
        if exc.code == 413:
            return jsonify(error="El archivo es demasiado grande (maximo 4 MB)."), 413
        return jsonify(error=exc.description), exc.code

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        logger.error("Unexpected error: %s", exc, exc_info=True)
        return jsonify(error="No se pudo completar la operación. Inténtalo de nuevo."), 500

    return app
