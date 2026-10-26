"""Memory profiling checks (tracemalloc). The same measurements, at smaller sizes, feed
docs/evidence/testing/memory_profile.json via scripts/memory_profile.py.

Limits are deliberately loose: they catch leaks and accidental O(n^2) behaviour, not
machine-to-machine noise. The real numbers live in the evidence file.
"""
import unittest

from feature_store.feature_manager import FeatureManager
from inference_engine.cache_manager import CachingDecorator
from scripts.memory_profile import (
    measure,
    profile_cache_growth,
    profile_excel_parse,
    profile_feature_extraction,
    profile_model_load,
    pure_python_baseline,
    synthetic_records,
)

MIB = 1024  # numbers below are in KiB


class FeatureExtractionMemoryTests(unittest.TestCase):
    def test_batch_extraction_matches_the_pure_python_baseline(self):
        # Two independently rounded values can differ by one hundredth on an exact tie (e.g. 64.325).
        records = synthetic_records(2_000)
        batch = FeatureManager.extract_many(records)
        baseline = pure_python_baseline(records)
        for new, old in zip(batch, baseline, strict=True):
            self.assertEqual(new.student_ref, old.student_ref)
            self.assertAlmostEqual(new.average_grade, old.average_grade, delta=0.0101)
            self.assertAlmostEqual(new.grade_trend, old.grade_trend, delta=0.0101)

    def test_memory_grows_roughly_linearly_with_the_number_of_students(self):
        small, large = profile_feature_extraction(sizes=(1_000, 8_000))
        ratio = (large["extract_many_pandas_numpy"]["peak_kib"] /
                 small["extract_many_pandas_numpy"]["peak_kib"])
        self.assertLess(ratio, 8 * 3)  # 8x the students must not cost anywhere near 8^2 the memory

    def test_ten_thousand_students_fit_comfortably_in_memory(self):
        records = synthetic_records(10_000)
        _, stats = measure(lambda: FeatureManager.extract_many(records))
        self.assertLess(stats["peak_kib"], 100 * MIB)


class OtherComponentsMemoryTests(unittest.TestCase):
    def test_model_load_is_small_and_nothing_large_is_retained(self):
        stats = profile_model_load()
        self.assertLess(stats["retained_kib"], 50 * MIB)

    def test_largest_allowed_excel_file_parses_within_budget(self):
        stats = profile_excel_parse()
        self.assertEqual(stats["records_parsed"], stats["rows"])
        self.assertLess(stats["peak_kib"], 100 * MIB)

    def test_prediction_cache_does_not_grow_without_limit(self):
        stats = profile_cache_growth(predictions=CachingDecorator._MAX_ENTRIES + 2_000)
        self.assertTrue(stats["bounded"])
        self.assertLessEqual(stats["cache_entries"], CachingDecorator._MAX_ENTRIES)


if __name__ == "__main__":
    unittest.main()
