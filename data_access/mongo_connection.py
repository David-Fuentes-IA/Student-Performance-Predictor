"""
data_access/mongo_connection.py

One job (SRP): create and cache the MongoDB client.

Design note (traceability: NFR-5 Reliability, NFR-2 Security):
    - The client is created lazily and cached per process. On Vercel each
      serverless instance therefore opens ONE connection pool and reuses
      it across warm invocations instead of reconnecting on every request.
    - Failures are translated to `DataAccessError` with a safe
      `user_message`, so the Presentation layer never shows a driver
      traceback (and never the connection string).
    - The URI contains the database password: it is never logged. Use
      `redact_uri()` if a URI ever has to appear in a message.
"""

import re

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from core import config
from core.exception_handler import DataAccessError
from core.logger import get_logger

logger = get_logger(__name__)

_clients: dict[str, MongoClient] = {}

_CREDENTIALS_RE = re.compile(r"(://)([^:/@]+):([^@]+)@")


def redact_uri(uri: str) -> str:
    """Hide the password of a connection string (safe for logs)."""
    return _CREDENTIALS_RE.sub(r"\1\2:****@", uri)


def get_client(uri: str | None = None) -> MongoClient:
    """Return the cached MongoClient for `uri` (defaults to MONGODB_URI)."""
    uri = uri or config.mongodb_uri()
    if not uri:
        raise DataAccessError(
            "MONGODB_URI is not configured",
            user_message="La base de datos no esta configurada (falta MONGODB_URI).",
        )
    if uri not in _clients:
        _clients[uri] = MongoClient(
            uri,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
            maxPoolSize=10,
            appName="StudentPerformancePredictor",
        )
    return _clients[uri]


def get_database(uri: str | None = None, db_name: str | None = None) -> Database:
    """Return the application database, verifying that the server answers."""
    client = get_client(uri)
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        logger.error("MongoDB connection failed: %s", type(exc).__name__)
        raise DataAccessError(
            f"MongoDB connection failed ({type(exc).__name__})",
            user_message=(
                "No se pudo conectar con la base de datos. Verifica la cadena de "
                "conexion, el usuario/contrasena y el acceso de red en MongoDB Atlas."
            ),
        ) from exc
    return client[db_name or config.mongodb_db_name()]
