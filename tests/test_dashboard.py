import unittest
from io import BytesIO
from unittest.mock import patch
from pypdf import PdfReader
from webapp import create_app
from main_api import get_group_dashboard_data, _repository
from presentation.report_data import summarize
from presentation.pdf_reports import build_group_report, build_student_report
from core.exception_handler import AppError

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_dashboard_and_static(self):
        for path in ('/', '/static/dashboard.js', '/static/dashboard.css'):
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_data_and_identifiers(self):
        data = self.client.get('/api/groups/301-A').get_json()
        self.assertEqual(len(data['students']), 12)
        self.assertEqual(sum(data['summary']['counts'].values()), 12)
        self.assertEqual(data['summary'], summarize(data['students']))
        for s in data['students']:
            self.assertEqual(_repository.get_student(s['student_id']).name, s['name'])
            self.assertAlmostEqual(s['average_grade'], sum(s['grades']) / len(s['grades']), places=2)

    def test_student_pdfs(self):
        students = get_group_dashboard_data('301-A')
        for s in (students[0], students[-1]):
            r=self.client.get(f"/reports/groups/301-A/students/{s['student_id']}.pdf")
            self.assertEqual(r.status_code, 200)
            self.assertIn('attachment;',r.headers['Content-Disposition'])
            self.assertEqual(r.mimetype, 'application/pdf')
            text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(r.data)).pages)
            self.assertIn(s['student_id'], text)
            self.assertIn(f"{s['risk_score']:.1f}/100",text)
            self.assertIn('datos sintéticos', text)

    def test_complete_group_pdf(self):
        r=self.client.get('/reports/groups/301-A.pdf?risk=high&search=missing')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['Cache-Control'],'no-store')
        text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(r.data)).pages)
        for s in get_group_dashboard_data('301-A'):
            self.assertIn(s['student_id'],text)
        self.assertIn('12 alumnos',text)

    def test_invalid_and_cross_group(self):
        self.assertEqual(self.client.get('/api/groups/bad!').status_code,400)
        self.assertEqual(self.client.get('/?group=bad!').status_code,400)
        for sid in ('missing','301-B-000'):
            self.assertEqual(self.client.get(f'/reports/groups/301-A/students/{sid}.pdf').status_code,404)

    def test_empty_and_medium_tier(self):
        self.assertEqual(summarize([])['total'],0)
        self.assertEqual(summarize([])['period_averages'],[])
        rows=[dict(average_grade=50,attendance_pct=70,participation_score=60,grades=[40,60],risk_score=50,risk_label=t) for t in ('low','medium','high')]
        self.assertEqual(summarize(rows)['counts'],dict(low=1,medium=1,high=1))
        self.assertTrue(build_group_report('EMPTY',[]).startswith(b'%PDF'))
        with patch('webapp.dashboard.get_group_dashboard_data',return_value=[]):
            self.assertEqual(self.client.get('/api/groups/EMPTY').get_json()['students'],[])

    def test_long_names_and_large_pdf(self):
        s=dict(get_group_dashboard_data('301-A')[0],name='Ana & Luis <Ejemplo> '*3)
        pdf=build_student_report('301-A',s,summarize([s]))
        self.assertIn('Ana & Luis <Ejemplo>',PdfReader(BytesIO(pdf)).pages[0].extract_text())
        rows=[dict(s,student_id=f'BIG-{i:03d}') for i in range(100)]
        pages=PdfReader(BytesIO(build_group_report('BIG',rows))).pages
        self.assertGreater(len(pages),2)
        self.assertIn('BIG-099','\n'.join(p.extract_text() for p in pages))

    def test_imported_records_with_unequal_grades_and_external_ids(self):
        from data_access.student_repository import InMemoryAcademicRepository, StudentRecord, StudentGroup
        from data_pipeline.etl_processor import ETLProcessor
        repo = InMemoryAcademicRepository()
        repo._groups['MIX.1'] = StudentGroup('MIX.1', [
            StudentRecord('REG / 1', 'Ana', [50], 90, 70),
            StudentRecord('REG-2', 'Luis', [80, 80, 80], 95, 90),
        ])
        with patch('main_api._repository', repo), patch('main_api._etl', ETLProcessor(repo)):
            response = self.client.get('/api/groups/MIX.1')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()['summary']['period_averages'], [65, 80, 80])
            pdf = self.client.get('/reports/groups/MIX.1/students/REG%20%2F%201.pdf')
            self.assertEqual(pdf.status_code, 200)
            self.assertIn('REG / 1', PdfReader(BytesIO(pdf.data)).pages[0].extract_text())

    def test_safe_errors(self):
        with patch('webapp.dashboard.get_group_dashboard_data',side_effect=AppError('private/path')):
            for path in ('/api/groups/301-A','/reports/groups/301-A.pdf'):
                r=self.client.get(path)
                self.assertEqual(r.status_code,503)
                self.assertNotIn('private/path',r.get_data(as_text=True))

if __name__=='__main__':
    unittest.main()
