"""No provider traffic: real RSA validation and read-only Git readiness."""
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import subprocess
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from race_ai import keirin_nationwide_auto_storage as storage


def run_git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


class OfficialReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.pem = key.private_bytes(serialization.Encoding.PEM,
                                   serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()).decode("ascii")
        cls.pin = sha256(key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        run_git(self.repo, "init", "--initial-branch=main")
        (self.repo / "fixture.txt").write_text("Synthetic readiness fixture only.\n")
        run_git(self.repo, "add", "fixture.txt")
        run_git(self.repo, "-c", "user.name=fixture", "-c",
                "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        run_git(self.repo, "remote", "add", "origin", "https://github.com/haji84/RACE-AI.git")
        self.env = {
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "haji84/RACE-AI",
            "GITHUB_REPOSITORY_ID": "1416489937", "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": "123456",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": run_git(self.repo, "rev-parse", "HEAD"),
            "RACE_AI_KEIRIN_PRIVATE_RSA_PEM": self.pem,
            "RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED": "true",
            "RACE_AI_AB_PUBLIC_CAPTURE_ENABLED": "true",
            "RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED": "true",
            "RACE_AI_AB_SOURCE_S3_PREFIX": "",
            "RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED": "true",
        }
        self.commands = []
        self.real_run = subprocess.run
        self.remote_returncode = 0
        self.remote_stdout = "a" * 40 + "\trefs/heads/state/keirin-encrypted-history\n"

    def implementation(self):
        try:
            from scripts import keirin_official_readiness
        except ImportError:
            self.fail("The source-free readiness entry point is missing")
        return keirin_official_readiness

    def transport(self, command, **kwargs):
        self.commands.append(command)
        self.assertNotIn("RACE_AI_KEIRIN_PRIVATE_RSA_PEM", kwargs.get("env", {}))
        if command == ["git", "ls-remote", "--exit-code", "--refs", "origin",
                       "refs/heads/state/keirin-encrypted-history"]:
            return subprocess.CompletedProcess(command, self.remote_returncode,
                                               self.remote_stdout)
        if command in (["git", "remote", "get-url", "--all", "origin"],
                       ["git", "rev-parse", "HEAD"]):
            return self.real_run(command, **kwargs)
        self.fail("Readiness attempted a non-read-only Git command")

    def assess(self, *, changes=None, matching_fixture_pin=True):
        readiness = self.implementation()
        env = dict(self.env, **(changes or {}))
        selected_pin = self.pin if matching_fixture_pin else storage.PINNED_OWNER_SPKI_SHA256
        with patch.dict(os.environ, env, clear=True), \
             patch.object(storage, "PINNED_OWNER_SPKI_SHA256", selected_pin), \
             patch.object(readiness.subprocess, "run", side_effect=self.transport), \
             patch("socket.socket.connect", side_effect=AssertionError("Provider network is forbidden")):
            return readiness.assess(repo=self.repo)

    def test_real_matching_rsa_and_existing_branch_verify_configuration_only_without_writes(self):
        before = {str(path.relative_to(self.repo)): sha256(path.read_bytes()).hexdigest()
                  for path in self.repo.rglob("*") if path.is_file()}
        report = self.assess()
        after = {str(path.relative_to(self.repo)): sha256(path.read_bytes()).hexdigest()
                 for path in self.repo.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(report["state"], "CONFIGURATION_READY_LIVE_ACCEPTANCE_PENDING")
        self.assertTrue(report["checks"]["owner_private_key_matches_pin"])
        self.assertTrue(report["checks"]["state_branch_readable"])
        self.assertEqual(report["provider_requests"], 0)
        self.assertEqual(report["state_writes"], 0)
        self.assertFalse(report["live_acceptance_completed"])
        self.assertEqual(report["source_commit"], self.env["GITHUB_SHA"])
        self.assertEqual(len(self.commands), 3)
        self.assertNotIn("PRIVATE KEY", json.dumps(report))

    def test_real_synthetic_rsa_cannot_match_the_existing_owner_pin(self):
        report = self.assess(matching_fixture_pin=False)
        self.assertEqual(report["state"], "HOLD_OWNER_PUBLIC_SPKI_PIN_MISMATCH")
        self.assertFalse(report["checks"]["owner_private_key_matches_pin"])
        self.assertEqual(self.commands, [])

    def test_missing_and_invalid_keys_are_fixed_holds_before_git_access(self):
        for value, expected in (
            ("", "HOLD_EXISTING_OWNER_PRIVATE_SECRET_NOT_CONFIGURED"),
            ("private-untrusted-error-sentinel", "HOLD_EXISTING_OWNER_PRIVATE_SECRET_INVALID"),
        ):
            with self.subTest(expected=expected):
                report = self.assess(changes={"RACE_AI_KEIRIN_PRIVATE_RSA_PEM": value})
                self.assertEqual(report["state"], expected)
                self.assertNotIn("private-untrusted-error-sentinel", json.dumps(report))
                self.assertEqual(self.commands, [])

    def test_untrusted_contexts_never_read_the_key_or_state_remote(self):
        for changes in (
            {"GITHUB_ACTIONS": "false"}, {"GITHUB_REPOSITORY": "fork/RACE-AI"},
            {"GITHUB_REPOSITORY_ID": "999"}, {"GITHUB_REF": "refs/heads/feature"},
            {"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_EVENT_NAME": "schedule"},
            {"GITHUB_RUN_ID": "0"}, {"GITHUB_RUN_ATTEMPT": ""},
            {"GITHUB_SHA": "private-invalid-commit"},
            {"GITHUB_EVENT_NAME": "workflow_dispatch", "RACE_AI_KEIRIN_READINESS_MODE": "run"},
        ):
            with self.subTest(changes=changes):
                report = self.assess(changes={**changes, "RACE_AI_KEIRIN_PRIVATE_RSA_PEM": ""})
                self.assertEqual(report["state"], "HOLD_UNTRUSTED_READINESS_CONTEXT")
                self.assertEqual(self.commands, [])
                self.assertNotIn("private-invalid-commit", json.dumps(report))
        self.assertEqual(self.assess(changes={"GITHUB_EVENT_NAME": "workflow_dispatch",
            "RACE_AI_KEIRIN_READINESS_MODE": "readiness"})["state"],
            "CONFIGURATION_READY_LIVE_ACCEPTANCE_PENDING")

    def test_origin_and_checkout_binding_reject_before_remote_access(self):
        report = self.assess(changes={"GITHUB_SHA": "b" * 40})
        self.assertEqual(report["state"], "HOLD_CHECKOUT_COMMIT_MISMATCH")
        self.assertFalse(any(command[1] == "ls-remote" for command in self.commands))
        self.commands.clear()
        run_git(self.repo, "remote", "set-url", "origin", "https://example.invalid/private-origin")
        report = self.assess()
        self.assertEqual(report["state"], "HOLD_UNEXPECTED_GIT_REMOTE")
        self.assertFalse(any(command[1] == "ls-remote" for command in self.commands))
        self.assertNotIn("example.invalid", json.dumps(report))

    def test_missing_ambiguous_and_invalid_remote_branch_never_report_ready(self):
        for status, output, expected in (
            (2, "", "HOLD_EXISTING_STATE_BRANCH_NOT_FOUND"),
            (128, "private-transport-error", "HOLD_STATE_BRANCH_NOT_READABLE"),
            (0, "a" * 40 + "\trefs/heads/another-state\n", "HOLD_STATE_BRANCH_RESPONSE_INVALID"),
            (0, self.remote_stdout * 2, "HOLD_STATE_BRANCH_RESPONSE_INVALID"),
        ):
            with self.subTest(status=status, expected=expected):
                self.remote_returncode, self.remote_stdout = status, output
                report = self.assess()
                self.assertEqual(report["state"], expected)
                self.assertFalse(report["checks"]["state_branch_readable"])
                self.assertNotIn("private-transport-error", json.dumps(report))

    def test_each_opt_in_is_reported_without_disclosing_its_value_or_claiming_live_completion(self):
        for name, value, check in (
            ("RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED", "false", "ab_autogen_enabled"),
            ("RACE_AI_AB_PUBLIC_CAPTURE_ENABLED", "", "public_capture_enabled"),
            ("RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED", "false", "github_state_store_enabled"),
            ("RACE_AI_AB_SOURCE_S3_PREFIX", "private-prefix-sentinel", "external_source_store_unconfigured"),
            ("RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED", "false", "official_source_enabled"),
        ):
            with self.subTest(name=name):
                report = self.assess(changes={name: value})
                self.assertTrue(report["state"].startswith("HOLD_"))
                self.assertFalse(report["checks"][check])
                self.assertTrue(report["checks"]["state_branch_readable"])
                self.assertFalse(report["live_acceptance_completed"])
                self.assertNotIn("private-prefix-sentinel", json.dumps(report))

    def test_official_results_configuration_is_independent_from_new_capture(self):
        report = self.assess(changes={
            "RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED": "false",
            "RACE_AI_AB_PUBLIC_CAPTURE_ENABLED": "false",
        })
        self.assertEqual(report["state"], "HOLD_NATIONWIDE_AB_NOT_SELECTED")
        self.assertTrue(report["independent_result_route_configured"])
        self.assertFalse(report["live_acceptance_completed"])
        self.assertEqual(report["provider_requests"], 0)
        self.assertEqual(report["state_writes"], 0)
        self.assertFalse(self.assess(changes={
            "RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED": "false",
            "RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED": "",
        })["independent_result_route_configured"])

    def test_cli_missing_secret_emits_only_fixed_json_and_failure_exit(self):
        readiness = self.implementation()
        output = StringIO()
        with patch.dict(os.environ, dict(self.env, RACE_AI_KEIRIN_PRIVATE_RSA_PEM=""), clear=True), \
             redirect_stdout(output):
            code = readiness.main(["--repo", str(self.repo)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["state"],
                         "HOLD_EXISTING_OWNER_PRIVATE_SECRET_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
