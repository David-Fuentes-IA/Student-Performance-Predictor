import os
import unittest
import uuid
from unittest.mock import patch

import main_api
from core.exception_handler import GroupNotFoundError
from data_access.student_repository import InMemoryAcademicRepository
from feature_store.feature_manager import FeatureVector
from inference_engine.cache_manager import CachingDecorator
from inference_engine.risk_predictor import IRiskPredictionEngine, RiskResult
from webapp import create_app


class CountingEngine(IRiskPredictionEngine):
    def __init__(self):
        self.calls = 0

    def predict_risk(self, feature_vector):
        self.calls += 1
        return RiskResult(feature_vector.student_ref, 10.0, "low")


def vector(grade=80.0, ref="S1"):
    return FeatureVector(ref, grade, 0.0, 90.0, 70.0)


class InMemoryRepositoryTests(unittest.TestCase):
    def test_lists_only_demo_groups(self):
        repo = InMemoryAcademicRepository()
        self.assertEqual([g["group_id"] for g in repo.list_groups()], ["301-A", "301-B", "301-C"])

    def test_unknown_group_is_not_invented(self):
        with self.assertRaises(GroupNotFoundError):
            InMemoryAcademicRepository().get_group("FAKE-99")


class CacheKeyTests(unittest.TestCase):
    def test_same_data_hits_cache(self):
        engine = CountingEngine()
        cache = CachingDecorator(engine)
        cache.predict_risk(vector())
        cache.predict_risk(vector())
        self.assertEqual(engine.calls, 1)

    def test_changed_data_for_same_student_is_recomputed(self):
        engine = CountingEngine()
        cache = CachingDecorator(engine)
        cache.predict_risk(vector(grade=80.0))
        cache.predict_risk(vector(grade=40.0))
        self.assertEqual(engine.calls, 2)

    def test_entry_expires_after_ttl(self):
        engine = CountingEngine()
        cache = CachingDecorator(engine)
        with patch("inference_engine.cache_manager.time.monotonic", side_effect=[0.0, 61.0, 61.0]):
            cache.predict_risk(vector())
            cache.predict_risk(vector())
        self.assertEqual(engine.calls, 2)


class UnifiedAppDemoModeTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_group_selector_lists_groups_and_flags_demo_mode(self):
        payload = self.client.get("/api/groups").get_json()
        self.assertEqual([g["group_id"] for g in payload["groups"]], ["301-A", "301-B", "301-C"])
        self.assertEqual(payload["mode"], "demo")
        self.assertIn("Modo demo", payload["notice"])

    def test_dashboard_uses_select_and_links_to_admin(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('<select id="group"', html)
        self.assertIn('href="/admin"', html)

    def test_nonexistent_group_returns_404_everywhere(self):
        for path in ("/api/groups/FAKE-99", "/reports/groups/FAKE-99.pdf",
                     "/api/v1/groups/FAKE-99/risk-report"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertIn("no existe", response.get_json()["error"])

    def test_health_reports_demo_mode_without_details(self):
        response = self.client.get("/health")
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["mode"], "demo")
        self.assertTrue(body["model_loaded"])
        self.assertFalse(body["database"])
        self.assertEqual(body["status"], "degraded")

    def test_admin_page_loads_but_api_requires_database(self):
        page = self.client.get("/admin/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('href="/"', page.get_data(as_text=True))  # link back to the dashboard
        response = self.client.get("/admin/api/groups")
        self.assertEqual(response.status_code, 503)
        self.assertIn("modo demo", response.get_json()["error"])

    def test_admin_and_dashboard_share_the_orchestrator_repository(self):
        from webapp import admin
        self.assertIs(main_api.get_repository(), main_api._repository)
        with patch("webapp.admin.main_api.get_repository", return_value=InMemoryAcademicRepository()):
            with self.assertRaises(Exception):
                admin.repo()


@unittest.skipUnless(os.getenv("MONGODB_TEST_URI"), "set MONGODB_TEST_URI to run against a real MongoDB")
class AdminToDashboardIntegrationTests(unittest.TestCase):
    """A group created in /admin must be analysable in / with no restart."""

    def setUp(self):
        from pymongo import MongoClient
        from data_access.mongo_repository import MongoAcademicRepository
        from data_pipeline.etl_processor import ETLProcessor

        self.mongo = MongoClient(os.environ["MONGODB_TEST_URI"])
        self.db = self.mongo[f"spp_test_{uuid.uuid4().hex[:8]}"]
        self.repo = MongoAcademicRepository(db=self.db)
        self.patches = [
            patch.object(main_api, "_repository", self.repo),
            patch.object(main_api, "_etl", ETLProcessor(self.repo)),
        ]
        for p in self.patches:
            p.start()
        self.client = create_app().test_client()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.mongo.drop_database(self.db.name)
        self.mongo.close()

    def test_created_group_and_student_appear_in_dashboard(self):
        self.assertEqual(self.client.post("/admin/api/groups", json={"group_id": "T-1"}).status_code, 201)
        student = {"student_id": "M001", "name": "Ana Prueba", "grades": [90, 85, 88],
                   "attendance_pct": 95, "participation_score": 90}
        self.assertEqual(self.client.post("/admin/api/groups/T-1/students", json=student).status_code, 201)

        groups = self.client.get("/api/groups").get_json()
        self.assertEqual(groups["mode"], "database")
        self.assertIn("T-1", [g["group_id"] for g in groups["groups"]])

        data = self.client.get("/api/groups/T-1").get_json()
        self.assertEqual([s["student_id"] for s in data["students"]], ["M001"])

        # Changing the student's data must change the prediction immediately (cache keyed by data).
        before = data["students"][0]["risk_score"]
        worse = dict(student, grades=[20, 15, 10], attendance_pct=30, participation_score=10)
        self.client.post("/admin/api/groups/T-1/students", json=worse)
        after = self.client.get("/api/groups/T-1").get_json()["students"][0]["risk_score"]
        self.assertGreater(after, before)

    def test_missing_group_is_404_not_503(self):
        self.assertEqual(self.client.get("/api/groups/NOPE").status_code, 404)


if __name__ == "__main__":
    unittest.main()
