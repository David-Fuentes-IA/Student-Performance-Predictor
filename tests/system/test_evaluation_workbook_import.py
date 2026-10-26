"""System: the fixed evaluation workbook, imported through the administration panel into a real
MongoDB and analysed by the dashboard, exactly as a teacher would use it."""
import statistics

import pytest

from learning_module.evaluation_data import DEFAULT_PATH, load_evaluation_workbook
from tests.helpers import MongoAppTestCase

pytestmark = pytest.mark.mongo


class EvaluationWorkbookImportTests(MongoAppTestCase):
    def test_import_the_fixed_group_and_get_realistic_predictions(self):
        response = self.upload("EVAL-240", DEFAULT_PATH.read_bytes(), filename="grupo_evaluacion.xlsx",
                               create_group="true")
        body = response.get_json()
        self.assertEqual((response.status_code, body["created"], body["rejected"]), (200, 240, []))

        data = self.client.get("/api/groups/EVAL-240").get_json()
        students = data["students"]
        self.assertEqual(len(students), 240)

        # Scores are spread over the range instead of clustering at 0/100: the data are noisy.
        scores = [s["risk_score"] for s in students]
        self.assertGreater(len({round(x) for x in scores}), 40)
        self.assertEqual({s["risk_label"] for s in students}, {"low", "medium", "high"})

        # Students who really ended up at risk get higher scores on average than the rest.
        labels = load_evaluation_workbook().labels
        at_risk = [s["risk_score"] for s in students if labels[s["student_id"]] == 1]
        others = [s["risk_score"] for s in students if labels[s["student_id"]] == 0]
        self.assertGreater(statistics.mean(at_risk), statistics.mean(others) + 20)

    def test_importing_the_fixed_file_twice_changes_nothing(self):
        content = DEFAULT_PATH.read_bytes()
        self.upload("EVAL-240", content, create_group="true")
        again = self.upload("EVAL-240", content).get_json()
        self.assertEqual((again["created"], again["updated"], again["unchanged"]), (0, 0, 240))
