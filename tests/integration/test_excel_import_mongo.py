"""Integration: Excel upload -> validation -> MongoDB -> dashboard, against a real MongoDB.

Run with MONGODB_TEST_URI set (e.g. mongodb://localhost:27018); skipped otherwise.
"""
import pytest

from tests.helpers import MongoAppTestCase, xlsx_bytes

pytestmark = pytest.mark.mongo


def row(student_id, p1=85, attendance=92, participation=88):
    return [student_id, f"Alumno {student_id}", p1, p1, p1, None, attendance, participation]


class ExcelImportIntegrationTests(MongoAppTestCase):
    def dashboard_ids(self, group_id):
        return sorted(s["student_id"] for s in self.client.get(f"/api/groups/{group_id}").get_json()["students"])

    def test_partial_import_saves_valid_rows_and_reports_the_rest(self):
        content = xlsx_bytes([row("A1"), row("A2"), row("A3", p1=150)])
        response = self.upload("G1", content, create_group="true", mode="partial")
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual((body["created"], len(body["rejected"])), (2, 1))
        self.assertEqual(body["rejected"][0]["row"], 4)
        self.assertEqual(self.dashboard_ids("G1"), ["A1", "A2"])

    def test_reimporting_the_same_file_changes_nothing(self):
        content = xlsx_bytes([row("A1"), row("A2")])
        self.upload("G1", content, create_group="true")
        again = self.upload("G1", content).get_json()
        self.assertEqual((again["created"], again["updated"], again["unchanged"]), (0, 0, 2))

    def test_reimport_with_new_values_updates_only_that_student_and_the_risk_follows(self):
        self.upload("G1", xlsx_bytes([row("A1"), row("A2")]), create_group="true")
        risk_before = {s["student_id"]: s["risk_score"] for s in self.client.get("/api/groups/G1").get_json()["students"]}
        worse = xlsx_bytes([row("A1", p1=20, attendance=30, participation=10), row("A2")])
        result = self.upload("G1", worse).get_json()
        self.assertEqual((result["updated"], result["unchanged"]), (1, 1))
        risk_after = {s["student_id"]: s["risk_score"] for s in self.client.get("/api/groups/G1").get_json()["students"]}
        self.assertGreater(risk_after["A1"], risk_before["A1"])
        self.assertEqual(risk_after["A2"], risk_before["A2"])

    def test_strict_mode_with_one_invalid_row_stores_nothing(self):
        content = xlsx_bytes([row("A1"), row("A2", p1=-5)])
        response = self.upload("G2", content, create_group="true", mode="strict")
        self.assertEqual(response.status_code, 400)
        self.assertIn("estricto", response.get_json()["error"])
        groups = [g["group_id"] for g in self.client.get("/api/groups").get_json()["groups"]]
        self.assertNotIn("G2", groups)

    def test_importing_into_an_unknown_group_requires_explicit_creation(self):
        response = self.upload("NOPE", xlsx_bytes([row("A1")]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("no existe", response.get_json()["error"])

    def test_every_import_is_logged(self):
        self.upload("G1", xlsx_bytes([row("A1")]), filename="calificaciones_301.xlsx", create_group="true")
        imports = self.client.get("/admin/api/imports").get_json()["imports"]
        self.assertEqual(imports[0]["filename"], "calificaciones_301.xlsx")
        self.assertEqual(imports[0]["group_id"], "G1")

    def test_invalid_group_ids_are_rejected_before_anything_is_written(self):
        for bad in ("bad!id", "-start", "x" * 40):
            with self.subTest(bad):
                response = self.upload(bad, xlsx_bytes([row("A1")]), create_group="true")
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/groups").get_json()["groups"], [])
