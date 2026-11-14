"""Count-only source-free readiness for REAL saved BOAT forecast comparison.

Caller first authenticates the existing AES saved-view. This module cannot
declare an external official source or new research features authenticated.
No provider GET, secret handling, original modification or race IDs in output.
"""
from collections import Counter
import math
import re

from . import saved_view_feed as F
from .retained_model_pdca_audit import _saved_clock, _result_context

SCHEMA = "RACE_AI_BOAT_SIX_WAY_REAL_READINESS_V1"
RESEARCH = "RACE_AI_BOAT_SIX_WAY_INTERACTIONS_V1"
GRADE = "RACE_AI_BOAT_GRADE_TRANSITION_RESEARCH_V1"
TICKET = re.compile(r"[1-6]-[1-6]-[1-6]\Z")


def _full_120(value):
    if not isinstance(value, list) or len(value) != 120:
        return False
    seen, total = set(), 0.0
    for entry in value:
        if not isinstance(entry, dict):
            return False
        ticket, score = entry.get("ticket"), entry.get("score")
        if (not isinstance(ticket, str) or not TICKET.fullmatch(ticket) or
                len(set(ticket.split("-"))) != 3 or ticket in seen or
                type(score) not in (float, int) or not math.isfinite(score) or score <= 0):
            return False
        seen.add(ticket)
        total += score
    return len(seen) == 120 and abs(total - 1) <= 1e-7


def scan_views(views, *, aes_saved_view_authenticated):
    if aes_saved_view_authenticated is not True or not isinstance(views, list):
        raise ValueError("SIX_WAY_READINESS_AUTHENTICATED_VIEW_REQUIRED")
    if len(views) > 64:
        raise ValueError("SIX_WAY_READINESS_VIEW_COUNT_BOUND")
    count = Counter()
    reasons = Counter()
    seen = set()
    for view in views:
        if not isinstance(view, dict) or view.get("dataset_status") != "REAL_REPORTED":
            raise ValueError("SIX_WAY_READINESS_REAL_SAVED_VIEW_REQUIRED")
        # Validate original identities but never disclose SHA or original bytes.
        F.forecast_anchor(view)
        for row in view.get("records", []):
            if row.get("sport") != "boat":
                continue
            race = row.get("race_id")
            if not isinstance(race, str) or race in seen:
                raise ValueError("SIX_WAY_READINESS_DUPLICATE_RACE_OR_ID")
            seen.add(race)
            count["distinct_real_saved_races"] += 1
            try:
                state, _, _ = _result_context(row)
            except (KeyError, ValueError, TypeError):
                state = "HOLD_RESULT_FORMAT"
            if state == "FINAL":
                count["official_result_receipt_formally_matched"] += 1
            candidates = ([row["prediction"]] if row.get("prediction") else []) + list(row.get("comparison_predictions") or [])
            p1 = [p for p in candidates if isinstance(p, dict) and p.get("stage") == "P1"]
            if not p1:
                reasons["NO_SAVED_P1"] += 1
                continue
            count["races_with_saved_p1"] += 1
            timed = []
            for p in p1:
                try:
                    _saved_clock(p, row)
                    timed.append(p)
                except (KeyError, ValueError, TypeError):
                    pass
            if not timed:
                reasons["NO_VERIFIABLE_PRE_CUTOFF_P1_CLOCK"] += 1
                continue
            count["races_with_receipt_timed_p1"] += 1
            vectors = [p for p in timed if _full_120(p.get("full_120"))]
            if not vectors:
                reasons["NO_COMPLETE_SAVED_120_PROBABILITY_VECTOR"] += 1
                continue
            count["races_with_saved_120_vector"] += 1
            if state != "FINAL":
                reasons["OFFICIAL_RESULT_NOT_FORMALLY_SETTLED"] += 1
                continue
            valid_context = [p for p in vectors if isinstance(p.get("six_way_context"), dict)
                             and p["six_way_context"].get("schema") == RESEARCH]
            if not valid_context:
                reasons["NO_PRE_CUTOFF_TILT_ENTRY_QUALIFYING_CONTEXT"] += 1
                continue
            count["races_with_declared_tactical_context"] += 1
            valid_grade = [p for p in valid_context if isinstance(p.get("grade_transition"), dict)
                           and p["grade_transition"].get("schema") == GRADE]
            if not valid_grade:
                reasons["NO_PRE_CUTOFF_GRADE_HISTORY_FOR_ALL_SIX"] += 1
                continue
            count["races_with_declared_grade_context"] += 1
            reasons["REQUIRES_INDEPENDENT_FEATURE_AND_SOURCE_READBACK"] += 1
    return {
        "schema": SCHEMA,
        "scope": "AES_SAVED_VIEW_COUNT_ONLY_NO_NEW_COLLECTION",
        "counted_races": count["distinct_real_saved_races"],
        "official_result_receipt_formally_matched": count["official_result_receipt_formally_matched"],
        "races_with_saved_p1": count["races_with_saved_p1"],
        "races_with_receipt_timed_p1": count["races_with_receipt_timed_p1"],
        "races_with_saved_120_vector": count["races_with_saved_120_vector"],
        "races_with_declared_tactical_context": count["races_with_declared_tactical_context"],
        "races_with_declared_grade_context": count["races_with_declared_grade_context"],
        "reason_counts": dict(sorted(reasons.items())),
        "actual_three_way_120_results_scored": 0,
        "authenticated_six_way_features_proven": False,
        "new_provider_requests": 0,
        "originals_modified": False,
        "production_changed": False,
        "actual_purchases": False,
    }
