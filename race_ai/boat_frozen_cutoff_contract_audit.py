"""Counts-only comparison of 2026-11-07 immutable result contract vs later observations.

The frozen policy and stored owner rows are read-only. No source HTTP, picks,
personal data, owner capability or raw digest is returned to logs. Categories
only describe the earlier parser's first rejection guard and known next gates.
"""
from datetime import date
from math import isfinite
import re

SCHEMA = "RACE_AI_FROZEN_CUTOFF_CONTRACT_COUNTS_V1"
OLD = "RAW_OFFICIAL_RESULT_PER_ORIGINAL_CUTOFF"
NEW = "RAW_OFFICIAL_SP_RESULT_PER_SAVED_MODEL_CUTOFF"


def _is_sha(v):
    return isinstance(v, str) and re.fullmatch("[0-9a-f]{64}", v) is not None


def _old_guard(row, result, proof):
    if not isinstance(proof, dict):
        return ("PROOF_NOT_OBJECT",)
    reasons = []
    if row.get("sport") != "boat" or not row.get("private_cycle_view", True) or result.get("status") != "final":
        reasons.append("RESULT_CONTEXT_INVALID")
    if proof.get("basis") != OLD:
        reasons.append("PROOF_BASIS_NOT_REGISTERED")
    if proof.get("formal_eligible") is not False:
        reasons.append("FORMAL_FLAG_NOT_FALSE")
    if proof.get("roster_identity_verified") is not True:
        reasons.append("ROSTER_IDENTITY_NOT_VERIFIED")
    if proof.get("all_originals_saved_before_both") is not True:
        reasons.append("SAVE_BEFORE_CUTOFF_NOT_VERIFIED")
    if not _is_sha(proof.get("source_sha256")) or proof.get("source_sha256") != result.get("source_sha256"):
        reasons.append("RESULT_SOURCE_HASH_NOT_BOUND")
    offset = proof.get("maximum_offset_seconds")
    if type(offset) not in (int, float) or not isfinite(offset) or not (0 <= offset <= 60):
        reasons.append("REGISTERED_OFFSET_OUT_OF_RANGE")
    return tuple(reasons)


def summarize(view, *, expected_day="2026-11-07"):
    if date.fromisoformat(expected_day).isoformat() != expected_day:
        raise ValueError("FROZEN_GATE_DAY_INVALID")
    if not isinstance(view, dict) or not isinstance(view.get("records"), list):
        raise ValueError("FROZEN_GATE_VIEW_INVALID")
    counters = dict(
        saved_day_races=0,final_results=0,final_with_proof=0,
        registered_basis=0,sp_per_model_basis=0,unknown_basis=0,
        legacy_first_guard_passed=0,legacy_first_guard_failed=0,
        first_guard_basis_mismatch=0,first_guard_offset_out_of_range=0,
        first_guard_other_failure=0,registered_next_gate_multi_schedule=0,
        reference_results_without_cutoff_proof=0)
    for row in view["records"]:
        if row.get("sport") != "boat" or row.get("event_date_jst") != expected_day:
            continue
        counters["saved_day_races"] += 1
        result = row.get("result") or {}
        if result.get("status") != "final":
            continue
        counters["final_results"] += 1
        proof = result.get("cutoff_reconciliation")
        if proof is None:
            counters["reference_results_without_cutoff_proof"] += 1
            continue
        counters["final_with_proof"] += 1
        basis = proof.get("basis") if isinstance(proof, dict) else None
        if basis == OLD:
            counters["registered_basis"] += 1
        elif basis == NEW:
            counters["sp_per_model_basis"] += 1
        else:
            counters["unknown_basis"] += 1
        fails = _old_guard(row, result, proof)
        if fails:
            counters["legacy_first_guard_failed"] += 1
            if "PROOF_BASIS_NOT_REGISTERED" in fails:
                counters["first_guard_basis_mismatch"] += 1
            if "REGISTERED_OFFSET_OUT_OF_RANGE" in fails:
                counters["first_guard_offset_out_of_range"] += 1
            if any(x not in ("PROOF_BASIS_NOT_REGISTERED","REGISTERED_OFFSET_OUT_OF_RANGE") for x in fails):
                counters["first_guard_other_failure"] += 1
        else:
            counters["legacy_first_guard_passed"] += 1
            if len(set(row.get("saved_schedule_cutoff_variants") or ())) > 1:
                counters["registered_next_gate_multi_schedule"] += 1
    if counters["saved_day_races"] > 288:
        raise ValueError("FROZEN_GATE_RACE_BOUND")
    return dict(schema=SCHEMA, day=expected_day, **counters, source_requests=0,
                immutable_policy_replaced=False, original_predictions_modified=False,
                represents_final_verdict=False)
