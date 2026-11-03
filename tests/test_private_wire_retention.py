"""One authored original checkpoint; supplied fictional retention evidence only."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
import tracemalloc
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests.test_permissioned_model_case import fixture, authorities
from tests.test_offline_model_run import Clock, AT, LATE, MODELS, canonical, sha
from race_ai.permissioned_model_case import prepare_case, load_case


def digest(schema, value):
    return sha(schema.encode("ascii") + b"\0" + canonical(value).encode())


class PrivateWireRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_dir = tempfile.TemporaryDirectory(prefix="race29-original-fictional-")
        cls.original = Path(cls.original_dir.name) / "case.sqlite"
        request, raw, policy = fixture()
        cls.seal = prepare_case(cls.original, request, raw, policy, clock=Clock(), **authorities(request))
        cls.loaded = load_case(cls.original, expected_request_sha256=cls.seal["request_sha256"],
                              private_path_verifier=authorities(request)["private_path_verifier"])

    @classmethod
    def tearDownClass(cls):
        cls.original_dir.cleanup()

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.private_wire_retention"),
                             "pure retention handoff is missing")
        self.module = importlib.import_module("race_ai.private_wire_retention")
        self.temp = tempfile.TemporaryDirectory(prefix="race29-private-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "case.sqlite"
        shutil.copyfile(self.original, self.path)
        self.clock = Clock()
        self.destination = {"destination_ref": "fictional-private-destination", "owner_scope_ref": "fictional-owner-scope",
            "adapter_contract_sha256": "a" * 64, "max_wire_bytes": 4 * 1024 * 1024}
        self.policy = {"policy_ref": "fictional-retention-policy", "retain_until": "2030-02-15T10:00:00+09:00",
            "protection_policy_sha256": "b" * 64, "immutability_policy_sha256": "c" * 64}
        self.binding = self.base()
        from race_ai import permissioned_source_delivery as source
        for target in (patch("socket.create_connection", side_effect=AssertionError("network forbidden")),
                       patch.object(source, "deliver", side_effect=AssertionError("inference forbidden"))):
            target.start()
            self.addCleanup(target.stop)

    def base(self):
        result = {"schema": "RACE_AI_RETENTION_PRE_PUBLIC_BASE_BINDING_V1", "scope": "PRE_PUBLIC_BASE_ONLY",
            "coordinator_ref": "fictional-pre-public-coordinator", "contract_sha256": "d" * 64,
            "case_request_sha256": self.seal["request_sha256"], "wire_sha256": self.loaded["wire_sha256"],
            "ordered_plans_sha256": digest("RACE_AI_RETENTION_ORIGINAL_PLANS_V1", self.loaded["plans"]),
            "destination_sha256": digest("RACE_AI_RETENTION_DESTINATION_V1", self.destination)}
        result["base_binding_sha256"] = digest(result["schema"], result)
        return result

    def gates(self):
        return {"private_path_verifier": lambda path, **kw: True,
            "admit_source_storage": lambda request, snapshot: request["source_policy_sha256"] == self.loaded["request"]["policy_record_sha256"]
                and snapshot == self.loaded["delivery"]["snapshot"],
            "admit_owner_destination": lambda request: request["destination"]["destination_ref"] == "fictional-private-destination",
            "admit_coordinator": lambda request, expected: expected == self.base() and request["coordinator_binding"] == expected}

    def prepare(self, **overrides):
        options = {"expected_case_request_sha256": self.seal["request_sha256"], "destination": self.destination,
            "retention_policy": self.policy, "coordinator_binding": self.binding, "clock": self.clock, **self.gates()}
        options.update(overrides)
        return self.module.prepare_retention_handoff(self.path, **options)

    def evidence(self, handoff):
        request = handoff["request"]
        descriptor = {"schema": "RACE_AI_PRIVATE_WIRE_READBACK_V1", "request_sha256": handoff["request_sha256"],
            "destination_ref": self.destination["destination_ref"], "object_ref": "fictional-whole-object",
            "object_version": "immutable-version-001", "wire_sha256": request["wire_sha256"],
            "wire_byte_count": request["wire_byte_count"], "observed_at": "2030-01-15T10:30:00+09:00",
            "reader_attestation_ref": "fictional-protected-readback"}
        receipt = {"schema": "RACE_AI_PRIVATE_WIRE_RETENTION_RECEIPT_V1",
            **{key: descriptor[key] for key in ("request_sha256", "destination_ref", "object_ref", "object_version", "wire_sha256", "wire_byte_count")},
            "committed_at": "2030-01-15T09:16:00+09:00", "retained_until": self.policy["retain_until"],
            "protection_policy_sha256": self.policy["protection_policy_sha256"],
            "immutability_policy_sha256": self.policy["immutability_policy_sha256"], "issuer_ref": "fictional-independent-issuer"}
        return descriptor, receipt, b"FICTIONAL_OPAQUE_PROOF_NO_REAL_ISSUER"

    def verify(self, handoff, **overrides):
        descriptor, receipt, proof = self.evidence(handoff)
        options = {"expected_case_request_sha256": self.seal["request_sha256"],
            "expected_retention_request_sha256": handoff["request_sha256"], "readback_bytes": handoff["wire"],
            "readback_descriptor": descriptor, "receipt_claims": receipt, "receipt_proof": proof,
            "clock": Clock(LATE), "private_path_verifier": self.gates()["private_path_verifier"],
            "admit_protected_readback": lambda request, record: record == descriptor,
            "verify_independent_receipt": lambda request, record, opaque: record == receipt and opaque == proof}
        options.update(overrides)
        return self.module.verify_retention_evidence(self.path, handoff["request"], **options)

    def assert_unpromoted(self, result):
        for field in ("write_authority", "full_private_payload_retention_verified", "source_rights_verified",
            "producer_execution_authenticated", "coordinator_authenticated", "global_exactly_once_verified",
            "cloned_store_protection_verified", "official_prediction", "eligible_for_hit_at_8"):
            self.assertIs(result[field], False, field)

    def test_default_and_each_missing_or_nontrue_capability_return_no_wire(self):
        options = {"expected_case_request_sha256": self.seal["request_sha256"], "destination": self.destination,
            "retention_policy": self.policy, "coordinator_binding": self.binding, "clock": self.clock}
        result = self.module.prepare_retention_handoff(self.path, **options)
        self.assertEqual(result["status"], "RETENTION_UNVERIFIED_DO_NOT_WRITE")
        for name in self.gates():
            for denied in (None, lambda *a, **kw: 1):
                with self.subTest(name=name):
                    result = self.prepare(**{name: denied})
                    self.assertNotIn("wire", result)
                    self.assertNotIn("request", result)
                    self.assert_unpromoted(result)

    def test_deterministic_handoff_preserves_whole_original_wire_four_models_and_case(self):
        before, files = self.path.read_bytes(), set(Path(self.temp.name).iterdir())
        result = self.prepare()
        self.assertEqual(result["status"], "NOT_SENT_NO_WRITE_AUTHORITY")
        self.assertEqual(result["wire"], self.loaded["wire"])
        self.assertEqual([x["model_id"] for x in result["request"]["models"]], list(MODELS))
        self.assertEqual(result["request_sha256"], digest(result["request"]["schema"], result["request"]))
        self.clock.at = "2030-01-15T09:20:00+09:00"
        again = self.prepare()
        self.assertEqual(result["request_sha256"], again["request_sha256"])
        self.assertEqual(result["request"], again["request"])
        self.assertNotEqual(result["prepared_at"], again["prepared_at"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(set(Path(self.temp.name).iterdir()), files)
        self.assert_unpromoted(result)

    def test_invalid_numeric_cap_denies_before_even_private_callback(self):
        def forbidden(*args, **kwargs):
            self.fail("callback before invalid numeric cap admission")
        for cap in (None, True, 1.0, 0, -1, 4 * 1024 * 1024 + 1):
            with self.subTest(cap=cap):
                destination = {**self.destination, "max_wire_bytes": cap}
                result = self.prepare(destination=destination, **dict.fromkeys(self.gates(), forbidden))
                self.assertEqual(result["status"], "RETENTION_UNVERIFIED_DO_NOT_WRITE")
                self.assertNotIn("wire", result)

    def test_insufficient_cap_requires_private_load_but_no_retention_admission(self):
        seen = []
        def private(path, *, stage):
            seen.append(stage)
            return True
        def forbidden(*args):
            self.fail("retention gate before capacity check")
        result = self.prepare(destination={**self.destination, "max_wire_bytes": 1}, private_path_verifier=private,
            admit_source_storage=forbidden, admit_owner_destination=forbidden, admit_coordinator=forbidden)
        self.assertTrue(seen)
        self.assertEqual(result["status"], "RETENTION_UNVERIFIED_DO_NOT_WRITE")
        self.assertNotIn("wire", result)

    def test_base_binding_is_reconstructed_from_all_original_plans_and_excludes_request(self):
        captured = []
        def coordinator(request, expected):
            captured.append(expected)
            return expected == self.base()
        result = self.prepare(admit_coordinator=coordinator)
        self.assertEqual(captured, [self.base()])
        self.assertNotIn("request_sha256", captured[0])
        for field in ("wire_sha256", "ordered_plans_sha256", "destination_sha256"):
            with self.subTest(field=field):
                wrong = deepcopy(self.binding)
                wrong[field] = "f" * 64
                wrong["base_binding_sha256"] = digest(wrong["schema"], {k: v for k, v in wrong.items() if k != "base_binding_sha256"})
                with self.assertRaises(ValueError):
                    self.prepare(coordinator_binding=wrong)
        self.assert_unpromoted(result)

    def test_missing_coordinator_and_current_public_manifest_are_not_substitutes(self):
        result = self.prepare(coordinator_binding=None)
        self.assertNotIn("wire", result)
        for wrong in ({"schema": "RACE_AI_PERMISSIONED_SUBMISSION_MANIFEST_V1"},
                      {**self.binding, "scope": "MODEL1_PUBLIC_INTENT"},
                      {**self.binding, "retention_request_sha256": "f" * 64}):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.prepare(coordinator_binding=wrong)

    def test_destination_and_source_grants_must_cover_explicit_retention_horizon(self):
        grant_end = datetime.fromisoformat("2030-01-16T10:00:00+09:00")
        def source(request, snapshot):
            return datetime.fromisoformat(request["retention_policy"]["retain_until"]) <= grant_end
        result = self.prepare(admit_source_storage=source)
        self.assertNotIn("wire", result)
        with self.assertRaises(ValueError):
            self.prepare(retention_policy={**self.policy, "retain_until": self.loaded["request"]["sales_cutoff_at"]})

    def test_closed_slow_and_reversed_prepare_clocks_never_return_actionable_bytes(self):
        self.clock.at = LATE
        result = self.prepare()
        self.assertNotIn("wire", result)
        self.clock.at = AT
        def late(request):
            self.clock.at = LATE
            return True
        result = self.prepare(admit_owner_destination=late)
        self.assertNotIn("wire", result)
        self.clock.at = AT
        def backwards(request):
            self.clock.at = "2030-01-15T09:14:59+09:00"
            return True
        with self.assertRaises(ValueError):
            self.prepare(admit_owner_destination=backwards)

    def test_late_supplied_evidence_admits_only_qualified_callback_predicates(self):
        handoff = self.prepare()
        result = self.verify(handoff)
        self.assertEqual(result["status"], "ADMITTED_BY_CALLBACK")
        self.assertIs(result["whole_wire_equal"], True)
        self.assertIs(result["protected_readback_admitted_by_callback"], True)
        self.assertIs(result["receipt_admitted_by_callback"], True)
        self.assertNotIn("wire", result)
        self.assertNotIn("receipt_proof", result)
        self.assert_unpromoted(result)

    def test_full_bytes_alone_or_missing_separate_evidence_gates_never_verify_retention(self):
        handoff = self.prepare()
        for name in ("admit_protected_readback", "verify_independent_receipt"):
            for denied in (None, lambda *a: 1):
                with self.subTest(name=name):
                    result = self.verify(handoff, **{name: denied})
                    self.assertEqual(result["status"], "WHOLE_BYTES_MATCH_UNVERIFIED")
                    self.assert_unpromoted(result)
        for name in ("readback_descriptor", "receipt_claims", "receipt_proof", "readback_bytes"):
            with self.subTest(name=name):
                result = self.verify(handoff, **{name: None})
                self.assertNotEqual(result["status"], "ADMITTED_BY_CALLBACK")
                self.assert_unpromoted(result)

    def test_partial_reencoded_mutable_or_oversized_body_and_proof_are_rejected(self):
        handoff = self.prepare()
        for body in (handoff["wire"][:-1], b'{"ordinary":"JSON"}', bytearray(handoff["wire"]), b"x" * (4 * 1024 * 1024 + 1)):
            with self.subTest(kind=type(body).__name__, length=len(body)), self.assertRaises(ValueError):
                self.verify(handoff, readback_bytes=body)
        for proof in (bytearray(b"proof"), b"x" * 65537):
            with self.subTest(kind=type(proof).__name__), self.assertRaises(ValueError):
                self.verify(handoff, receipt_proof=proof)
        result = self.verify(handoff, receipt_proof=b"not-the-independent-fixture-proof")
        self.assertFalse(result["receipt_admitted_by_callback"])

    def test_rehashed_request_cannot_replace_original_roster_policy_case_or_wire(self):
        handoff = self.prepare()
        for field in ("models", "source_policy_sha256", "case_delivery_sha256", "wire_sha256"):
            with self.subTest(field=field):
                wrong = deepcopy(handoff)
                if field == "models":
                    wrong["request"][field][0]["model_version"] = "REWRITTEN"
                else:
                    wrong["request"][field] = "f" * 64
                wrong["request_sha256"] = digest(wrong["request"]["schema"], wrong["request"])
                with self.assertRaises(ValueError):
                    self.verify(wrong)
        with self.assertRaises(ValueError):
            self.verify(handoff, expected_retention_request_sha256="f" * 64)

    def test_descriptor_receipt_identity_policy_and_retained_horizon_must_agree(self):
        handoff = self.prepare()
        descriptor, receipt, proof = self.evidence(handoff)
        for field, value in (("object_version", "other-version"), ("destination_ref", "foreign-destination"),
                ("wire_byte_count", True), ("wire_sha256", "f" * 64), ("request_sha256", "f" * 64)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(handoff, readback_descriptor={**descriptor, field: value})
        for field, value in (("immutability_policy_sha256", "f" * 64), ("protection_policy_sha256", "f" * 64),
                ("retained_until", "2030-01-16T10:00:00+09:00"), ("object_ref", "different-object")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(handoff, receipt_claims={**receipt, field: value})

    def test_independent_commit_chronology_cannot_be_fabricated_from_later_read(self):
        handoff = self.prepare()
        descriptor, receipt, proof = self.evidence(handoff)
        for at in ("2030-01-15T09:14:59+09:00", "2030-01-15T10:00:00+09:00", "2030-01-15T12:00:00+09:00"):
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.verify(handoff, receipt_claims={**receipt, "committed_at": at})
        with self.assertRaises(ValueError):
            self.verify(handoff, readback_descriptor={**descriptor, "observed_at": "2030-01-15T09:15:01+09:00"})
        with self.assertRaises(ValueError):
            self.verify(handoff, readback_descriptor={**descriptor, "observed_at": "2030-01-15T12:00:00+09:00"})

    def test_opaque_refs_exact_types_extra_keys_and_nonfinite_metadata_fail_closed(self):
        for ref in ("https://fictional.invalid", "owner@example.invalid", "../file", r"C:\private", "token?query"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.prepare(destination={**self.destination, "destination_ref": ref})
        for wrong in ({**self.policy, "unexpected": True}, {**self.policy, "retain_until": float("nan")}):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.prepare(retention_policy=wrong)

    def test_callback_mutation_is_bounded_and_private_errors_do_not_echo(self):
        huge = "x" * (8 * 1024 * 1024)
        tracemalloc.start()
        try:
            self.prepare(admit_owner_destination=lambda request: False)
            baseline = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        def mutate(request):
            request["untrusted"] = huge
            return True
        tracemalloc.start()
        try:
            try:
                result = self.prepare(admit_owner_destination=mutate)
            except ValueError:
                pass
            else:
                self.assertNotIn("wire", result)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, baseline + 1024 * 1024)
        def private(*args):
            raise RuntimeError("FICTIONAL_PRIVATE_RETENTION_KEY")
        try:
            self.prepare(admit_owner_destination=private)
        except ValueError as error:
            self.assertNotIn("FICTIONAL_PRIVATE_RETENTION_KEY", "".join(traceback.format_exception(error)))
        else:
            self.fail("private callback exception was accepted")

    def test_metadata_and_proof_limits_precede_private_lookup_or_hashing(self):
        def forbidden(*args, **kwargs):
            self.fail("private callback before resource rejection")
        for value in ("x" * (8 * 1024 * 1024), {"cycle": None}):
            if type(value) is dict:
                value["cycle"] = value
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                self.prepare(retention_policy={**self.policy, "policy_ref": value}, private_path_verifier=forbidden)
        handoff = self.prepare()
        with self.assertRaises(ValueError):
            self.verify(handoff, receipt_proof=b"x" * 65537, private_path_verifier=forbidden)

    def test_cumulative_metadata_budget_rejects_compact_repeated_strings_boundedly(self):
        policy = {**self.policy, "untrusted_padding": ["x" * 16384] * 1000}
        def forbidden(*args, **kwargs):
            self.fail("callback before cumulative metadata budget")
        tracemalloc.start()
        try:
            with patch.object(self.module, "_hash", side_effect=AssertionError("digest before metadata budget")):
                with self.assertRaises(ValueError):
                    self.prepare(retention_policy=policy, private_path_verifier=forbidden)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 512 * 1024)

    def test_verifier_gate_mutation_or_private_error_does_not_promote_evidence(self):
        handoff = self.prepare()
        for name in ("admit_protected_readback", "verify_independent_receipt"):
            with self.subTest(name=name):
                def mutate(request, *args):
                    request["wire_sha256"] = "f" * 64
                    return True
                result = self.verify(handoff, **{name: mutate})
                self.assertEqual(result["status"], "WHOLE_BYTES_MATCH_UNVERIFIED")
                self.assert_unpromoted(result)
                def private(*args):
                    raise RuntimeError("FICTIONAL_PRIVATE_RECEIPT_PROOF_KEY")
                try:
                    self.verify(handoff, **{name: private})
                except ValueError as error:
                    self.assertNotIn("FICTIONAL_PRIVATE_RECEIPT_PROOF_KEY", "".join(traceback.format_exception(error)))
                else:
                    self.fail("private verifier exception was accepted")
        self.assertEqual(handoff["request"]["wire_sha256"], self.loaded["wire_sha256"])
        self.assertEqual(handoff["wire"], self.loaded["wire"])

    def test_historical_verification_tracks_clock_after_each_separate_gate(self):
        handoff = self.prepare()
        clock = Clock(LATE)
        def readback(request, descriptor):
            clock.at = "2030-01-15T11:10:00+09:00"
            return True
        def receipt(request, claims, proof):
            clock.at = LATE
            return True
        with self.assertRaises(ValueError):
            self.verify(handoff, clock=clock, admit_protected_readback=readback, verify_independent_receipt=receipt)

    def test_dst_fold_utc_rollback_rejects_even_when_local_wall_clock_increases(self):
        handoff = self.prepare()
        zone = ZoneInfo("America/New_York")
        first = datetime(2030, 11, 3, 1, 30, tzinfo=zone, fold=1)  # 06:30 UTC
        second = datetime(2030, 11, 3, 1, 45, tzinfo=zone, fold=0)  # 05:45 UTC
        values = iter((first, second))
        with self.assertRaises(ValueError):
            self.verify(handoff, clock=lambda: next(values, second))

    def test_dst_fallback_utc_forward_accepts_even_when_local_wall_clock_decreases(self):
        handoff = self.prepare()
        zone = ZoneInfo("America/New_York")
        first = datetime(2030, 11, 3, 1, 45, tzinfo=zone, fold=0)  # 05:45 UTC
        second = datetime(2030, 11, 3, 1, 30, tzinfo=zone, fold=1)  # 06:30 UTC
        values = iter((first, second))
        result = self.verify(handoff, clock=lambda: next(values, second))
        self.assertEqual(result["status"], "ADMITTED_BY_CALLBACK")
        self.assertEqual(result["observed_at"], "2030-11-03T06:30:00+00:00")
        self.assert_unpromoted(result)

    def test_immutable_version_and_receipt_proof_semantics_require_honest_external_gates(self):
        handoff = self.prepare()
        descriptor, receipt, proof = self.evidence(handoff)
        descriptor["object_version"] = receipt["object_version"] = "latest"
        result = self.verify(handoff, readback_descriptor=descriptor, receipt_claims=receipt,
            admit_protected_readback=lambda request, value: value["object_version"] == "immutable-version-001",
            verify_independent_receipt=lambda request, claims, opaque: claims["object_version"] == "immutable-version-001")
        self.assertEqual(result["status"], "WHOLE_BYTES_MATCH_UNVERIFIED")
        self.assert_unpromoted(result)


if __name__ == "__main__":
    unittest.main()
