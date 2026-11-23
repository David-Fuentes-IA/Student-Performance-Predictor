"""Unit: e-mail alerts, with a fake SMTP server (no e-mail ever leaves the machine)."""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from core import email_alerts
from core.email_alerts import DIGEST_SECONDS, EmailAlerts, mask, parse_recipients


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout

    def __enter__(self):
        if FakeSMTP.fail:
            raise ConnectionRefusedError("mail server down")
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        FakeSMTP.sent.append(message)


def alerts(**kwargs):
    FakeSMTP.sent = []
    FakeSMTP.fail = False
    return EmailAlerts(recipients=["admin@escuela.mx"], host="smtp.test", smtp_factory=FakeSMTP, **kwargs)


def event(level="ERROR", status=None, message="Unexpected error: boom", path="/api/groups/G1"):
    return {"created_at": datetime(2026, 11, 22, 20, 0), "level": level, "kind": "error inesperado", "status": status,
            "method": "GET", "path": path, "ref": "ABCD1234", "message": message}


class WhatIsMailedTests(unittest.TestCase):
    def test_errors_and_failed_requests_are_mailed_rejected_input_is_not(self):
        a = alerts()
        a.consider([event("ERROR"), event("WARNING", status=503), event("WARNING", status=400), event("WARNING")])
        self.assertEqual(a.pending(), 2)
        self.assertTrue(a.tick(now=0))
        body = FakeSMTP.sent[0].get_content()
        self.assertIn("2 error(es)", body)
        self.assertIn("ABCD1234", body)

    def test_off_without_configuration(self):
        a = EmailAlerts(recipients=[], host="", smtp_factory=FakeSMTP)
        a.consider([event()])
        self.assertFalse(a.enabled)
        self.assertEqual(a.pending(), 0)


class SafetyTests(unittest.TestCase):
    def test_at_most_one_summary_every_five_minutes(self):
        a = alerts()
        a.consider([event()])
        self.assertTrue(a.tick(now=1000))
        for _ in range(100):                                        # an attacker provoking errors
            a.consider([event()])
        self.assertFalse(a.tick(now=1000 + DIGEST_SECONDS - 1))
        self.assertTrue(a.tick(now=1000 + DIGEST_SECONDS))
        self.assertEqual(len(FakeSMTP.sent), 2)
        self.assertIn("100 error(es)", FakeSMTP.sent[1].get_content())

    def test_user_input_never_reaches_a_header_and_stays_on_one_line(self):
        a = alerts()
        a.consider([event(path="/api/x\r\nBcc: victim@evil.com", message="boom\r\nSubject: hacked")])
        a.tick(now=0)
        message = FakeSMTP.sent[0]
        self.assertEqual(message["Subject"], email_alerts.SUBJECT)
        self.assertIsNone(message["Bcc"])
        self.assertNotIn("\nBcc:", message.get_content())
        self.assertNotIn("\nSubject: hacked", message.get_content())

    def test_a_broken_mail_server_is_recorded_not_raised(self):
        a = alerts()
        FakeSMTP.fail = True
        a.consider([event()])
        with self.assertLogs("student_predictor.core.email_alerts", level="WARNING") as logs:
            self.assertFalse(a.tick(now=0))
        self.assertIn("ConnectionRefusedError", a.status()["last_error"])
        self.assertIn("EMAIL ALERT FAILED", logs.output[0])

    def test_the_test_email_carries_the_last_minutes_of_the_log(self):
        a = alerts()
        a.send_test([event("WARNING", status=400, message="REQUEST REJECTED | 400 POST /admin/api/groups")], now=0)
        body = FakeSMTP.sent[0].get_content()
        self.assertIn("ultimos 10 minutos (1", body)
        self.assertIn("REQUEST REJECTED", body)
        a.send_test([], now=100)
        self.assertIn("No hubo eventos", FakeSMTP.sent[1].get_content())

    def test_the_test_button_cannot_be_spammed(self):
        a = alerts()
        self.assertEqual(a.send_test(now=0), "sent")
        self.assertEqual(a.send_test(now=10), "too_soon")
        self.assertEqual(a.send_test(now=31), "sent")


class ConfigurationTests(unittest.TestCase):
    def test_recipients_are_validated_and_limited_to_three(self):
        self.assertEqual(parse_recipients(" a@x.mx, bad, b@y.com ,c@z.org,d@w.net"), ["a@x.mx", "b@y.com", "c@z.org"])

    def test_the_panel_shows_masked_addresses(self):
        self.assertEqual(mask("gabriel@gmail.com"), "g***@gmail.com")
        self.assertEqual(alerts().status()["recipients"], ["a***@escuela.mx"])

    def test_from_env(self):
        env = {"ALERT_EMAIL_TO": "a@x.mx", "SMTP_HOST": "mailpit", "SMTP_PORT": "1025", "SMTP_STARTTLS": "false"}
        with patch.dict(os.environ, env):
            a = email_alerts.from_env()
        self.assertTrue(a.enabled)
        self.assertEqual((a.host, a.port, a.starttls), ("mailpit", 1025, False))


if __name__ == "__main__":
    unittest.main()
