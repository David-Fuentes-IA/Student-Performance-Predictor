import unittest

from core.exception_handler import DataAccessError, GroupNotFoundError
from data_access.student_repository import (
    DEMO_GROUP_IDS,
    IAcademicDataRepository,
    InMemoryAcademicRepository,
)
from data_pipeline.fail_fast_validator import FailFastValidator


class InMemoryRepositoryBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryAcademicRepository()

    def test_implements_the_interface_the_rest_of_the_system_depends_on(self):
        self.assertIsInstance(self.repo, IAcademicDataRepository)
        self.assertEqual(self.repo.backend, "memory")

    def test_demo_groups_have_valid_students_with_matching_ids(self):
        for group_id in DEMO_GROUP_IDS:
            group = self.repo.get_group(group_id)
            self.assertEqual(len(group.students), 12)
            for student in group.students:
                self.assertTrue(student.student_id.startswith(group_id + "-"))
                FailFastValidator.validate(student)

    def test_same_seed_gives_the_same_data(self):
        a = InMemoryAcademicRepository(seed=1).get_group("301-A").students
        b = InMemoryAcademicRepository(seed=1).get_group("301-A").students
        self.assertEqual(a, b)

    def test_get_student_by_id(self):
        student = self.repo.get_student("301-B-003")
        self.assertEqual(student.student_id, "301-B-003")

    def test_unknown_student_and_unknown_group_are_data_access_errors(self):
        with self.assertRaises(DataAccessError):
            self.repo.get_student("301-A-999")
        with self.assertRaises(GroupNotFoundError):
            self.repo.get_group("NOPE")

    def test_empty_or_non_string_group_id_is_rejected(self):
        for bad in ("", None, 123):
            with self.subTest(bad), self.assertRaises(DataAccessError):
                self.repo.get_group(bad)

    def test_saved_predictions_are_logged_and_the_log_is_a_copy(self):
        self.repo.save_prediction("301-A-000", 91.5, "high")
        log = self.repo.get_prediction_log()
        self.assertEqual((log[0]["student_ref"], log[0]["risk_score"], log[0]["risk_label"]), ("301-A-000", 91.5, "high"))
        self.assertIn("recorded_at", log[0])
        log.clear()
        self.assertEqual(len(self.repo.get_prediction_log()), 1)

    def test_list_groups_reports_the_student_counts(self):
        self.assertEqual({g["group_id"]: g["student_count"] for g in self.repo.list_groups()},
                         {"301-A": 12, "301-B": 12, "301-C": 12})


if __name__ == "__main__":
    unittest.main()
