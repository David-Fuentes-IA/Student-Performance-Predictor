"""/health (liveness) and /ready (readiness).

Found in the Docker run: with MongoDB stopped, /health waited the driver's 8 s, the container
HEALTHCHECK (4 s) timed out and Docker marked a perfectly working container "unhealthy". Liveness must not
depend on the database, and a slow database must never make a health probe slow.
"""
import threading
import time
import unittest
from unittest.mock import patch

import main_api
from webapp import create_app, dashboard


class FakeDatabase:
    def __init__(self, ping):
        self.ping_calls = 0
        self._ping = ping

    def command(self, name):
        self.ping_calls += 1
        return self._ping()


class FakeMongoRepository:
    backend = "mongodb"

    def __init__(self, ping):
        self.db = FakeDatabase(ping)


def broken_ping():
    raise ConnectionError("db01.internal:27017 refused the connection")


class HealthAndReadinessTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()                                    # free a ping that is still waiting
        dashboard._db_checker.submit(lambda: None).result(timeout=10)   # let the shared worker go idle

    def with_repository(self, repository):
        return patch.object(main_api, "_repository", repository)

    def test_demo_mode_is_alive_and_ready_without_a_database(self):
        health, ready = self.client.get("/health"), self.client.get("/ready")
        self.assertEqual((health.status_code, ready.status_code), (200, 200))
        self.assertEqual((health.get_json()["mode"], health.get_json()["database"]), ("demo", False))
        self.assertTrue(ready.get_json()["ready"])

    def test_working_database_means_ok_and_ready(self):
        with self.with_repository(FakeMongoRepository(lambda: {"ok": 1})):
            health, ready = self.client.get("/health").get_json(), self.client.get("/ready")
        self.assertEqual((health["status"], health["database"], health["mode"]), ("ok", True, "database"))
        self.assertEqual(ready.status_code, 200)

    def test_unreachable_database_keeps_liveness_green_but_readiness_red(self):
        with self.with_repository(FakeMongoRepository(broken_ping)):
            health, ready = self.client.get("/health"), self.client.get("/ready")
        self.assertEqual(health.status_code, 200)             # alive: restarting would not fix the database
        self.assertEqual((health.get_json()["status"], health.get_json()["database"]), ("degraded", False))
        self.assertEqual(ready.status_code, 503)               # but do not send it traffic
        self.assertFalse(ready.get_json()["ready"])
        self.assertNotIn("db01.internal", ready.get_data(as_text=True))

    def test_a_slow_database_never_makes_the_probes_slow(self):
        slow = FakeMongoRepository(lambda: self.release.wait(10))
        with self.with_repository(slow):
            started = time.perf_counter()
            health = self.client.get("/health")
            elapsed = time.perf_counter() - started
        self.assertEqual(health.status_code, 200)
        self.assertFalse(health.get_json()["database"])
        self.assertLess(elapsed, dashboard._DB_CHECK_TIMEOUT_SECONDS + 1.0)   # far below the driver's 8 s

    def test_the_database_is_not_pinged_on_every_probe(self):
        repository = FakeMongoRepository(lambda: {"ok": 1})
        with self.with_repository(repository):
            for _ in range(5):
                self.client.get("/health")
                self.client.get("/ready")
        self.assertEqual(repository.db.ping_calls, 1)

    def test_a_missing_model_is_alive_but_not_ready(self):
        with patch.object(main_api, "_trained_model", None):
            health, ready = self.client.get("/health"), self.client.get("/ready")
        self.assertEqual(health.status_code, 200)
        self.assertFalse(health.get_json()["model_loaded"])
        self.assertEqual(health.get_json()["status"], "degraded")
        self.assertEqual(ready.status_code, 503)


if __name__ == "__main__":
    unittest.main()
