"""Saved-only acceptance uses real crypto/Git; only remote transport is local."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json
import os
import subprocess
import sys
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_run_history as history
from scripts import keirin_official_day_pipeline as pipeline
from tests.test_keirin_official_run_history import git

DAY = "2026-11-18"
NOW = datetime(2026, 11, 19, 1, tzinfo=timezone.utc)


class OfficialSavedOnlyCheck(unittest.TestCase):
    def setUp(self):
        # Shared fixture creates actual frozen forecasts and authenticated
        # synthetic server artifacts. No scorer or decryption is replaced.
        from tests.test_keirin_official_day_pipeline import OfficialCollectedSettlement
        from tests.test_keirin_official_public_source import fixtures
        from race_ai import keirin_official_public_source as official
        from urllib.parse import parse_qs, urlsplit
        OfficialCollectedSettlement.setUp(self)
        self.root = Path(self.tmp.name)
        key = serialization.load_pem_private_key(self.pem, password=None)
        self.public = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        data = json.loads(json.dumps(fixtures()).replace("20261002", "20261118")
                          .replace("2026/10/02", "2026/11/18"))
        data["JSJ017"]["rInfo"] = data["JSJ017"]["rInfo"][:1]
        data["JSJ001"]["C0201data"]["C0201race"] = data["JSJ001"]["C0201data"]["C0201race"][:1]
        self.data = data
        get = lambda url: json.dumps(data[parse_qs(urlsplit(url).query)["type"][0]]).encode()
        clock = lambda: datetime(2026, 11, 18, 8, tzinfo=timezone.utc)
        self.schedule = official.fetch_day_schedule(DAY, fetcher=get, clock=clock)
        self.record = official.fetch_race_result(self.rid, schedule=self.schedule,
                                                fetcher=get, clock=clock)
        self.origin, self.writer, self.reader = [self.root / name for name in
                                               ("origin.git", "writer", "reader")]
        git(self.root, "init", "--bare", "-b", archive.BRANCH, str(self.origin))
        git(self.root, "clone", str(self.origin), str(self.writer))
        git(self.writer, "config", "user.name", "Synthetic saved-only fixture")
        git(self.writer, "config", "user.email", "fixture@example.invalid")
        (self.writer / "README.md").write_text("Synthetic existing history only.\n")
        git(self.writer, "add", "README.md")
        git(self.writer, "commit", "-m", "existing synthetic history")
        git(self.writer, "push", "origin", archive.BRANCH)
        git(self.root, "clone", str(self.origin), str(self.reader))
        git(self.reader, "checkout", "-b", "main")
        git(self.reader, "remote", "set-url", "origin", "https://github.com/haji84/RACE-AI.git")
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "haji84/RACE-AI",
            "GITHUB_REPOSITORY_ID": "1416489937", "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "987654",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": git(self.reader, "rev-parse", "HEAD"),
            "RACE_AI_KEIRIN_SAVED_CHECK_MODE": "saved-only",
            "RACE_AI_KEIRIN_PRIVATE_RSA_PEM": self.pem.decode("ascii"),
            "RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED": "false",
            "RACE_AI_AB_PUBLIC_CAPTURE_ENABLED": "false",
            "RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED": "false",
            "RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED": "false",
        }
        self.commands, self.invocations = [], 0
        self.real_run = subprocess.run

    def seed(self, *, result=True, bundle=True, original=True):
        if original:
            archive.append_once(repo=self.writer, raw_cipher=self.original["raw_cipher"],
                expected_cipher_sha256=self.original["cipher_sha256"],
                producer_run_id=self.original["producer_run_id"],
                producer_commit=self.original["producer_commit"], synthetic_local=True)
        safe = {"day_jst": DAY}
        payload = {"schema": "RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1",
                   "kind": "OFFICIAL_SETTLEMENT", "day_jst": DAY,
                   "schedule": self.schedule, "safe_report": safe,
                   "official_records": {self.rid: self.record} if result else {},
                   "origin_run_bundles": {"123456": self.bundle} if bundle else {}}
        raw = history.seal_evidence(pipeline.private_snapshot_json(payload),
            self.public, DAY, "2026-11-18T17:00:00+09:00")
        history.append_revision(repo=self.writer, day=DAY, raw_cipher=raw,
                                safe_report=safe, synthetic_local=True)

    def implementation(self):
        try:
            from scripts import keirin_official_saved_check
        except ImportError:
            self.fail("The explicit, read-only saved-history entry point is missing")
        return keirin_official_saved_check

    def transport(self, command, **kwargs):
        self.commands.append(command)
        self.assertNotIn("RACE_AI_KEIRIN_PRIVATE_RSA_PEM", kwargs.get("env", {}))
        self.assertFalse(set(command) & {"push", "commit", "update-ref", "reset", "worktree"})
        actual = list(command)
        if command[0] == "git" and ("fetch" in command or "ls-remote" in command):
            actual[actual.index("origin")] = str(self.origin)
        return self.real_run(actual, **kwargs)

    def invoke(self, changes=None):
        implementation = self.implementation()
        self.invocations += 1
        output = self.root / f"check-{self.invocations}"
        env = dict(self.env, **(changes or {}))
        stream = StringIO()
        with patch.dict(os.environ, env, clear=True), \
             patch("subprocess.run", side_effect=self.transport), \
             patch("socket.create_connection", side_effect=AssertionError("No HTTP traffic is allowed")), \
             redirect_stdout(stream):
            status = implementation.main(["--repo", str(self.reader),
                "--private-root", str(output)], clock=lambda: NOW)
        return status, json.loads(stream.getvalue()), output

    def test_saved_history_is_replayed_with_all_live_flags_off_without_remote_writes(self):
        self.seed()
        before = git(self.origin, "rev-parse", archive.BRANCH)
        status, report, output = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual(report["state"], "SAVED_ONLY_REPLAYED_LIVE_ACCEPTANCE_PENDING")
        self.assertEqual(report["observed_state_commit"], before)
        self.assertEqual(report["provider_requests"], 0)
        self.assertEqual(report["state_writes"], 0)
        self.assertFalse(report["live_acceptance_completed"])
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), before)
        self.assertEqual(report["days_completed"], 1)
        saved = json.loads((output / DAY / "safe.json").read_bytes())
        self.assertEqual(saved["paired_A_B_scored"], 1)
        owner = history.decrypt_evidence((output / DAY / "owner-view.sealed.json").read_bytes(), self.pem)
        self.assertIn("ranked_tickets", owner["owner_rows"][0]["A"])
        self.assertEqual(owner["safe_report"], saved)
        files = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
        self.assertEqual(files, {"batch-safe.json", f"{DAY}/safe.json", f"{DAY}/owner-view.sealed.json"})
        for path in output.rglob("*"):
            if path.is_file():
                raw = path.read_bytes()
                self.assertNotIn(b"PRIVATE KEY", raw)
                self.assertNotIn(b"ranked_tickets", raw)
                self.assertNotIn("架空選手".encode(), raw)

    def test_empty_existing_state_is_explicit_hold_and_nonzero(self):
        status, report, output = self.invoke()
        self.assertEqual(status, 2)
        self.assertEqual(report["state"], "HOLD_NO_SAVED_OFFICIAL_DAYS")
        self.assertFalse(report["live_acceptance_completed"])
        self.assertEqual(list(output.rglob("*.sealed.json")), [])

    def test_owner_review_archive_is_not_promoted_to_official_evidence(self):
        path = self.writer / "state/keirin/owner-review/v1/2026-11-18/owner-view.sealed.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"synthetic_opaque_owner_review":"not an official delta"}\n')
        git(self.writer, "add", str(path.relative_to(self.writer)))
        git(self.writer, "commit", "-m", "synthetic separate owner review namespace")
        git(self.writer, "push", "origin", archive.BRANCH)
        status, report, output = self.invoke()
        self.assertEqual(status, 2)
        self.assertEqual(report["state"], "HOLD_NO_SAVED_OFFICIAL_DAYS")
        self.assertEqual(report["days_completed"], 0)
        self.assertEqual(list(output.rglob("*.sealed.json")), [])

    def test_missing_saved_origin_does_not_trigger_api_or_persist_and_is_not_success(self):
        self.seed(bundle=False)
        before = git(self.origin, "rev-parse", archive.BRANCH)
        status, report, output = self.invoke()
        self.assertEqual(status, 2)
        self.assertEqual(report["state"], "HOLD_SAVED_EVIDENCE_INCOMPLETE")
        self.assertEqual(report["days_held"], 1)
        saved = json.loads((output / DAY / "safe.json").read_bytes())
        self.assertEqual(saved["paired_A_B_scored"], 0)
        self.assertEqual(saved["original_proof_states"][self.rid],
                         "HOLD_GITHUB_ORIGIN_EVIDENCE_NOT_AVAILABLE")
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), before)

    def test_missing_saved_result_is_hold_without_requesting_a_provider(self):
        self.seed(result=False)
        status, report, output = self.invoke()
        self.assertEqual(status, 2)
        self.assertEqual(report["state"], "HOLD_SAVED_EVIDENCE_INCOMPLETE")
        saved = json.loads((output / DAY / "safe.json").read_bytes())
        self.assertEqual(saved["official_result_states"][self.rid], "HOLD_OFFICIAL_RESULT_NOT_COLLECTED")

    def test_saved_schedule_results_and_bundle_cannot_hide_missing_frozen_original(self):
        self.seed(original=False)
        status, report, output = self.invoke()
        self.assertEqual(status, 2)
        self.assertEqual(report["state"], "HOLD_SAVED_EVIDENCE_INCOMPLETE")
        self.assertEqual(report["days_completed"], 0)
        saved = json.loads((output / DAY / "safe.json").read_bytes())
        self.assertEqual(saved["registered_races"], 1)
        self.assertEqual(saved["originals_present"], 0)
        self.assertEqual(saved["paired_A_B_scored"], 0)
        self.assertEqual(saved["missing_originals"], 1)

    def test_invalid_cli_arguments_cannot_echo_accidentally_pasted_private_values(self):
        implementation = self.implementation()
        marker = "SYNTHETIC_ARG_SECRET_DO_NOT_ECHO"
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                status = implementation.main(["--repo", str(self.reader),
                    "--private-root", str(self.root / "invalid-args"), "--unexpected", marker])
            except SystemExit as exc:
                status = exc.code
        self.assertNotIn(marker, stdout.getvalue() + stderr.getvalue())
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(stdout.getvalue())["state"], "HOLD_SAVED_ONLY_ARGUMENTS_INVALID")

    def test_untrusted_events_refs_repository_and_run_identity_are_rejected_before_git(self):
        for change in (
            {"GITHUB_EVENT_NAME": "schedule"}, {"GITHUB_EVENT_NAME": "push"},
            {"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_REF": "refs/heads/feature"},
            {"GITHUB_REPOSITORY": "fork/RACE-AI"}, {"GITHUB_REPOSITORY_ID": "999"},
            {"GITHUB_RUN_ID": ""}, {"GITHUB_RUN_ATTEMPT": "0"},
            {"GITHUB_SHA": "0" * 40}, {"RACE_AI_KEIRIN_SAVED_CHECK_MODE": "run"},
        ):
            with self.subTest(change=change):
                self.commands.clear()
                status, report, _ = self.invoke(change)
                self.assertEqual(status, 2)
                self.assertEqual(report["state"], "HOLD_UNTRUSTED_SAVED_ONLY_CONTEXT")
                self.assertEqual(self.commands, [])

    def test_missing_invalid_and_wrong_owner_keys_are_rejected_before_state_read(self):
        wrong = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        wrong_pem = wrong.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("ascii")
        for pem, reason in (("", "EXISTING_OWNER_PRIVATE_SECRET_NOT_CONFIGURED"),
            ("not a key with private bytes", "EXISTING_OWNER_PRIVATE_SECRET_INVALID"),
            (wrong_pem, "OWNER_PUBLIC_SPKI_PIN_MISMATCH")):
            with self.subTest(reason=reason):
                self.commands.clear()
                status, report, _ = self.invoke({"RACE_AI_KEIRIN_PRIVATE_RSA_PEM": pem})
                self.assertEqual(status, 2)
                self.assertEqual(report["state"], "HOLD_" + reason)
                self.assertEqual(self.commands, [])
                self.assertNotIn(pem or "PRIVATE KEY", json.dumps(report))

    def test_origin_and_checkout_mismatch_cannot_read_saved_state(self):
        for wrong in ("origin", "commit"):
            with self.subTest(wrong=wrong):
                if wrong == "origin":
                    git(self.reader, "remote", "set-url", "origin", "https://github.com/fork/RACE-AI.git")
                else:
                    git(self.reader, "remote", "set-url", "origin", "https://github.com/haji84/RACE-AI.git")
                self.commands.clear()
                status, report, _ = self.invoke({"GITHUB_SHA": "a" * 40} if wrong == "commit" else None)
                self.assertEqual(status, 2)
                self.assertEqual(report["state"], "HOLD_UNEXPECTED_GIT_REMOTE" if wrong == "origin"
                                 else "HOLD_CHECKOUT_COMMIT_MISMATCH")
                self.assertFalse(any("fetch" in command for command in self.commands))

    def test_corrupt_archive_is_a_hold_and_never_overwrites_originals(self):
        self.seed()
        git(self.writer, "pull", "--ff-only", "origin", archive.BRANCH)
        sealed, _ = archive._refs(self.rid)
        path = self.writer / sealed
        path.write_bytes(path.read_bytes() + b"tampered")
        git(self.writer, "add", sealed)
        git(self.writer, "commit", "-m", "synthetic corrupt archive")
        git(self.writer, "push", "origin", archive.BRANCH)
        before = git(self.origin, "rev-parse", archive.BRANCH)
        status, report, _ = self.invoke()
        self.assertEqual(status, 2)
        self.assertEqual(report["state"], "HOLD_SAVED_EVIDENCE_INCOMPLETE")
        self.assertEqual(report["days_held"], 1)
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), before)

    def test_saved_result_revision_replays_latest_lineage_without_touching_prior_bytes(self):
        from race_ai import keirin_official_public_source as official
        from urllib.parse import parse_qs, urlsplit
        self.seed()
        self.data["JSJ018"]["resultList"][0]["harai3renList"][0]["kingaku"] = "2,340円"
        self.data["JSJ012"]["haraiGakuSubData"]["RT3HaraiGakuDispItemSubData"][0]["haraiGaku"] = "2,340"
        self.data["JSJ012"]["lastUpdateTime"] = "2026/11/18 12:06&nbsp;更新"
        get = lambda url: json.dumps(self.data[parse_qs(urlsplit(url).query)["type"][0]]).encode()
        corrected = official.fetch_race_result(self.rid, schedule=self.schedule, fetcher=get,
            clock=lambda: datetime(2026, 11, 18, 8, 10, tzinfo=timezone.utc),
            previous_result=self.record["result"])
        safe = {"day_jst": DAY}
        raw = history.seal_evidence(pipeline.private_snapshot_json({
            "schema": "RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1", "kind": "OFFICIAL_SETTLEMENT",
            "day_jst": DAY, "safe_report": safe, "official_records": {self.rid: corrected}}),
            self.public, DAY, "2026-11-18T17:10:00+09:00")
        history.append_revision(repo=self.writer, day=DAY, raw_cipher=raw,
                                safe_report=safe, synthetic_local=True)
        before = git(self.origin, "rev-parse", archive.BRANCH)
        status, _, output = self.invoke()
        self.assertEqual(status, 0)
        restored = history.decrypt_evidence((output / DAY / "owner-view.sealed.json").read_bytes(), self.pem)
        self.assertEqual(restored["owner_rows"][0]["result"]["payouts_100yen"][0]["yen"], 2340)
        self.assertEqual(restored["safe_report"]["result_receipts"][0]["cipher_file_sha256"],
                         self.original["cipher_sha256"])
        self.assertEqual(git(self.origin, "rev-parse", archive.BRANCH), before)

    def test_actual_missing_dependency_cannot_be_reported_as_success(self):
        # -S removes installed third-party dependencies in a fresh process;
        # no import or runtime operation is mocked into succeeding.
        output = self.root / "missing-dependencies"
        source = Path(__file__).resolve().parents[1]
        code = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
                "runpy.run_module('scripts.keirin_official_saved_check',run_name='__main__')")
        done = self.real_run([sys.executable, "-I", "-S", "-c", code, str(source),
            "--repo", str(self.reader), "--private-root", str(output)],
            env=self.env, text=True, capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 2)
        report = json.loads(done.stdout)
        self.assertEqual(report["state"], "HOLD_SAVED_ONLY_DEPENDENCY_UNAVAILABLE")
        self.assertNotIn("PRIVATE KEY", done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
