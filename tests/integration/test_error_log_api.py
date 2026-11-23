"""Integration: the error log seen from the web (reference codes, the admin viewer, the PDF and CSV exports).

The user only ever sees a short message plus a reference code; the administrator finds that exact request in the
log, with the technical detail. Runs without a database (memory store) and, when MONGODB_TEST_URI is set, against a
real MongoDB, where events are kept for all time."""
import unittest
from unittest.mock import Mock, patch

import main_api
from core import event_log
from core.exception_handler import PredictionEngineError
from tests.helpers import MongoAppTestCase
from webapp import create_app


def events(client, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get("/admin/api/error-log?" + query).get_json()


class ReferenceCodeTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_every_error_answer_carries_a_reference_code_and_no_internals(self):
        failing = Mock()
        failing.predict_many.side_effect = PredictionEngineError("model crashed at /opt/model/rf.bin")
        with patch.object(main_api, "_engine", failing):
            responses = [self.client.get("/api/groups/301-A"),                       # 503
                         self.client.get("/api/groups/bad id!"),                     # 400
                         self.client.get("/api/no-existe")]                          # 404
        for response in responses:
            with self.subTest(status=response.status_code):
                body = response.get_json()
                self.assertRegex(body["ref"], r"^[0-9A-F]{8}$")
                self.assertEqual(response.headers["X-Request-ID"], body["ref"])
                self.assertNotIn("/opt/model", response.get_data(as_text=True))

    def test_a_wrong_page_shows_the_reference_code(self):
        response = self.client.get("/no-existe")
        self.assertIn("Codigo de referencia", response.get_data(as_text=True))

    def test_successful_answers_are_unchanged(self):
        body = self.client.get("/api/groups/301-A").get_json()
        self.assertNotIn("ref", body)


class ViewerInDemoModeTests(unittest.TestCase):
    """Without a database the log lives in memory, and the viewer still works."""

    def setUp(self):
        self.client = create_app().test_client()

    def test_the_rejected_request_appears_with_the_code_the_user_saw(self):
        ref = self.client.get("/api/groups/bad id!").get_json()["ref"]
        body = events(self.client, q=ref)
        self.assertFalse(body["persistent"])
        self.assertEqual(body["total"], 1)
        entry = body["events"][0]
        self.assertEqual((entry["status"], entry["kind"]), (400, "solicitud rechazada"))
        self.assertIn("Identificador de grupo", entry["message"])

    def test_bad_filters_are_400(self):
        for params in ({"level": "BOGUS"}, {"kind": "nada"}, {"from": "2026-13-01"},
                       {"from": "2026-11-20", "to": "2026-11-01"}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/admin/api/error-log", query_string=params).status_code, 400)

    def test_favicon_requests_are_not_noise_in_the_log(self):
        before = events(self.client)["counts"]["total"]
        self.client.get("/favicon.ico")
        self.assertEqual(events(self.client)["counts"]["total"], before)


class MongoErrorLogTests(MongoAppTestCase):
    def test_events_are_stored_in_mongodb_with_the_traceback_for_the_admin_only(self):
        failing = Mock()
        failing.predict_many.side_effect = RuntimeError("something unforeseen")
        self.client.post("/admin/api/groups", json={"group_id": "G1"})
        self.client.post("/admin/api/groups/G1/students", json={"student_id": "S1", "name": "Ana", "grades": [80],
                                                                "attendance_pct": 90, "participation_score": 80})
        with patch.object(main_api, "_engine", failing):
            user_view = self.client.get("/api/groups/G1")
        self.assertEqual(user_view.status_code, 503)
        self.assertNotIn("unforeseen", user_view.get_data(as_text=True))
        ref = user_view.get_json()["ref"]

        body = events(self.client, q=ref)
        self.assertTrue(body["persistent"])
        self.assertGreaterEqual(body["total"], 1)
        self.assertTrue(any(e.get("traceback") for e in body["events"]))
        event_log.get_event_log().flush()
        self.assertGreaterEqual(self.db[event_log.COLLECTION].count_documents({"ref": ref}), 1)

    def test_pdf_and_csv_exports_contain_the_failures_safely(self):
        self.client.get("/api/groups/<script>alert(1)</script>")
        self.client.post("/admin/api/groups", data='{"group_id": "=HYPERLINK(1)"}', content_type="application/json")
        pdf = self.client.get("/admin/api/error-log/export.pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        csv = self.client.get("/admin/api/error-log/export.csv")
        self.assertEqual(csv.status_code, 200)
        self.assertIn("attachment", csv.headers["Content-Disposition"])
        text = csv.get_data(as_text=True)
        self.assertIn("solicitud rechazada", text)
        self.assertNotIn(",=", text)                      # a formula never starts a cell (CSV injection)

    def test_the_log_needs_the_admin_password_when_one_is_set(self):
        with patch.dict("os.environ", {"ADMIN_PASSWORD": "pw-test"}):
            client = create_app().test_client()
            for url in ("/admin/api/error-log", "/admin/api/error-log/export.pdf", "/admin/api/error-log/export.csv"):
                with self.subTest(url=url):
                    self.assertEqual(client.get(url).status_code, 401)
