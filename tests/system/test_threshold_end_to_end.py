import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]



class EndToEndThresholdTests(unittest.TestCase):
    def labels_with(self, threshold):
        script = ("import json, collections, main_api;"
                  "print(json.dumps(collections.Counter(s['risk_label'] for s in main_api.get_group_dashboard_data('301-A'))))")
        env = dict(os.environ, MONGODB_URI="")
        if threshold is None:
            env.pop("RISK_THRESHOLD", None)
        else:
            env["RISK_THRESHOLD"] = str(threshold)
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_lowering_the_threshold_turns_more_students_high_risk(self):
        default, lowered = self.labels_with(None), self.labels_with(1)
        self.assertGreater(lowered.get("high", 0), default.get("high", 0))


if __name__ == "__main__":
    unittest.main()
