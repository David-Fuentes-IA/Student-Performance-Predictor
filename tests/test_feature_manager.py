import random
import unittest

from data_access.student_repository import (
    InMemoryAcademicRepository,
    StudentGroup,
    StudentRecord,
)
from data_pipeline.etl_processor import ETLProcessor
from feature_store.feature_manager import FeatureManager


def record(student_id, grades, attendance=90.0, participation=80.0):
    return StudentRecord(student_id, f"Name {student_id}", grades, attendance, participation)


class ExtractManyTests(unittest.TestCase):
    def _random_records(self, n=300):
        rng = random.Random(1)
        return [
            record(f"S{i}", [round(rng.uniform(0, 100), 1) for _ in range(rng.randint(1, 8))],
                   round(rng.uniform(0, 100), 1), round(rng.uniform(0, 100), 1))
            for i in range(n)
        ]

    def test_batch_equals_single_record_extraction(self):
        records = self._random_records()
        self.assertEqual(FeatureManager.extract_many(records), [FeatureManager.extract(r) for r in records])

    def test_values_match_plain_python_within_rounding(self):
        for r, v in zip(self._random_records(), FeatureManager.extract_many(self._random_records()), strict=True):
            self.assertAlmostEqual(v.average_grade, sum(r.grades) / len(r.grades), delta=0.0051)
            self.assertAlmostEqual(v.grade_trend, r.grades[-1] - r.grades[0], delta=0.0051)

    def test_single_grade_has_zero_trend(self):
        vector = FeatureManager.extract_many([record("A", [55.5])])[0]
        self.assertEqual((vector.average_grade, vector.grade_trend), (55.5, 0.0))

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(FeatureManager.extract_many([]), [])

    def test_record_without_grades_is_rejected(self):
        with self.assertRaises(ValueError):
            FeatureManager.extract_many([record("A", [])])


class EtlUsesBatchExtractionTests(unittest.TestCase):
    def test_invalid_records_are_skipped_and_valid_ones_match_extract(self):
        repo = InMemoryAcademicRepository()
        good = [record("301-A-900", [70, 80, 90]), record("301-A-901", [40])]
        bad = [record("301-A-902", []), record("301-A-903", [150])]
        repo._groups["301-A"] = StudentGroup("301-A", good + bad)
        vectors = ETLProcessor(repo).process_group("301-A")
        self.assertEqual(vectors, [FeatureManager.extract(r) for r in good])


if __name__ == "__main__":
    unittest.main()
