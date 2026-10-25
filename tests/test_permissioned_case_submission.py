"""Fictional admissions/HTTP; one actual pinned private BOAT checkpoint."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import tracemalloc
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests.test_permissioned_model_case import fixture, authorities
from tests.test_offline_model_run import Clock, AT, LATE, MODELS, canonical, sha
from race_ai.permissioned_model_case import prepare_case

BRANCH = "audit/freeze-fictional-intent"
PIN = "e" * 40  # Fictional executor declaration, never execution authentication.
BASE = "https://api.github.com/repos/haji84/RACE-AI"


def gates():
    return {"private_path_verifier": lambda path, **kw: True,
        "admit_store": lambda path, manifest, **kw: True,
        "verify_source": lambda claim, snapshot: True,
        "verify_cutoff": lambda claim, row: True,
        "admit_model_roster": lambda claim, declarations: True,
        "independent_release_check": lambda claim: True,
        "admit_transport": lambda claim, transport: True}


class RecordingTransport:
    def __init__(self, fail=None):
        self.calls, self.files, self.fail = [], {}, fail

    def __call__(self, url, method, data):
        self.calls.append((url, method, data))
        if self.fail == method:
            raise RuntimeError("FICTIONAL_PRIVATE_TRANSPORT_TOKEN")
        if method == "PUT":
            body = json.loads(data)
            if set(body) != {"message", "content", "branch"} or body["branch"] != BRANCH:
                raise AssertionError("wrong create-only request")
            raw = base64.b64decode(body["content"], validate=True)
            commit = hashlib.sha1(url.encode()).hexdigest()
            self.files[url + "?ref=" + commit] = raw
            return {"commit": {"sha": commit}, "private_response": "MUST_NOT_PERSIST"}
        return {"type": "file", "encoding": "base64",
                "content": base64.b64encode(self.files[url]).decode()}


def schema_rows(path, table):
    with closing(sqlite3.connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            return []
        return db.execute("SELECT * FROM " + table).fetchall()


class PermissionedCaseSubmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = tempfile.TemporaryDirectory(prefix="race28-original-fictional-")
        cls.original = Path(cls.prepared.name) / "case.sqlite"
        request, raw, policy = fixture()
        cls.seal = prepare_case(cls.original, request, raw, policy, clock=Clock(), **authorities(request))

    @classmethod
    def tearDownClass(cls):
        cls.prepared.cleanup()

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.permissioned_case_submission"),
                             "durable submission boundary is missing")
        self.module = importlib.import_module("race_ai.permissioned_case_submission")
        self.temp = tempfile.TemporaryDirectory(prefix="race28-fictional-attempt-")
        self.addCleanup(self.temp.cleanup)
        self.case_path = Path(self.temp.name) / "case.sqlite"
        shutil.copyfile(self.original, self.case_path)
        self.path = Path(self.temp.name) / "attempt.sqlite"
        self.clock, self.transport = Clock(), RecordingTransport()
        self.network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def identity(self):
        return {"expected_request_sha256": self.seal["request_sha256"], "expected_branch": BRANCH,
                "submission_source_sha40": PIN, "clock": self.clock}

    def dispatch(self, **overrides):
        options = {**self.identity(), **gates(), "transport": self.transport}
        options.update(overrides)
        return self.module.dispatch_prepared_case(self.path, self.case_path, **options)

    def recover(self, **overrides):
        options = {**self.identity(), "private_path_verifier": gates()["private_path_verifier"],
                   "admit_store": gates()["admit_store"]}
        options.update(overrides)
        return self.module.recover_submission_attempts(self.path, self.case_path, **options)

    def test_default_and_each_missing_or_nontrue_admission_never_creates_or_sends(self):
        default = self.module.dispatch_prepared_case(self.path, self.case_path, **self.identity())
        self.assertEqual(default["status"], "DENIED")
        for name in (*gates(), "transport"):
            for denied in (None, lambda *a, **kw: 1):
                if name == "transport" and denied is not None:
                    continue
                with self.subTest(name=name, denied=denied):
                    outcome = self.dispatch(**{name: denied})
                    self.assertEqual(outcome["status"], "DENIED")
                    self.assertFalse(self.path.exists())
                    self.assertEqual(self.transport.calls, [])

    def test_actual_legacy_writer_sends_four_original_plans_and_replays_without_writes(self):
        before = self.case_path.read_bytes()
        result = self.dispatch()
        self.assertEqual(result["status"], "NORMAL_READBACKS_COMPLETE_RECEIPTS_PENDING")
        self.assertEqual([x["model_id"] for x in result["models"]], list(MODELS))
        self.assertTrue(all(x["normal_acknowledged"] for x in result["models"]))
        self.assertFalse(result["dispatch_barrier"])
        self.assertEqual([x[1] for x in self.transport.calls], ["PUT", "GET"] * 4)
        self.assertEqual(len(schema_rows(self.path, "submission_intents")), 4)
        self.assertEqual(len(schema_rows(self.path, "submission_evidence")), 8)
        self.assertEqual(self.case_path.read_bytes(), before)
        persisted = self.path.read_bytes()
        self.clock.at = LATE
        replay = self.dispatch(**{name: None for name in gates() if name not in ("private_path_verifier", "admit_store")}, transport=None)
        self.assertEqual(replay, {**result, "github_reads": 0})
        self.assertEqual(self.path.read_bytes(), persisted)
        self.assertNotIn(b"MUST_NOT_PERSIST", persisted)
        self.assertFalse(result["full_private_payload_retention_verified"])
        self.assertFalse(result["global_exactly_once_verified"])
        self.assertFalse(result["cloned_store_protection_verified"])

    def test_summary_counts_this_invocations_guarded_get_attempts(self):
        result = self.dispatch()
        self.assertEqual(result["github_reads"], 4)
        self.assertEqual(self.dispatch()["github_reads"], 0)
        self.path = Path(self.temp.name) / "failed-read.sqlite"
        self.transport = RecordingTransport(fail="GET")
        failed = self.dispatch()
        self.assertEqual(failed["github_reads"], 1)
        self.assertTrue(failed["dispatch_barrier"])

    def test_put_failure_is_irreversibly_case_wide_and_unknown_recovery_reads_zero(self):
        self.transport.fail = "PUT"
        result = self.dispatch()
        self.assertTrue(result["dispatch_barrier"])
        self.assertEqual([x["status"] for x in result["models"]],
                         ["INTENT_CONSUMED_RECOVERY_ONLY"] + ["NOT_ATTEMPTED"] * 3)
        self.assertEqual(len(self.transport.calls), 1)
        before = self.path.read_bytes()
        self.transport.fail = None
        self.dispatch()
        recovery = self.recover(github_fetch=lambda url: self.fail("unknown commit read"))
        self.assertEqual(recovery["github_reads"], 0)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_get_failure_retains_commit_before_read_and_never_appends_normal_ack(self):
        self.transport.fail = "GET"
        result = self.dispatch()
        first = result["models"][0]
        self.assertEqual(first["status"], "COMMIT_KNOWN_READBACK_UNVERIFIED")
        self.assertIsInstance(first["commit_sha"], str)
        self.assertFalse(first["normal_acknowledged"])
        self.assertEqual(len(schema_rows(self.path, "submission_evidence")), 1)
        self.dispatch()
        self.assertEqual(len(self.transport.calls), 2)

    def test_known_commit_recovery_uses_existing_resolver_and_never_clears_barrier(self):
        self.transport.fail = "GET"
        result = self.dispatch()
        commit = result["models"][0]["commit_sha"]
        prepared = self.seal["plans"][0]
        run = {"id": 42, "head_sha": commit, "event": "push", "head_branch": BRANCH,
               "repository": {"full_name": "haji84/RACE-AI"}, "created_at": "2030-01-15T09:16:00+09:00"}
        responses = {BASE + "/actions/runs?head_sha=" + commit + "&event=push&per_page=100":
                     {"total_count": 1, "workflow_runs": [run]}, BASE + "/actions/runs/42": run,
                     BASE + "/contents/" + prepared["path"] + "?ref=" + commit:
                     {"type": "file", "encoding": "base64", "content":
                      base64.b64encode((canonical(prepared["anchor"]) + "\n").encode()).decode()}}
        reads = []
        def fetch(url):
            reads.append(url)
            return deepcopy(responses[url])
        from race_ai.github_freeze_receipt import verify_github_freeze
        self.clock.at = LATE
        recovery = self.recover(admit_reader=lambda *a: True, github_fetch=fetch,
                                trusted_legacy_verifier=verify_github_freeze)
        self.assertEqual(len(reads), 3)
        self.assertTrue(recovery["dispatch_barrier"])
        self.assertTrue(recovery["models"][0]["witness"]["external_pre_cutoff_presence_verified"])
        self.assertFalse(recovery["models"][0]["normal_acknowledged"])
        self.assertEqual([x["status"] for x in recovery["models"]][1:], ["NOT_ATTEMPTED"] * 3)
        before = self.path.read_bytes()
        cached = self.recover()
        self.assertEqual(cached["models"], recovery["models"])
        self.assertEqual(self.path.read_bytes(), before)
        self.dispatch()
        self.assertEqual(len(self.transport.calls), 2)

    def test_recovery_reopen_never_creates_and_rechecks_private_store_before_get(self):
        self.transport.fail = "GET"
        self.dispatch()
        pristine = self.path.read_bytes()
        from race_ai.github_freeze_receipt import verify_github_freeze
        for failure in ("disappeared", "post_open", "sqlite_private_error"):
            with self.subTest(failure=failure):
                self.path.write_bytes(pristine)
                reads, post_opens = [], 0
                def reader_admission(*args):
                    if failure == "disappeared":
                        self.path.unlink()
                    return True
                def private(path, *, stage):
                    nonlocal post_opens
                    if path == self.path and stage == "POST_OPEN":
                        post_opens += 1
                        if failure == "post_open" and post_opens == 2:
                            return False
                    return True
                original = sqlite3.connect
                def reconnect(database, *args, **kwargs):
                    if failure == "sqlite_private_error" and (str(database) == str(self.path)
                            or str(database) == self.path.as_uri() + "?mode=rw"):
                        raise sqlite3.OperationalError("FICTIONAL_PRIVATE_SECOND_OPEN_TOKEN")
                    return original(database, *args, **kwargs)
                with patch.object(self.module.sqlite3, "connect", side_effect=reconnect):
                    try:
                        self.recover(admit_reader=reader_admission, private_path_verifier=private,
                                     github_fetch=lambda url: reads.append(url) or {},
                                     trusted_legacy_verifier=verify_github_freeze)
                    except Exception as error:
                        self.assertIsInstance(error, ValueError)
                        self.assertNotIn("FICTIONAL_PRIVATE_SECOND_OPEN_TOKEN", "".join(traceback.format_exception(error)))
                    else:
                        self.fail("recovery reopened an absent or unadmitted store")
                self.assertEqual(reads, [])
                if failure == "disappeared":
                    self.assertFalse(self.path.exists())

    def test_callback_mutation_cannot_retarget_original_fingerprint(self):
        def mutate(claim):
            claim["plan"]["anchor"]["prediction_sha256"] = "f" * 64
            return True
        result = self.dispatch(independent_release_check=mutate)
        self.assertEqual(result["status"], "DENIED")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.transport.calls, [])

    def test_callback_oversized_mutation_rejects_before_canonical_allocation(self):
        huge = "x" * (8 * 1024 * 1024)  # Preallocated before tracing the callback.
        tracemalloc.start()
        try:
            self.dispatch(verify_source=lambda claim, snapshot: False)
            baseline = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        def mutate(claim):
            claim["untrusted_mutation"] = huge
            return True
        tracemalloc.start()
        try:
            result = self.dispatch(independent_release_check=mutate)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(result["status"], "DENIED")
        self.assertLess(peak, baseline + 1024 * 1024)
        self.assertLess(peak, 8 * 1024 * 1024)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.transport.calls, [])

    def test_racing_barrier_after_normal_ack_retains_this_invocations_get_count(self):
        original = self.module._evidence
        marker = Path(self.temp.name) / "competing.puts"
        def interleaved(db, path, manifest, position, kind, *args, **kwargs):
            result = original(db, path, manifest, position, kind, *args, **kwargs)
            if position == 1 and kind == "NORMAL_ACK":
                command = [sys.executable, "-B", "-X", "utf8", __file__, "--worker", "before_put",
                           str(self.path), str(self.case_path), self.seal["request_sha256"], str(marker)]
                competing = subprocess.run(command, capture_output=True, timeout=30)
                self.assertEqual(competing.returncode, 71, competing.stderr.decode())
            return result
        with patch.object(self.module, "_evidence", side_effect=interleaved):
            result = self.dispatch()
        self.assertEqual([x[1] for x in self.transport.calls], ["PUT", "GET"])
        self.assertTrue(result["dispatch_barrier"])
        self.assertEqual(result["github_reads"], 1)
        self.assertTrue(result["models"][0]["normal_acknowledged"])
        self.assertEqual(result["models"][1]["status"], "INTENT_CONSUMED_RECOVERY_ONLY")

    def test_cutoff_after_slow_callbacks_or_at_put_edge_sends_nothing(self):
        for phase in ("PRE_INTENT", "PRE_PUT"):
            with self.subTest(phase=phase):
                self.path = Path(self.temp.name) / (phase + ".sqlite")
                self.clock.at = AT
                def slow(claim):
                    if claim["phase"] == phase:
                        self.clock.at = LATE
                    return True
                result = self.dispatch(independent_release_check=slow)
                self.assertEqual(self.transport.calls, [])
                self.assertEqual(len(schema_rows(self.path, "submission_intents")) if self.path.exists() else 0,
                                 int(phase == "PRE_PUT"))
                self.assertFalse(result["eligible_for_hit_at_8"])

    def test_honest_authority_expiring_before_cutoff_denies_while_currently_valid(self):
        expiry = datetime.fromisoformat("2030-01-15T09:20:00+09:00")
        self.assertLess(self.clock(), expiry)
        def full_window(claim, snapshot):
            return datetime.fromisoformat(claim["manifest"]["sales_cutoff_at"]) <= expiry
        result = self.dispatch(verify_source=full_window)
        self.assertEqual(result["status"], "DENIED")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.transport.calls, [])

    def test_last_store_gate_crossing_cutoff_after_consumption_permits_zero_put(self):
        calls = 0
        def slow(path, manifest, *, stage):
            nonlocal calls
            if stage == "PRE_COMMIT":
                calls += 1
                if calls == 2:
                    self.clock.at = LATE
            return True
        result = self.dispatch(admit_store=slow)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(len(schema_rows(self.path, "submission_intents")), 1)
        self.assertTrue(result["dispatch_barrier"])

    def test_clock_rollback_between_pre_put_and_return_does_not_read_or_ack(self):
        recording = self.transport
        def advance(claim):
            if claim["phase"] == "PRE_PUT":
                self.clock.at = "2030-01-15T09:20:00+09:00"
            return True
        def rollback(url, method, data):
            response = recording(url, method, data)
            if method == "PUT":
                self.clock.at = "2030-01-15T09:17:00+09:00"
            return response
        result = self.dispatch(transport=rollback, independent_release_check=advance)
        self.assertTrue(result["dispatch_barrier"])
        self.assertEqual([x[1] for x in recording.calls], ["PUT"])
        self.assertFalse(result["models"][0]["normal_acknowledged"])

    def test_committed_high_water_rejects_rolled_back_restart_clock(self):
        self.clock.at = "2030-01-15T09:20:00+09:00"
        self.dispatch()
        self.clock.at = AT
        with self.assertRaises(ValueError):
            self.dispatch()
        with self.assertRaises(ValueError):
            self.recover()

    def known_commit_recovery(self):
        self.transport.fail = "GET"
        commit = self.dispatch()["models"][0]["commit_sha"]
        prepared = self.seal["plans"][0]
        run = {"id": 42, "head_sha": commit, "event": "push", "head_branch": BRANCH,
               "repository": {"full_name": "haji84/RACE-AI"}, "created_at": "2030-01-15T09:16:00+09:00"}
        responses = {BASE + "/actions/runs?head_sha=" + commit + "&event=push&per_page=100":
                     {"total_count": 1, "workflow_runs": [run]}, BASE + "/actions/runs/42": run,
                     BASE + "/contents/" + prepared["path"] + "?ref=" + commit:
                     {"type": "file", "encoding": "base64", "content":
                      base64.b64encode((canonical(prepared["anchor"]) + "\n").encode()).decode()}}
        reads = []
        def fetch(url):
            reads.append(url)
            return deepcopy(responses[url])
        from race_ai.github_freeze_receipt import verify_github_freeze
        return {"admit_reader": lambda *a: True, "github_fetch": fetch,
                "trusted_legacy_verifier": verify_github_freeze}, reads

    def test_historical_recovery_rejects_dst_fold_utc_rollback_before_any_get(self):
        options, reads = self.known_commit_recovery()
        before = self.path.read_bytes()
        zone = ZoneInfo("America/New_York")
        first = datetime(2030, 11, 3, 1, 30, tzinfo=zone, fold=1)  # 06:30 UTC
        second = datetime(2030, 11, 3, 1, 45, tzinfo=zone, fold=0)  # 05:45 UTC
        values = iter((first, second))
        with self.assertRaises(self.module.SubmissionError):
            self.recover(clock=lambda: next(values, second), **options)
        self.assertEqual(reads, [])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(schema_rows(self.path, "submission_intents")), 1)
        self.assertEqual([row[1] for row in schema_rows(self.path, "submission_evidence")], ["PUT_COMMIT"])

    def test_historical_recovery_accepts_dst_fallback_utc_advance_and_equal_instants(self):
        options, reads = self.known_commit_recovery()
        zone = ZoneInfo("America/New_York")
        first = datetime(2030, 11, 3, 1, 45, tzinfo=zone, fold=0)  # 05:45 UTC
        second = datetime(2030, 11, 3, 1, 30, tzinfo=zone, fold=1)  # 06:30 UTC
        same_instant_utc = second.astimezone(timezone.utc)
        values = iter((first, second, same_instant_utc))
        try:
            result = self.recover(clock=lambda: next(values, same_instant_utc), **options)
        except ValueError as error:
            self.fail("UTC-forward historical recovery was rejected: " + str(error))
        self.assertEqual(len(reads), 3)
        self.assertTrue(result["dispatch_barrier"])
        self.assertFalse(result["models"][0]["normal_acknowledged"])
        self.assertEqual(result["models"][0]["witness"]["observed_at"], same_instant_utc.isoformat())
        self.assertEqual([row["status"] for row in result["models"]][1:], ["NOT_ATTEMPTED"] * 3)
        self.assertEqual(len(self.transport.calls), 2)  # Only the original PUT and failed GET.
        self.assertFalse(result["eligible_for_hit_at_8"])

    def test_historical_recovery_invalid_naive_or_failing_clock_stays_private_and_read_only(self):
        options, reads = self.known_commit_recovery()
        before = self.path.read_bytes()
        def failing():
            raise RuntimeError("FICTIONAL_PRIVATE_CLOCK_DETAIL")
        for clock in (lambda: None, lambda: True, lambda: "not-a-datetime",
                      lambda: datetime(2030, 11, 3, 6, 30), failing):
            with self.subTest(clock=clock):
                try:
                    self.recover(clock=clock, **options)
                except self.module.SubmissionError as error:
                    self.assertEqual(str(error), "INVALID_OR_CLOSED_SUBMISSION_CLOCK")
                    self.assertNotIn("FICTIONAL_PRIVATE_CLOCK_DETAIL", "".join(traceback.format_exception(error)))
                else:
                    self.fail("invalid submission clock was accepted")
                self.assertEqual(reads, [])
                self.assertEqual(self.path.read_bytes(), before)

    def test_exact_store_admission_is_required_and_local_clones_are_not_authenticated(self):
        original_path = self.path
        self.dispatch()
        calls = len(self.transport.calls)
        clone = Path(self.temp.name) / "unadmitted-copy.sqlite"
        shutil.copyfile(original_path, clone)
        self.path = clone
        result = self.dispatch(admit_store=lambda path, manifest, **kw: path == original_path)
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(len(self.transport.calls), calls)
        self.assertFalse(result["cloned_store_protection_verified"])
        # A deliberately overbroad fictional store gate cannot authenticate a
        # restored/pre-intent store: a separate empty path can invoke PUT again.
        self.path = Path(self.temp.name) / "deliberately-unauthenticated-new-store.sqlite"
        repeated = self.dispatch()
        self.assertEqual(len(self.transport.calls), calls + 8)
        self.assertFalse(repeated["global_exactly_once_verified"])
        self.assertFalse(repeated["cloned_store_protection_verified"])

    def test_rehashed_false_gate_normal_ack_hash_and_partial_roster_are_rejected(self):
        for failure in ("gate", "ack", "missing"):
            with self.subTest(failure=failure):
                self.path = Path(self.temp.name) / ("corrupt-" + failure + ".sqlite")
                self.transport = RecordingTransport()
                self.dispatch()
                with closing(sqlite3.connect(self.path)) as db:
                    table = "submission_intents" if failure in ("gate", "missing") else "submission_evidence"
                    verb = "DELETE" if failure == "missing" else "UPDATE"
                    trigger = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (table + "_no_" + verb.lower(),)).fetchone()[0]
                    db.execute("DROP TRIGGER " + table + "_no_" + verb.lower())
                    if failure == "missing":
                        db.execute("DELETE FROM submission_intents WHERE position=2")
                    else:
                        where = "position=1" + (" AND kind='NORMAL_ACK'" if failure == "ack" else "")
                        obj = json.loads(db.execute("SELECT json FROM " + table + " WHERE " + where).fetchone()[0])
                        if failure == "gate":
                            obj["gates"]["source"] = 1
                            domain, value = b"RACE_AI_PERMISSIONED_SUBMISSION_INTENT_V1\0", obj
                        else:
                            obj["payload"]["writer_return_sha256"] = "f" * 64
                            domain, value = b"RACE_AI_PERMISSIONED_SUBMISSION_EVIDENCE_V1\0", [1, "NORMAL_ACK", obj]
                        digest = sha(domain + canonical(value).encode())
                        db.execute("UPDATE " + table + " SET json=?,sha256=? WHERE " + where, (canonical(obj), digest))
                    db.execute(trigger)
                    db.commit()
                with self.assertRaises(ValueError):
                    self.recover()

    def test_store_resource_and_invalid_utf8_bounds_reject_without_private_diagnostics(self):
        self.dispatch()
        pristine = self.path.read_bytes()
        # Public entry must validate the original codec/model hashes first;
        # distinguish that existing baseline from an oversized attempt field.
        tracemalloc.start()
        try:
            self.recover()
            baseline = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        for table, column, expression in (("submission_manifest", "json", "CAST(zeroblob(16777216) AS TEXT)"),
                ("submission_intents", "sha256", "CAST(zeroblob(16777216) AS TEXT)"),
                ("submission_evidence", "kind", "CAST(zeroblob(16777216) AS TEXT)"),
                ("submission_evidence", "json", "zeroblob(16777216)")):
            with self.subTest(table=table, column=column):
                self.path.write_bytes(pristine)
                with closing(sqlite3.connect(self.path)) as db:
                    trigger = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (table + "_no_update",)).fetchone()[0]
                    db.execute("DROP TRIGGER " + table + "_no_update")
                    # Only one row is corrupted; unique kinds are retained.
                    rowid = db.execute("SELECT rowid FROM " + table + " LIMIT 1").fetchone()[0]
                    db.execute("UPDATE " + table + " SET " + column + "=" + expression + " WHERE rowid=?", (rowid,))
                    db.execute(trigger)
                    db.commit()
                tracemalloc.start()
                try:
                    with self.assertRaises(ValueError):
                        self.recover()
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertLess(peak, baseline + 1024 * 1024)
                self.assertLess(peak, 8 * 1024 * 1024)
        self.path.write_bytes(pristine)
        private = b'{"secret":"FICTIONAL_PRIVATE_ATTEMPT_TEXT_\xff"}'
        with closing(sqlite3.connect(self.path)) as db:
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='submission_manifest_no_update'").fetchone()[0]
            db.execute("DROP TRIGGER submission_manifest_no_update")
            db.execute("UPDATE submission_manifest SET json=CAST(? AS TEXT)", (private,))
            db.execute(trigger)
            db.commit()
        try:
            self.recover()
        except Exception as error:
            self.assertIsInstance(error, ValueError)
            self.assertNotIn("FICTIONAL_PRIVATE_ATTEMPT_TEXT_", "".join(traceback.format_exception(error)))
        else:
            self.fail("invalid UTF-8 attempt metadata was accepted")

    def test_foreign_store_unchanged_and_changed_destination_or_request_is_not_adopted(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE unrelated(value TEXT)")
            db.commit()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.dispatch()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.transport.calls, [])
        for key, value in (("expected_branch", "main"), ("submission_source_sha40", True),
                           ("expected_request_sha256", "f" * 64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.dispatch(**{key: value})

    def test_sticky_guard_rejects_extra_put_wrong_url_body_or_forged_success(self):
        from race_ai.append_only_freeze_writer import submit_anchor as original
        for kind in ("extra", "url", "body", "forged"):
            with self.subTest(kind=kind):
                self.path = Path(self.temp.name) / (kind + ".sqlite")
                self.transport = RecordingTransport()
                def bad(plan, branch, token, check, request):
                    if kind == "forged":
                        return {"status": "COMMIT_EXISTS_BUT_PRE_CUTOFF_PROOF_UNVERIFIED"}
                    if kind in ("url", "body"):
                        try:
                            request(BASE + "/other" if kind == "url" else BASE + "/contents/" + plan["path"],
                                    "PUT", b"{}")
                        except Exception:
                            pass
                    result = original(plan, branch, token, check, request=request)
                    if kind == "extra":
                        try:
                            request(BASE + "/contents/" + plan["path"], "PUT", b"{}")
                        except Exception:
                            pass
                    return result
                with patch.object(self.module, "submit_anchor", side_effect=bad):
                    result = self.dispatch()
                self.assertTrue(result["dispatch_barrier"])
                self.assertFalse(result["models"][0]["normal_acknowledged"])
                self.assertLessEqual(sum(x[1] == "PUT" for x in self.transport.calls), 1)

    def test_private_transport_and_admission_errors_do_not_leak(self):
        secret = "FICTIONAL_PRIVATE_TRANSPORT_TOKEN"
        def private(*a, **kw):
            raise RuntimeError(secret)
        try:
            result = self.dispatch(independent_release_check=private)
        except Exception as error:
            self.assertNotIn(secret, str(error))
            self.assertNotIn(secret, "".join(traceback.format_exception(error)))
        else:
            self.assertNotIn(secret, canonical(result))
        self.assertFalse(self.path.exists())
        self.transport.fail = "PUT"
        result = self.dispatch()
        self.assertNotIn(secret, canonical(result))
        self.assertNotIn(secret.encode(), self.path.read_bytes())

    def test_uncertain_intent_commit_never_calls_legacy_writer(self):
        connect = sqlite3.connect
        class Uncertain(sqlite3.Connection):
            def execute(connection, sql, *args):
                result = super().execute(sql, *args)
                if sql == "COMMIT" and str(connection.execute("PRAGMA application_id").fetchone()[0]) == str(0x52415355):
                    raise sqlite3.OperationalError("FICTIONAL_PRIVATE_UNCERTAIN_COMMIT")
                return result
        def factory(database, *a, **kw):
            if str(database) == str(self.path):
                kw["factory"] = Uncertain
            return connect(database, *a, **kw)
        with patch.object(self.module.sqlite3, "connect", side_effect=factory):
            try:
                result = self.dispatch()
            except Exception as error:
                self.assertNotIn("FICTIONAL_PRIVATE_UNCERTAIN_COMMIT", "".join(traceback.format_exception(error)))
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(len(schema_rows(self.path, "submission_intents")), 1)

    def test_real_crashes_consume_intent_and_never_repeat_put(self):
        for mode, count, known in (("before_commit", 0, False), ("before_put", 0, False),
                                   ("after_put", 1, False), ("before_get", 1, True),
                                   ("before_ack", 1, True)):
            with self.subTest(mode=mode):
                self.path = Path(self.temp.name) / (mode + ".sqlite")
                marker = Path(self.temp.name) / (mode + ".puts")
                command = [sys.executable, "-B", "-X", "utf8", __file__, "--worker", mode,
                           str(self.path), str(self.case_path), self.seal["request_sha256"], str(marker)]
                completed = subprocess.run(command, capture_output=True, timeout=30)
                self.assertEqual(completed.returncode, 71, completed.stderr.decode())
                self.assertEqual(len(marker.read_text().splitlines()) if marker.exists() else 0, count)
                if mode == "before_commit":
                    self.clock.at = LATE
                result = self.dispatch()
                self.assertEqual(self.transport.calls, [])
                if mode != "before_commit":
                    self.assertTrue(result["dispatch_barrier"])
                    self.assertEqual(result["models"][0]["commit_sha"] is not None, known)

    def test_live_concurrent_process_cannot_skip_unacknowledged_first_model(self):
        marker = Path(self.temp.name) / "concurrent.puts"
        waiting = Path(str(marker) + ".waiting")
        release = Path(str(marker) + ".release")
        command = [sys.executable, "-B", "-X", "utf8", __file__, "--worker", "concurrent",
                   str(self.path), str(self.case_path), self.seal["request_sha256"], str(marker)]
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        deadline = time.monotonic() + 15
        while not waiting.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(waiting.exists())
        result = self.dispatch()
        self.assertTrue(result["dispatch_barrier"])
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(len(marker.read_text().splitlines()), 1)
        release.touch()
        stdout, stderr = child.communicate(timeout=30)
        self.assertEqual(child.returncode, 0, stderr.decode())
        self.assertEqual(len(marker.read_text().splitlines()), 4)


def worker(mode, attempt_path, case_path, expected, marker):
    module = importlib.import_module("race_ai.permissioned_case_submission")
    transport = RecordingTransport()
    connect = sqlite3.connect
    class Crash(sqlite3.Connection):
        def execute(connection, sql, *args):
            if sql == "COMMIT" and mode == "before_commit":
                os._exit(71)
            return super().execute(sql, *args)
    def factory(database, *a, **kw):
        if str(database) == attempt_path:
            kw["factory"] = Crash
        return connect(database, *a, **kw)
    def recording(url, method, data):
        if method == "PUT":
            if mode == "before_put":
                os._exit(71)
            with open(marker, "a", encoding="utf-8") as stream:
                stream.write(url + "\n")
            if mode == "after_put":
                os._exit(71)
            if mode == "concurrent" and not Path(marker + ".waiting").exists():
                Path(marker + ".waiting").touch()
                deadline = time.monotonic() + 20
                while not Path(marker + ".release").exists() and time.monotonic() < deadline:
                    time.sleep(.01)
        if method == "GET" and mode == "before_get":
            os._exit(71)
        return transport(url, method, data)
    original = module.submit_anchor
    def legacy(*args, **kw):
        result = original(*args, **kw)
        if mode == "before_ack":
            os._exit(71)
        return result
    with patch.object(module.sqlite3, "connect", side_effect=factory), \
         patch.object(module, "submit_anchor", side_effect=legacy), \
         patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
        module.dispatch_prepared_case(attempt_path, case_path, expected_request_sha256=expected,
            expected_branch=BRANCH, submission_source_sha40=PIN, clock=Clock(), transport=recording, **gates())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(*sys.argv[2:])
    else:
        unittest.main()
