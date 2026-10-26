"""Shared test helpers: Excel builders and a real-MongoDB test base class."""
import io
import os
import unittest
import uuid
from unittest.mock import patch

from openpyxl import Workbook

from data_pipeline.excel_importer import TEMPLATE_COLUMNS

VALID_ROW = ["A0001", "Ana Prueba", 80, 85, 90, 95, 92, 88]


def xlsx_bytes(rows, headers=None, sheet="Calificaciones"):
    """Build an .xlsx in memory. `rows` are lists in TEMPLATE_COLUMNS order."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(list(headers if headers is not None else TEMPLATE_COLUMNS))
    for row in rows:
        ws.append(list(row))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def class_rows(count, prefix="E"):
    """`count` valid students with deterministic, varied data (some clearly at risk)."""
    rows = []
    for i in range(count):
        at_risk = i % 5 == 0
        grades = [30 + i % 20, 35 + i % 15, 32 + i % 10, 28 + i % 12] if at_risk else [
            70 + i % 25, 72 + i % 20, 75 + i % 20, 78 + i % 18]
        rows.append([f"{prefix}{i:04d}", f"Alumno Prueba {i:03d}", *grades, 55 if at_risk else 92, 40 if at_risk else 88])
    return rows


class MongoAppTestCase(unittest.TestCase):
    """Runs the unified app against a throw-away database in a real MongoDB.

    Skipped unless MONGODB_TEST_URI is set (e.g. mongodb://localhost:27018).
    """

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("MONGODB_TEST_URI"):
            raise unittest.SkipTest("set MONGODB_TEST_URI to run against a real MongoDB")

    def setUp(self):
        from pymongo import MongoClient

        import main_api
        from data_access.mongo_repository import MongoAcademicRepository
        from data_pipeline.etl_processor import ETLProcessor
        from webapp import create_app

        self.mongo = MongoClient(os.environ["MONGODB_TEST_URI"])
        self.db = self.mongo[f"spp_test_{uuid.uuid4().hex[:8]}"]
        self.repo = MongoAcademicRepository(db=self.db)
        self.patches = [
            patch.object(main_api, "_repository", self.repo),
            patch.object(main_api, "_etl", ETLProcessor(self.repo)),
        ]
        for p in self.patches:
            p.start()
        self.client = create_app().test_client()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.mongo.drop_database(self.db.name)
        self.mongo.close()

    def upload(self, group_id, content, filename="grupo.xlsx", **fields):
        data = {"file": (io.BytesIO(content), filename), **fields}
        return self.client.post(f"/admin/api/groups/{group_id}/import", data=data,
                                content_type="multipart/form-data")
