"""System: the lesson-17 input-validation exercise, applied to our Excel upload.

Valid file, empty file, wrong type (PDF), corrupted file, extremely large file, no file.
Each must be answered with a meaningful message, never a traceback, and must not change data.
"""
import io
import unittest

import pytest

from tests.helpers import MongoAppTestCase, xlsx_bytes
from webapp import create_app

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def assert_clean_error(test, response, status, fragment):
    test.assertEqual(response.status_code, status)
    body = response.get_data(as_text=True)
    test.assertIn(fragment, response.get_json()["error"])
    for leak in ("Traceback", "openpyxl", "BadZipFile", ".py"):
        test.assertNotIn(leak, body)


class UploadRejectedBeforeReachingTheDatabaseTests(unittest.TestCase):
    """Cases answered without touching storage, so they also run in demo mode."""

    def setUp(self):
        self.client = create_app().test_client()

    def post(self, data):
        return self.client.post("/admin/api/groups/G1/import", data=data, content_type="multipart/form-data")

    def test_no_file_at_all(self):
        assert_clean_error(self, self.post({}), 400, "Selecciona un archivo")

    def test_wrong_extension(self):
        response = self.post({"file": (io.BytesIO(PDF_BYTES), "reporte.pdf")})
        assert_clean_error(self, response, 400, ".xlsx")

    def test_extremely_large_file(self):
        response = self.post({"file": (io.BytesIO(b"0" * (5 * 1024 * 1024)), "enorme.xlsx")})
        assert_clean_error(self, response, 413, "demasiado grande")


@pytest.mark.mongo
class UploadValidatedAgainstARealDatabaseTests(MongoAppTestCase):
    def setUp(self):
        super().setUp()
        self.client.post("/admin/api/groups", json={"group_id": "G1"})

    def students(self):
        return self.client.get("/api/groups/G1").get_json()["students"]

    def test_valid_file_is_accepted(self):
        response = self.upload("G1", xlsx_bytes([["A1", "Ana", 80, 85, None, None, 90, 88]]))
        self.assertEqual((response.status_code, response.get_json()["created"]), (200, 1))
        self.assertEqual(len(self.students()), 1)

    def test_empty_file(self):
        assert_clean_error(self, self.upload("G1", b""), 400, "vacio")
        self.assertEqual(self.students(), [])

    def test_pdf_content_disguised_as_excel(self):
        assert_clean_error(self, self.upload("G1", PDF_BYTES), 400, "No se pudo leer")
        self.assertEqual(self.students(), [])

    def test_corrupted_excel(self):
        assert_clean_error(self, self.upload("G1", xlsx_bytes([["A1", "Ana", 80, None, None, None, 90, 88]])[:250]),
                           400, "No se pudo leer")
        self.assertEqual(self.students(), [])

    def test_excel_without_the_required_columns(self):
        content = xlsx_bytes([["A1", "Ana", 80]], headers=["matricula", "nombre", "parcial1"])
        assert_clean_error(self, self.upload("G1", content), 400, "Faltan columnas obligatorias")
