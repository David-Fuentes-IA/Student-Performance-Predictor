"""
core/email_alerts.py

E-mail alerts for real failures: every ERROR / CRITICAL event of the error log, and every failed request (5xx), is
mailed to the address(es) in ALERT_EMAIL_TO. Rejected input (4xx) is not mailed: a reviewer typing bad data would
otherwise fill the inbox.

Configuration (only in .env / environment variables, never in the code, the browser or the database):
    ALERT_EMAIL_TO   one to three addresses, comma separated
    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_STARTTLS (true)
Without ALERT_EMAIL_TO and SMTP_HOST the alerts are off and nothing else changes.

Safety decisions:
    - one summary e-mail at most every 5 minutes ("7 errores en los ultimos 5 minutos"): provoking a thousand errors
      cannot flood the inbox or get the sending account blocked;
    - the subject is fixed text (no user input can reach a mail header) and every value in the body is cut and put on
      one line;
    - no traceback and no student names: the e-mail says what failed, where and the reference code; the detail stays in
      the error log;
    - it runs on the error log's background thread with a 10-second timeout: a slow or broken mail server never delays
      a user's request, and a failure to send is logged as a WARNING (which is never mailed, so it cannot loop).
"""

from __future__ import annotations

import os
import re
import smtplib
import threading
import time
from collections import deque
from datetime import datetime, timezone
from email.message import EmailMessage

DIGEST_SECONDS = 5 * 60
TEST_INTERVAL = 30
_MAX_PENDING = 200
_ADDRESS = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
SUBJECT = "[Student Performance Predictor] Errores en el sistema"


def _one_line(value, limit: int = 300) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= limit else text[:limit] + "..."


def mask(address: str) -> str:
    """g***@gmail.com: the panel shows who receives alerts without publishing the full address."""
    user, _, domain = address.partition("@")
    return (user[:1] + "***@" + domain) if domain else "***"


def parse_recipients(text: str) -> list[str]:
    addresses = [a.strip() for a in (text or "").split(",") if a.strip()]
    return [a for a in addresses if _ADDRESS.match(a)][:3]


def is_alert(event: dict) -> bool:
    return event.get("level") in ("ERROR", "CRITICAL") or (event.get("status") or 0) >= 500


class EmailAlerts:
    def __init__(self, *, recipients: list[str], host: str, port: int = 587, user: str = "", password: str = "",
                 sender: str = "", starttls: bool = True, smtp_factory=smtplib.SMTP) -> None:
        self.recipients = recipients
        self.host = host
        self.port = port
        self.user = user
        self._password = password
        self.sender = sender or user or "alertas@student-predictor.local"
        self.starttls = starttls
        self._smtp_factory = smtp_factory
        self._pending: deque[dict] = deque(maxlen=_MAX_PENDING)
        self._lock = threading.Lock()
        self._last_digest: float | None = None
        self._last_test: float | None = None
        self.last_sent_at: datetime | None = None
        self.last_error: str | None = None
        self.sent = 0

    @property
    def enabled(self) -> bool:
        return bool(self.recipients and self.host)

    # -- called by the error log --------------------------------------------------------------------------------
    def consider(self, events: list[dict]) -> None:
        if not self.enabled:
            return
        alerts = [e for e in events if is_alert(e)]
        if alerts:
            with self._lock:
                self._pending.extend(alerts)

    def tick(self, now: float | None = None) -> bool:
        """Send the summary if there is something waiting and the last one was 5 minutes ago or more."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if not self._pending or (self._last_digest is not None and now - self._last_digest < DIGEST_SECONDS):
                return False
            batch = list(self._pending)
            self._pending.clear()
            self._last_digest = now
        return self._send(self._digest_body(batch))

    def pending(self) -> int:
        return len(self._pending)

    # -- the panel's test button ----------------------------------------------------------------------------------
    def send_test(self, now: float | None = None) -> str:
        """'sent', 'too_soon' or 'failed'."""
        now = time.monotonic() if now is None else now
        if self._last_test is not None and now - self._last_test < TEST_INTERVAL:
            return "too_soon"
        self._last_test = now
        body = ("Correo de prueba de las alertas de Student Performance Predictor.\n\n"
                "Si lo recibiste, las alertas por correo funcionan: cada error real del sistema llegara a esta "
                "direccion, como maximo un resumen cada 5 minutos.\n")
        return "sent" if self._send(body, subject=SUBJECT.replace("Errores en el sistema", "Correo de prueba")) else "failed"

    def status(self) -> dict:
        return {"enabled": self.enabled, "recipients": [mask(r) for r in self.recipients],
                "last_sent_at": self.last_sent_at, "last_error": self.last_error, "pending": self.pending(),
                "sent": self.sent, "digest_minutes": DIGEST_SECONDS // 60}

    # -- internals -----------------------------------------------------------------------------------------------
    def _digest_body(self, events: list[dict]) -> str:
        lines = [f"Se registraron {len(events)} error(es) en Student Performance Predictor.", ""]
        for e in events[:50]:
            when = e.get("created_at")
            when = when.strftime("%d/%m/%Y %H:%M:%S UTC") if isinstance(when, datetime) else _one_line(when)
            request_text = _one_line(" ".join(str(x) for x in (e.get("status"), e.get("method"), e.get("path")) if x), 200)
            lines += [f"- {when} | {_one_line(e.get('level'), 10)} | {_one_line(e.get('kind'), 40)}",
                      f"  Solicitud: {request_text or '-'} | Codigo: {_one_line(e.get('ref') or '-', 12)}",
                      f"  {_one_line(e.get('message'))}", ""]
        if len(events) > 50:
            lines.append(f"... y {len(events) - 50} mas.")
        lines += ["Detalle tecnico: /admin -> Bitacora de errores (busca el codigo).",
                  "Este correo no contiene nombres de alumnos ni contrasenas."]
        return "\n".join(lines)

    def _send(self, body: str, subject: str = SUBJECT) -> bool:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(body)
        try:
            with self._smtp_factory(self.host, self.port, timeout=10) as smtp:
                if self.starttls:
                    smtp.starttls()
                if self.user:
                    smtp.login(self.user, self._password)
                smtp.send_message(message)
        except Exception as exc:  # noqa: BLE001 - never break the caller; record why for the panel
            self.last_error = f"{type(exc).__name__}: {_one_line(exc, 160)}"
            from core.logger import get_logger

            get_logger(__name__).warning("EMAIL ALERT FAILED | %s", self.last_error)   # WARNING: never mailed
            return False
        self.last_sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.last_error = None
        self.sent += 1
        return True


def from_env() -> EmailAlerts:
    try:
        port = int(os.environ.get("SMTP_PORT", "587") or 587)
    except ValueError:
        port = 587
    return EmailAlerts(
        recipients=parse_recipients(os.environ.get("ALERT_EMAIL_TO", "")),
        host=os.environ.get("SMTP_HOST", "").strip(),
        port=port,
        user=os.environ.get("SMTP_USER", "").strip(),
        password=os.environ.get("SMTP_PASSWORD", ""),
        sender=os.environ.get("SMTP_FROM", "").strip(),
        starttls=os.environ.get("SMTP_STARTTLS", "true").strip().lower() not in ("false", "0", "no"),
    )
