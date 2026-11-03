"""Fictional case/ACL authorities; actual pinned models and local process storage."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import subprocess
import sys
import tempfile
import traceback
import tracemalloc
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import race_ai
import tests
REFERENCE = ROOT / "pr71-private-transport-reference"
race_ai.__path__.append(str(REFERENCE / "race_ai"))
tests.__path__.append(str(REFERENCE / "tests"))
from tests.test_offline_model_run import case, canonical, sha, Clock, MODELS, VERSIONS, MODEL_PIN, AT, LATE


def fixture(policy=None):
    manifest, raws, default, _ = case()
    policy = policy or default
    job = manifest["jobs"][0]
    check = job["input_check"]
    request = {"schema": "RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V1", "case_id": "fictional-boat-case-1",
        "race_id": job["race_id"], "ledger": manifest["ledger"],
        "source_payload_sha256": check["source_payload_sha256"],
        "policy_record_sha256": policy.document_sha256,
        "feature_snapshot_sha256": check["feature_snapshot_sha256"], "as_of": check["as_of"],
        "sales_cutoff_at": manifest["ledger"]["records"][0]["sales_cutoff_at"],
        "expected_model_ids": list(MODELS), "expected_model_versions": dict(VERSIONS),
        "model_source_sha40": MODEL_PIN, "executor_source_sha40": "d" * 40,
        "input_evidence_ref": "fictional-reviewed-input", "cutoff_evidence_ref": "fictional-official-cutoff",
        "model_declaration_evidence_ref": "fictional-prospective-declaration"}
    return request, raws[job["race_id"]], policy


def authorities(request, stages=None):
    declaration = tuple((name, VERSIONS[name], MODEL_PIN) for name in MODELS)
    def private(path, *, stage):
        if stages is not None:
            stages.append(stage)
        return True  # Authored test stand-in, NEVER a real Windows ACL proof.
    return {"private_path_verifier": private,
            "verify_input": lambda claimed, snapshot, policy_sha: claimed == request and policy_sha == request["policy_record_sha256"],
            "verify_cutoff": lambda row: row == request["ledger"]["records"][0],
            "admit_model_roster": lambda value: value == declaration}


def database_rows(path):
    with closing(sqlite3.connect(path)) as db:
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return db.execute("SELECT * FROM permissioned_case").fetchall() if ("permissioned_case",) in tables else []


def corrupt(path, alter):
    with closing(sqlite3.connect(path)) as db:
        trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='permissioned_case_no_update'").fetchone()[0]
        db.execute("DROP TRIGGER permissioned_case_no_update")
        request_sha, text, wire = db.execute("SELECT request_sha256,metadata,wire FROM permissioned_case").fetchone()
        metadata, wire = alter(json.loads(text), wire)
        digest = sha(b"RACE_AI_PERMISSIONED_MODEL_CASE_CHECKPOINT_V1\0" +
                     canonical([request_sha, metadata, sha(wire)]).encode())
        db.execute("UPDATE permissioned_case SET metadata=?,wire=?,content_sha256=?",
                   (canonical(metadata), wire, digest))
        db.execute(trigger)
        db.commit()


class PermissionedModelCaseTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.permissioned_model_case"),
                             "permissioned one-case checkpoint is missing")
        self.module = importlib.import_module("race_ai.permissioned_model_case")
        self.temp = tempfile.TemporaryDirectory(prefix="race-ai-permissioned-fictional-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private.sqlite"
        self.request, self.raw, self.policy = fixture()
        self.clock = Clock()
        self.network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def prepare(self, **overrides):
        options = authorities(self.request)
        options.update(overrides)
        return self.module.prepare_case(self.path, self.request, self.raw, self.policy, clock=self.clock, **options)

    def loaded(self, summary):
        return self.module.load_case(self.path, expected_request_sha256=summary["request_sha256"],
                                     private_path_verifier=authorities(self.request)["private_path_verifier"])

    def assert_denied_without_work(self, **overrides):
        from race_ai import permissioned_source_delivery as source
        with patch.object(source, "deliver", side_effect=AssertionError("model call before admission")):
            result = self.prepare(**overrides)
        self.assertEqual(result["status"], "NO_FORECAST")
        self.assertTrue(result["reasons"])
        self.assertFalse(self.path.exists())
        self.assertNotIn("snapshot", result)
        self.assertFalse(result["official_prediction"])
        return result

    def test_default_and_each_missing_authority_deny_before_model_or_target_creation(self):
        from race_ai import permissioned_source_delivery as source
        with patch.object(source, "deliver", side_effect=AssertionError("default model")):
            result = self.module.prepare_case(self.path, self.request, self.raw, self.policy, clock=self.clock)
        self.assertEqual(result["status"], "NO_FORECAST")
        self.assertFalse(self.path.exists())
        for name in authorities(self.request):
            with self.subTest(name=name):
                self.assert_denied_without_work(**{name: None})
                self.assert_denied_without_work(**{name: lambda *a, **k: 1})

    def test_missing_each_storage_or_analysis_purpose_never_creates_target(self):
        from tests.test_permissioned_source_delivery import policy_doc, gate
        purposes = ["analysis", "private_storage", "private_derived"]
        for missing in purposes:
            with self.subTest(missing=missing):
                self.policy = gate(policy_doc([p for p in purposes if p != missing]))
                self.request["policy_record_sha256"] = self.policy.document_sha256
                self.assert_denied_without_work()

    def test_actual_four_model_delivery_and_original_codec_wire_are_sealed_once(self):
        from race_ai import permissioned_source_delivery as source
        stages = []
        options = authorities(self.request, stages)
        with patch.object(source, "deliver", wraps=source.deliver) as observed:
            result = self.module.prepare_case(self.path, self.request, self.raw, self.policy,
                                              clock=self.clock, **options)
        self.assertEqual(observed.call_count, 1)
        self.assertIs(observed.call_args.kwargs["persist"], True)
        self.assertEqual(result["status"], "PREPARED_NOT_EXTERNAL_FROZEN")
        self.assertEqual(len(result["plans"]), 4)
        self.assertTrue(all(plan["status"] == "PREPARED_NOT_WRITTEN" for plan in result["plans"]))
        self.assertFalse(result["external_freeze_verified"])
        self.assertIn("POST_OPEN", stages)
        self.assertIn("PRE_COMMIT", stages)
        loaded = self.loaded(result)
        from race_ai import private_delivery_codec as codec
        self.assertEqual(sha(loaded["wire"]), result["wire_sha256"])
        self.assertEqual(codec.serialize_private_delivery(loaded["delivery"]), loaded["wire"])
        self.assertEqual(loaded["plans"], result["plans"])
        self.assertEqual(list(loaded["delivery"]["research_suite"]["models"]), list(MODELS))
        self.assertEqual(loaded["delivery"]["feature_snapshot_sha256"], self.request["feature_snapshot_sha256"])
        self.assertEqual(len(database_rows(self.path)), 1)

    def test_committed_replay_after_cutoff_never_renews_source_authority_or_models(self):
        result = self.prepare()
        before = self.path.read_bytes()
        self.clock.at = LATE
        def forbidden(*a, **k):
            raise AssertionError("historical source/model authority queried")
        from race_ai import permissioned_source_delivery as source
        with patch.object(source, "deliver", side_effect=forbidden), patch.object(source.PermissionPolicy, "authorize", side_effect=forbidden):
            replay = self.prepare(verify_input=forbidden, verify_cutoff=forbidden, admit_model_roster=forbidden)
            loaded = self.loaded(result)
        self.assertEqual(replay, result)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(loaded["delivery"]["delivery_sha256"], result["delivery_sha256"])

    def test_same_path_changed_request_or_raw_bytes_does_not_bypass_original_first(self):
        result = self.prepare()
        before = self.path.read_bytes()
        self.request["case_id"] = "new-nonce-must-not-recompute"
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.path.read_bytes(), before)
        self.request, self.raw, self.policy = fixture()
        self.raw += b"\n"
        self.request["source_payload_sha256"] = sha(self.raw)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.path.read_bytes(), before)

    def test_closed_real_case_returns_hash_only_diagnostic_without_backdating(self):
        self.clock.at = LATE
        result = self.assert_denied_without_work()
        self.assertIn("MISSED_DEADLINE", result["reasons"])

    def test_missing_full_field_publication_sample_or_supplemental_does_not_drop_input(self):
        from race_ai.comprehensive_four_sport_models import digest
        for failure in ("missing", "publication", "sample", "supplemental"):
            with self.subTest(failure=failure):
                self.request, self.raw, self.policy = fixture()
                record = json.loads(self.raw)
                features = record["snapshot"]["participants"][0]["features"]
                if failure == "missing":
                    del features["ability"]
                elif failure == "publication":
                    features["ability"]["published_at"] = None
                elif failure == "sample":
                    features["ability"]["sample_n"] = True
                else:
                    record["supplemental"] = [{"unrecognized": "must not be discarded"}]
                self.raw = canonical(record).encode()
                self.request["source_payload_sha256"] = sha(self.raw)
                self.request["feature_snapshot_sha256"] = digest(record["snapshot"])
                self.assert_denied_without_work()

    def test_nullable_unavailable_intake_evidence_returns_no_forecast(self):
        for key in ("policy_record_sha256", "feature_snapshot_sha256", "as_of", "sales_cutoff_at",
                    "executor_source_sha40", "input_evidence_ref", "cutoff_evidence_ref", "model_declaration_evidence_ref"):
            with self.subTest(key=key):
                self.request, self.raw, self.policy = fixture()
                self.request[key] = None
                self.assert_denied_without_work()

    def test_input_snapshot_policy_hashes_and_exact_model_declarations_must_match(self):
        for key in ("source_payload_sha256", "feature_snapshot_sha256", "policy_record_sha256", "model_source_sha40"):
            with self.subTest(key=key):
                self.request, self.raw, self.policy = fixture()
                self.request[key] = "f" * (40 if key == "model_source_sha40" else 64)
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.path.exists())

    def test_bool_int_alias_and_huge_string_are_rejected_before_canonical_copy(self):
        self.request["ledger"]["records"][0]["race_no"] = True
        with self.assertRaises(ValueError):
            self.prepare()
        self.request, self.raw, self.policy = fixture()
        self.request["input_evidence_ref"] = "x" * (8 * 1024 * 1024)
        tracemalloc.start()
        try:
            with self.assertRaises(ValueError):
                self.prepare()
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024)
        self.assertFalse(self.path.exists())

    def test_private_path_gate_is_required_on_load_and_after_target_creation(self):
        result = self.prepare()
        with self.assertRaises(ValueError):
            self.module.load_case(self.path, expected_request_sha256=result["request_sha256"])
        with self.assertRaises(ValueError):
            self.module.load_case(self.path, expected_request_sha256=True,
                                  private_path_verifier=authorities(self.request)["private_path_verifier"])
        other = Path(self.temp.name) / "not-approved-after-open.sqlite"
        def gate(path, *, stage):
            return stage == "PRE_OPEN"
        from race_ai import permissioned_source_delivery as source
        with patch.object(source, "deliver", side_effect=AssertionError("unprivate model")):
            options = authorities(self.request)
            options["private_path_verifier"] = gate
            outcome = self.module.prepare_case(other, self.request, self.raw, self.policy, clock=self.clock, **options)
        self.assertEqual(outcome["status"], "NO_FORECAST")
        self.assertEqual(database_rows(other), [])

    def test_git_directory_git_file_and_reparse_path_rejected_without_work(self):
        for git_file in (False, True):
            folder = Path(self.temp.name) / ("git-file" if git_file else "git-directory")
            folder.mkdir()
            ((folder / ".git").write_text("gitdir: external\n") if git_file else (folder / ".git").mkdir())
            with self.assertRaises(ValueError):
                self.module.prepare_case(folder / "private.sqlite", self.request, self.raw, self.policy,
                                          clock=self.clock, **authorities(self.request))
        target = Path(self.temp.name) / "real-directory"
        target.mkdir()
        link = Path(self.temp.name) / "linked-directory"
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            self.assertEqual(made.returncode, 0, made.stderr.decode(errors="replace"))
        else:
            link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.module.prepare_case(link / "private.sqlite", self.request, self.raw, self.policy,
                                      clock=self.clock, **authorities(self.request))
        self.assertFalse((target / "private.sqlite").exists())

    def test_foreign_database_not_adopted_or_changed_and_no_model_call(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE unrelated(value TEXT)")
            db.commit()
        before = self.path.read_bytes()
        from race_ai import permissioned_source_delivery as source
        with patch.object(source, "deliver", side_effect=AssertionError("foreign model")):
            with self.assertRaises(ValueError):
                self.prepare()
        self.assertEqual(self.path.read_bytes(), before)

    def test_oversized_sqlite_wire_blob_or_text_is_rejected_before_allocation(self):
        for expression in ("zeroblob(16777216)", "CAST(zeroblob(16777216) AS TEXT)"):
            with self.subTest(expression=expression):
                self.path = Path(self.temp.name) / ("wire-" + sha(expression.encode()) + ".sqlite")
                result = self.prepare()
                with closing(sqlite3.connect(self.path)) as db:
                    trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='permissioned_case_no_update'").fetchone()[0]
                    db.execute("DROP TRIGGER permissioned_case_no_update")
                    db.execute("UPDATE permissioned_case SET wire=" + expression)
                    db.execute(trigger)
                    db.commit()
                tracemalloc.start()
                try:
                    with patch.object(self.module, "_hash", side_effect=AssertionError("digest before resource admission")):
                        with self.assertRaises(self.module.PermissionedCaseError):
                            self.loaded(result)
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertLess(peak, 1024 * 1024, f"oversized wire allocated {peak} Python bytes")

    def test_sqlite_metadata_type_and_utf8_byte_budget_precede_json_parse(self):
        for value in ("x" * (16 * 1024 * 1024), b"x" * (16 * 1024 * 1024), "漢" * (1024 * 1024)):
            with self.subTest(kind=type(value).__name__, characters=len(value)):
                self.path = Path(self.temp.name) / ("metadata-" + type(value).__name__ + str(len(value)) + ".sqlite")
                result = self.prepare()
                with closing(sqlite3.connect(self.path)) as db:
                    trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='permissioned_case_no_update'").fetchone()[0]
                    db.execute("DROP TRIGGER permissioned_case_no_update")
                    db.execute("UPDATE permissioned_case SET metadata=?", (value,))
                    db.execute(trigger)
                    db.commit()
                tracemalloc.start()
                try:
                    with patch.object(self.module.json, "loads", side_effect=AssertionError("parse before resource admission")):
                        with self.assertRaises(self.module.PermissionedCaseError):
                            self.loaded(result)
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertLess(peak, 1024 * 1024, f"oversized metadata allocated {peak} Python bytes")

    def test_sqlite_hash_columns_are_admitted_before_materializing_contents(self):
        for field in ("request_sha256", "content_sha256"):
            with self.subTest(field=field):
                self.path = Path(self.temp.name) / (field + ".sqlite")
                result = self.prepare()
                with closing(sqlite3.connect(self.path)) as db:
                    trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='permissioned_case_no_update'").fetchone()[0]
                    db.execute("DROP TRIGGER permissioned_case_no_update")
                    db.execute("UPDATE permissioned_case SET " + field + "=CAST(zeroblob(16777216) AS TEXT)")
                    db.execute(trigger)
                    db.commit()
                tracemalloc.start()
                try:
                    with self.assertRaises(self.module.PermissionedCaseError):
                        self.loaded(result)
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertLess(peak, 1024 * 1024, f"oversized hash allocated {peak} Python bytes")

    def test_expected_source_parse_denial_traceback_omits_private_key(self):
        self.raw = b'{"FICTIONAL_PRIVATE_SOURCE_KEY":1,"FICTIONAL_PRIVATE_SOURCE_KEY":2}'
        self.request["source_payload_sha256"] = sha(self.raw)
        try:
            self.prepare()
        except ValueError as error:
            formatted = "".join(traceback.format_exception(error))
            self.assertIsInstance(error, self.module.PermissionedCaseError)
            self.assertNotIn("FICTIONAL_PRIVATE_SOURCE_KEY", formatted)
            self.assertIn("permissioned case rejected", formatted)
        else:
            self.fail("malformed source was accepted")
        self.assertFalse(self.path.exists())

    def test_expected_request_date_and_timestamp_denials_omit_private_values(self):
        for key, secret in (("event_date_jst", "FICTIONAL_PRIVATE_DATE_VALUE"),
                            ("as_of", "FICTIONAL_PRIVATE_TIMESTAMP_VALUE")):
            with self.subTest(key=key):
                self.request, self.raw, self.policy = fixture()
                if key == "event_date_jst":
                    self.request["ledger"][key] = secret
                else:
                    self.request[key] = secret
                try:
                    self.prepare()
                except ValueError as error:
                    formatted = "".join(traceback.format_exception(error))
                    self.assertIsInstance(error, self.module.PermissionedCaseError)
                    self.assertNotIn(secret, formatted)
                else:
                    self.fail("malformed request was accepted")
                self.assertFalse(self.path.exists())

    def test_expected_checkpoint_json_and_timestamp_denials_are_generic(self):
        for failure in ("json", "timestamp"):
            with self.subTest(failure=failure):
                self.path = Path(self.temp.name) / ("private-error-" + failure + ".sqlite")
                result = self.prepare()
                if failure == "json":
                    with closing(sqlite3.connect(self.path)) as db:
                        trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='permissioned_case_no_update'").fetchone()[0]
                        db.execute("DROP TRIGGER permissioned_case_no_update")
                        db.execute("UPDATE permissioned_case SET metadata=?", ('{"private":"FICTIONAL_PRIVATE_CHECKPOINT_VALUE",}',))
                        db.execute(trigger)
                        db.commit()
                else:
                    def change(metadata, wire):
                        metadata["generated_at"] = "FICTIONAL_PRIVATE_CHECKPOINT_VALUE"
                        return metadata, wire
                    corrupt(self.path, change)
                try:
                    self.loaded(result)
                except ValueError as error:
                    self.assertIsInstance(error, self.module.PermissionedCaseError)
                    self.assertNotIn("FICTIONAL_PRIVATE_CHECKPOINT_VALUE", "".join(traceback.format_exception(error)))
                else:
                    self.fail("malformed checkpoint was accepted")

    def test_invalid_utf8_sqlite_text_denial_omits_private_value(self):
        result = self.prepare()
        private = b'{"private":"FICTIONAL_PRIVATE_SQLITE_TEXT_\xff"}'
        with closing(sqlite3.connect(self.path)) as db:
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='permissioned_case_no_update'").fetchone()[0]
            db.execute("DROP TRIGGER permissioned_case_no_update")
            db.execute("UPDATE permissioned_case SET metadata=CAST(? AS TEXT)", (private,))
            db.execute(trigger)
            db.commit()
        try:
            self.loaded(result)
        except Exception as error:
            self.assertIsInstance(error, self.module.PermissionedCaseError)
            self.assertNotIn("FICTIONAL_PRIVATE_SQLITE_TEXT_", str(error))
            self.assertNotIn("FICTIONAL_PRIVATE_SQLITE_TEXT_", "".join(traceback.format_exception(error)))
        else:
            self.fail("invalid UTF-8 SQLite TEXT was accepted")

    def test_unc_and_device_unc_are_rejected_before_any_path_probe(self):
        for path in (r"\\fictional-do-not-connect.invalid\share\private.sqlite",
                     r"\\?\UNC\fictional-do-not-connect.invalid\share\private.sqlite"):
            with self.subTest(path=path):
                with patch.object(Path, "is_dir", side_effect=AssertionError("filesystem/network probe")), \
                     patch.object(Path, "exists", side_effect=AssertionError("filesystem/network probe")), \
                     patch.object(Path, "lstat", side_effect=AssertionError("filesystem/network probe")), \
                     patch.object(Path, "resolve", side_effect=AssertionError("filesystem/network probe")):
                    with self.assertRaises(self.module.PermissionedCaseError):
                        self.module.prepare_case(path, self.request, self.raw, self.policy,
                                                 clock=self.clock, **authorities(self.request))

    def test_unc_userprofile_expansion_is_rejected_before_any_path_probe(self):
        remote_home = ({"USERPROFILE": r"\\fictional-do-not-connect.invalid\share"} if os.name == "nt"
                       else {"HOME": "//fictional-do-not-connect.invalid/share"})
        with patch.dict(os.environ, remote_home), \
             patch.object(Path, "is_dir", side_effect=AssertionError("filesystem/network probe")), \
             patch.object(Path, "exists", side_effect=AssertionError("filesystem/network probe")), \
             patch.object(Path, "lstat", side_effect=AssertionError("filesystem/network probe")), \
             patch.object(Path, "resolve", side_effect=AssertionError("filesystem/network probe")):
            with self.assertRaises(self.module.PermissionedCaseError):
                self.module.prepare_case("~/private.sqlite", self.request, self.raw, self.policy,
                                         clock=self.clock, **authorities(self.request))

    def test_git_hardlinked_target_and_sidecars_reject_before_model_or_writes(self):
        from race_ai import permissioned_source_delivery as source
        repo = Path(self.temp.name) / "fictional-git-root"
        (repo / ".git").mkdir(parents=True)
        for suffix in ("", "-journal", "-wal", "-shm"):
            with self.subTest(suffix=suffix):
                self.path = Path(self.temp.name) / ("hardlink" + suffix + ".sqlite")
                inside = repo / ("private-alias" + suffix)
                inside.touch()
                outside = Path(str(self.path) + suffix)
                os.link(inside, outside)
                before = inside.read_bytes()
                with patch.object(source, "deliver", side_effect=AssertionError("hardlinked model")):
                    with self.assertRaises(self.module.PermissionedCaseError):
                        self.prepare()
                self.assertEqual(inside.read_bytes(), before)
                self.assertEqual(outside.read_bytes(), before)
                if suffix:
                    self.assertFalse(self.path.exists())

    def test_new_hardlink_at_post_open_is_rechecked_before_schema_or_private_insert(self):
        from race_ai import permissioned_source_delivery as source
        repo = Path(self.temp.name) / "fictional-git-root"
        (repo / ".git").mkdir(parents=True)
        alias = repo / "private-alias"
        def introduced(path, *, stage):
            if stage == "POST_OPEN":
                os.link(path, alias)
            return True
        with patch.object(source, "deliver", side_effect=AssertionError("hardlinked model")):
            with self.assertRaises(self.module.PermissionedCaseError):
                self.prepare(private_path_verifier=introduced)
        self.assertEqual(alias.read_bytes(), b"")
        self.assertEqual(self.path.read_bytes(), b"")

    def test_reparse_ancestor_is_rejected_by_lstat_before_any_following_probe(self):
        ancestor = Path(self.temp.name) / "unchecked-fictional-junction"
        target = ancestor / "private.sqlite"
        real_lstat = Path.lstat
        visited = []
        def nofollow(path, *args, **kwargs):
            visited.append(path)
            if path == ancestor:
                return SimpleNamespace(st_file_attributes=1024, st_mode=0o040700, st_nlink=1)
            if ancestor in path.parents:
                raise AssertionError("descendant probe through unchecked reparse ancestor")
            return real_lstat(path, *args, **kwargs)
        with patch.object(Path, "lstat", autospec=True, side_effect=nofollow), \
             patch.object(Path, "is_dir", side_effect=AssertionError("REPARSE_ANCESTOR_FOLLOW_BEFORE_REJECTION")), \
             patch.object(Path, "exists", side_effect=AssertionError("REPARSE_ANCESTOR_FOLLOW_BEFORE_REJECTION")), \
             patch.object(Path, "is_symlink", side_effect=AssertionError("following predicate before lstat")), \
             patch.object(Path, "resolve", side_effect=AssertionError("resolve before reparse rejection")):
            with self.assertRaises(self.module.PermissionedCaseError):
                self.module.prepare_case(target, self.request, self.raw, self.policy,
                                         clock=self.clock, **authorities(self.request))
        self.assertIn(ancestor, visited)
        self.assertNotIn(target, visited)

    def test_git_markers_and_sidecars_use_lstat_without_following_predicates(self):
        for kind in ("git", "sidecar"):
            with self.subTest(kind=kind):
                folder = Path(self.temp.name) / ("nofollow-" + kind)
                folder.mkdir()
                target = folder / "private.sqlite"
                marker = folder / ".git" if kind == "git" else Path(str(target) + "-journal")
                marker.touch()
                with patch.object(Path, "exists", side_effect=AssertionError("following exists before lstat")), \
                     patch.object(Path, "is_dir", side_effect=AssertionError("following is_dir before lstat")), \
                     patch.object(Path, "is_file", side_effect=AssertionError("following is_file before lstat")), \
                     patch.object(Path, "is_symlink", side_effect=AssertionError("predicate before lstat")):
                    if kind == "git":
                        with self.assertRaises(self.module.PermissionedCaseError):
                            self.module._path(target)
                    else:
                        self.assertEqual(self.module._path(target), target)

    def test_valid_three_entrant_inputs_are_denied_before_pinned_exact_eight_suite(self):
        from race_ai import permissioned_source_delivery as source
        from race_ai.comprehensive_four_sport_models import digest, validate
        from tests.test_permissioned_source_delivery import snapshot
        for sport, row_index in (("autorace", 4), ("horse", 6)):
            with self.subTest(sport=sport):
                self.request, self.raw, self.policy = fixture()
                full = snapshot(sport)
                full["participants"] = full["participants"][:3]
                validate(full, allow_source=self.policy.authorize)
                self.raw = canonical({"schema": source.FEED_SCHEMA, "snapshot": full}).encode()
                self.request.update(race_id=self.request["ledger"]["records"][row_index]["race_id"],
                    source_payload_sha256=sha(self.raw), feature_snapshot_sha256=digest(full),
                    as_of=full["race"]["as_of"], sales_cutoff_at=full["race"]["sales_cutoff_at"])
                result = self.assert_denied_without_work(verify_cutoff=lambda row: True)
                self.assertEqual(result["reasons"], ["PINNED_MODEL_CARDINALITY_UNSUPPORTED"])

    def test_rehashed_wire_plan_and_chronology_tamper_fail_semantic_load(self):
        from race_ai import private_delivery_codec as codec
        from race_ai.comprehensive_four_sport_models import digest
        for failure in ("wire", "plan", "chronology"):
            with self.subTest(failure=failure):
                self.path = Path(self.temp.name) / (failure + ".sqlite")
                result = self.prepare()
                def change(metadata, wire):
                    if failure == "wire":
                        delivery = codec.deserialize_private_delivery(wire)
                        delivery["source_payload_sha256"] = "f" * 64
                        delivery["delivery_sha256"] = digest({k: v for k, v in delivery.items() if k != "delivery_sha256"})
                        wire = codec.serialize_private_delivery(delivery)
                        metadata["delivery_sha256"] = delivery["delivery_sha256"]
                        metadata["wire_sha256"] = sha(wire)
                    elif failure == "plan":
                        metadata["plans"][0]["eligible_for_hit_at_8"] = 0
                    else:
                        metadata["persisted_at"] = LATE
                    return metadata, wire
                corrupt(self.path, change)
                with self.assertRaises(ValueError):
                    self.loaded(result)

    def test_deadline_or_clock_rollback_after_insert_rolls_back_entire_case(self):
        for at in (LATE, "2030-01-15T09:14:59+09:00"):
            with self.subTest(at=at):
                self.clock.at = AT
                self.path = Path(self.temp.name) / sha(at.encode())
                insert = self.module._insert_case
                def cross(*args, **kwargs):
                    insert(*args, **kwargs)
                    self.clock.at = at
                with patch.object(self.module, "_insert_case", side_effect=cross):
                    with self.assertRaises(ValueError):
                        self.prepare()
                self.assertEqual(database_rows(self.path), [])

    def test_unexpected_model_error_propagates_and_leaves_no_checkpoint(self):
        from race_ai import permissioned_source_delivery as source
        with patch.object(source, "deliver", side_effect=RuntimeError("authored unexpected failure")):
            with self.assertRaises(RuntimeError):
                self.prepare()
        self.assertEqual(database_rows(self.path), [])

    def test_policy_expiration_is_rechecked_at_execution_time(self):
        from tests.test_permissioned_source_delivery import policy_doc, gate
        self.policy = gate(policy_doc(expiry="2030-01-15T09:20:00+09:00"))
        self.request["policy_record_sha256"] = self.policy.document_sha256
        self.clock.at = "2030-01-15T09:25:00+09:00"
        self.assert_denied_without_work()

    def test_selected_source_race_mismatch_is_rejected_before_model_or_creation(self):
        from race_ai import permissioned_source_delivery as source
        self.request["race_id"] = self.request["ledger"]["records"][1]["race_id"]
        with patch.object(source, "deliver", wraps=source.deliver) as observed:
            with self.assertRaises(ValueError):
                self.prepare(verify_cutoff=lambda row: row == self.request["ledger"]["records"][1])
        self.assertEqual(observed.call_count, 0)
        self.assertFalse(self.path.exists())

    def test_policy_expiration_during_lock_wait_prevents_model_execution(self):
        from tests.test_permissioned_source_delivery import policy_doc, gate
        from race_ai import permissioned_source_delivery as source
        self.policy = gate(policy_doc(expiry="2030-01-15T09:20:00+09:00"))
        self.request["policy_record_sha256"] = self.policy.document_sha256
        connect = sqlite3.connect
        def delayed(database, *args, **kwargs):
            connection = connect(database, *args, **kwargs)
            if str(database) == str(self.path):
                self.clock.at = "2030-01-15T09:25:00+09:00"
            return connection
        with patch.object(self.module.sqlite3, "connect", side_effect=delayed), patch.object(source, "deliver", wraps=source.deliver) as observed:
            result = self.prepare()
        self.assertEqual(result["status"], "NO_FORECAST")
        self.assertEqual(observed.call_count, 0)
        self.assertEqual(database_rows(self.path), [])

    def test_policy_expiration_after_insert_cannot_commit_private_forecast(self):
        from tests.test_permissioned_source_delivery import policy_doc, gate
        self.policy = gate(policy_doc(expiry="2030-01-15T09:20:00+09:00"))
        self.request["policy_record_sha256"] = self.policy.document_sha256
        insert = self.module._insert_case
        def delayed(*args, **kwargs):
            insert(*args, **kwargs)
            self.clock.at = "2030-01-15T09:25:00+09:00"
        with patch.object(self.module, "_insert_case", side_effect=delayed):
            result = self.prepare()
        self.assertEqual(result["status"], "NO_FORECAST")
        self.assertEqual(database_rows(self.path), [])

    def test_real_process_crash_before_commit_and_closed_retry_never_backdates(self):
        completed = subprocess.run([sys.executable, "-B", "-X", "utf8", __file__,
                                    "--worker", "before", str(self.path)], capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 71, completed.stderr.decode())
        self.assertEqual(database_rows(self.path), [])
        self.clock.at = LATE
        result = self.prepare()
        self.assertEqual(result["status"], "NO_FORECAST")
        self.assertEqual(database_rows(self.path), [])

    def test_real_process_crash_after_commit_and_concurrent_creation_keep_one_wire(self):
        completed = subprocess.run([sys.executable, "-B", "-X", "utf8", __file__,
                                    "--worker", "after", str(self.path)], capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 72, completed.stderr.decode())
        before = self.path.read_bytes()
        self.clock.at = LATE
        self.prepare()
        self.assertEqual(self.path.read_bytes(), before)
        self.path = Path(self.temp.name) / "concurrent.sqlite"
        marker = str(Path(self.temp.name) / "actual-model-calls.txt")
        command = [sys.executable, "-B", "-X", "utf8", __file__, "--worker", "concurrent", str(self.path), marker]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for child in children:
            stdout, stderr = child.communicate(timeout=40)
            self.assertEqual(child.returncode, 0, stderr.decode())
        self.assertEqual(Path(marker).read_text().splitlines(), ["actual-model"])
        self.assertEqual(len(database_rows(self.path)), 1)


def worker(mode, path, marker=None):
    module = importlib.import_module("race_ai.permissioned_model_case")
    request, raw, policy = fixture()
    from race_ai import permissioned_source_delivery as source
    deliver = source.deliver
    def actual(*args, **kwargs):
        result = deliver(*args, **kwargs)
        if mode == "before":
            os._exit(71)
        if marker:
            with open(marker, "a", encoding="utf-8") as stream:
                stream.write("actual-model\n")
        return result
    with patch.object(source, "deliver", side_effect=actual), patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
        module.prepare_case(path, request, raw, policy, clock=Clock(), **authorities(request))
    if mode == "after":
        os._exit(72)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(*sys.argv[2:])
    else:
        unittest.main()
