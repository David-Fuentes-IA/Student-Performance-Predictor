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
        self.assertEqual((data["risk_threshold"], data["passing_grade"]), (main_api.RISK_THRESHOLD, main_api.PASSING_GRADE))
        self.assertIn(f"riesgo estimado desde {main_api.RISK_THRESHOLD:g}", data["risk_levels"])
        self.assertIn("promedio menor a 6.0", data["risk_levels"])
        for student in data["students"]:
            expected = label_for(student["risk_score"], main_api.RISK_THRESHOLD, student["average_grade"],
                                 main_api.PASSING_GRADE)
            self.assertEqual(student["risk_label"], expected)
            self.assertEqual(student["risk_label"] == "high", bool(student["alert_reasons"]))
            self.assertEqual("failing_average" in student["alert_reasons"],
                             student["average_grade"] < main_api.PASSING_GRADE)

    def test_every_student_with_a_failing_average_is_high_risk_in_every_demo_group(self):
        for group in ("301-A", "301-B", "301-C"):
            for student in self.client.get(f"/api/groups/{group}").get_json()["students"]:
                if student["average_grade"] < main_api.PASSING_GRADE:
                    self.assertEqual(student["risk_label"], "high", student["student_id"])

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
            flat = " ".join(text.split())
            self.assertIn("riesgo estimado desde 90", flat)
            self.assertIn("promedio menor a 6.0", flat)

    def test_the_student_pdf_explains_why_an_alert_was_raised(self):
        students = main_api.get_group_dashboard_data("301-A")
        flagged = next(s for s in students if s["alert_reasons"])
        text = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(
            BytesIO(build_student_report("301-A", flagged, summarize(students)))).pages)
        self.assertIn("Motivo de la alerta", text)


if __name__ == "__main__":
    unittest.main()
