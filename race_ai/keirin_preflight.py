"""Mandatory pre-race KEIRIN factor *inspection* contract, not an estimator.

Records every item for the race and every rider. Unknown observations are
explicitly recorded, never invented. This module does not grant usage rights,
obtain provider data, calibrate probability, or authorize betting.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

SCHEMA = "RACE_AI_KEIRIN_PRE_RACE_AUDIT_V1"
STATES = frozenset({"verified", "unavailable", "stale", "rights_blocked", "not_applicable"})
SHA = re.compile(r"^[0-9a-f]{64}$")

# Inspection is compulsory for ALL items. Critical items must additionally be
# verified for a full forecast. Other unavailable items lower coverage and are
# disclosed, rather than being silently imputed.
RACE_ITEMS = (
    "race_id_date_venue_no", "event_grade_and_class", "race_stage",
    "advancement_and_points_rules", "race_distance", "start_time",
    "official_sales_cutoff", "all_entrants_and_vehicle_numbers",
    "late_scratches_substitutions_revisions", "line_order_all_riders",
    "line_roles_and_solo_riders", "line_competition_and_lead_candidates",
    "race_formation_comments", "early_position_scenarios",
    "front_race_and_breakaway_scenarios", "late_attack_scenarios",
    "line_break_and_mixed_finish_scenarios", "venue_lap_length",
    "bank_cant_and_corner_shape", "home_straight_length",
    "track_surface_and_condition", "track_weather_effect_history",
    "wind_speed", "wind_direction", "rainfall", "surface_wetness",
    "air_temperature", "humidity", "same_day_lane_or_style_bias",
    "venue_distance_style_effect", "race_revision_and_publication",
    "source_access_permission_and_asof",
)
RIDER_ITEMS = (
    "identity_number_and_grade", "race_score", "opponent_strength_adjustment",
    "win_rate", "second_place_rate", "third_place_rate", "top_three_rate",
    "last_3_races_rank_and_rivals", "last_10_races_rank_and_rivals",
    "recent_race_video_observations", "recent_strength_or_form_change",
    "style_escape", "style_makuri", "style_sashi", "style_mark",
    "start_S_count", "home_H_count", "back_B_count",
    "lead_attempt_and_success", "makuri_attempt_and_success",
    "sashi_attempt_and_success", "late_lap_and_agari_time",
    "last_lap_acceleration", "front_positioning_preference",
    "bank_positioning_and_traffic", "stamina_and_pace_resilience",
    "line_leader_or_follow_role", "second_rider_tracking_and_pass",
    "third_rider_tracking_and_gap", "teammate_pair_history",
    "same_line_three_way_history", "direct_head_to_head",
    "opponent_style_matchup", "venue_and_distance_compatibility",
    "wind_and_surface_compatibility", "start_or_line_reliability",
    "recent_fall_disqualification", "injury_illness_and_recovery",
    "absence_reason_and_return_state", "rest_days_and_fatigue",
    "athlete_comments_and_intent", "gear_ratio_and_changes",
    "equipment_or_mechanical_issues", "age_term_experience",
    "position_flexibility_and_solo_behavior",
)
CRITICAL_RACE = frozenset({
    "race_id_date_venue_no", "event_grade_and_class", "race_stage",
    "advancement_and_points_rules", "race_distance",
    "official_sales_cutoff", "all_entrants_and_vehicle_numbers",
    "late_scratches_substitutions_revisions", "line_order_all_riders",
    "line_roles_and_solo_riders", "source_access_permission_and_asof",
})
CRITICAL_RIDER = frozenset({
    "identity_number_and_grade", "race_score",
    "last_3_races_rank_and_rivals", "style_escape", "style_makuri",
    "style_sashi", "style_mark", "line_leader_or_follow_role",
    "athlete_comments_and_intent",
})


class PreRaceAuditError(ValueError):
    pass


def _require(ok, message):
    if not ok:
        raise PreRaceAuditError(message)


def _time(value):
    _require(type(value) is str, "INVALID_TIME")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreRaceAuditError("INVALID_TIME") from exc
    _require(result.tzinfo is not None and result.utcoffset() is not None,
             "TIMEZONE_REQUIRED")
    return result


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def expected_keys(starters):
    _require(type(starters) is list and 3 <= len(starters) <= 9 and
             all(type(n) is int and 1 <= n <= 9 for n in starters) and
             len(set(starters)) == len(starters), "INVALID_STARTERS")
    return (tuple("race/" + x for x in RACE_ITEMS) +
            tuple("rider/%d/%s" % (n, x) for n in sorted(starters)
                  for x in RIDER_ITEMS))


def audit_pre_race(report, *, race_id, starters, cutoff_at,
                   snapshot_as_of, issued_at, evidence_sha256):
    """Check a FULL audit, including explicit missing/rights-blocked values.

    Verification of rights_ref authenticity is EXTERNAL to this validator.
    This only validates audit completeness, time ordering, and provenance
    structure. Its result is NOT evidence of rights or independently frozen picks.
    """
    _require(type(report) is dict and set(report) == {
        "schema", "race_id", "starters", "official_cutoff_at",
        "evidence_sha256", "checked_at", "items"
    } and report["schema"] == SCHEMA and
        report["race_id"] == race_id and report["starters"] == starters and
        report["official_cutoff_at"] == cutoff_at and
        report["evidence_sha256"] == evidence_sha256 and
        _sha(evidence_sha256), "AUDIT_BINDING_INVALID")
    cutoff = _time(cutoff_at)
    snap = _time(snapshot_as_of)
    issued = _time(issued_at)
    checked = _time(report["checked_at"])
    _require(snap <= checked <= issued < cutoff, "AUDIT_AFTER_CUTOFF_OR_SNAPSHOT")
    expected = set(expected_keys(starters))
    entries = report["items"]
    _require(type(entries) is list and len(entries) == len(expected),
             "AUDIT_ITEM_COUNT_MISMATCH")
    seen = set()
    missing = []
    missing_critical = []
    for item in entries:
        _require(type(item) is dict and set(item) == {
            "key", "status", "reason", "source_url",
            "published_at", "captured_at", "rights_ref", "observation_sha256"
        }, "AUDIT_ITEM_SHAPE_INVALID")
        key = item["key"]
        _require(type(key) is str and key in expected and key not in seen,
                 "AUDIT_DUPLICATE_OR_UNKNOWN_KEY")
        seen.add(key)
        status = item["status"]
        _require(type(status) is str and status in STATES, "AUDIT_STATUS_INVALID")
        if status == "verified":
            src = item["source_url"]
            url = urlsplit(src) if type(src) is str else None
            _require(url is not None and url.scheme == "https" and
                     bool(url.netloc) and not url.username and not url.password and
                     type(item["rights_ref"]) is str and
                     len(item["rights_ref"]) > 0 and
                     _sha(item["observation_sha256"]) and
                     item["reason"] is None, "AUDIT_VERIFIED_PROVENANCE_MISSING")
            published = _time(item["published_at"])
            captured = _time(item["captured_at"])
            _require(published <= captured <= snap,
                     "AUDIT_SOURCE_NOT_PRE_RACE")
        else:
            _require(type(item["reason"]) is str and
                     1 <= len(item["reason"]) <= 500,
                     "AUDIT_MISSING_REASON_REQUIRED")
            # Missing is not a measured zero and must not carry a guessed value.
            _require(item["source_url"] is None and
                     item["observation_sha256"] is None and
                     item["published_at"] is None and
                     item["captured_at"] is None and
                     item["rights_ref"] is None,
                     "AUDIT_MISSING_VALUE_MUST_BE_EMPTY")
            missing.append(key)
            parts = key.split("/")
            is_core = ((parts[0] == "race" and parts[1] in CRITICAL_RACE) or
                       (parts[0] == "rider" and parts[2] in CRITICAL_RIDER))
            if is_core:
                missing_critical.append(key)
    _require(seen == expected, "AUDIT_ITEMS_INCOMPLETE")
    return {
        "schema": "RACE_AI_KEIRIN_PRE_RACE_AUDIT_RESULT_V1",
        "all_factors_checked": True,
        "total_items": len(entries),
        "verified_count": len(entries) - len(missing),
        "unknown_or_unusable_count": len(missing),
        "missing_keys": sorted(missing),
        "missing_critical_keys": sorted(missing_critical),
        "full_forecast_gate_passed": not missing_critical,
        "probabilities_calibrated": False,
        "source_rights_independently_verified": False,
        "external_pre_cutoff_freeze_verified": False,
    }
