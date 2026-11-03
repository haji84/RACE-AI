"""One original authored case, supplied fictional retention and transport only."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
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

from tests.test_permissioned_model_case import fixture, authorities
from tests.test_permissioned_case_submission import BRANCH, PIN, RecordingTransport, schema_rows, gates
from tests.test_offline_model_run import Clock, LATE, canonical, sha, MODELS
from race_ai.permissioned_model_case import prepare_case, load_case
from race_ai import private_wire_retention as retention


class RetainedSubmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_dir = tempfile.TemporaryDirectory(prefix="race33-original-fictional-")
        cls.original = Path(cls.original_dir.name) / "case.sqlite"
        request, raw, policy = fixture()
        cls.seal = prepare_case(cls.original, request, raw, policy, clock=Clock(), **authorities(request))
        cls.loaded = load_case(cls.original, expected_request_sha256=cls.seal["request_sha256"],
                              private_path_verifier=lambda *a, **kw: True)

    @classmethod
    def tearDownClass(cls):
        cls.original_dir.cleanup()

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.retained_case_submission"),
                             "durable original-wire prerequisite is missing")
        self.module = importlib.import_module("race_ai.retained_case_submission")
        self.temp = tempfile.TemporaryDirectory(prefix="race33-fictional-")
        self.addCleanup(self.temp.cleanup)
        self.case_path = Path(self.temp.name) / "case.sqlite"
        shutil.copyfile(self.original, self.case_path)
        self.path = Path(self.temp.name) / "attempt.sqlite"
        self.clock = Clock("2030-01-15T09:16:00+09:00")
        self.transport = RecordingTransport()
        race = self.loaded["delivery"]["snapshot"]["race"]
        self.slot = {"schema": "RACE_AI_PROSPECTIVE_COMPARISON_SLOT_V1", "scope_ref": "fictional-declared-scope",
            "race_id": self.loaded["request"]["race_id"], "race_revision": race["race_revision"],
            "as_of_utc": datetime.fromisoformat(race["as_of"]).astimezone(timezone.utc).isoformat(), "model_ids": list(MODELS)}
        self.destination = {"destination_ref": "fictional-private-destination", "owner_scope_ref": "fictional-owner",
            "adapter_contract_sha256": "a" * 64, "max_wire_bytes": 4 * 1024 * 1024}
        self.policy = {"policy_ref": "fictional-retention", "retain_until": "2030-02-15T10:00:00+09:00",
            "protection_policy_sha256": "b" * 64, "immutability_policy_sha256": "c" * 64}
        from race_ai import permissioned_source_delivery as source
        for guard in (patch.object(source, "deliver", side_effect=AssertionError("inference forbidden")),
                      patch("socket.create_connection", side_effect=AssertionError("network forbidden"))):
            guard.start()
            self.addCleanup(guard.stop)

    def access(self):
        return {"private_path_verifier": lambda path, **kw: True, "admit_store": lambda path, claim, **kw: True}

    def identity(self):
        return {"expected_request_sha256": self.seal["request_sha256"], "expected_branch": BRANCH,
                "submission_source_sha40": PIN, "clock": self.clock}

    def reserve(self, **overrides):
        options = {**self.identity(), **self.access(), "slot": self.slot, "assignment_ref": "fictional-sole-store-assignment",
                   "destination": self.destination, "retention_policy": self.policy}
        options.update(overrides)
        return self.module.reserve_retained_case(self.path, self.case_path, **options)

    def handoff(self, reservation):
        return retention.prepare_retention_handoff(self.case_path,
            expected_case_request_sha256=self.seal["request_sha256"], destination=self.destination,
            retention_policy=self.policy, coordinator_binding=reservation["base_binding"], clock=self.clock,
            private_path_verifier=self.access()["private_path_verifier"], admit_source_storage=lambda *a: True,
            admit_owner_destination=lambda *a: True, admit_coordinator=lambda *a: True)

    def evidence_inputs(self, reservation):
        handoff = self.handoff(reservation)
        request = handoff["request"]
        descriptor = {"schema": retention.READBACK, "request_sha256": handoff["request_sha256"],
            "destination_ref": self.destination["destination_ref"], "object_ref": "fictional-whole-object",
            "object_version": "immutable-v1", "wire_sha256": request["wire_sha256"], "wire_byte_count": request["wire_byte_count"],
            "observed_at": "2030-01-15T09:18:00+09:00", "reader_attestation_ref": "fictional-protected-reader"}
        receipt = {"schema": retention.RECEIPT,
            **{key: descriptor[key] for key in ("request_sha256", "destination_ref", "object_ref", "object_version", "wire_sha256", "wire_byte_count")},
            "committed_at": "2030-01-15T09:17:00+09:00", "retained_until": self.policy["retain_until"],
            "protection_policy_sha256": self.policy["protection_policy_sha256"],
            "immutability_policy_sha256": self.policy["immutability_policy_sha256"], "issuer_ref": "fictional-independent-issuer"}
        return {"readback_bytes": self.loaded["wire"], "readback_descriptor": descriptor,
                "receipt_claims": receipt, "receipt_proof": b"FICTIONAL_OPAQUE_PROOF"}

    def admit(self, reservation, inputs=None, **overrides):
        inputs = inputs or self.evidence_inputs(reservation)
        self.clock.at = "2030-01-15T09:19:00+09:00"
        options = {"expected_request_sha256": self.seal["request_sha256"],
            "expected_reservation_sha256": reservation["reservation_sha256"], **inputs, "clock": self.clock,
            **self.access(), **{name: lambda *a: True for name in ("admit_source_storage", "admit_owner_destination",
                "admit_coordinator", "admit_protected_readback", "verify_independent_receipt")}}
        options.update(overrides)
        return self.module.admit_case_retention(self.path, self.case_path, **options)

    def dispatch(self, reservation, **overrides):
        options = {**self.identity(), **gates(), "expected_reservation_sha256": reservation["reservation_sha256"],
            "admit_retention_action": lambda claim, prerequisite: True, "transport": self.transport}
        options.update(overrides)
        return self.module.dispatch_retained_case(self.path, self.case_path, **options)

    def test_default_assignment_and_each_private_gate_deny_before_creation(self):
        for name in ("private_path_verifier", "admit_store"):
            for value in (None, lambda *a, **kw: 1):
                with self.subTest(name=name, value=value):
                    result = self.reserve(**{name: value})
                    self.assertEqual(result["status"], "DENIED")
                    self.assertFalse(self.path.exists())

    def test_reservation_replays_without_clock_and_b_is_acyclic(self):
        first = self.reserve()
        before = self.path.read_bytes()
        again = self.reserve(clock=lambda: self.fail("cached C clock"))
        self.assertEqual(first, again)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(len(schema_rows(self.path, "submission_reservation")), 1)
        self.assertNotEqual(first["base_binding"]["contract_sha256"], first["reservation_sha256"])
        self.assertEqual(first["reservation"]["slot"], self.slot)
        with self.assertRaises(ValueError):
            self.reserve(assignment_ref="another-assignment")

    def test_no_retention_means_zero_intents_and_zero_public_calls(self):
        reservation = self.reserve()
        result = self.dispatch(reservation)
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(schema_rows(self.path, "submission_intents"), [])
        self.assertEqual(self.transport.calls, [])

    def test_actual_existing_verifier_commits_e_before_original_four_public_writes(self):
        before = self.case_path.read_bytes()
        reservation = self.reserve()
        admission = self.admit(reservation)
        self.assertEqual(admission["retention_request"]["coordinator_binding"], reservation["base_binding"])
        self.assertEqual(admission["evidence"]["reservation_row_sha256"], reservation["reservation_row_sha256"])
        self.assertEqual(self.reserve(clock=lambda: self.fail("cached C after E")), reservation)
        self.assertEqual(len(schema_rows(self.path, "submission_retention")), 1)
        def observed(url, method, data):
            self.assertEqual(len(schema_rows(self.path, "submission_retention")), 1)
            if method == "PUT":
                self.assertNotIn(b"FICTIONAL_OPAQUE_PROOF", data)
            return self.transport(url, method, data)
        self.clock.at = "2030-01-15T09:20:00+09:00"
        result = self.dispatch(reservation, transport=observed)
        self.assertEqual(result["status"], "NORMAL_READBACKS_COMPLETE_RECEIPTS_PENDING")
        self.assertEqual(result["github_reads"], 4)
        self.assertTrue(all(row["normal_acknowledged"] for row in result["models"]))
        self.assertEqual(len(schema_rows(self.path, "submission_intents")), 4)
        self.assertEqual(self.case_path.read_bytes(), before)
        self.assertFalse(result["full_private_payload_retention_verified"])
        self.assertFalse(result["global_exactly_once_verified"])
        for key in self.module.ROW_FIELDS:
            self.assertEqual(result[key], admission[key])

    def test_new_profile_labels_claims_and_recorded_gate_are_explicit(self):
        reservation = self.reserve()
        self.admit(reservation)
        claims = []
        def action(claim, prerequisite):
            claims.append(claim)
            self.assertEqual(prerequisite["reservation"], reservation["reservation"])
            return True
        result = self.dispatch(reservation, admit_retention_action=action)
        self.assertEqual(result["scope"], "LOCAL_CONTRACT_CALLBACK_ATTESTED")
        self.assertEqual(result["schema"], "RACE_AI_PERMISSIONED_SUBMISSION_RESULT_V2")
        self.assertTrue(claims)
        self.assertTrue(all(c["schema"] == "RACE_AI_PERMISSIONED_SUBMISSION_CLAIM_V2" for c in claims))
        for _, text, _ in schema_rows(self.path, "submission_intents"):
            self.assertIs(json.loads(text)["gates"]["retention"], True)

    def test_each_missing_retention_gate_or_partial_wire_creates_no_e_or_intent(self):
        reservation = self.reserve()
        supplied = self.evidence_inputs(reservation)
        for name in ("admit_source_storage", "admit_owner_destination", "admit_coordinator",
                     "admit_protected_readback", "verify_independent_receipt"):
            with self.subTest(name=name):
                self.admit(reservation, supplied, **{name: None})
                self.assertEqual(schema_rows(self.path, "submission_retention"), [])
        with self.assertRaises(ValueError):
            self.admit(reservation, {**supplied, "readback_bytes": supplied["readback_bytes"][:-1]})
        self.assertEqual(schema_rows(self.path, "submission_intents"), [])

    def test_e_exact_cache_never_calls_clock_or_renewal_and_changed_proof_refuses(self):
        reservation = self.reserve()
        inputs = self.evidence_inputs(reservation)
        first = self.admit(reservation, inputs)
        before = self.path.read_bytes()
        def forbidden(*a, **kw):
            self.fail("historical renewal")
        again = self.admit(reservation, inputs, clock=forbidden,
            **dict.fromkeys(("admit_source_storage", "admit_owner_destination", "admit_coordinator",
                            "admit_protected_readback", "verify_independent_receipt"), forbidden))
        self.assertEqual(first, again)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.admit(reservation, {**inputs, "receipt_proof": b"changed"}, clock=forbidden)

    def test_missing_action_denies_before_intent_but_preput_denial_keeps_barrier(self):
        reservation = self.reserve()
        self.admit(reservation)
        self.dispatch(reservation, admit_retention_action=None)
        self.assertEqual(schema_rows(self.path, "submission_intents"), [])
        result = self.dispatch(reservation, admit_retention_action=lambda claim, pre: claim["phase"] != "PRE_PUT")
        self.assertTrue(result["dispatch_barrier"])
        self.assertEqual(len(schema_rows(self.path, "submission_intents")), 1)
        self.assertEqual(self.transport.calls, [])

    def test_explicit_new_recovery_never_adopts_legacy_or_unknown_commit(self):
        reservation = self.reserve()
        self.admit(reservation)
        self.transport.fail = "PUT"
        self.dispatch(reservation)
        from race_ai.permissioned_case_submission import recover_submission_attempts
        inputs = {**self.identity(), **self.access(), "github_fetch": lambda url: self.fail("unknown commit read")}
        with self.assertRaises(ValueError):
            recover_submission_attempts(self.path, self.case_path, **inputs)
        result = recover_submission_attempts(self.path, self.case_path, **inputs,
            submission_contract="RETAINED_V2", expected_reservation_sha256=reservation["reservation_sha256"])
        self.assertTrue(result["dispatch_barrier"])
        self.assertEqual(result["github_reads"], 0)

    def test_disappeared_retained_store_is_never_recreated_or_written(self):
        reservation = self.reserve()
        self.admit(reservation)
        def store(path, claim, *, stage):
            if stage == "PRE_OPEN":
                path.unlink()
            return True
        try:
            self.dispatch(reservation, admit_store=store)
        except ValueError:
            pass
        self.assertFalse(self.path.exists())
        self.assertEqual(self.transport.calls, [])

    def alter(self, table, transform):
        with closing(sqlite3.connect(self.path)) as db:
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (table + "_no_update",)).fetchone()[0]
            db.execute("DROP TRIGGER " + table + "_no_update")
            transform(db)
            db.execute(trigger)
            db.commit()

    def test_full_assignment_and_slot_strict_types_are_bound(self):
        seen = []
        def store(path, c, **kw):
            seen.append(deepcopy(c))
            return c["slot"] == self.slot and c["assignment_ref"] == "fictional-sole-store-assignment"
        reserved = self.reserve(admit_store=store)
        self.assertTrue(seen)
        self.assertTrue(all(c == reserved["reservation"] for c in seen))
        for key, value in (("race_revision", True), ("race_revision", 1.0), ("race_revision", 0),
                           ("race_id", "another-source"), ("model_ids", list(reversed(MODELS)))):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.reserve(slot={**self.slot, key: value})

    def test_rehashed_semantic_c_and_e_forgery_stays_denied(self):
        reservation = self.reserve()
        self.admit(reservation)
        saved = self.path.read_bytes()
        for table, field, value, schema, key in (
            ("submission_reservation", "wire_byte_count", True, self.module.C_ROW, "reservation"),
            ("submission_retention", "readback_byte_count", True, self.module.E_ROW, "evidence"),
            ("submission_retention", "admitted_at", "2030-01-15T09:16:00+09:00", self.module.E_ROW, "evidence"),
            ("submission_reservation", "commit_guard_at", "2030-01-15T00:15:00+00:00", self.module.C_ROW, None),
            ("submission_retention", "commit_guard_at", "2030-01-15T00:18:00+00:00", self.module.E_ROW, None)):
            self.path.write_bytes(saved)
            def tamper(db):
                obj = json.loads(db.execute("SELECT json FROM " + table).fetchone()[0])
                (obj[key] if key else obj)[field] = value
                db.execute("UPDATE " + table + " SET json=?,sha256=?", (retention._raw(obj).decode(), self.module._hash(schema, obj)))
            self.alter(table, tamper)
            with self.subTest(table=table, field=field), self.assertRaises(ValueError):
                self.dispatch(reservation)
            self.assertEqual(self.transport.calls, [])

    def test_large_sqlite_proof_is_rejected_before_materializing(self):
        reservation = self.reserve()
        self.admit(reservation)
        self.alter("submission_retention", lambda db: db.execute("UPDATE submission_retention SET proof=zeroblob(16777216)"))
        tracemalloc.start()
        try:
            with self.assertRaises(ValueError):
                self.reserve()
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        # Actual unchanged case decoding peaks near 4.8 MiB on this fixture;
        # fetching the forbidden 16 MiB proof would exceed this bounded margin.
        self.assertLess(peak, 8 * 1024 * 1024)

    def test_malformed_sqlite_text_is_sanitized(self):
        reservation = self.reserve()
        marker = b'FICTIONAL_PRIVATE_RACE33_TEXT_\xff'
        self.alter("submission_reservation", lambda db: db.execute("UPDATE submission_reservation SET json=CAST(? AS TEXT)", (marker,)))
        try:
            self.dispatch(reservation)
        except ValueError as error:
            self.assertNotIn("FICTIONAL_PRIVATE_RACE33_TEXT", "".join(traceback.format_exception(error)))
        else:
            self.fail("invalid private checkpoint accepted")

    def test_chronology_and_slow_last_gate_never_commit_e(self):
        reservation = self.reserve()
        supplied = self.evidence_inputs(reservation)
        bad = deepcopy(supplied)
        bad["receipt_claims"]["committed_at"] = "2030-01-15T09:15:00+09:00"
        with self.assertRaises(ValueError):
            self.admit(reservation, bad)
        def last(*args):
            self.clock.at = LATE
            return True
        with self.assertRaises(ValueError):
            self.admit(reservation, supplied, verify_independent_receipt=last)
        self.assertEqual(schema_rows(self.path, "submission_retention"), [])
        self.assertEqual(schema_rows(self.path, "submission_intents"), [])

    def test_mutating_action_and_callback_rollbacks_do_not_create_intent(self):
        reservation = self.reserve()
        self.admit(reservation)
        def mutate(claim, prerequisite):
            prerequisite["reservation"]["slot"]["race_revision"] = 2
            return True
        self.dispatch(reservation, admit_retention_action=mutate)
        self.assertEqual(schema_rows(self.path, "submission_intents"), [])
        def reverse(claim, prerequisite):
            self.clock.at = "2030-01-15T09:17:00+09:00"
            return True
        self.dispatch(reservation, admit_retention_action=reverse)
        self.assertEqual(schema_rows(self.path, "submission_intents"), [])

    def test_precommit_deadline_checks_after_c_and_e_insert(self):
        def last(path, c, *, stage):
            if stage == "PRE_COMMIT":
                self.clock.at = LATE
            return True
        with self.assertRaises(ValueError):
            self.reserve(admit_store=last)
        self.assertEqual(schema_rows(self.path, "submission_reservation"), [])
        self.path.unlink()
        self.clock.at = "2030-01-15T09:16:00+09:00"
        reservation = self.reserve()
        with self.assertRaises(ValueError):
            self.admit(reservation, admit_store=last)
        self.assertEqual(schema_rows(self.path, "submission_retention"), [])

    def test_receipt_cannot_predate_post_callback_reservation_guard(self):
        def slow(path, c, *, stage):
            if stage == "PRE_COMMIT":
                self.clock.at = "2030-01-15T09:20:00+09:00"
            return True
        reservation = self.reserve(admit_store=slow)
        inputs = self.evidence_inputs(reservation)
        with self.assertRaises(ValueError):
            self.admit(reservation, inputs, clock=Clock("2030-01-15T09:21:00+09:00"))
        self.assertEqual(schema_rows(self.path, "submission_retention"), [])

    def test_restart_cannot_rollback_post_callback_admission_guard(self):
        reservation = self.reserve()
        def slow(path, c, *, stage):
            if stage == "PRE_COMMIT":
                self.clock.at = "2030-01-15T09:21:00+09:00"
            return True
        self.admit(reservation, admit_store=slow)
        self.clock.at = "2030-01-15T09:20:00+09:00"
        result = self.dispatch(reservation)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(schema_rows(self.path, "submission_intents"), [])
        self.assertEqual(result["status"], "DENIED")

    def child(self, mode, config, marker):
        config_path = Path(self.temp.name) / (mode + ".json")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        command = [sys.executable, "-B", "-X", "utf8", "-c",
            "from tests.test_retained_case_submission import worker; import sys; worker(*sys.argv[1:])",
            mode, str(config_path), str(marker)]
        return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def child_config(self, reservation=None):
        return {"attempt_path": str(self.path), "case_path": str(self.case_path),
            "expected_request_sha256": self.seal["request_sha256"], "slot": self.slot,
            "destination": self.destination, "retention_policy": self.policy,
            "reservation_sha256": reservation["reservation_sha256"] if reservation else None,
            "inputs": {k: v for k, v in self.evidence_inputs(reservation).items() if k not in ("readback_bytes", "receipt_proof")} if reservation else None}

    def test_real_crash_before_after_c_and_e_commit(self):
        for phase in ("C", "E"):
            for edge in ("before", "after"):
                with self.subTest(phase=phase, edge=edge):
                    self.path = Path(self.temp.name) / (phase + edge + ".sqlite")
                    self.clock.at = "2030-01-15T09:16:00+09:00"
                    reservation = self.reserve() if phase == "E" else None
                    process = self.child(phase + edge, self.child_config(reservation), Path(self.temp.name) / "unused")
                    out, err = process.communicate(timeout=30)
                    self.assertEqual(process.returncode, 73, err.decode())
                    table = "submission_reservation" if phase == "C" else "submission_retention"
                    self.assertEqual(len(schema_rows(self.path, table)), int(edge == "after"))
                    self.clock.at = "2030-01-15T09:16:00+09:00"
                    c = self.reserve()
                    if phase == "E":
                        self.admit(c)
                    self.assertEqual(len(schema_rows(self.path, "submission_reservation")), 1)
                    self.assertEqual(schema_rows(self.path, "submission_intents"), [])

    def test_two_process_reservation_overlaps_inside_transaction(self):
        marker = Path(self.temp.name) / "overlap"
        first = self.child("hold", self.child_config(), marker)
        self.addCleanup(lambda: first.poll() is None and first.kill())
        deadline = time.monotonic() + 15
        while not Path(str(marker) + ".holding").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(Path(str(marker) + ".holding").exists())
        second = self.child("overlap", self.child_config(), marker)
        self.addCleanup(lambda: second.poll() is None and second.kill())
        while not Path(str(marker) + ".second").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(Path(str(marker) + ".second").exists())
        self.assertIsNone(second.poll())
        Path(str(marker) + ".release").touch()
        a, ea = first.communicate(timeout=30)
        b, eb = second.communicate(timeout=30)
        self.assertEqual(first.returncode, 0, ea.decode())
        self.assertEqual(second.returncode, 0, eb.decode())
        self.assertEqual(a, b)
        self.assertEqual(len(schema_rows(self.path, "submission_reservation")), 1)


def worker(mode, config_path, marker):
    from race_ai import retained_case_submission as module
    from race_ai import permissioned_case_submission as core
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    connect = sqlite3.connect
    class Fault(sqlite3.Connection):
        def execute(connection, sql, *args):
            if mode == "overlap" and sql == "BEGIN IMMEDIATE":
                Path(marker + ".second").touch()
            if sql == "COMMIT" and mode in ("Cbefore", "Ebefore"):
                os._exit(73)
            result = super().execute(sql, *args)
            if sql == "COMMIT" and mode in ("Cafter", "Eafter"):
                os._exit(73)
            return result
    def factory(database, *a, **kw):
        if str(database) == config["attempt_path"] or str(database).startswith(Path(config["attempt_path"]).as_uri() + "?mode=rw"):
            kw["factory"] = Fault
        return connect(database, *a, **kw)
    def store(path, c, *, stage):
        if mode == "hold" and stage == "PRE_COMMIT":
            Path(marker + ".holding").touch()
            deadline = time.monotonic() + 20
            while not Path(marker + ".release").exists() and time.monotonic() < deadline:
                time.sleep(.01)
        return True
    access = {"private_path_verifier": lambda *a, **kw: True, "admit_store": store}
    with patch.object(core.sqlite3, "connect", side_effect=factory), patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
        if mode.startswith("E"):
            loaded = load_case(config["case_path"], expected_request_sha256=config["expected_request_sha256"], private_path_verifier=access["private_path_verifier"])
            result = module.admit_case_retention(config["attempt_path"], config["case_path"], expected_request_sha256=config["expected_request_sha256"],
                expected_reservation_sha256=config["reservation_sha256"], **config["inputs"], readback_bytes=loaded["wire"], receipt_proof=b"FICTIONAL_OPAQUE_PROOF",
                clock=Clock("2030-01-15T09:19:00+09:00"), **access,
                **dict.fromkeys(("admit_source_storage", "admit_owner_destination", "admit_coordinator", "admit_protected_readback", "verify_independent_receipt"), lambda *a: True))
        else:
            result = module.reserve_retained_case(config["attempt_path"], config["case_path"], expected_request_sha256=config["expected_request_sha256"],
                expected_branch=BRANCH, submission_source_sha40=PIN, slot=config["slot"], assignment_ref="fictional-sole-store-assignment",
                destination=config["destination"], retention_policy=config["retention_policy"], clock=Clock("2030-01-15T09:16:00+09:00"), **access)
        print(result["reservation_sha256"])


if __name__ == "__main__":
    unittest.main()
