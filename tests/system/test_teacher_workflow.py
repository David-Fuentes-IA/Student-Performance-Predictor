"""System: the whole application as a teacher uses it, against a real MongoDB.

Checklist from lesson 17: valid input accepted, predictions generated, reports displayed
correctly, and the workflow finishes within the response time required by NFR-1
(<= 10 s for a group of 50). Run with MONGODB_TEST_URI set; skipped otherwise.
"""
import statistics
import time
from io import BytesIO

import pytest
from pypdf import PdfReader

from tests.helpers import MongoAppTestCase, class_rows, xlsx_bytes

pytestmark = pytest.mark.mongo

GROUP_RESPONSE_LIMIT_SECONDS = 10.0  # NFR-1, group of 50


def pdf_text(data):
    return " ".join(" ".join(p.extract_text().split()) for p in PdfReader(BytesIO(data)).pages)


class TeacherWorkflowTests(MongoAppTestCase):
    def test_create_group_import_excel_analyse_and_download_reports(self):
        # 1. The administrator creates the group and imports the class list.
        created = self.client.post("/admin/api/groups", json={
            "group_id": "SYS-1", "name": "Ingenieria de Software II", "period": "2026-B", "teacher": "Docente"})
        self.assertEqual(created.status_code, 201)
        rows = class_rows(50)
        imported = self.upload("SYS-1", xlsx_bytes(rows))
        self.assertEqual((imported.status_code, imported.get_json()["created"]), (200, 50))

        # 2. The group is offered in the dashboard selector with its real size.
        groups = {g["group_id"]: g["student_count"] for g in self.client.get("/api/groups").get_json()["groups"]}
        self.assertEqual(groups["SYS-1"], 50)

        # 3. Predictions are generated for everyone, inside the NFR-1 response time.
        started = time.perf_counter()
        response = self.client.get("/api/groups/SYS-1")
        elapsed = time.perf_counter() - started
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, GROUP_RESPONSE_LIMIT_SECONDS)
        students = data["students"]
        self.assertEqual(len(students), 50)
        self.assertEqual(sum(data["summary"]["counts"].values()), 50)
        for student in students:
            self.assertTrue(0 <= student["risk_score"] <= 100)
            self.assertIn(student["risk_label"], {"low", "medium", "high"})

        # 4. The model separates the students who were built to be at risk (every 5th row).
        at_risk_ids = {r[0] for i, r in enumerate(rows) if i % 5 == 0}
        risky = [s["risk_score"] for s in students if s["student_id"] in at_risk_ids]
        others = [s["risk_score"] for s in students if s["student_id"] not in at_risk_ids]
        self.assertGreater(statistics.mean(risky), statistics.mean(others))

        # 5. Both PDF reports download and contain the data shown on screen.
        group_pdf = self.client.get("/reports/groups/SYS-1.pdf")
        self.assertEqual((group_pdf.status_code, group_pdf.mimetype), (200, "application/pdf"))
        text = pdf_text(group_pdf.data)
        self.assertIn(rows[0][0], text)
        self.assertIn(rows[-1][0], text)
        student = students[0]
        student_pdf = self.client.get(f"/reports/groups/SYS-1/students/{student['student_id']}.pdf")
        self.assertEqual(student_pdf.status_code, 200)
        self.assertIn(f"{student['risk_score']:.1f}/100", pdf_text(student_pdf.data))

    def test_changing_a_students_data_changes_the_prediction_for_the_next_report(self):
        self.client.post("/admin/api/groups", json={"group_id": "SYS-2"})
        good = ["Z1", "Alumno Z1", 90, 92, 95, 94, 96, 92]
        self.upload("SYS-2", xlsx_bytes([good]))
        before = self.client.get("/api/groups/SYS-2").get_json()["students"][0]["risk_score"]
        failing = ["Z1", "Alumno Z1", 25, 20, 15, 10, 35, 15]
        self.upload("SYS-2", xlsx_bytes([failing]))
        after = self.client.get("/api/groups/SYS-2").get_json()["students"][0]["risk_score"]
        self.assertGreater(after, before)

    def test_a_group_with_no_students_is_a_valid_empty_report(self):
        self.client.post("/admin/api/groups", json={"group_id": "EMPTY-1"})
        data = self.client.get("/api/groups/EMPTY-1").get_json()
        self.assertEqual((data["students"], data["summary"]["total"]), ([], 0))
        self.assertEqual(self.client.get("/reports/groups/EMPTY-1.pdf").status_code, 200)

    def test_health_reports_a_working_database(self):
        body = self.client.get("/health").get_json()
        self.assertEqual((body["mode"], body["database"], body["model_loaded"]), ("database", True, True))
        self.assertEqual(body["status"], "ok")
