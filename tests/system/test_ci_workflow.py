"""Static guards for the CI/CD pipeline: the stages, their order and the safety rules must not be
weakened by accident (for example removing the quality gate, or delivering without tests)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def job_block(text: str, job: str) -> str:
    """Text of one job: from its key to the next job key (2-space indentation)."""
    start = re.search(rf"(?m)^  {re.escape(job)}:\s*$", text)
    assert start, f"job '{job}' not found"
    following = re.search(r"(?m)^  [a-z][a-z0-9-]*:\s*$", text[start.end():])
    return text[start.start(): start.end() + (following.start() if following else len(text))]


class PipelineShapeTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_on_every_push_and_pull_request(self):
        self.assertRegex(self.text, r"(?m)^on:\s*\n\s+push:")
        self.assertRegex(self.text, r"(?m)^\s+pull_request:")

    def test_stages_follow_the_course_order_and_each_needs_the_previous_one(self):
        chain = [("test", "build"), ("model-validation", "test"), ("container", "model-validation"),
                 ("kubernetes", "container"), ("deliver", "container"), ("deliver", "kubernetes")]
        for job, previous in chain:
            with self.subTest(job=job, needs=previous):
                needs = re.search(r"needs:\s*(\[[^\]]*\]|\S+)", job_block(self.text, job)).group(1)
                self.assertIn(previous, re.findall(r"[a-z][a-z0-9-]*", needs))

    def test_kubernetes_manifests_are_deployed_and_self_healing_is_checked(self):
        k8s = job_block(self.text, "kubernetes")
        self.assertIn("kubectl apply -f k8s/app.yaml", k8s)
        self.assertIn("rollout status deployment/spp-app", k8s)
        self.assertIn("scripts/smoke_test.py", k8s)
        self.assertIn("delete pod", k8s)

    def test_build_stage_lints_and_trains(self):
        build = job_block(self.text, "build")
        self.assertIn("ruff check .", build)
        self.assertIn("scripts/train_model.py", build)

    def test_tests_run_strictly_against_a_real_mongodb(self):
        test = job_block(self.text, "test")
        self.assertIn("image: mongo:7", test)
        self.assertIn("MONGODB_TEST_URI", test)
        self.assertIn("collect_test_evidence.py --strict", test)

    def test_the_model_quality_gate_is_a_blocking_stage(self):
        gate = job_block(self.text, "model-validation")
        self.assertIn("evaluate_models.py --gate", gate)
        gate_step = gate[gate.index("--gate") - 300: gate.index("--gate")]
        self.assertNotIn("continue-on-error", gate_step)

    def test_the_container_is_smoke_tested(self):
        container = job_block(self.text, "container")
        self.assertIn("docker compose up -d --build", container)
        self.assertIn("scripts/smoke_test.py", container)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_only_main_is_delivered(self):
        deliver = job_block(self.text, "deliver")
        self.assertIn("github.ref == 'refs/heads/main'", deliver)
        self.assertIn("github.event_name == 'push'", deliver)

    def test_least_privilege_permissions(self):
        self.assertRegex(self.text, r"(?m)^permissions:\s*\n\s+contents: read")
        self.assertEqual(self.text.count("packages: write"), 1)
        self.assertIn("packages: write", job_block(self.text, "deliver"))

    def test_no_secrets_other_than_the_automatic_token(self):
        self.assertEqual(set(re.findall(r"secrets\.(\w+)", self.text)), {"GITHUB_TOKEN"})

    def test_no_stage_is_allowed_to_fail_silently(self):
        self.assertNotIn("continue-on-error: true", self.text)

    def test_python_version_matches_the_docker_image(self):
        ci_version = re.search(r'PYTHON_VERSION:\s*"([\d.]+)"', self.text).group(1)
        docker_version = re.search(r"FROM python:([\d.]+)-slim", (ROOT / "Dockerfile").read_text(encoding="utf-8")).group(1)
        self.assertEqual(ci_version, docker_version)


if __name__ == "__main__":
    unittest.main()
