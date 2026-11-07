"""Assess measured private saves without claiming a user visibility receipt.

This pure assessment performs no source reads, writes, clock reads or model
calls. Its caller supplies post-commit timestamps and an assessment instant.
"""
from __future__ import annotations

from .comprehensive_four_sport_models import moment
from .purchase_window_policy import policy


def assess_delivery(cutoff_at, *, source_captured_at=None, generated_at=None,
                    saved_at=None, assessed_at=None):
    """Classify only a complete, ordered source -> generation -> saved chain.

T-15 and T-10 are inclusive product targets. Private persistence is measured
separately from independently observed user visibility, which stays unknown.
Absent or invalid evidence never becomes an on-time delivery assertion.
"""
    evidence = {"source_captured_at": source_captured_at,
                "generated_at": generated_at, "saved_at": saved_at,
                "assessed_at": assessed_at, "next_cutoff_at": cutoff_at}
    parsed = {}
    invalid = False
    for name, value in evidence.items():
        try:
            parsed[name] = moment(value) if value is not None else None
        except (TypeError, ValueError):
            parsed[name] = None
            invalid = True
    result = {name: value.isoformat() if value is not None else None
              for name, value in parsed.items()}
    result.update(state="UNKNOWN", reason=None, window_status="UNKNOWN",
                  target_open_at=None, target_due_at=None, visible_at=None,
                  readiness_evidence_independently_verified=False,
                  independent_user_visibility_time_verified=False)
    cutoff = parsed["next_cutoff_at"]
    if cutoff is not None:
        targets = policy(cutoff.isoformat())
        result["target_open_at"] = targets["first_preview_target_at"]
        result["target_due_at"] = targets["final_forecast_visible_by"]
    if invalid:
        result["reason"] = "INVALID_TIMESTAMP"
    elif cutoff is None:
        result["reason"] = "CUTOFF_NOT_AVAILABLE"
    elif parsed["saved_at"] is None:
        result.update(state="NOT_SAVED", reason="NO_SAVED_FORECAST")
    elif any(parsed[name] is None for name in
             ("source_captured_at", "generated_at", "assessed_at")):
        result["reason"] = "MISSING_TIMESTAMP_EVIDENCE"
    elif not (parsed["source_captured_at"] <= parsed["generated_at"]
              <= parsed["saved_at"] <= parsed["assessed_at"]):
        result["reason"] = "INCONSISTENT_TIMESTAMP_ORDER"
    else:
        saved = parsed["saved_at"]
        result["state"] = "SAVED"
        if saved < moment(result["target_open_at"]):
            result.update(window_status="EARLY", reason="SAVED_BEFORE_TARGET_WINDOW")
        elif saved <= moment(result["target_due_at"]):
            result.update(window_status="ON_TIME", reason="SAVED_IN_TARGET_WINDOW")
        else:
            result.update(window_status="LATE", reason=(
                "SAVED_AFTER_CUTOFF" if saved >= cutoff else "SAVED_AFTER_TARGET_DUE"))
    return result
