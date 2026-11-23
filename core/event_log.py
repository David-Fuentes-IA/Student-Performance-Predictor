"""
core/event_log.py

Persistent log of everything that went wrong ("bitácora de errores"): every WARNING, ERROR or CRITICAL line any module
writes, plus every request the application rejected (4xx) or failed (5xx), with the reference code the user was shown.

Why a separate store and not only the log file:
    the file and `docker compose logs` are lost when the container is recreated, and nobody can read them from the
    application. These events are kept in MongoDB (collection `event_log`, all time) so the administration panel can
    list, filter and export them; without a database they are kept in memory (the last 5,000).

How it works (Observer on the logging system + Repository, DIP):
    EventLogHandler is a logging.Handler attached to the project's root logger. emit() only builds a small dict and
    puts it on a queue, so a request never waits for the database; a daemon thread writes the queue to the store in
    batches. If the store fails (MongoDB down), the events stay in a bounded retry buffer and in the log file; the
    handler never logs through the project's own logger, so it cannot feed back into itself.

Privacy (DR-1): messages come from the project's loggers, which never write student names or passwords; long values
are cut. The traceback is stored for the administrator (it is never sent to a user).
"""

from __future__ import annotations

import logging
import queue
import re
import sys
import threading
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Protocol

LEVELS = ("WARNING", "ERROR", "CRITICAL")
COLLECTION = "event_log"
_MAX_MESSAGE = 2000
_MAX_TRACEBACK = 8000
_MEMORY_LIMIT = 5000
_RETRY_LIMIT = 10000

# Not failures: a high-risk student is the system working as designed (it is in the normal log).
_IGNORED_PREFIXES = ("RISK ALERT",)

# Category shown to the administrator, derived from the message (first match wins).
_KINDS = (
    ("seguridad", re.compile(r"ADMIN AUTH FAILED|ADMIN_PASSWORD")),
    ("solicitud rechazada", re.compile(r"^REQUEST (REJECTED|FAILED)")),
    ("no encontrado", re.compile(r"NotFound|not found")),
    ("base de datos", re.compile(r"Mongo|database|Data access", re.IGNORECASE)),
    ("datos invalidos", re.compile(r"invalid|skipped|rejected|Validation", re.IGNORECASE)),
    ("modelo", re.compile(r"model|predict", re.IGNORECASE)),
    ("error inesperado", re.compile(r"Unexpected")),
)
KINDS = tuple(name for name, _ in _KINDS) + ("otro",)


def classify(message: str) -> str:
    for name, pattern in _KINDS:
        if pattern.search(message):
            return name
    return "otro"


