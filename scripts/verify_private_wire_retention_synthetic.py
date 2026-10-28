"""Pure retention contract over one authored original case, without cloud I/O.

Source/owner/coordinator/readback/receipt admissions are fictional. Matching
bytes and admitted fixture proofs never establish actual protected retention.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def digest(domain, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(domain.encode("ascii") + b"\0" + raw).hexdigest()


def main():
    if not __debug__:
        raise RuntimeError("Verification requires enabled assertions")
    sys.path.insert(0, str(ROOT))
    from scripts.verify_offline_model_run_synthetic import check_reference
    check_reference()
    from tests.test_permissioned_model_case import fixture, authorities
    from tests.test_offline_model_run import Clock, LATE
    from race_ai.permissioned_model_case import prepare_case, load_case
    from race_ai.private_wire_retention import prepare_retention_handoff, verify_retention_evidence, PrivateRetentionError

    request, raw, policy = fixture()
    clock = Clock()
    private = lambda path, **kwargs: True  # Fictional ACL decision only.
    with tempfile.TemporaryDirectory(prefix="race-ai-fictional-retention-") as directory:
        case = Path(directory) / "case.sqlite"
        prepared = prepare_case(case, request, raw, policy, clock=clock, **authorities(request))
        assert prepared["status"] == "PREPARED_NOT_EXTERNAL_FROZEN"
        expected = prepared["request_sha256"]
        loaded = load_case(case, expected_request_sha256=expected, private_path_verifier=private)
        original_bytes = case.read_bytes()
        destination = {"destination_ref": "fictional-private-object-store", "owner_scope_ref": "fictional-owner",
                       "adapter_contract_sha256": "a" * 64, "max_wire_bytes": 4 * 1024 * 1024}
        retention = {"policy_ref": "fictional-horizon-grant", "retain_until": "2030-01-16T11:00:00+09:00",
                     "protection_policy_sha256": "b" * 64, "immutability_policy_sha256": "c" * 64}
        binding = {"schema": "RACE_AI_RETENTION_PRE_PUBLIC_BASE_BINDING_V1", "scope": "PRE_PUBLIC_BASE_ONLY",
                   "coordinator_ref": "fictional-prospective-coordinator", "contract_sha256": "d" * 64,
                   "case_request_sha256": expected, "wire_sha256": loaded["wire_sha256"],
                   "ordered_plans_sha256": digest("RACE_AI_RETENTION_ORIGINAL_PLANS_V1", loaded["plans"]),
                   "destination_sha256": digest("RACE_AI_RETENTION_DESTINATION_V1", destination)}
        binding["base_binding_sha256"] = digest(binding["schema"], binding)
        args = {"expected_case_request_sha256": expected, "destination": destination,
                "retention_policy": retention, "coordinator_binding": binding, "clock": clock,
                "private_path_verifier": private}
        denied = prepare_retention_handoff(case, **args)
        assert denied["status"] == "RETENTION_UNVERIFIED_DO_NOT_WRITE"
        assert "wire" not in denied and "request" not in denied
        calls = {name: [] for name in ("source", "owner", "coordinator", "readback", "receipt")}
        def source_gate(claim, snapshot):
            calls["source"].append((deepcopy(claim), deepcopy(snapshot)))
            return snapshot == loaded["delivery"]["snapshot"]
        def owner_gate(claim):
            calls["owner"].append(deepcopy(claim))
            return claim["destination"] == destination
        def coordinator_gate(claim, actual):
            calls["coordinator"].append((deepcopy(claim), deepcopy(actual)))
            return actual == binding and claim["coordinator_binding"] == binding
        gates = {"admit_source_storage": source_gate, "admit_owner_destination": owner_gate,
                 "admit_coordinator": coordinator_gate}
        def forbidden(*args, **kwargs):
            raise AssertionError("retention path attempted inference or a writer")
        with patch("race_ai.permissioned_source_delivery.deliver", side_effect=forbidden), \
             patch("race_ai.append_only_freeze_writer.submit_anchor", side_effect=forbidden):
            before_admissions = {key: len(calls[key]) for key in ("source", "owner", "coordinator")}
            handoff = prepare_retention_handoff(case, **args, **gates)
            assert all(len(calls[key]) > before_admissions[key] for key in before_admissions)
            clock.at = "2030-01-15T09:15:01+09:00"
            before_admissions = {key: len(calls[key]) for key in before_admissions}
            repeat = prepare_retention_handoff(case, **args, **gates)
            assert all(len(calls[key]) > before_admissions[key] for key in before_admissions)
            assert handoff["status"] == "NOT_SENT_NO_WRITE_AUTHORITY"
            assert repeat["request_sha256"] == handoff["request_sha256"]
            assert handoff["wire"] == repeat["wire"] == loaded["wire"]
            assert handoff["request"]["wire_sha256"] == hashlib.sha256(loaded["wire"]).hexdigest()
            assert len(handoff["request"]["models"]) == 4
            assert all(item == (handoff["request"], loaded["delivery"]["snapshot"]) for item in calls["source"])
            assert all(item == handoff["request"] for item in calls["owner"])
            assert all(item == (handoff["request"], binding) for item in calls["coordinator"])
            clock.at = LATE
            readback = {"schema": "RACE_AI_PRIVATE_WIRE_READBACK_V1", "request_sha256": handoff["request_sha256"],
                        "destination_ref": destination["destination_ref"], "object_ref": "fictional-original-object",
                        "object_version": "fictional-immutable-version", "wire_sha256": loaded["wire_sha256"],
                        "wire_byte_count": len(loaded["wire"]), "observed_at": LATE,
                        "reader_attestation_ref": "fictional-protected-reader"}
            receipt = {"schema": "RACE_AI_PRIVATE_WIRE_RETENTION_RECEIPT_V1", "request_sha256": handoff["request_sha256"],
                       "destination_ref": destination["destination_ref"], "object_ref": readback["object_ref"],
                       "object_version": readback["object_version"], "wire_sha256": loaded["wire_sha256"],
                       "wire_byte_count": len(loaded["wire"]), "committed_at": "2030-01-15T09:16:00+09:00",
                       "retained_until": retention["retain_until"], "protection_policy_sha256": retention["protection_policy_sha256"],
                       "immutability_policy_sha256": retention["immutability_policy_sha256"], "issuer_ref": "fictional-issuer"}
            proof = b"FICTIONAL_PROOF_NOT_REAL_AUTHORITY"
            evidence = {"expected_case_request_sha256": expected, "expected_retention_request_sha256": handoff["request_sha256"],
                        "readback_bytes": loaded["wire"], "readback_descriptor": readback, "receipt_claims": receipt,
                        "receipt_proof": proof, "clock": clock, "private_path_verifier": private}
            unverified = verify_retention_evidence(case, handoff["request"], **evidence)
            assert unverified["status"] == "WHOLE_BYTES_MATCH_UNVERIFIED"
            assert not unverified["protected_readback_admitted_by_callback"] and not unverified["receipt_admitted_by_callback"]
            assert not calls["readback"] and not calls["receipt"]
            def readback_gate(claim, actual):
                calls["readback"].append((deepcopy(claim), deepcopy(actual)))
                return actual == readback
            def receipt_gate(claim, actual, actual_proof):
                calls["receipt"].append((deepcopy(claim), deepcopy(actual), actual_proof))
                return actual == receipt and actual_proof == proof
            checks = {"admit_protected_readback": readback_gate, "verify_independent_receipt": receipt_gate}
            for missing, counter, flag in (("admit_protected_readback", "readback", "protected_readback_admitted_by_callback"),
                                           ("verify_independent_receipt", "receipt", "receipt_admitted_by_callback")):
                before = len(calls[counter])
                partial = verify_retention_evidence(case, handoff["request"], **evidence,
                    **{key: value for key, value in checks.items() if key != missing})
                assert partial["status"] != "ADMITTED_BY_CALLBACK" and partial[flag] is False
                assert len(calls[counter]) == before
                refused = verify_retention_evidence(case, handoff["request"], **evidence,
                    **{key: (lambda *args: False) if key == missing else value for key, value in checks.items()})
                assert refused["status"] != "ADMITTED_BY_CALLBACK" and refused[flag] is False
            before_readback, before_receipt = len(calls["readback"]), len(calls["receipt"])
            admitted = verify_retention_evidence(case, handoff["request"], **evidence, **checks)
            assert admitted["status"] == "ADMITTED_BY_CALLBACK" and admitted["whole_wire_equal"]
            assert admitted["protected_readback_admitted_by_callback"] and admitted["receipt_admitted_by_callback"]
            assert len(calls["readback"]) > before_readback and len(calls["receipt"]) > before_receipt
            assert all(item == (handoff["request"], readback) for item in calls["readback"][before_readback:])
            assert all(item == (handoff["request"], receipt, proof) for item in calls["receipt"][before_receipt:])
            tampered = deepcopy(evidence)
            tampered["readback_bytes"] = bytes([loaded["wire"][0] ^ 1]) + loaded["wire"][1:]
            before = (len(calls["readback"]), len(calls["receipt"]))
            try:
                wrong = verify_retention_evidence(case, handoff["request"], **tampered, **checks)
            except PrivateRetentionError:
                pass
            else:
                assert not wrong["whole_wire_equal"] and wrong["status"] != "ADMITTED_BY_CALLBACK"
            assert before == (len(calls["readback"]), len(calls["receipt"]))
        assert case.read_bytes() == original_bytes
        for result in (denied, handoff, repeat, unverified, admitted):
            assert not result["write_authority"]
            for key in ("full_private_payload_retention_verified", "source_rights_verified", "producer_execution_authenticated",
                        "coordinator_authenticated", "global_exactly_once_verified", "cloned_store_protection_verified",
                        "official_prediction", "eligible_for_hit_at_8"):
                assert result[key] is False
        print(json.dumps({"scope": "FICTIONAL_PRIVATE_WHOLE_WIRE_CONTRACT_ONLY", "original_cases": 1, "models": 4,
            "deterministic_request_preserved": True, "original_typed_wire_preserved": True,
            "mismatched_byte_rejected": True, "separate_readback_receipt_callbacks_exercised": True,
            "current_public_dispatch_retention_prerequisite_enforced": False,
            "source_requests": 0, "external_writes": 0, "protected_cloud_retention_verified": False,
            "real_forecasts": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    def no_network(*args, **kwargs):
        raise AssertionError("network forbidden")
    with patch("socket.create_connection", side_effect=no_network), \
         patch("socket.socket.connect", side_effect=no_network), \
         patch("urllib.request.OpenerDirector.open", side_effect=no_network):
        raise SystemExit(main())
