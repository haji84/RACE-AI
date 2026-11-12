"""Read-only bridge: retained BOAT K history + authenticated P1 inputs to the
existing 44-factor / 120-ticket research overlay.

No source fetching, weight fitting, official forecast, private-state publication,
or interpolation of missing observations occurs here. In particular, a race's
winning method is NOT proof of which losing racer was directly attacked.
"""
from __future__ import annotations

import math
from .boat_racer_tendencies import _ts
from .boat_six_course_tactical_features import analyze_racer, matchup_features
from .boat_dynamic_tactical_context import (
    entry_response_profile, p1_tilt_entry_context,
    qualifying_standings, six_way_research_context,
)

SCHEMA = "RACE_AI_BOAT_44_P1_SOURCE_BRIDGE_V1"


def _need(value, label):
    if not value:
        raise ValueError("BOAT_44_BRIDGE_" + label)


def assemble_p1(*, race_id, venue_code, as_of, cutoff_at, roster,
                historical_records, exhibition, exhibition_receipt,
                slow_count, current_venue_rule, event_id, event_rules,
                standings, standings_receipt, board_complete, baseline,
                admit_source, corner_evidence=None):
    """Prepare an existing-overlay record from *provided* pre-cutoff facts.

    The source-admission callback is mandatory. It is not independent
    authentication; the owner-only producer must verify source bytes, clocks,
    archive membership and the encrypted-state readback separately.
    Missing or structurally inapplicable rates remain None and cause HOLD.
    """
    _need(callable(admit_source), "SOURCE_ADMISSION_REQUIRED")
    now, close = _ts(as_of), _ts(cutoff_at)
    _need(now < close, "POST_CUTOFF_ASOF")
    _need(type(roster) is list and len(roster) == 6 and
          all(type(r) is dict and set(r) == {"frame", "racer_id"} for r in roster),
          "SIX_OFFICIAL_ROSTER_REQUIRED")
    by_frame = {r["frame"]: r["racer_id"] for r in roster}
    _need(set(by_frame) == set(range(1, 7)) and
          len(set(by_frame.values())) == 6 and
          all(type(rid) is str and rid.isascii() and len(rid) == 4
              and rid.isdecimal() for rid in by_frame.values()),
          "ROSTER_IDENTITY_INVALID")
    _need(type(exhibition) is list and len(exhibition) == 6 and
          all(type(row) is dict and
              row.get("racer_id") == by_frame.get(row.get("frame"))
              for row in exhibition), "ROSTER_EXHIBITION_MISMATCH")
    _need(type(historical_records) is list and
          len(historical_records) <= 25000, "HISTORY_BOUNDED")
    _need(type(baseline) is dict and baseline.get("race_id") == race_id
          and baseline.get("as_of") == as_of
          and type(baseline.get("full_120")) is list
          and len(baseline["full_120"]) == 120, "BASELINE120_REQUIRED")
    _need(admit_source("exhibition", exhibition_receipt) is True,
          "EXHIBITION_SOURCE_NOT_ADMITTED")
    if current_venue_rule is not None:
        _need(admit_source("venue_tilt", current_venue_rule["receipt"]) is True,
              "VENUE_RULE_NOT_ADMITTED")
    if event_rules is not None:
        _need(admit_source("event_rules", event_rules["receipt"]) is True,
              "EVENT_RULES_NOT_ADMITTED")
    if standings_receipt is not None:
        _need(admit_source("event_standings", standings_receipt) is True,
              "EVENT_STANDINGS_NOT_ADMITTED")
    for item in historical_records:
        _need(type(item) is dict and
              admit_source("past_K", {"source_sha256": item.get("source_sha256"),
                                      "captured_at": item.get("result_captured_at")}) is True,
              "PAST_RESULT_NOT_ADMITTED")
        _need(_ts(item["result_captured_at"]) <= now,
              "PAST_RESULT_AFTER_ASOF")
        _need(item["race_id"] != race_id, "TARGET_RESULT_IN_HISTORY")

    tilt = p1_tilt_entry_context(
        race_id=race_id, venue_code=venue_code, as_of=as_of,
        cutoff_at=cutoff_at, exhibition=exhibition,
        receipt=exhibition_receipt, slow_count=slow_count,
        current_venue_rule=current_venue_rule)
    racer_ids = list(by_frame.values())
    profiles = {rid: analyze_racer(historical_records, racer_id=rid,
                                  as_of=as_of,
                                  corner_evidence=corner_evidence)
                for rid in racer_ids}
    entry = {rid: entry_response_profile(historical_records,
                                         racer_id=rid, as_of=as_of)
             for rid in racer_ids}
    by_course = {row["course"]: row["racer_id"] for row in exhibition}
    matchup = matchup_features(profiles, entrant_by_course=by_course)
    qualifying = None
    if event_rules is not None and standings_receipt is not None:
        qualifying = qualifying_standings(
            event_id=event_id, venue_code=venue_code, as_of=as_of,
            event_rules=event_rules, standings=standings,
            standings_receipt=standings_receipt,
            board_complete=board_complete)
    context = six_way_research_context(matchup, tilt, entry, qualifying)
    missing = []
    for name, rate in context["six_course_features"].items():
        if type(rate) not in (float, int) or not math.isfinite(rate):
            missing.append("six_course_features." + name)
    for course, row in context["entry_tilt_cross_features"].items():
        for name in ("tilt_deg", "historical_inward_move_win_rate",
                     "historical_outward_move_top3_rate",
                     "inner_pressure_kept_course_rate"):
            if type(row[name]) not in (int, float) or not math.isfinite(row[name]):
                missing.append("entry_tilt_cross_features." + course + "." + name)
    if context["current_venue_rule_status"] != \
            "CLAIMED_CURRENT_RECEIPT_REQUIRES_INDEPENDENT_AUTH":
        missing.append("current_venue_rule")
    q = context["qualifying_rank_and_point_gaps"]
    if q is None or q["border_status"] != "CURRENT_RANK_ONLY_NOT_FINAL":
        missing.append("official_event_qualifying_board")
    else:
        by_id = {r["racer_id"]: r for r in q["standings"]}
        for rid in racer_ids:
            person = by_id.get(rid)
            if (person is None or person["official_rank"] is None or
                    person["official_rate"] is None or
                    person["eligibility"] != "ELIGIBLE" or
                    type(q["rate_gaps"].get(rid)) not in (int, float)):
                missing.append("qualifying." + rid)
    # The actual overlay performs final 120-value and full-schema validation.
    record = {"stage": "P1", "context": context, "cutoff_at": cutoff_at,
              "baseline": baseline}
    return {
        "schema": SCHEMA,
        "race_id": race_id,
        "status": "P1_CONTEXT_READY_UNVERIFIED" if not missing
                  else "HOLD_MISSING_ACTUAL_SOURCE_FACTS",
        "missing": missing,
        "record": record if not missing else None,
        "source_independently_authenticated_here": False,
        "training_or_probability_improvement_proven": False,
        "original_model_or_weights_modified": False,
        "historical_records_examined": len(historical_records),
    }
