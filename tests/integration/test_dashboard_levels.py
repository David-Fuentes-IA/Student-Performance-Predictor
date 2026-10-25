import unittest
from io import BytesIO

from pypdf import PdfReader

import main_api
from core.risk_levels import label_for
from presentation.pdf_reports import build_group_report, build_student_report
from presentation.report_data import summarize
from webapp import create_app


class DashboardAndReportsTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_api_exposes_threshold_and_labels_are_consistent_with_it(self):
        data = self.client.get("/api/groups/301-A").get_json()
        self.assertEqual(data["risk_threshold"], main_api.RISK_THRESHOLD)
        self.assertIn(f"alto desde {main_api.RISK_THRESHOLD:g}", data["risk_levels"])
        for student in data["students"]:
            self.assertEqual(student["risk_label"], label_for(student["risk_score"], main_api.RISK_THRESHOLD))

    def test_page_has_the_threshold_tag_and_legend_placeholders(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="threshold-tag"', html)
        self.assertIn('id="risk-legend"', html)

    def test_pdfs_print_the_configured_levels(self):
        students = main_api.get_group_dashboard_data("301-A")
        group_text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(build_group_report("301-A", students, 90))).pages)
        student_text = "\n".join(p.extract_text() for p in PdfReader(
            BytesIO(build_student_report("301-A", students[0], summarize(students), 90))).pages)
        for text in (group_text, student_text):
            self.assertIn("alto desde 90", " ".join(text.split()))


if __name__ == "__main__":
    unittest.main()
