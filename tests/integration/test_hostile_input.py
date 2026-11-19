"""Integration: inputs a hostile client sends to the admin API (Milestone 4 adversarial review).

Each case was found by fuzzing every route against a throw-away MongoDB: before the fix it either answered 500 or
stored something it should have rejected (a group literally called "None", a grade of 1 from JSON `true`).
The rule checked here: bad input gets a 400 with a Spanish message, and nothing is written."""
import io
import unittest

from openpyxl import Workbook

from tests.helpers import MongoAppTestCase
from webapp import create_app

HEADER = ["matricula", "nombre", "parcial1", "parcial2", "parcial3", "asistencia_pct", "participacion"]


def workbook(*rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(list(r))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class HostileJsonTests(MongoAppTestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.client.post("/admin/api/groups", json={"group_id": "G1"}).status_code, 201)

    def groups(self):
        return [g["group_id"] for g in self.client.get("/admin/api/groups").get_json()["groups"]]

    def student(self, **fields):
        body = {"student_id": "S1", "name": "Ana", "grades": [80], "attendance_pct": 90, "participation_score": 80, **fields}
        return self.client.post("/admin/api/groups/G1/students", json=body)

    def test_null_text_fields_are_empty_not_the_word_none(self):
        response = self.client.post("/admin/api/groups", json={"group_id": None})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("None", self.groups())

    def test_objects_and_lists_are_not_accepted_as_text(self):
        for value in ({"$ne": None}, ["G2"], True):
            with self.subTest(value=value):
                response = self.client.post("/admin/api/groups", json={"group_id": "G2", "teacher": value})
                self.assertEqual(response.status_code, 400)
                self.assertIn("texto", response.get_json()["error"])
        self.assertNotIn("G2", self.groups())

    def test_a_numeric_matricula_is_still_accepted(self):
        self.assertEqual(self.student(student_id=12345).status_code, 201)

    def test_booleans_and_nulls_are_not_numbers(self):
        for fields in ({"grades": [True]}, {"attendance_pct": True}, {"participation_score": None}, {"grades": [None]}):
            with self.subTest(fields=fields):
                self.assertEqual(self.student(**fields).status_code, 400)
        self.assertEqual(self.client.get("/admin/api/groups/G1/students").get_json()["students"], [])

    def test_more_partials_than_the_form_has_is_a_400_not_a_database_error(self):
        response = self.student(grades=[80] * 50)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Maximo 4", response.get_json()["error"])

    def test_out_of_range_values_get_a_spanish_message_with_the_value(self):
        for fields, word in (({"grades": [150]}, "calificacion"), ({"attendance_pct": -5}, "asistencia"),
                             ({"participation_score": 101}, "participacion"), ({"grades": ["NaN"]}, "calificacion")):
            with self.subTest(fields=fields):
                response = self.student(**fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn(word, response.get_json()["error"])

    def test_seed_rejects_bodies_that_are_not_objects_and_absurd_counts(self):
        for raw in ("123", '"texto"', "[1]", '{"count": 1e400}', '{"count": true}', '{"count": "abc"}'):
            with self.subTest(body=raw):
                response = self.client.post("/admin/api/seed", data=raw, content_type="application/json")
                self.assertEqual(response.status_code, 400)

    def test_a_huge_skip_in_the_collection_browser_is_not_a_500(self):
        response = self.client.get("/admin/api/collections/students?skip=99999999999999999999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["documents"], [])


class WrongUrlTests(unittest.TestCase):
    """Typing a wrong address or method gets a Spanish answer (JSON for the API, a page for the browser)."""

    def setUp(self):
        self.client = create_app().test_client()

    def test_wrong_api_url_and_method_answer_in_spanish_json(self):
        cases = (("get", "/api/no-existe", 404, "no existe"), ("delete", "/api/groups", 405, "no admite"),
                 ("get", "/admin/api/collections/", 404, "no existe"))
        for method, url, status, text in cases:
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, status)
                self.assertIn(text, response.get_json()["error"])

    def test_wrong_page_url_gets_a_spanish_page_with_a_way_back(self):
        for url in ("/no-existe", "/.env", "/static/../.env"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                body = response.get_data(as_text=True)
                self.assertIn("no existe", body)
                self.assertIn('href="/"', body)
                self.assertNotIn("Not Found", body)


class HostileExcelTests(MongoAppTestCase):
    def test_rejected_rows_are_explained_in_spanish_and_valid_rows_survive(self):
        content = workbook(("S1", "Ana", 80, 70, 60, 90, 80), ("S2", "Out", 101, 80, 80, 90, 80),
                           ("S3", "Neg", 80, 80, 80, -1, 80), ("S4", "Bool", True, 70, 70, 90, 80),
                           ("S5", "<script>alert(1)</script>", 50, 40, None, 70, 60))
        response = self.upload("X1", content, create_group="true")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["created"], 2)
        reasons = {r["student_id"]: r["reason"] for r in body["rejected"]}
        self.assertIn("calificacion invalida: 101", reasons["S2"])
        self.assertIn("asistencia invalida", reasons["S3"])
        self.assertIn("no numerico", reasons["S4"])
        for reason in reasons.values():
            self.assertNotIn("student '", reason)    # the internal English message must not reach the panel

    def test_a_file_that_is_not_really_an_xlsx_is_rejected_cleanly(self):
        for content in (b"", b"hello", b"MZ\x90\x00" * 100):
            with self.subTest(size=len(content)):
                response = self.upload("X2", content, create_group="true")
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("X2", [g["group_id"] for g in self.client.get("/admin/api/groups").get_json()["groups"]])
