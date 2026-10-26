import unittest
from dataclasses import replace

from core.exception_handler import ValidationError
from data_access.student_repository import StudentRecord
from data_pipeline.fail_fast_validator import FailFastValidator

GOOD = StudentRecord("S1", "Ana", [70.0, 80.0], 90.0, 85.0)


class FailFastValidatorTests(unittest.TestCase):
    def test_valid_record_passes(self):
        FailFastValidator.validate(GOOD)

    def test_boundary_values_are_accepted(self):
        FailFastValidator.validate(StudentRecord("S1", "Ana", [0, 100], 0, 0))
        FailFastValidator.validate(StudentRecord("S1", "Ana", [100], 100, 100))

    def test_invalid_values_are_rejected_with_a_message_naming_the_student(self):
        cases = {
            "no grades": replace(GOOD, grades=[]),
            "grade below range": replace(GOOD, grades=[-0.1]),
            "grade above range": replace(GOOD, grades=[70, 100.1]),
            "grade is None": replace(GOOD, grades=[None]),
            "grade is NaN": replace(GOOD, grades=[float("nan")]),
            "grade is infinite": replace(GOOD, grades=[float("inf")]),
            "attendance below range": replace(GOOD, attendance_pct=-1),
            "attendance above range": replace(GOOD, attendance_pct=101),
            "attendance is None": replace(GOOD, attendance_pct=None),
            "participation below range": replace(GOOD, participation_score=-5),
            "participation above range": replace(GOOD, participation_score=100.5),
            "participation is None": replace(GOOD, participation_score=None),
        }
        for label, record in cases.items():
            with self.subTest(label), self.assertRaises(ValidationError) as ctx:
                FailFastValidator.validate(record)
            self.assertIn("S1", ctx.exception.user_message)

    def test_unexpected_types_are_validation_errors_not_crashes(self):
        # Before the fix a text grade raised TypeError and a bool passed as 1.
        cases = {
            "grade as text": replace(GOOD, grades=["90"]),
            "grade as bool": replace(GOOD, grades=[True]),
            "attendance as text": replace(GOOD, attendance_pct="95"),
            "participation as list": replace(GOOD, participation_score=[80]),
        }
        for label, record in cases.items():
            with self.subTest(label), self.assertRaises(ValidationError):
                FailFastValidator.validate(record)

    def test_stops_at_the_first_problem(self):
        record = replace(GOOD, grades=[150], attendance_pct=-1)
        with self.assertRaises(ValidationError) as ctx:
            FailFastValidator.validate(record)
        self.assertIn("grade", str(ctx.exception))

    def test_never_modifies_the_record(self):
        record = replace(GOOD, grades=[70, 80])
        FailFastValidator.validate(record)
        self.assertEqual(record.grades, [70, 80])


if __name__ == "__main__":
    unittest.main()
