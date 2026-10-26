"""Static guards for the Kubernetes manifests. The CI also deploys them to a throw-away cluster
(see .github/workflows/ci.yml, job `kubernetes`); these tests keep the reliability and security
decisions from being undone by an edit."""
import re
import unittest
from pathlib import Path

K8S = Path(__file__).resolve().parents[2] / "k8s"


def documents(name: str) -> list[str]:
    return [d for d in re.split(r"(?m)^---\s*$", (K8S / name).read_text(encoding="utf-8")) if "kind:" in d]


def kind(name: str, wanted: str) -> str:
    return next(d for d in documents(name) if re.search(rf"(?m)^kind:\s*{wanted}\s*$", d))


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.deployment = kind("app.yaml", "Deployment")

    def test_runs_at_least_two_replicas_and_never_drops_below_during_updates(self):
        self.assertGreaterEqual(int(re.search(r"replicas:\s*(\d+)", self.deployment).group(1)), 2)
        self.assertIn("maxUnavailable: 0", self.deployment)

    def test_liveness_uses_health_and_readiness_uses_ready(self):
        liveness = re.search(r"livenessProbe:.*?path:\s*(\S+?)[,}]", self.deployment, re.S).group(1)
        readiness = re.search(r"readinessProbe:.*?path:\s*(\S+?)[,}]", self.deployment, re.S).group(1)
        self.assertEqual((liveness, readiness), ("/health", "/ready"))
        self.assertIn("startupProbe", self.deployment)

    def test_declares_resource_requests_and_limits(self):
        self.assertRegex(self.deployment, r"requests:\s*\{cpu:\s*\S+,\s*memory:\s*\S+\}")
        self.assertRegex(self.deployment, r"limits:\s*\{cpu:\s*\S+,\s*memory:\s*\S+\}")

    def test_hardened_security_context(self):
        for setting in ("runAsNonRoot: true", "allowPrivilegeEscalation: false", "readOnlyRootFilesystem: true",
                        "drop: [ALL]"):
            self.assertIn(setting, self.deployment)

    def test_writable_paths_are_explicit_volumes(self):
        for path in ("/app/logs", "/app/.gunicorn", "/tmp"):
            self.assertIn(f"mountPath: {path}", self.deployment)

    def test_configuration_and_secrets_come_from_kubernetes_objects(self):
        self.assertIn("configMapRef: {name: spp-config}", self.deployment)
        self.assertIn("secretRef: {name: spp-secrets}", self.deployment)
        self.assertNotRegex(self.deployment, r"mongodb(\+srv)?://")


class OtherObjectsTests(unittest.TestCase):
    def test_config_never_seeds_demo_data_in_a_real_deployment(self):
        self.assertIn('SEED_DEMO: "false"', kind("app.yaml", "ConfigMap"))

    def test_service_routes_to_the_application_pods(self):
        service = kind("app.yaml", "Service")
        self.assertIn("selector: {app: spp-app}", service)
        self.assertIn("targetPort: http", service)

    def test_autoscaler_keeps_two_pods_minimum(self):
        hpa = kind("app.yaml", "HorizontalPodAutoscaler")
        self.assertGreaterEqual(int(re.search(r"minReplicas:\s*(\d+)", hpa).group(1)), 2)
        self.assertGreater(int(re.search(r"maxReplicas:\s*(\d+)", hpa).group(1)),
                           int(re.search(r"minReplicas:\s*(\d+)", hpa).group(1)))

    def test_secret_template_contains_placeholders_only(self):
        secret = (K8S / "secret.example.yaml").read_text(encoding="utf-8")
        self.assertIn("TEMPLATE ONLY", secret)
        self.assertNotRegex(secret, r'(?m)^\s+MONGODB_URI:\s*"mongodb')
        self.assertNotRegex(secret, r'(?m)^\s+ADMIN_PASSWORD:\s*"(?!<)')

    def test_in_cluster_database_is_marked_for_development_only(self):
        self.assertIn("DEVELOPMENT / CI ONLY", (K8S / "mongodb-dev.yaml").read_text(encoding="utf-8"))

    def test_every_object_lives_in_the_project_namespace(self):
        for name in ("app.yaml", "mongodb-dev.yaml", "secret.example.yaml"):
            for document in documents(name):
                with self.subTest(name=name):
                    self.assertIn("namespace: student-predictor", document)


if __name__ == "__main__":
    unittest.main()
