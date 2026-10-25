"""Static guards for the container files: the security and reliability decisions of Phase 6 must not
be undone by accident. (The image itself is built and smoke-tested in CI; see scripts/smoke_test.py.)"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class DockerfileTests(unittest.TestCase):
    def setUp(self):
        self.text = read("Dockerfile")
        joined = re.sub(r"\\\n\s*", " ", self.text)  # a trailing backslash continues the instruction
        self.instructions = [ln.strip() for ln in joined.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    def test_is_multi_stage(self):
        self.assertGreaterEqual(sum(1 for ln in self.instructions if ln.startswith("FROM ")), 2)

    def test_runs_as_a_non_root_user(self):
        users = [ln for ln in self.instructions if ln.startswith("USER ")]
        self.assertTrue(users)
        self.assertNotIn(users[-1].split()[1], ("root", "0"))

    def test_serves_with_gunicorn_not_the_flask_development_server(self):
        command = next(ln for ln in self.instructions if ln.startswith("CMD ["))
        self.assertIn("gunicorn", command)
        self.assertNotIn("app.run", self.text)
        self.assertNotIn("flask run", self.text)

    def test_has_a_healthcheck_on_the_liveness_endpoint(self):
        self.assertIn("HEALTHCHECK", self.text)
        self.assertIn("/health", self.text)

    def test_trains_the_model_at_build_time_so_the_app_never_trains_at_startup(self):
        self.assertIn("scripts/train_model.py", self.text)

    def test_contains_no_secrets_or_env_files(self):
        self.assertNotRegex(self.text, r"(?i)\bENV\b[^\n]*(MONGODB_URI|PASSWORD|TOKEN|SECRET)")
        self.assertNotRegex(self.text, r"COPY[^\n]*\.env\b(?!\.example)")

    def test_pins_a_python_minor_version(self):
        self.assertRegex(self.text, r"FROM python:3\.\d+-slim")


class DockerIgnoreTests(unittest.TestCase):
    def test_excludes_secrets_virtualenvs_history_and_tests(self):
        entries = {ln.strip() for ln in read(".dockerignore").splitlines() if ln.strip() and not ln.startswith("#")}
        for required in (".env", "venv/", ".git/", "tests/", "models/*.joblib", "logs/"):
            self.assertIn(required, entries)

    def test_keeps_the_env_template_available(self):
        self.assertIn("!.env.example", read(".dockerignore"))


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.text = read("docker-compose.yml")

    def test_defines_the_application_and_its_database(self):
        self.assertRegex(self.text, r"(?m)^  app:")
        self.assertRegex(self.text, r"(?m)^  mongo:")
        self.assertIn("mongo:7", self.text)

    def test_the_app_waits_for_a_healthy_database(self):
        self.assertIn("condition: service_healthy", self.text)
        self.assertIn("healthcheck:", self.text)

    def test_database_data_live_in_a_named_volume(self):
        self.assertIn("mongo_data:/data/db", self.text)
        self.assertRegex(self.text, r"(?m)^volumes:\s*\n\s+mongo_data:")

    def test_does_not_inherit_the_developers_localhost_connection_string(self):
        uri = re.search(r"MONGODB_URI:\s*(.+)", self.text).group(1)
        self.assertIn("DOCKER_MONGODB_URI", uri)
        self.assertIn("mongodb://mongo:27017", uri)

    def test_has_no_hard_coded_credentials(self):
        self.assertNotRegex(self.text, r"mongodb(\+srv)?://[^\s\"']+:[^\s\"'@]+@")
        self.assertNotRegex(self.text, r"(?im)^\s+ADMIN_PASSWORD:\s*(?!\$\{)[^\s#]+")  # only ${VARIABLE} references

    def test_the_single_command_documented_in_the_readme_matches(self):
        self.assertIn("docker compose up --build", self.text)


class LinuxCompatibilityTests(unittest.TestCase):
    def test_entrypoint_uses_unix_line_endings_and_hands_over_with_exec(self):
        raw = (ROOT / "docker" / "entrypoint.sh").read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.startswith(b"#!/bin/sh"))
        self.assertIn(b'exec "$@"', raw)

    def test_git_is_told_to_keep_shell_scripts_on_lf(self):
        self.assertIn("*.sh text eol=lf", read(".gitattributes"))

    def test_gunicorn_is_a_runtime_dependency_but_skipped_on_windows(self):
        self.assertRegex(read("requirements.txt"), r"(?m)^gunicorn>=[\d.]+;\s*sys_platform\s*!=\s*\"win32\"")


if __name__ == "__main__":
    unittest.main()
