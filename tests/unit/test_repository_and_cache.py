import unittest
from unittest.mock import patch

from core.exception_handler import GroupNotFoundError
from data_access.student_repository import InMemoryAcademicRepository
from feature_store.feature_manager import FeatureVector
from inference_engine.cache_manager import CachingDecorator
from inference_engine.risk_predictor import IRiskPredictionEngine, RiskResult


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


if __name__ == "__main__":
    unittest.main()
