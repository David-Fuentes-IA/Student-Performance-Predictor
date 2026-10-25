import unittest

from core.exception_handler import ValidationError
from data_pipeline.excel_importer import (
    MAX_ID_LENGTH,
    MAX_NAME_LENGTH,
    MAX_ROWS,
    build_template,
    parse_workbook,
)
from tests.helpers import VALID_ROW, xlsx_bytes


def parse(rows, **kwargs):
    return parse_workbook(xlsx_bytes(rows, **kwargs))


def row(student_id="A1", name="Ana", p1=80, p2=None, p3=None, p4=None, attendance=90, participation=85):
    return [student_id, name, p1, p2, p3, p4, attendance, participation]


class ValidFilesTests(unittest.TestCase):
    def test_the_downloadable_template_is_itself_importable(self):
        parsed = parse_workbook(build_template())
        self.assertEqual((len(parsed.records), len(parsed.rejected)), (2, 0))
        self.assertEqual(parsed.records[1].grades, [55.0, 48.0, 60.0])

    def test_valid_rows_become_records(self):
        parsed = parse([VALID_ROW])
        record = parsed.records[0]
        self.assertEqual((record.student_id, record.name), ("A0001", "Ana Prueba"))
        self.assertEqual(record.grades, [80.0, 85.0, 90.0, 95.0])
        self.assertEqual((record.attendance_pct, record.participation_score), (92.0, 88.0))

    def test_boundary_values_are_accepted(self):
        parsed = parse([row("B0", p1=0, attendance=0, participation=0), row("B100", p1=100, attendance=100, participation=100)])
        self.assertEqual((len(parsed.records), len(parsed.rejected)), (2, 0))

    def test_numeric_ids_text_numbers_and_percent_signs_are_normalised(self):
        parsed = parse([row(123.0, p1="85,5", attendance="90%")])
        record = parsed.records[0]
        self.assertEqual(record.student_id, "123")
        self.assertEqual((record.grades, record.attendance_pct), ([85.5], 90.0))

    def test_header_aliases_and_accents_are_understood(self):
        headers = ["Matrícula", "Nombre", "P1", "P2", "P3", "P4", "Asistencia", "Participación"]
        parsed = parse([VALID_ROW], headers=headers)
        self.assertEqual(len(parsed.records), 1)

    def test_fully_blank_rows_are_skipped_and_not_counted(self):
        parsed = parse([VALID_ROW, [None] * 8, row("A2")])
        self.assertEqual((parsed.total_rows, len(parsed.records)), (2, 2))


class FileLevelRejectionTests(unittest.TestCase):
    def assert_rejected(self, content, fragment):
        with self.assertRaises(ValidationError) as ctx:
            parse_workbook(content)
        self.assertIn(fragment, ctx.exception.user_message)

    def test_empty_file(self):
        self.assert_rejected(b"", "vacio")

    def test_pdf_content_instead_of_excel(self):
        self.assert_rejected(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n", "No se pudo leer")

    def test_random_text_file(self):
        self.assert_rejected(b"matricula,nombre\nA1,Ana\n", "No se pudo leer")

    def test_corrupted_workbook(self):
        self.assert_rejected(xlsx_bytes([VALID_ROW])[:300], "No se pudo leer")

    def test_missing_required_column_names_the_column(self):
        headers = ["matricula", "nombre", "parcial1", "asistencia_pct"]  # participacion missing
        self.assert_rejected(xlsx_bytes([["A1", "Ana", 80, 90]], headers=headers), "participacion")

    def test_header_only_file_has_no_students(self):
        self.assert_rejected(xlsx_bytes([]), "no contiene alumnos")

    def test_too_many_rows(self):
        rows = [row(f"M{i}") for i in range(MAX_ROWS + 1)]
        self.assert_rejected(xlsx_bytes(rows), str(MAX_ROWS))


class RowLevelRejectionTests(unittest.TestCase):
    def reasons(self, rows):
        parsed = parse(rows)
        return {r.row: r.reason for r in parsed.rejected}, parsed

    def test_each_invalid_row_is_reported_with_its_excel_row_number(self):
        reasons, parsed = self.reasons([
            row("OK1"),                                   # row 2: valid
            row("G1", p1=150),                            # row 3: grade above range
            row("G2", p1=-1),                             # row 4: grade below range
            row("T1", p1="abc"),                          # row 5: text instead of number
            row("N1", name="  "),                         # row 6: empty name
            row("H1", p1=80, p2=None, p3=70),             # row 7: gap in partials
            row("A1", attendance=None),                   # row 8: missing attendance
            row("OK1"),                                   # row 9: duplicate id
            row("X" * (MAX_ID_LENGTH + 1)),               # row 10: id too long
            row("L1", name="n" * (MAX_NAME_LENGTH + 1)),  # row 11: name too long
            row("", name="Sin matricula"),                # row 12: empty id
            row("P1", participation=101),                 # row 13: participation above range
        ])
        self.assertEqual([r.student_id for r in parsed.records], ["OK1"])
        self.assertEqual(sorted(reasons), list(range(3, 14)))
        self.assertIn("abc", reasons[5])
        self.assertIn("sin huecos", reasons[7])
        self.assertIn("repetida", reasons[9])

    def test_valid_rows_survive_next_to_invalid_ones(self):
        parsed = parse([row("A1"), row("A2", p1=500), row("A3")])
        self.assertEqual([r.student_id for r in parsed.records], ["A1", "A3"])
        self.assertEqual(len(parsed.rejected), 1)


if __name__ == "__main__":
    unittest.main()
