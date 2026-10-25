"""Integration: the administration API against a real MongoDB (groups, students, seeding,
database browser and the optional ADMIN_PASSWORD protection, NFR-2)."""
import os
from unittest.mock import patch

import pytest

from tests.helpers import MongoAppTestCase

pytestmark = pytest.mark.mongo

GOOD = {"student_id": "M001", "name": "Ana Prueba", "grades": [80, 85, 90],
        "attendance_pct": 95, "participation_score": 90}


class GroupAndStudentManagementTests(MongoAppTestCase):
    def setUp(self):
        super().setUp()
        self.client.post("/admin/api/groups", json={"group_id": "G1", "name": "Grupo uno"})

    def test_duplicate_and_invalid_group_ids_are_rejected(self):
        duplicate = self.client.post("/admin/api/groups", json={"group_id": "G1"})
        self.assertEqual((duplicate.status_code, "ya existe" in duplicate.get_json()["error"]), (400, True))
        for bad in ("", "has space", "-x", "y" * 40):
            with self.subTest(bad):
                self.assertEqual(self.client.post("/admin/api/groups", json={"group_id": bad}).status_code, 400)

    def test_request_body_must_be_json(self):
        response = self.client.post("/admin/api/groups", data="not json", content_type="text/plain")
        self.assertEqual(response.status_code, 400)

    def test_manual_student_validation_messages(self):
        cases = {
            "no grades": dict(GOOD, grades=[]),
            "grade out of range": dict(GOOD, grades=[150]),
            "text grade": dict(GOOD, grades=["abc"]),
            "empty name": dict(GOOD, name="  "),
            "id too long": dict(GOOD, student_id="x" * 40),
            "attendance out of range": dict(GOOD, attendance_pct=120),
        }
        for label, payload in cases.items():
            with self.subTest(label):
                response = self.client.post("/admin/api/groups/G1/students", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("Traceback", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/admin/api/groups/G1/students").get_json()["students"], [])

    def test_add_list_history_and_delete_a_student(self):
        self.assertEqual(self.client.post("/admin/api/groups/G1/students", json=GOOD).status_code, 201)
        self.client.post("/admin/api/groups/G1/students", json=dict(GOOD, grades=[40, 45, 50]))
        listed = self.client.get("/admin/api/groups/G1/students").get_json()["students"]
        self.assertEqual((len(listed), listed[0]["grades"]), (1, [40.0, 45.0, 50.0]))
        history = self.client.get("/admin/api/groups/G1/students/M001/history").get_json()["history"]
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(self.client.delete("/admin/api/groups/G1/students/M001").status_code, 200)
        self.assertEqual(self.client.delete("/admin/api/groups/G1/students/M001").status_code, 404)

    def test_clear_students_then_delete_the_group(self):
        self.client.post("/admin/api/groups/G1/students", json=GOOD)
        self.assertEqual(self.client.delete("/admin/api/groups/G1/students").get_json()["deleted"], 1)
        self.assertEqual(self.client.delete("/admin/api/groups/G1").status_code, 200)
        self.assertEqual(self.client.get("/api/groups/G1").status_code, 404)
        self.assertEqual(self.client.delete("/admin/api/groups/G1").status_code, 404)

    def test_operations_on_an_unknown_group_are_404(self):
        for method, path in (("get", "/admin/api/groups/NOPE/students"), ("delete", "/admin/api/groups/NOPE/students")):
            self.assertEqual(getattr(self.client, method)(path).status_code, 404, path)


class SeedingAndBrowserTests(MongoAppTestCase):
    def test_seed_is_idempotent_and_purge_leaves_real_groups_alone(self):
        self.client.post("/admin/api/groups", json={"group_id": "REAL-1"})
        self.client.post("/admin/api/groups/REAL-1/students", json=GOOD)
        first = self.client.post("/admin/api/seed", json={"count": 30}).get_json()
        again = self.client.post("/admin/api/seed", json={"count": 30}).get_json()
        self.assertEqual((first["created"], again["created"], again["unchanged"]), (30, 0, 30))
        self.assertEqual(self.client.delete("/admin/api/seed").status_code, 200)
        remaining = [g["group_id"] for g in self.client.get("/admin/api/groups").get_json()["groups"]]
        self.assertEqual(remaining, ["REAL-1"])
        self.assertEqual(len(self.client.get("/admin/api/groups/REAL-1/students").get_json()["students"]), 1)

    def test_seed_count_is_validated(self):
        for bad in (0, 501, "many", None):
            with self.subTest(bad):
                self.assertEqual(self.client.post("/admin/api/seed", json={"count": bad}).status_code, 400)

    def test_stats_and_database_browser(self):
        self.client.post("/admin/api/seed", json={"count": 12})
        stats = self.client.get("/admin/api/stats").get_json()["collections"]
        self.assertEqual((stats["groups"], stats["academic_records"]), (3, 12))
        page = self.client.get("/admin/api/collections/academic_records?limit=5").get_json()
        self.assertEqual((page["total"], len(page["documents"])), (12, 5))
        self.assertNotIn("name", page["documents"][0])  # academic records carry no personal name (DR-1)

    def test_browser_refuses_unknown_collections(self):
        self.assertEqual(self.client.get("/admin/api/collections/system.users").status_code, 400)


class AdminPasswordTests(MongoAppTestCase):
    def test_every_admin_api_route_is_protected_except_the_public_ones(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "s3cret"}):
            self.assertEqual(self.client.get("/admin/api/groups").status_code, 401)
            self.assertEqual(self.client.get("/admin/api/groups", headers={"X-Admin-Password": "wrong"}).status_code, 401)
            self.assertEqual(self.client.post("/admin/api/seed", json={"count": 5}).status_code, 401)
            self.assertEqual(self.client.get("/admin/api/groups", headers={"X-Admin-Password": "s3cret"}).status_code, 200)
            for public in ("/admin/api/health", "/admin/api/auth-required", "/admin/api/template.xlsx"):
                self.assertEqual(self.client.get(public).status_code, 200, public)
            self.assertTrue(self.client.get("/admin/api/auth-required").get_json()["required"])

    def test_without_a_configured_password_the_panel_is_open(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": ""}):
            self.assertEqual(self.client.get("/admin/api/groups").status_code, 200)
            self.assertFalse(self.client.get("/admin/api/auth-required").get_json()["required"])
