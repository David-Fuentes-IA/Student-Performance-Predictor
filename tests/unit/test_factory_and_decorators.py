import unittest
from unittest.mock import patch

from core.exception_handler import PredictionEngineError
from feature_store.feature_manager import FeatureVector
from inference_engine.cache_manager import AuditDecorator, CachingDecorator
from inference_engine.risk_predictor import (
    IRiskPredictionEngine,
    LogisticRegressionRiskEngine,
    RandomForestRiskEngine,
    RiskResult,
    create_risk_engine,
)

CACHE_LOGGER = "student_predictor.inference_engine.cache_manager"


class FixedModel:
    def __init__(self, probability=0.4):
        self.probability = probability

    def predict_proba(self, rows):
        return [[1 - self.probability, self.probability] for _ in rows]


class BrokenModel:
    def predict_proba(self, rows):
        raise RuntimeError("internal failure in /opt/models/rf.bin")


class CountingEngine(IRiskPredictionEngine):
    def __init__(self):
        self.calls = 0

    def predict_risk(self, feature_vector):
        self.calls += 1
        return RiskResult(feature_vector.student_ref, 20.0, "low")


def vector(ref="S1", grade=70.0):
    return FeatureVector(ref, grade, 0.0, 90.0, 80.0)


class FactoryTests(unittest.TestCase):
    def test_builds_each_registered_strategy(self):
        self.assertIsInstance(create_risk_engine("random_forest", trained_model=FixedModel()), RandomForestRiskEngine)
        self.assertIsInstance(create_risk_engine("logistic_regression", trained_model=FixedModel()),
                              LogisticRegressionRiskEngine)

    def test_engine_type_is_case_and_whitespace_insensitive(self):
        self.assertIsInstance(create_risk_engine("  Random_Forest ", trained_model=FixedModel()), RandomForestRiskEngine)

    def test_unknown_engine_type_is_a_clear_error(self):
        for bad in ("xgboost", "", "random forest"):
            with self.subTest(bad), self.assertRaises(PredictionEngineError) as ctx:
                create_risk_engine(bad, trained_model=FixedModel())
            self.assertIn("not supported", ctx.exception.user_message)

    def test_engine_without_a_model_is_rejected(self):
        for engine_type in ("random_forest", "logistic_regression"):
            with self.subTest(engine_type), self.assertRaises(PredictionEngineError):
                create_risk_engine(engine_type, trained_model=None)


class EngineTests(unittest.TestCase):
    def test_probability_becomes_a_0_to_100_score_rounded_to_one_decimal(self):
        result = RandomForestRiskEngine(FixedModel(0.4567)).predict_risk(vector())
        self.assertEqual(result.risk_score, 45.7)
        self.assertEqual((result.student_ref, result.risk_label), ("S1", "medium"))

    def test_extreme_probabilities(self):
        self.assertEqual(RandomForestRiskEngine(FixedModel(0.0)).predict_risk(vector()).risk_score, 0.0)
        self.assertEqual(RandomForestRiskEngine(FixedModel(1.0)).predict_risk(vector()).risk_label, "high")

    def test_model_failure_becomes_a_safe_prediction_engine_error(self):
        with self.assertRaises(PredictionEngineError) as ctx:
            RandomForestRiskEngine(BrokenModel()).predict_risk(vector())
        self.assertNotIn("/opt/models", ctx.exception.user_message)
        self.assertIn("/opt/models", str(ctx.exception))  # kept for the developer log


class DecoratorTests(unittest.TestCase):
    def test_audit_decorator_returns_the_wrapped_result_unchanged(self):
        inner = CountingEngine()
        self.assertEqual(AuditDecorator(inner).predict_risk(vector()), RiskResult("S1", 20.0, "low"))

    def test_clear_cache_forces_a_new_inference(self):
        inner = CountingEngine()
        cache = CachingDecorator(inner)
        cache.predict_risk(vector())
        cache.clear_cache()
        cache.predict_risk(vector())
        self.assertEqual(inner.calls, 2)

    def test_different_students_do_not_share_cache_entries(self):
        inner = CountingEngine()
        cache = CachingDecorator(inner)
        cache.predict_risk(vector("S1"))
        cache.predict_risk(vector("S2"))
        self.assertEqual(inner.calls, 2)

    def test_cache_stays_bounded(self):
        inner = CountingEngine()
        cache = CachingDecorator(inner)
        with patch.object(CachingDecorator, "_MAX_ENTRIES", 5):
            for i in range(40):
                cache.predict_risk(vector(f"S{i}"))
        self.assertLessEqual(len(cache._cache), 5)

    def test_a_cache_hit_does_not_reach_the_audit_trail(self):
        # Figure 5 order: Caching(Audit(engine)) - the audit only records real inferences.
        stack = CachingDecorator(AuditDecorator(CountingEngine(), model_version="v-test"))
        with self.assertLogs(CACHE_LOGGER, level="INFO") as first:
            stack.predict_risk(vector())
        self.assertTrue(any("AUDIT-TRAIL" in line for line in first.output))
        with self.assertLogs(CACHE_LOGGER, level="INFO") as second:
            stack.predict_risk(vector())
        self.assertFalse(any("AUDIT-TRAIL" in line for line in second.output))
        self.assertTrue(any("Cache hit" in line for line in second.output))


class BatchPredictionTests(unittest.TestCase):
    """Phase 8 optimisation: one model call per group instead of one per student."""

    def vectors(self, n=5):
        return [FeatureVector(f"S{i}", 50.0 + i * 5, 0.0, 80.0, 70.0) for i in range(n)]

    def test_batch_and_one_by_one_give_identical_results(self):
        for engine_class in (RandomForestRiskEngine, LogisticRegressionRiskEngine):
            with self.subTest(engine_class.__name__):
                engine = engine_class(FixedModel(0.62))
                vectors = self.vectors()
                self.assertEqual(engine.predict_many(vectors), [engine.predict_risk(v) for v in vectors])

    def test_empty_group(self):
        self.assertEqual(RandomForestRiskEngine(FixedModel()).predict_many([]), [])

    def test_a_failing_batch_names_the_students_but_hides_internals(self):
        with self.assertRaises(PredictionEngineError) as ctx:
            RandomForestRiskEngine(BrokenModel()).predict_many(self.vectors(3))
        self.assertIn("S0", str(ctx.exception))
        self.assertNotIn("/opt/models", ctx.exception.user_message)

    def test_the_cache_sends_only_the_missing_students_to_the_engine_and_keeps_the_order(self):
        inner = CountingEngine()
        cache = CachingDecorator(inner)
        first = self.vectors(3)
        cache.predict_many(first)
        self.assertEqual(inner.calls, 3)
        mixed = [first[2], FeatureVector("NEW", 70.0, 0.0, 90.0, 80.0), first[0]]
        results = cache.predict_many(mixed)
        self.assertEqual(inner.calls, 4)
        self.assertEqual([r.student_ref for r in results], ["S2", "NEW", "S0"])

    def test_the_audit_trail_still_has_one_line_per_student(self):
        engine = AuditDecorator(CountingEngine(), model_version="v-batch")
        with self.assertLogs(CACHE_LOGGER, level="INFO") as logs:
            engine.predict_many(self.vectors(4))
        lines = [line for line in logs.output if "AUDIT-TRAIL" in line]
        self.assertEqual(len(lines), 4)
        self.assertTrue(all("batch=4" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
