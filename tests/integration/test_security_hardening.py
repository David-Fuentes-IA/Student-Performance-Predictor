"""Milestone 4 security corrections (no new features): security headers on every response, an audit line for
every rejected administrator password, and a visible warning when the administration panel has no password."""
import os
import unittest
from unittest.mock import patch

from webapp import SECURITY_HEADERS, create_app

ADMIN_LOGGER = "student_predictor.webapp.admin"
APP_LOGGER = "student_predictor.webapp"


class SecurityHeaderTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_every_kind_of_response_carries_the_security_headers(self):
        for path in ("/", "/admin/", "/api/groups", "/api/groups/301-A", "/health", "/ready",
                     "/reports/groups/301-A.pdf", "/api/groups/NOPE", "/static/dashboard.js", "/no-such-page"):
            response = self.client.get(path)
            for name, value in SECURITY_HEADERS.items():
                with self.subTest(path=path, header=name):
                    self.assertEqual(response.headers.get(name), value)

    def test_the_policy_allows_only_this_server_and_forbids_framing(self):
        policy = SECURITY_HEADERS["Content-Security-Policy"]
        self.assertIn("default-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertNotIn("http", policy)   # no outside host is trusted
        self.assertEqual(SECURITY_HEADERS["X-Frame-Options"], "DENY")


class AdminPasswordAuditTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_a_rejected_password_is_logged_without_the_value_tried(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "s3cret"}), self.assertLogs(ADMIN_LOGGER, "WARNING") as logs:
            response = self.client.get("/admin/api/groups", headers={"X-Admin-Password": "guess-123"})
        self.assertEqual(response.status_code, 401)
        line = "\n".join(logs.output)
        self.assertIn("ADMIN AUTH FAILED", line)
        self.assertIn("wrong password", line)
        self.assertNotIn("guess-123", line)
        self.assertNotIn("s3cret", line)

    def test_a_missing_password_is_logged_as_such(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "s3cret"}), self.assertLogs(ADMIN_LOGGER, "WARNING") as logs:
            self.client.post("/admin/api/seed", json={"count": 5})
        self.assertIn("no password", "\n".join(logs.output))

    def test_public_routes_and_a_correct_password_log_nothing(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "s3cret"}), self.assertNoLogs(ADMIN_LOGGER, "WARNING"):
            self.assertEqual(self.client.get("/admin/api/auth-required").status_code, 200)


class OpenAdminWarningTests(unittest.TestCase):
    def test_start_up_warns_when_a_database_is_configured_without_an_admin_password(self):
        with (patch.dict(os.environ, {"MONGODB_URI": "mongodb://db.example:27017", "ADMIN_PASSWORD": ""}),
              self.assertLogs(APP_LOGGER, "WARNING") as logs):
            create_app()
        self.assertIn("ADMIN_PASSWORD is empty", "\n".join(logs.output))

    def test_no_warning_in_demo_mode_or_with_a_password(self):
        for env in ({"MONGODB_URI": "", "ADMIN_PASSWORD": ""},
                    {"MONGODB_URI": "mongodb://db.example:27017", "ADMIN_PASSWORD": "s3cret"}):
            with self.subTest(env=env), patch.dict(os.environ, env), self.assertNoLogs(APP_LOGGER, "WARNING"):
                create_app()

    def test_the_admin_page_shows_the_warning_when_no_password_is_required(self):
        page = create_app().test_client().get("/admin/").get_data(as_text=True)
        self.assertIn("/admin/api/auth-required", page)
        self.assertIn("Sin contrase&ntilde;a", page)


if __name__ == "__main__":
    unittest.main()
