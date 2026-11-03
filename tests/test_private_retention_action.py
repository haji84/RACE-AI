"""One newly authored fictional model setup; operations never recompute models."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import importlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import os
import subprocess
import sys
import time
import traceback
import tracemalloc
import unittest
from unittest.mock import patch

from tests.test_retained_case_submission import RetainedSubmissionTests
from tests.test_permissioned_case_submission import BRANCH, PIN, RecordingTransport, gates, schema_rows
from tests.test_offline_model_run import Clock, LATE
from race_ai import retained_case_submission as retained
from race_ai import private_wire_retention as retention
from race_ai import permissioned_case_submission as core


def adapter_declaration():
    return {"schema": "RACE_AI_PRIVATE_RETENTION_LOCAL_ADAPTER_V1",
        "destination_contract": "LOCAL_SQLITE_D1_BATCH_CANDIDATE_V1",
        "runtime_scope": "EXPLICIT_INJECTED_LOCAL_TEST_CANDIDATE_ONLY",
        "source_commit_sha40": "9aeb2b425de9d05a44cb31f72a242a5111ada80a",
        "vault_module_sha256": "383264d3a676e04fc91a6c4956ef79d5bda709a09f6ad5b03e0d6062b6891024",
        "vault_schema_sha256": "950646a723ba6b6fed4446084a9f1510fb18b1540dcc0c5c5ff1cba0eae41b0c",
        "native_test_adapter_sha256": "04c26b80e27110b891e297a0d615cf99e9db84446f4d1ee978274f64f88db215"}


def private_gates():
    return {key: lambda *a, **kw: True for key in ("private_path_verifier", "admit_store",
        "admit_source_storage", "admit_owner_destination", "admit_coordinator", "verify_cutoff",
        "admit_model_roster", "admit_private_action", "admit_private_adapter")}


class RecordingVault:
    """Unit-only recording seam; root separately exercises the actual pinned JS."""
    def __init__(self):
        self.wire, self.claim, self.calls = None, None, []

    def result(self, claim, status):
        module = importlib.import_module("race_ai.private_retention_action")
        return {"schema": "RACE_AI_LOCAL_PRIVATE_WIRE_RESULT_V1", "status": status,
            "scope": "LOCAL_ONLY", "locator": module._locator(claim), "claim": deepcopy(claim),
            "wire": self.wire, "wire_sha256": claim["wire_sha256"], "wire_bytes": claim["wire_bytes"],
            "chunk_count": len(claim["chunk_sha256"]), "retention_status": "RETENTION_UNVERIFIED",
            **dict.fromkeys(module.FALSE_FLAGS, False)}

    def create(self, claim, wire):
        self.calls.append("create")
        self.claim, self.wire = deepcopy(claim), wire
        return self.result(claim, "LOCAL_CREATED")

    def read(self, claim, locator):
        self.calls.append("read")
        return self.result(claim, "LOCAL_READBACK")


class PrivateActionTests(RetainedSubmissionTests):
    # Reuse setup helpers, not the inherited test collection.
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.private_retention_action"),
                             "consumed private-retention action is missing")
        super().setUp()
        self.action = importlib.import_module("race_ai.private_retention_action")
        self.declaration = adapter_declaration()
        self.destination.update(destination_ref="local-private-vault-fictional",
            adapter_contract_sha256=retention._hash(self.declaration["schema"], self.declaration))
        self.policy["retain_until"] = datetime.fromisoformat(self.policy["retain_until"]).astimezone(timezone.utc).isoformat()
        self.vault = RecordingVault()

    def reserve(self, **kw):
        return super().reserve(submission_contract="PRIVATE_ACTION_V3", **kw)

    def consume(self, c, **kw):
        args = {**self.identity(), **private_gates(), "expected_reservation_sha256": c["reservation_sha256"],
            "private_adapter_declaration": self.declaration, "private_create": self.vault.create}
        args.update(kw)
        return self.action.consume_private_retention_action(self.path, self.case_path, **args)

    def read_action(self, c, p, **kw):
        args = {"expected_request_sha256": self.seal["request_sha256"],
            "expected_reservation_sha256": c["reservation_sha256"],
            "expected_private_action_sha256": p["private_action_sha256"], "clock": Clock(LATE),
            **self.access(), "admit_private_reader": lambda *a: True, "private_read": self.vault.read}
        args.update(kw)
        return self.action.read_private_retention_action(self.path, self.case_path, **args)

    def admit(self, c, inputs=None, **kw):
        return super().admit(c, inputs, submission_contract="PRIVATE_ACTION_V3", **kw)

    def dispatch(self, c, **kw):
        return super().dispatch(c, submission_contract="PRIVATE_ACTION_V3", **kw)

    def test_fresh_private_action_is_committed_before_one_create_and_no_public_intent(self):
        c = self.reserve()
        before = self.case_path.read_bytes()
        def create(claim, wire):
            self.assertEqual(len(schema_rows(self.path, "submission_private_action")), 1)
            self.assertEqual(wire, self.loaded["wire"])
            return self.vault.create(claim, wire)
        p = self.consume(c, private_create=create)
        self.assertEqual(p["status"], "LOCAL_PRIVATE_READBACK_UNVERIFIED")
        self.assertEqual((p["create_calls"], p["read_calls"]), (1, 0))
        self.assertEqual(schema_rows(self.path, "submission_intents"), [])
        self.assertEqual(self.case_path.read_bytes(), before)
        self.assertTrue(p["private_action_consumed"])
        self.assertTrue(all(p[key] is False for key in self.action.FALSE_FLAGS))

    def test_default_gates_and_writer_deny_before_p(self):
        c = self.reserve()
        for key in (*private_gates(), "private_create", "private_adapter_declaration"):
            with self.subTest(key=key):
                p = self.consume(c, **{key: None})
                self.assertEqual(p["status"], "DENIED")
                self.assertFalse(p["private_action_consumed"])
                self.assertEqual(schema_rows(self.path, "submission_private_action"), [])
        self.assertEqual(self.vault.calls, [])

    def test_prior_p_bootstraps_without_writer_clock_or_write_gates(self):
        c = self.reserve()
        first = self.consume(c)
        raw = self.path.read_bytes()
        result = self.consume(c, clock=None, private_create=None, private_adapter_declaration=None,
            **{key: None for key in private_gates() if key not in self.access()})
        self.assertEqual(result["status"], "PRIVATE_ACTION_CONSUMED_READ_ONLY")
        self.assertEqual(result["private_action_sha256"], first["private_action_sha256"])
        self.assertEqual((result["create_calls"], result["read_calls"]), (0, 0))
        self.assertEqual(raw, self.path.read_bytes())

    def test_after_cutoff_read_is_exact_and_cannot_create_or_release(self):
        c = self.reserve()
        p = self.consume(c)
        result = self.read_action(c, p)
        self.assertEqual(result["status"], "LOCAL_PRIVATE_READBACK_UNVERIFIED")
        self.assertEqual((result["create_calls"], result["read_calls"]), (0, 1))
        self.assertEqual(self.vault.calls, ["create", "read"])
        self.assertEqual(schema_rows(self.path, "submission_retention"), [])
        with self.assertRaises(ValueError):
            self.read_action(c, p, expected_private_action_sha256="0" * 64)

    def test_p_is_required_before_e_callbacks_and_e_binds_exact_final_row(self):
        c = self.reserve()
        inputs = self.evidence_inputs(c)
        with self.assertRaises(ValueError):
            self.admit(c, inputs, expected_private_action_sha256="0" * 64,
                admit_source_storage=lambda *a: self.fail("E callback before P"))
        self.clock.at = "2030-01-15T09:16:00+09:00"
        p = self.consume(c)
        e = self.admit(c, inputs, expected_private_action_sha256=p["private_action_sha256"])
        self.assertEqual(e["evidence"]["schema"], "RACE_AI_RETAINED_SUBMISSION_ADMISSION_V3")
        self.assertEqual(e["evidence"]["private_action_sha256"], p["private_action_sha256"])
        self.clock.at = "2030-01-15T09:20:00+09:00"
        result = self.dispatch(c, expected_private_action_sha256=p["private_action_sha256"])
        self.assertEqual(result["schema"], "RACE_AI_PERMISSIONED_SUBMISSION_RESULT_V3")
        self.assertEqual(result["github_reads"], 4)
        self.assertEqual(result["private_action_sha256"], p["private_action_sha256"])
        with closing(sqlite3.connect(self.path)) as db:
            obj = json.loads(db.execute("SELECT json FROM submission_intents LIMIT 1").fetchone()[0])
            self.assertIs(obj["gates"]["private_action"], True)
        replay = self.dispatch(c, expected_private_action_sha256=p["private_action_sha256"], clock=None)
        self.assertEqual(replay["github_reads"], 0)

    def test_local_readback_never_admits_e_or_public(self):
        c = self.reserve()
        p = self.consume(c)
        result = self.dispatch(c, expected_private_action_sha256=p["private_action_sha256"])
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(schema_rows(self.path, "submission_retention"), [])

    def test_wrong_profile_and_expected_final_p_are_not_fallbacks(self):
        c = self.reserve()
        p = self.consume(c)
        for wrong in (None, p["private_action_candidate_sha256"], "e" * 64):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.dispatch(c, expected_private_action_sha256=wrong)
        with self.assertRaises(ValueError):
            retained.reserve_retained_case(self.path, self.case_path, **self.identity(), **self.access(),
                slot=self.slot, assignment_ref="fictional-sole-store-assignment", destination=self.destination,
                retention_policy=self.policy)

    def test_current_storage_authorities_cover_complete_purposes_and_horizon(self):
        c = self.reserve()
        seen = []
        def source(request, snapshot):
            seen.append(request)
            self.assertEqual(request["models"], [{"model_id": n, "model_version": m["model_version"],
                "prediction_sha256": m["prediction_sha256"]} for n, m in self.loaded["delivery"]["research_suite"]["models"].items()])
            self.assertEqual(request["retention_policy"], self.policy)
            self.assertEqual(snapshot, self.loaded["delivery"]["snapshot"])
            return False
        p = self.consume(c, admit_source_storage=source)
        self.assertEqual(p["status"], "DENIED")
        self.assertTrue(seen)
        self.assertEqual(self.vault.calls, [])
        self.assertEqual(schema_rows(self.path, "submission_private_action"), [])

    def test_all_nontrue_and_mutating_gates_deny_without_p(self):
        c = self.reserve()
        for key in private_gates():
            for false in (1, 1.0, False):
                with self.subTest(key=key, value=false):
                    p = self.consume(c, **{key: lambda *a, value=false, **kw: value})
                    self.assertFalse(p["private_action_consumed"])
        def mutate(claim, prerequisite):
            prerequisite["vault_claim"]["owner_ref"] = "forged-owner"
            return True
        self.assertFalse(self.consume(c, admit_private_action=mutate)["private_action_consumed"])
        self.assertEqual(schema_rows(self.path, "submission_private_action"), [])

    def test_post_p_denial_is_consumed_with_zero_create_forever(self):
        c = self.reserve()
        def action(claim, prerequisite):
            return claim["phase"] != "PRE_PRIVATE_CREATE"
        p = self.consume(c, admit_private_action=action)
        self.assertEqual(p["status"], "PRIVATE_ACTION_CONSUMED_READ_ONLY")
        self.assertTrue(p["private_action_consumed"])
        self.assertEqual(p["create_calls"], 0)
        self.assertEqual(self.consume(c)["create_calls"], 0)
        self.assertEqual(self.vault.calls, [])

    def test_seam_throw_mutation_alias_promotions_and_huge_metadata_are_consumed(self):
        for mode in ("throw", "claim", "bool", "float", "extra", "wire", "promotion", "huge"):
            self.path = Path(self.temp.name) / (mode + ".sqlite")
            self.clock.at = "2030-01-15T09:16:00+09:00"
            c = self.reserve()
            def create(claim, wire):
                if mode == "throw":
                    raise RuntimeError("FICTIONAL_PRIVATE_SEAM_VALUE")
                result = self.vault.create(claim, wire)
                if mode == "claim":
                    claim["owner_ref"] = "changed"
                elif mode == "bool":
                    result["wire_bytes"] = True
                elif mode == "float":
                    result["wire_bytes"] = float(result["wire_bytes"])
                elif mode == "extra":
                    result["unrecognized"] = None
                elif mode == "wire":
                    result["wire"] = bytearray(wire)
                elif mode == "promotion":
                    result["independent_retention_proof"] = True
                elif mode == "huge":
                    result["claim"]["owner_ref"] = "x" * 8_000_000
                return result
            p = self.consume(c, private_create=create)
            self.assertEqual(p["status"], "PRIVATE_ACTION_CONSUMED_READ_ONLY", mode)
            self.assertEqual(p["create_calls"], 1)
            self.assertIsNone(p["readback"])
            self.assertEqual(self.consume(c)["create_calls"], 0)

    def test_last_path_gate_is_before_final_p_guard_and_create_edge(self):
        c = self.reserve()
        def slow(path, claim, *, stage):
            if stage == "PRE_COMMIT":
                self.clock.at = "2030-01-15T09:20:00+09:00"
            return True
        p = self.consume(c, admit_store=slow)
        self.assertEqual(p["private_action_commit_guard_at"], "2030-01-15T00:20:00+00:00")
        inputs = self.evidence_inputs(c)
        with self.assertRaises(ValueError):
            self.admit(c, inputs, expected_private_action_sha256=p["private_action_sha256"],
                       clock=Clock("2030-01-15T09:21:00+09:00"))
        self.assertEqual(schema_rows(self.path, "submission_retention"), [])

    def test_slow_final_gate_cutoff_and_rollback_never_create(self):
        for phase in ("PRE_PRIVATE_INTENT", "PRE_PRIVATE_CREATE"):
            self.path = Path(self.temp.name) / (phase + ".sqlite")
            self.clock.at = "2030-01-15T09:16:00+09:00"
            c = self.reserve()
            def late(claim, prerequisite):
                if claim["phase"] == phase:
                    self.clock.at = LATE
                return True
            if phase == "PRE_PRIVATE_INTENT":
                with self.assertRaises(ValueError):
                    self.consume(c, admit_private_action=late)
                self.assertEqual(schema_rows(self.path, "submission_private_action"), [])
            else:
                self.assertEqual(self.consume(c, admit_private_action=late)["create_calls"], 0)
                self.assertEqual(len(schema_rows(self.path, "submission_private_action")), 1)
        self.assertEqual(self.vault.calls, [])

    def test_uncertain_commit_persisted_still_calls_no_create(self):
        c = self.reserve()
        def uncertain(db):
            db.execute("COMMIT")
            raise OSError("FICTIONAL_PRIVATE_COMMIT")
        with patch.object(core, "_commit", uncertain), self.assertRaises(ValueError):
            self.consume(c)
        self.assertEqual(len(schema_rows(self.path, "submission_private_action")), 1)
        self.assertEqual(self.vault.calls, [])
        self.assertEqual(self.consume(c, clock=None, private_create=None)["create_calls"], 0)

    def test_rehashed_semantic_p_and_e_forgery_is_rejected(self):
        c = self.reserve()
        p = self.consume(c)
        self.admit(c, expected_private_action_sha256=p["private_action_sha256"])
        saved = self.path.read_bytes()
        for table, modify, domain in (
            ("submission_private_action", lambda p: p["action"]["vault_claim"].update(owner_ref="copied"), self.action.ROW),
            ("submission_private_action", lambda p: p["admissions"].update(source_storage=1), self.action.ROW),
            ("submission_private_action", lambda p: p.update(commit_guard_at="2030-01-15T00:15:00+00:00"), self.action.ROW),
            ("submission_retention", lambda p: p["evidence"].update(private_action_sha256="0" * 64), "RACE_AI_RETAINED_ADMISSION_ROW_V3")):
            self.path.write_bytes(saved)
            def alter(db):
                obj = json.loads(db.execute("SELECT json FROM " + table).fetchone()[0])
                modify(obj)
                db.execute("UPDATE " + table + " SET json=?,sha256=?", (retention._raw(obj).decode(), retention._hash(domain, obj)))
            self.alter(table, alter)
            with self.assertRaises(ValueError):
                self.consume(c)
        self.assertEqual(self.transport.calls, [])

    def test_p_columns_are_preflighted_and_private_errors_suppressed(self):
        c = self.reserve()
        self.consume(c)
        saved = self.path.read_bytes()
        for column in ("json", "sha256"):
            self.path.write_bytes(saved)
            self.alter("submission_private_action", lambda db: db.execute("UPDATE submission_private_action SET " + column + "=?", ("x" * 16_000_000,)))
            tracemalloc.start()
            try:
                with self.assertRaises(ValueError):
                    self.consume(c)
                self.assertLess(tracemalloc.get_traced_memory()[1], 8 * 1024 * 1024)
            finally:
                tracemalloc.stop()
        self.path.write_bytes(saved)
        self.alter("submission_private_action", lambda db: db.execute("UPDATE submission_private_action SET json=CAST(? AS TEXT)", (b'FICTIONAL_PRIVATE_P_TEXT_\xff',)))
        try:
            self.consume(c)
        except ValueError as error:
            self.assertNotIn("FICTIONAL_PRIVATE_P_TEXT", "".join(traceback.format_exception(error)))
        else:
            self.fail("malformed private state accepted")

    def test_immutable_p_blocks_replace_and_exact_read_gate_only(self):
        c = self.reserve()
        p = self.consume(c)
        with closing(sqlite3.connect(self.path)) as db:
            for sql in ("DELETE FROM submission_private_action", "UPDATE submission_private_action SET sha256='x'",
                        "INSERT OR REPLACE INTO submission_private_action SELECT * FROM submission_private_action"):
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute(sql)
        self.assertEqual(self.read_action(c, p, admit_private_reader=None)["read_calls"], 0)
        def mutate(claim, prerequisite, reader):
            prerequisite["vault_locator"] = "0" * 64
            return True
        self.assertEqual(self.read_action(c, p, admit_private_reader=mutate)["read_calls"], 0)
        self.assertEqual(self.read_action(c, p, clock=Clock("2030-01-15T09:15:00+09:00"))["read_calls"], 0)

    def process(self, mode, c, marker):
        config = Path(self.temp.name) / (mode + "-control.json")
        config.write_text(json.dumps({"attempt": str(self.path), "case": str(self.case_path),
            "request": self.seal["request_sha256"], "reservation": c["reservation_sha256"],
            "marker": str(marker)}), encoding="utf-8")
        return subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-c",
            "from tests.test_private_retention_action import private_worker; import sys; private_worker(*sys.argv[1:])",
            mode, str(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def wait_file(self, path, process):
        deadline = time.monotonic() + 15
        while not path.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.02)
        self.assertTrue(path.exists(), "child never reached the specified transaction boundary")

    def test_real_process_crashes_before_after_p_and_after_destination_commit(self):
        for mode in ("before", "after", "beforecreate", "destination"):
            self.path = Path(self.temp.name) / (mode + ".sqlite")
            c = self.reserve()
            marker = Path(self.temp.name) / (mode + ".wire")
            child = self.process(mode, c, marker)
            out, err = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 73, err.decode())
            self.assertEqual(len(schema_rows(self.path, "submission_private_action")), int(mode != "before"))
            self.assertEqual(marker.exists(), mode == "destination")
            if mode != "before":
                replay = self.consume(c, clock=None, private_create=None, private_adapter_declaration=None)
                self.assertTrue(replay["private_action_consumed"])
                self.assertEqual(replay["create_calls"], 0)
            if mode == "destination":
                p = self.consume(c, clock=None, private_create=None)
                self.vault.wire = marker.read_bytes()
                read = self.read_action(c, p)
                self.assertEqual(read["readback"]["wire"], self.loaded["wire"])
        self.assertEqual(self.vault.calls, ["read"])

    def test_two_processes_forced_overlap_own_one_p_and_one_create(self):
        c = self.reserve()
        marker = Path(self.temp.name) / "overlap-wire"
        first = self.process("hold", c, marker)
        second = None
        try:
            self.wait_file(Path(str(marker) + ".held"), first)
            second = self.process("contender", c, marker)
            self.wait_file(Path(str(marker) + ".contender"), second)
            self.assertIsNone(first.poll())
            self.assertIsNone(second.poll())
            Path(str(marker) + ".release").write_bytes(b"release")
            for process in (first, second):
                out, err = process.communicate(timeout=25)
                self.assertEqual(process.returncode, 0, err.decode())
                result = json.loads(out)
                self.assertTrue(result["consumed"])
            self.assertEqual(Path(str(marker) + ".calls").read_bytes(), b"create\n")
            self.assertEqual(len(schema_rows(self.path, "submission_private_action")), 1)
            self.assertEqual(marker.read_bytes(), self.loaded["wire"])
        finally:
            for process in (first, second):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)

    def test_declared_adapter_cap_horizon_and_new_path_do_not_authorize_retries(self):
        c = self.reserve()
        bad = deepcopy(self.declaration)
        bad["source_commit_sha40"] = "f" * 40
        with self.assertRaises(ValueError):
            self.consume(c, private_adapter_declaration=bad)
        self.assertEqual(schema_rows(self.path, "submission_private_action"), [])
        p = self.consume(c)
        with self.assertRaises(ValueError):
            self.consume(c, expected_reservation_sha256="0" * 64)
        self.path = Path(self.temp.name) / "not-assigned.sqlite"
        with self.assertRaises(ValueError):
            self.consume(c)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.vault.calls, ["create"])

    def test_recovery_clock_after_slow_reader_does_not_reverse(self):
        c = self.reserve()
        p = self.consume(c)
        clock = Clock("2030-01-15T09:20:00+09:00")
        def reader(claim, prerequisite, callback):
            clock.at = "2030-01-15T09:19:00+09:00"
            return True
        result = self.read_action(c, p, clock=clock, admit_private_reader=reader)
        self.assertEqual(result["read_calls"], 0)
        self.assertEqual(result["status"], "PRIVATE_READ_UNRESOLVED")

    def test_recovery_dst_fold_uses_utc_and_invalid_clocks_read_zero(self):
        c = self.reserve()
        p = self.consume(c)
        zone = ZoneInfo("America/New_York")
        for first, second, expected in (
            (datetime(2030, 11, 3, 1, 30, tzinfo=zone, fold=1), datetime(2030, 11, 3, 1, 45, tzinfo=zone, fold=0), 0),
            (datetime(2030, 11, 3, 1, 45, tzinfo=zone, fold=0), datetime(2030, 11, 3, 1, 30, tzinfo=zone, fold=1), 1)):
            samples = iter((first, second))
            result = self.read_action(c, p, clock=lambda: next(samples))
            self.assertEqual(result["read_calls"], expected)
        for clock in (lambda: None, lambda: datetime(2030, 1, 15), lambda: 1,
                      lambda: (_ for _ in ()).throw(ValueError("FICTIONAL_PRIVATE_CLOCK"))):
            result = self.read_action(c, p, clock=clock)
            self.assertEqual(result["read_calls"], 0)
            self.assertEqual(result["status"], "PRIVATE_READ_UNRESOLVED")

    def test_callback_mutation_is_bounded_and_private_exceptions_not_echoed(self):
        c = self.reserve()
        huge = "x" * 8_000_000
        def mutate(claim, prerequisite):
            claim["candidate"]["vault_claim"]["owner_ref"] = huge
            return True
        tracemalloc.start()
        try:
            result = self.consume(c, admit_private_action=mutate)
            self.assertFalse(result["private_action_consumed"])
            self.assertLess(tracemalloc.get_traced_memory()[1], 8 * 1024 * 1024)
        finally:
            tracemalloc.stop()
        def private_error(*a):
            raise RuntimeError("FICTIONAL_PRIVATE_GATE_BODY")
        try:
            self.consume(c, admit_private_action=private_error)
        except ValueError as error:
            self.assertNotIn("FICTIONAL_PRIVATE_GATE_BODY", "".join(traceback.format_exception(error)))
        else:
            self.fail("unexpected private callback error accepted")
        self.assertEqual(schema_rows(self.path, "submission_private_action"), [])

    def test_expected_p_and_prospective_candidate_are_exact_callback_arguments(self):
        c = self.reserve()
        claims, declarations = [], []
        def admit(claim, prerequisite):
            claims.append(deepcopy(claim))
            self.assertEqual(prerequisite["reservation"], c["reservation"])
            self.assertEqual(prerequisite["reservation_row_sha256"], c["reservation_row_sha256"])
            self.assertEqual(claim["candidate_sha256"], retention._hash(self.action.CANDIDATE, claim["candidate"]))
            if claim["phase"] == "PRE_PRIVATE_INTENT":
                self.assertIsNone(claim["private_action_sha256"])
                self.assertIsNone(claim["private_action_commit_guard_at"])
                self.assertNotIn("admissions", claim["candidate"])
            return True
        def roster(claim, models):
            declarations.append(models)
            return type(models) is tuple and models == tuple((m["model_id"], m["model_version"],
                self.loaded["request"]["model_source_sha40"]) for m in c["reservation"]["base_manifest"]["models"])
        p = self.consume(c, admit_private_action=admit, admit_model_roster=roster)
        self.assertTrue(declarations)
        self.assertEqual(claims[-1]["private_action_sha256"], p["private_action_sha256"])
        self.assertEqual(claims[-1]["private_action_commit_guard_at"], p["private_action_commit_guard_at"])
        self.assertEqual(claims[-1]["candidate"], claims[0]["candidate"])

    def test_expiry_before_required_horizon_is_not_current_storage_admission(self):
        c = self.reserve()
        expiry = datetime.fromisoformat("2030-01-15T10:00:00+09:00")
        def storage(request, snapshot):
            return expiry >= datetime.fromisoformat(request["retention_policy"]["retain_until"])
        p = self.consume(c, admit_source_storage=storage)
        self.assertFalse(p["private_action_consumed"])
        self.assertEqual(self.vault.calls, [])

    def test_rehashed_public_manifest_cross_p_and_copied_p_across_slot_deny(self):
        c = self.reserve()
        p = self.consume(c)
        self.admit(c, expected_private_action_sha256=p["private_action_sha256"])
        self.clock.at = "2030-01-15T09:20:00+09:00"
        self.dispatch(c, expected_private_action_sha256=p["private_action_sha256"])
        def corrupt(db):
            m = json.loads(db.execute("SELECT json FROM submission_manifest").fetchone()[0])
            m["private_action_sha256"] = p["private_action_candidate_sha256"]
            db.execute("UPDATE submission_manifest SET json=?,sha256=?", (core._raw(m).decode(), core._bound("MANIFEST", m, m)))
        self.alter("submission_manifest", corrupt)
        with self.assertRaises(ValueError):
            self.consume(c)
        self.path = Path(self.temp.name) / "different-slot.sqlite"
        self.clock.at = "2030-01-15T09:16:00+09:00"
        other = self.reserve(assignment_ref="another-independent-assignment")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO submission_private_action VALUES(1,?,?)", (retention._raw(p["private_action"]).decode(), p["private_action_sha256"]))
            db.commit()
        with self.assertRaises(ValueError):
            self.consume(other)

    def test_owner_removed_or_replaced_by_last_create_gate_consumes_without_create(self):
        for mode in ("missing", "foreign"):
            self.path = Path(self.temp.name) / (mode + "-owner.sqlite")
            c = self.reserve()
            def gate(claim, prerequisite):
                if claim["phase"] == "PRE_PRIVATE_CREATE":
                    self.path.unlink()
                    if mode == "foreign":
                        self.path.write_bytes(b"FICTIONAL_FOREIGN_OWNER")
                return True
            result = self.consume(c, admit_private_action=gate)
            self.assertTrue(result["private_action_consumed"])
            self.assertEqual(result["create_calls"], 0)
            self.assertEqual(self.vault.calls, [])
            if mode == "missing":
                self.assertFalse(self.path.exists())
            else:
                self.assertEqual(self.path.read_bytes(), b"FICTIONAL_FOREIGN_OWNER")

    def test_owner_removed_by_final_reader_gate_calls_no_read(self):
        c = self.reserve()
        p = self.consume(c)
        def reader(claim, prerequisite, callback):
            self.path.unlink()
            return True
        result = self.read_action(c, p, admit_private_reader=reader)
        self.assertEqual(result["read_calls"], 0)
        self.assertEqual(result["status"], "PRIVATE_READ_UNRESOLVED")
        self.assertFalse(self.path.exists())

    def test_final_clock_cannot_remove_owner_and_then_allow_create(self):
        c = self.reserve()
        armed, attempts = False, 0
        def gate(claim, prerequisite):
            nonlocal armed
            armed = claim["phase"] == "PRE_PRIVATE_CREATE"
            return True
        def clock():
            nonlocal attempts
            if armed:
                attempts += 1
                self.path.unlink()  # Windows may deny unlink of the open RO snapshot.
            return datetime.fromisoformat("2030-01-15T09:16:00+09:00")
        result = self.consume(c, admit_private_action=gate, clock=clock)
        self.assertEqual(attempts, 1)
        self.assertEqual(result["create_calls"], 0)
        self.assertTrue(result["private_action_consumed"])
        self.assertEqual(self.vault.calls, [])

    def test_oversized_seam_result_fieldset_is_bounded_before_set_allocation(self):
        result = {"fictional_" + str(i): None for i in range(200000)}
        candidate = {"vault_claim": {"schema": "FICTIONAL_MINIMAL"}, "vault_locator": "a" * 64}
        tracemalloc.start()
        try:
            with self.assertRaises(ValueError):
                self.action._operation(lambda *a: result, candidate, {"wire": b"x"})
            self.assertLess(tracemalloc.get_traced_memory()[1], 1024 * 1024)
        finally:
            tracemalloc.stop()

    def test_negative_huge_integer_metadata_never_allocates_abs_copy(self):
        huge = -(1 << 64000000)  # Allocate adversarial input before tracing.
        def mutate(owned):
            owned["n"] = huge
            return True
        declaration = {**adapter_declaration(), "source_commit_sha40": huge}
        candidate = {"vault_claim": {"schema": "FICTIONAL_MINIMAL"}, "vault_locator": "a" * 64}
        result = dict.fromkeys({"schema", "status", "scope", "locator", "claim", "wire", "wire_sha256",
            "wire_bytes", "chunk_count", "retention_status"} | set(self.action.FALSE_FLAGS))
        result["claim"] = {"n": huge}
        for mode in ("callback", "declaration", "result"):
            tracemalloc.start()
            try:
                if mode == "callback":
                    self.assertIs(self.action._call(mutate, {"n": 0}), False)
                elif mode == "declaration":
                    with self.assertRaises(ValueError):
                        self.action._declaration(declaration)
                else:
                    with self.assertRaises(ValueError):
                        self.action._operation(lambda *a: result, candidate, {"wire": b"x"})
                peak = tracemalloc.get_traced_memory()[1]
                self.assertLess(peak, 1024 * 1024, mode)
            finally:
                tracemalloc.stop()


# Only the new public tests are collected; old-profile coverage belongs to root.
for _name in tuple(vars(RetainedSubmissionTests)):
    if _name.startswith("test_") and _name not in PrivateActionTests.__dict__:
        setattr(PrivateActionTests, _name, None)
del RetainedSubmissionTests


def private_worker(mode, config_path):
    """Actual OS crashes/lock overlap; existing checkpoint only, no inference."""
    from race_ai import private_retention_action as action
    from race_ai import permissioned_source_delivery as source
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    marker = Path(config["marker"])
    calls = 0
    original_commit = core._commit
    vault = RecordingVault()
    def commit(db):
        if mode == "before":
            os._exit(73)
        original_commit(db)
        if mode == "after":
            os._exit(73)
    def admit(claim, prerequisite):
        nonlocal calls
        if claim["phase"] == "PRE_PRIVATE_CREATE" and mode == "beforecreate":
            os._exit(73)
        if claim["phase"] == "PRE_PRIVATE_INTENT":
            calls += 1
            if mode == "contender" and calls == 1:
                Path(str(marker) + ".contender").write_bytes(b"pre-lock")
            if mode == "hold" and calls == 2:
                Path(str(marker) + ".held").write_bytes(b"inside write transaction")
                deadline = time.monotonic() + 15
                while not Path(str(marker) + ".release").exists():
                    if time.monotonic() > deadline:
                        raise RuntimeError("fixture synchronization failed")
                    time.sleep(.01)
        return True
    def create(claim, wire):
        with marker.open("wb") as file:
            file.write(wire)
            file.flush()
            os.fsync(file.fileno())
        with Path(str(marker) + ".calls").open("ab") as file:
            file.write(b"create\n")
            file.flush()
            os.fsync(file.fileno())
        if mode == "destination":
            os._exit(73)
        return vault.create(claim, wire)
    with patch.object(source, "deliver", side_effect=AssertionError("worker inference forbidden")), patch.object(core, "_commit", commit):
        result = action.consume_private_retention_action(config["attempt"], config["case"],
            expected_request_sha256=config["request"], expected_reservation_sha256=config["reservation"],
            expected_branch=BRANCH, submission_source_sha40=PIN, private_adapter_declaration=adapter_declaration(),
            clock=Clock("2030-01-15T09:16:00+09:00"), **{**private_gates(), "admit_private_action": admit}, private_create=create)
    print(json.dumps({"consumed": result["private_action_consumed"], "creates": result["create_calls"]}))
