"""Integration: brute-force guard on the administrator password. After 10 wrong passwords from one address the
address is refused for 3 minutes (429), even with the right password; every step is in the error log."""
import os
import unittest
from unittest.mock import patch

from webapp import admin, create_app

URL = "/admin/api/stats"


class LockoutTests(unittest.TestCase):
    def setUp(self):
        admin.reset_lockouts()
        self.addCleanup(admin.reset_lockouts)
        env = patch.dict(os.environ, {"ADMIN_PASSWORD": "la-buena"})
        env.start()
        self.addCleanup(env.stop)
        self.client = create_app().test_client()

    def wrong(self, n):
        return [self.client.get(URL, headers={"X-Admin-Password": f"mala-{i}"}).status_code for i in range(n)]

    def test_ten_wrong_passwords_lock_the_address_for_three_minutes(self):
        self.assertEqual(self.wrong(9), [401] * 9)
        tenth = self.client.get(URL, headers={"X-Admin-Password": "mala-10"})
        self.assertEqual(tenth.status_code, 429)
        self.assertEqual(tenth.headers["Retry-After"], "180")
        self.assertIn("Espera 3 minutos", tenth.get_json()["error"])
        right = self.client.get(URL, headers={"X-Admin-Password": "la-buena"})
        self.assertEqual(right.status_code, 429)                    # locked even with the right password

    def test_the_lock_ends_after_three_minutes(self):
        start = 1000.0
        with patch("webapp.admin.time.monotonic", return_value=start):
            self.wrong(10)
        with patch("webapp.admin.time.monotonic", return_value=start + 179):
            self.assertEqual(self.client.get(URL, headers={"X-Admin-Password": "la-buena"}).status_code, 429)
        with patch("webapp.admin.time.monotonic", return_value=start + 181):
            self.assertNotIn(self.client.get(URL, headers={"X-Admin-Password": "la-buena"}).status_code, (401, 429))

    def test_requests_without_a_password_do_not_count(self):
        for _ in range(20):                                         # the panel's first calls, before the prompt
            self.assertEqual(self.client.get(URL).status_code, 401)
        self.assertEqual(self.wrong(1), [401])

    def test_a_correct_password_resets_the_count(self):
        self.wrong(9)
        self.client.get(URL, headers={"X-Admin-Password": "la-buena"})
        self.assertEqual(self.wrong(9), [401] * 9)

    def test_the_lockout_is_logged(self):
        with self.assertLogs("student_predictor.webapp.admin", level="WARNING") as logs:
            self.wrong(10)
            self.client.get(URL, headers={"X-Admin-Password": "la-buena"})
        text = "\n".join(logs.output)
        self.assertIn("ADMIN AUTH LOCKOUT", text)
        self.assertIn("ADMIN AUTH LOCKED", text)
        self.assertNotIn("la-buena", text)                          # never the password


if __name__ == "__main__":
    unittest.main()
