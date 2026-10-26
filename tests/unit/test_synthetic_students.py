import statistics
import unittest

from data_access.student_repository import StudentRecord
from data_access.synthetic_students import fake_name, simulate_students
from data_pipeline.fail_fast_validator import FailFastValidator
from learning_module.model_trainer import (
    generate_synthetic_training_set,
    students_to_dataset,
)


class SimulatorTests(unittest.TestCase):
    def test_same_seed_same_students_different_seed_different_students(self):
        self.assertEqual(simulate_students(50, seed=3), simulate_students(50, seed=3))
        self.assertNotEqual(simulate_students(50, seed=3), simulate_students(50, seed=4))

    def test_shape_and_ranges_of_every_student(self):
        students = simulate_students(500, seed=11, id_prefix="T")
        self.assertEqual(len({s.student_id for s in students}), 500)
        self.assertEqual(students[0].student_id, "T0001")
        self.assertEqual(students[0].name, fake_name(0))
        for s in students:
            self.assertIn(len(s.grades), (2, 3, 4))
            self.assertTrue(all(0 <= g <= 100 for g in s.grades))
            self.assertTrue(0 <= s.attendance_pct <= 100 and 0 <= s.participation_score <= 100)
            self.assertIn(s.shift, ("matutino", "vespertino"))
            self.assertIn(s.at_risk, (0, 1))

    def test_every_simulated_student_is_valid_input_for_the_system(self):
        for s in simulate_students(300, seed=5):
            FailFastValidator.validate(StudentRecord(s.student_id, s.name, s.grades, s.attendance_pct,
                                                     s.participation_score))

    def test_share_of_at_risk_students_is_realistic(self):
        students = simulate_students(3000, seed=21)
        share = sum(s.at_risk for s in students) / len(students)
        self.assertTrue(0.20 <= share <= 0.35, share)

    def test_evening_students_attend_less_for_the_same_traits(self):
        students = simulate_students(4000, seed=8)
        evening = statistics.mean(s.attendance_pct for s in students if s.shift == "vespertino")
        morning = statistics.mean(s.attendance_pct for s in students if s.shift == "matutino")
        self.assertGreater(morning - evening, 3.0)

    def test_classes_overlap_so_validation_has_errors_to_analyse(self):
        # The earlier generator separated the classes completely (every model scored 1.0).
        students = simulate_students(2000, seed=2)
        average = lambda s: sum(s.grades) / len(s.grades)  # noqa: E731
        worst_ok = min(average(s) for s in students if not s.at_risk)
        best_risky = max(average(s) for s in students if s.at_risk)
        self.assertGreater(best_risky, worst_ok)  # some at-risk students look better than some safe ones


class TrainingSetTests(unittest.TestCase):
    def test_training_set_has_four_features_and_binary_labels(self):
        X, y = generate_synthetic_training_set(n_samples=120, seed=7)
        self.assertEqual((len(X), len(y)), (120, 120))
        self.assertTrue(all(len(row) == 4 for row in X))
        self.assertEqual(set(y), {0, 1})

    def test_features_come_from_the_production_feature_manager(self):
        students = simulate_students(5, seed=1)
        X, _ = students_to_dataset(students)
        s = students[0]
        self.assertAlmostEqual(X[0][0], sum(s.grades) / len(s.grades), delta=0.0051)
        self.assertAlmostEqual(X[0][1], s.grades[-1] - s.grades[0], delta=0.0051)
        self.assertEqual((X[0][2], X[0][3]), (s.attendance_pct, s.participation_score))


if __name__ == "__main__":
    unittest.main()