def _cut(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + " …[recortado]"


# --------------------------------------------------------------------------
# Stores
# --------------------------------------------------------------------------

class EventLogStore(Protocol):
    def add_many(self, events: list[dict]) -> None: ...
    def query(self, *, level: str | None, kind: str | None, text: str | None, since: datetime | None,
              until: datetime | None, limit: int, skip: int) -> tuple[int, list[dict]]: ...
    def counts(self) -> dict: ...


def _matches(event: dict, level, kind, text, since, until) -> bool:
    if level and event["level"] != level:
        return False
    if kind and event["kind"] != kind:
        return False
    if since and event["created_at"] < since:
        return False
    if until and event["created_at"] > until:
        return False
    if text:
        needle = text.lower()
        haystack = " ".join(str(event.get(k) or "") for k in ("message", "path", "ref", "source")).lower()
        if needle not in haystack:
            return False
    return True


class InMemoryEventLogStore:
    """Demo mode (no database): the most recent events of this process."""

    def __init__(self, limit: int = _MEMORY_LIMIT) -> None:
        self._events: deque[dict] = deque(maxlen=limit)
        self._lock = threading.Lock()
        self.persistent = False

    def add_many(self, events: list[dict]) -> None:
        with self._lock:
            self._events.extend(events)

    def query(self, *, level=None, kind=None, text=None, since=None, until=None, limit=50, skip=0):
        with self._lock:
            found = [e for e in reversed(self._events) if _matches(e, level, kind, text, since, until)]
        return len(found), [dict(e) for e in found[skip:skip + limit]]

    def counts(self) -> dict:
        with self._lock:
            events = list(self._events)
        return _count(events)


def _count(events) -> dict:
    by_level = {name: 0 for name in LEVELS}
    by_kind: dict[str, int] = {}
    for e in events:
        by_level[e["level"]] = by_level.get(e["level"], 0) + 1
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    return {"total": sum(by_level.values()), "by_level": by_level, "by_kind": by_kind}


class MongoEventLogStore:
    """All-time events in the `event_log` collection (one document per event)."""

    def __init__(self, db) -> None:
        self._collection = db[COLLECTION]
        self.persistent = True
        try:
            self._collection.create_index([("created_at", -1)])
            self._collection.create_index([("level", 1), ("created_at", -1)])
        except Exception as exc:  # noqa: BLE001 - an index problem must not stop the application
            _stderr(f"event_log: could not create indexes ({type(exc).__name__})")

    def add_many(self, events: list[dict]) -> None:
        if events:
            self._collection.insert_many([dict(e) for e in events], ordered=False)

    def _filter(self, level, kind, text, since, until) -> dict:
        query: dict = {}
        if level:
            query["level"] = level
        if kind:
            query["kind"] = kind
        if since or until:
            query["created_at"] = {**({"$gte": since} if since else {}), **({"$lte": until} if until else {})}
        if text:
            pattern = {"$regex": re.escape(text), "$options": "i"}   # escaped: user text is never a regex
            query["$or"] = [{"message": pattern}, {"path": pattern}, {"ref": pattern}, {"source": pattern}]
        return query

    def query(self, *, level=None, kind=None, text=None, since=None, until=None, limit=50, skip=0):
        query = self._filter(level, kind, text, since, until)
        total = self._collection.count_documents(query)
        cursor = self._collection.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        return total, list(cursor)

    def counts(self) -> dict:
        by_level = {name: 0 for name in LEVELS}
        for row in self._collection.aggregate([{"$group": {"_id": "$level", "n": {"$sum": 1}}}]):
            by_level[row["_id"]] = row["n"]
        by_kind = {row["_id"]: row["n"] for row in
                   self._collection.aggregate([{"$group": {"_id": "$kind", "n": {"$sum": 1}}}])}
        return {"total": sum(by_level.values()), "by_level": by_level, "by_kind": by_kind}


# --------------------------------------------------------------------------
# Logging handler + background writer
# --------------------------------------------------------------------------

def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _request_context() -> dict:
    """Method, path, address and reference code of the request being served, if there is one."""
    try:
        from flask import g, has_request_context, request
    except ImportError:  # pragma: no cover - Flask is a dependency
        return {}
    if not has_request_context():
        return {}
    return {"method": request.method, "path": _cut(request.path, 300), "remote_addr": request.remote_addr,
            "ref": getattr(g, "request_id", None)}


class EventLogHandler(logging.Handler):
    def __init__(self, sink: "EventLog") -> None:
        super().__init__(level=logging.WARNING)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if message.startswith(_IGNORED_PREFIXES):
                return
            event = {
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
                "level": record.levelname if record.levelname in LEVELS else "WARNING",
                "kind": classify(message),
                "source": record.name.removeprefix("student_predictor."),
                "message": _cut(message, _MAX_MESSAGE),
                "status": getattr(record, "http_status", None),
                "exception": record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None,
                "traceback": _cut("".join(traceback.format_exception(*record.exc_info)), _MAX_TRACEBACK)
                if record.exc_info and record.exc_info[0] else None,
                **_request_context(),
            }
            self._sink.enqueue(event)
        except Exception:  # noqa: BLE001 - logging must never break the caller
            self.handleError(record)


class EventLog:
    """Owns the store, the queue and the writer thread. One per process (see `install`)."""

    def __init__(self) -> None:
        self.store: EventLogStore = InMemoryEventLogStore()
        self._queue: queue.Queue[dict] = queue.Queue()
        self._retry: deque[dict] = deque(maxlen=_RETRY_LIMIT)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.handler = EventLogHandler(self)

    def enqueue(self, event: dict) -> None:
        self._queue.put(event)
        self._ensure_thread()

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="event-log-writer", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            self.flush()

    def flush(self) -> int:
        """Write everything waiting to the store now. Returns how many events were written."""
        with self._lock:
            batch = list(self._retry)
            self._retry.clear()
            while True:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            if not batch:
                return 0
            try:
                self.store.add_many(batch)
                return len(batch)
            except Exception as exc:  # noqa: BLE001 - keep them and retry; never log through our own logger
                self._retry.extend(batch)
                _stderr(f"event_log: {len(batch)} events kept for retry ({type(exc).__name__})")
                return 0

    def pending(self) -> int:
        return self._queue.qsize() + len(self._retry)


_EVENT_LOG = EventLog()


def install(store: EventLogStore | None = None) -> EventLog:
    """Attach the handler to the project's root logger (once) and choose where events go."""
    from core.logger import get_logger

    get_logger("core.event_log")                        # makes sure the root logger is configured
    root = logging.getLogger("student_predictor")
    if _EVENT_LOG.handler not in root.handlers:
        root.addHandler(_EVENT_LOG.handler)
    if store is not None:
        _EVENT_LOG.store = store                        # anything still queued goes to the new store
    return _EVENT_LOG


def get_event_log() -> EventLog:
    return _EVENT_LOG
