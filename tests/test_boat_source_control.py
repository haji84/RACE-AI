"""Safe public counters accompany encrypted continuity; host needs no key."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import base64
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai import boat_private_original_archive as archive
from race_ai.github_continuous_supervisor import GitHubCLI, GitHubSupervisor, OWNED_TRIGGER_LINE, BRANCH, WORKFLOW_FILE, TRIGGER
from tests.test_continuity_checkpoint import session

try:
    safe = importlib.import_module("race_ai.boat_source_control")
    cli = importlib.import_module("scripts.boat_source_control")
except ModuleNotFoundError:
    safe = cli = None

KEY = bytes(range(32))
HEAD = "a" * 40
NOW = datetime(2030, 4, 1, 2, 1, tzinfo=timezone.utc)


def zipped(name, body):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as source: source.writestr(name, body)
    return target.getvalue()


def metadata(raw, name, ident, *, created="2030-04-01T02:00:00Z"):
    return dict(id=ident, name=name, expired=False, created_at=created, size_in_bytes=len(raw),
                digest="sha256:"+sha256(raw).hexdigest(), workflow_run=dict(id=7, repository_id=1416489937,
                head_repository_id=1416489937, head_sha=HEAD))


class SafeSourceControlTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(safe, "safe source-control schema/producer is absent")
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.root.chmod(0o700)

    def fixture(self, **changes):
        values = dict(requests_used=3, completed_round=1, prepared_round=None, lifetime_requests_base=4,
                      lifetime_requests=7, lifetime_completed_rounds_base=5, lifetime_completed_rounds=6,
                      source_wait=None, halted_reason=None)
        values.update(changes)
        inner = zipped("repeat-session.json", session(**values))
        cipher = archive.seal_original_zip(inner, run_id=7, head_sha=HEAD, kind="CONTINUITY", key=KEY)
        raw = zipped("private-original.enc", cipher)
        meta = metadata(raw, "race-cycle-continuity-7", 70)
        document = safe.build_summary(cipher, run_id=7, head_sha=HEAD, key=KEY)
        public = zipped("source-control.json", json.dumps(document).encode())
        public_meta = metadata(public, "race-source-control-7", 71, created="2030-04-01T02:00:01Z")
        return cipher, raw, meta, document, public, public_meta

    def client(self, raw, meta, public=None, public_meta=None):
        artifacts = [meta] + ([] if public_meta is None else [public_meta])
        mapping = {"actions/runs/7/artifacts?per_page=100": json.dumps(dict(total_count=len(artifacts), artifacts=artifacts)).encode(),
                   "actions/artifacts/70": json.dumps(meta).encode(), "actions/artifacts/70/zip": raw}
        if public_meta is not None:
            mapping.update({"actions/artifacts/71": json.dumps(public_meta).encode(), "actions/artifacts/71/zip": public})
        client = GitHubCLI()
        reader = patch.object(client, "raw", side_effect=lambda route: mapping[route]); reader.start(); self.addCleanup(reader.stop)
        return client

    def test_producer_exports_only_whitelisted_fields_from_exact_sealed_state(self):
        cipher, _, _, summary, _, _ = self.fixture(private_rows=[dict(secret="DO_NOT_PUBLISH_NATIVE")],
                                                  source_url="https://private.invalid/DO_NOT_PUBLISH_NATIVE",
                                                  control_reason="PRIVATE_RACER_DO_NOT_PUBLISH_NATIVE")
        encoded = json.dumps(summary).encode()
        self.assertNotIn(b"DO_NOT_PUBLISH_NATIVE", encoded)
        self.assertNotIn(b"source_url", encoded)
        self.assertEqual(summary["continuity_cipher_sha256"], sha256(cipher).hexdigest())
        self.assertEqual(summary["control"]["stop_reason"], "SOURCE_REVIEW_REQUIRED")
        self.assertTrue(safe.validate_summary(summary))
        runner = self.root/"runner"; runner.mkdir(mode=0o700)
        source = runner/"private-original.enc"; source.write_bytes(cipher); source.chmod(0o600)
        output = runner/"control"
        env = dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY="haji84/RACE-AI", GITHUB_REPOSITORY_ID="1416489937",
                   GITHUB_RUN_ID="7", GITHUB_SHA=HEAD, RUNNER_TEMP=str(runner), RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        with patch.dict(os.environ, env, clear=True), redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(cli.main(["pack", "--cipher", str(source), "--output-dir", str(output)]), 0)
            first = (output/"source-control.json").read_bytes()
            self.assertEqual(cli.main(["pack", "--cipher", str(source), "--output-dir", str(output)]), 0)
        self.assertEqual(json.loads(first), summary)
        self.assertEqual([p.name for p in output.iterdir()], ["source-control.json"])
        self.assertEqual((output.stat().st_mode & 0o777, (output/"source-control.json").stat().st_mode & 0o777), (0o700, 0o600))
        self.assertNotIn(base64.b64encode(KEY).decode(), stdout.getvalue())

    def test_optional_day_budget_baseline_is_bound_to_existing_encrypted_checkpoint(self):
        _, raw, meta, summary, public, public_meta = self.fixture(
            day_start_lifetime_requests=5)
        self.assertEqual(summary['control']['day_start_lifetime_requests'],5)
        client=self.client(raw,meta,public,public_meta)
        with patch.dict(os.environ,{},clear=True):
            control=client.final_control(dict(id=7,head_sha=HEAD))
        self.assertEqual(control['day_start_lifetime_requests'],5)
        self.assertEqual(control['lifetime_requests'],7)
        self.assertEqual(control['previous_session_requests'],3)
        for bad in (-1,8):
            with self.subTest(invalid_base=bad):
                with self.assertRaises(ValueError):
                    self.fixture(day_start_lifetime_requests=bad)

    def test_host_reads_actual_summary_and_cipher_receipts_without_accessing_key(self):
        _, raw, meta, _, public, public_meta = self.fixture()
        client = self.client(raw, meta, public, public_meta)
        before = deepcopy((meta, public_meta))
        with patch.dict(os.environ, {}, clear=True), patch.object(archive, "_key", side_effect=AssertionError("host attempted decryption")):
            control = client.final_control(dict(id=7, head_sha=HEAD))
        self.assertEqual((control["previous_run_id"], control["previous_session_requests"], control["lifetime_requests"]), (7, 3, 7))
        self.assertEqual(control["day_jst"], "2030-04-01")
        self.assertEqual(control["receipt"], {k: meta[k] for k in ("id", "digest", "created_at")})
        self.assertEqual(control["source_control_receipt"], {k: public_meta[k] for k in ("id", "digest", "created_at")})
        self.assertEqual((meta, public_meta), before)

    def test_real_supervisor_preserves_handoff_waits_incomplete_rounds_and_hard_stops(self):
        cases = (({}, "HANDOFF_WAIT"),
                 ({"prepared_round": 2}, "REVIEW_WAIT"),
                 ({"source_wait": dict(state="AUTHORIZATION_WAIT", reason="SOURCE_AUTHORIZATION_REQUIRED", retry_at=None,
                                        http_status=403, attempts=1)}, "SOURCE_WAIT"),
                 ({"source_wait": dict(state="RATE_LIMIT_WAIT", reason="HTTP_RATE_LIMIT", retry_at="2030-04-02T02:00:00Z",
                                        http_status=429, attempts=2)}, "SOURCE_WAIT"),
                 ({"halted_reason": "UNKNOWN_PRIVATE_HALT"}, "SOURCE_WAIT"))
        for index, (changes, expected) in enumerate(cases):
            _, raw, meta, _, public, public_meta = self.fixture(**changes)
            client = self.client(raw, meta, public, public_meta)
            with self.subTest(changes=changes), patch.dict(os.environ, {}, clear=True), \
                 patch.object(client, "active_runs", return_value=[]), \
                 patch.object(client, "latest_run", return_value=dict(id=7, status="completed", conclusion="success", head_sha=HEAD)), \
                 patch.object(client, "read_trigger", return_value=dict(head=HEAD, content="owner\n")), \
                 patch.object(client, "append_trigger", return_value="b"*40) as append:
                folder = self.root/str(index); folder.mkdir(mode=0o700)
                supervisor = GitHubSupervisor(folder, client=client, clock=lambda: NOW)
                try: self.assertEqual(supervisor.tick()["state"], expected)
                finally: supervisor.stop()
                self.assertEqual(append.call_count, int(expected == "HANDOFF_WAIT"))
                if append.called:
                    text = append.call_args.args[1]
                    self.assertIn("bounded per-worker handoff", text)
                    self.assertNotIn("unlimited", text)
                    self.assertIsNotNone(OWNED_TRIGGER_LINE.fullmatch(text.lstrip("\n")))

    def test_tampered_public_fields_or_sibling_artifact_never_fall_back(self):
        _, raw, meta, summary, public, public_meta = self.fixture()
        for kind in ("extra", "nested", "run", "head", "cipher", "digest", "repository", "expired"):
            doc = deepcopy(summary); checked = deepcopy(public_meta)
            if kind == "extra": doc["source_url"] = "https://private.invalid"
            if kind == "nested": doc["control"]["rows"] = []
            if kind == "run": doc["run_id"] = 8
            if kind == "head": doc["head_sha"] = "b"*40
            if kind == "cipher": doc["continuity_cipher_sha256"] = "f"*64
            altered = zipped("source-control.json", json.dumps(doc).encode())
            checked.update(digest="sha256:"+sha256(altered).hexdigest(), size_in_bytes=len(altered))
            if kind == "digest": checked["digest"] = "sha256:"+"0"*64
            if kind == "repository": checked["workflow_run"]["repository_id"] = 1
            if kind == "expired": checked["expired"] = True
            client = self.client(raw, meta, altered, checked)
            with self.subTest(kind=kind), patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
                client.final_control(dict(id=7, head_sha=HEAD))
        _, different, different_meta, _, _, _ = self.fixture(requests_used=4, lifetime_requests=8)
        with self.assertRaises(ValueError): self.client(different, different_meta, public, public_meta).final_control(dict(id=7, head_sha=HEAD))

    def test_legacy_clear_fallback_works_but_encrypted_without_companion_holds(self):
        _, raw, meta, _, _, _ = self.fixture()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): self.client(raw, meta).final_control(dict(id=7, head_sha=HEAD))
            clear = zipped("repeat-session.json", session(prepared_round=None))
            legacy = metadata(clear, "race-cycle-continuity-7", 70)
            control = self.client(clear, legacy).final_control(dict(id=7, head_sha=HEAD))
        self.assertEqual(control["previous_run_id"], 7)
        self.assertEqual(control["lifetime_requests"], 700)
        self.assertEqual(control["day_jst"], "2030-04-01")

    def test_day_handoff_waits_until_jst_midnight_after_preserving_source_denials(self):
        _, raw, meta, _, public, public_meta = self.fixture(control_reason="DAY_HANDOFF")
        client = self.client(raw, meta, public, public_meta)
        now = datetime(2030, 4, 1, 14, 50, tzinfo=timezone.utc)
        current = [now]
        with patch.dict(os.environ, {}, clear=True), patch.object(client, "active_runs", return_value=[]), \
             patch.object(client, "latest_run", return_value=dict(id=7, status="completed", conclusion="success", head_sha=HEAD)), \
             patch.object(client, "read_trigger", return_value=dict(head=HEAD, content="owner\n")) as trigger, \
             patch.object(client, "append_trigger", return_value="b"*40) as append:
            supervisor = GitHubSupervisor(self.root, client=client, clock=lambda: current[0])
            try:
                first = supervisor.tick()
                self.assertEqual(first["state"], "WAITING")
                self.assertEqual(first["waiting_reason"], "NEXT_JST_DAY")
                self.assertEqual(first["next_run_at"], "2030-04-02T00:00:00+09:00")
                self.assertEqual((trigger.call_count, append.call_count), (0, 0))
                self.assertEqual(supervisor.tick()["state"], "WAITING")
                current[0] = datetime(2030, 4, 1, 15, tzinfo=timezone.utc)
                self.assertEqual(supervisor.tick()["state"], "HANDOFF_WAIT")
                self.assertEqual(append.call_count, 1)
            finally: supervisor.stop()
        wait = dict(state="AUTHORIZATION_WAIT", reason="SOURCE_AUTHORIZATION_REQUIRED", retry_at=None, http_status=403, attempts=1)
        _, raw, meta, _, public, public_meta = self.fixture(control_reason="DAY_HANDOFF", source_wait=wait)
        denied = self.client(raw, meta, public, public_meta)
        folder = self.root/"denied"; folder.mkdir(mode=0o700)
        with patch.dict(os.environ, {}, clear=True), patch.object(denied, "active_runs", return_value=[]), \
             patch.object(denied, "latest_run", return_value=dict(id=7, status="completed", conclusion="success", head_sha=HEAD)), \
             patch.object(denied, "read_trigger", side_effect=AssertionError("source denial bypassed")):
            supervisor = GitHubSupervisor(folder, client=denied, clock=lambda: now)
            try: self.assertEqual(supervisor.tick()["state"], "SOURCE_WAIT")
            finally: supervisor.stop()

    def test_producer_rejects_wrong_scope_changed_output_and_non_actions_environment(self):
        cipher, _, _, _, _, _ = self.fixture()
        with self.assertRaises(ValueError): safe.build_summary(cipher, run_id=8, head_sha=HEAD, key=KEY)
        with self.assertRaises(ValueError): safe.build_summary(cipher, run_id=7, head_sha="b"*40, key=KEY)
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["pack", "--cipher", "absent", "--output-dir", str(self.root/"out")]), 2)

    def test_http_wait_normalization_uses_actual_continuity_save_and_never_slides(self):
        for status in (401, 403, 429):
            _, raw, meta, _, public, public_meta = self.fixture(halted_reason=f"SOURCE_HTTP_{status}_NO_RETRY")
            client = self.client(raw, meta, public, public_meta)
            with patch.dict(os.environ, {}, clear=True):
                first = client.final_control(dict(id=7, head_sha=HEAD))
                self.assertEqual(client.final_control(dict(id=7, head_sha=HEAD)), first)
            self.assertEqual(first["source_wait"]["http_status"], status)
            if status == 429:
                self.assertEqual(first["source_wait"]["retry_at"], "2030-04-01T02:03:00+00:00")
                self.assertIsNone(first["previous_halted_reason"])
            else:
                self.assertEqual(first["source_wait"]["state"], "AUTHORIZATION_WAIT")
                self.assertIsNone(first["source_wait"]["retry_at"])

    def test_producer_private_paths_and_immutable_output_fail_closed(self):
        cipher, _, _, _, _, _ = self.fixture()
        runner = self.root/"runner"; runner.mkdir(mode=0o700)
        source = runner/"private-original.enc"; source.write_bytes(cipher); source.chmod(0o600)
        output = runner/"control"
        env = dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY="haji84/RACE-AI", GITHUB_REPOSITORY_ID="1416489937",
                   GITHUB_RUN_ID="7", GITHUB_SHA=HEAD, RUNNER_TEMP=str(runner), RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        with patch.dict(os.environ, env, clear=True):
            cli.pack(cipher_path=source, output_dir=output)
            (output/safe.MEMBER).write_bytes(b"{}")
            with self.assertRaises(ValueError): cli.pack(cipher_path=source, output_dir=output)
            self.assertEqual((output/safe.MEMBER).read_bytes(), b"{}")
            with self.assertRaises(ValueError): cli.pack(cipher_path=source, output_dir=runner/".."/"outside")
            link = runner/"linked.enc"; link.symlink_to(source)
            with self.assertRaises(ValueError): cli.pack(cipher_path=link, output_dir=runner/"other")
            source.chmod(0o644)
            with self.assertRaises(ValueError): cli.pack(cipher_path=source, output_dir=runner/"other")
        self.assertFalse((self.root/"outside").exists())


class ReviewedWorkerPolicyTests(unittest.TestCase):
    def test_exact_bounded_policy_and_workflow_are_required(self):
        from race_ai import github_continuous_supervisor as supervisor
        root = Path(supervisor.__file__).resolve().parents[1]
        # The historical PR71 supervisor protects its old bounded policy,
        # independently from the current approved production P1 worker.
        worker = b"MAX_ROUNDS = 24\\nMAX_SECONDS = 65 * 60\\nSOURCE_LIMIT = 240\\nROUND_SOURCE_LIMIT = 45\\nPOLL_SECONDS = 180\\n"
        workflow = (root/WORKFLOW_FILE).read_bytes()
        client = GitHubCLI()
        def api(path, **_):
            if path == "pulls/71": return dict(state="open", head=dict(ref=BRANCH, sha=HEAD))
            if path == "git/commits/"+HEAD: return dict(tree=dict(sha="b"*40))
            raise AssertionError(path)
        files = {"race_ai/repeated_cycle.py": worker, WORKFLOW_FILE: workflow, TRIGGER: b"owner\n"}
        with patch.object(client, "api", side_effect=api), patch.object(client, "_file", side_effect=lambda path, _: files[path]):
            self.assertEqual(client.read_trigger()["content"], "owner\n")
            for old, new in ((b"MAX_ROUNDS = 24", b"MAX_ROUNDS = None"),
                             (b"MAX_SECONDS = 65 * 60", b"MAX_SECONDS = None"),
                             (b"SOURCE_LIMIT = 240", b"SOURCE_LIMIT = 241"),
                             (b"ROUND_SOURCE_LIMIT = 45", b"ROUND_SOURCE_LIMIT = 46"),
                             (b"POLL_SECONDS = 180", b"POLL_SECONDS = 179")):
                self.assertIn(old, worker)
                files["race_ai/repeated_cycle.py"] = worker.replace(old, new, 1)
                with self.subTest(changed=old), self.assertRaises(ValueError): client.read_trigger()
            files["race_ai/repeated_cycle.py"] = worker
            for bad in (worker+b"\nMAX_ROUNDS = 24\n", worker.replace(b"MAX_ROUNDS = 24", b"MAX_ROUNDS = True", 1),
                        worker.replace(b"MAX_SECONDS = 65 * 60", b"MAX_SECONDS = 65 * True", 1),
                        worker.replace(b"POLL_SECONDS = 180", b"# missing POLL_SECONDS", 1)):
                files["race_ai/repeated_cycle.py"] = bad
                with self.assertRaises(ValueError): client.read_trigger()
            files["race_ai/repeated_cycle.py"] = worker
            files[WORKFLOW_FILE] = workflow+b"\n# not the reviewed bytes\n"
            with self.assertRaises(ValueError): client.read_trigger()
