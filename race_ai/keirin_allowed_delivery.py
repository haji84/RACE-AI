"""Rights-gated, network-free KEIRIN permitted-delivery -> PR71 input bridge.

No live scraping, no built-in source grant, no made-up normalizations. All
347/437 inspection statuses are constructed, but missing source values remain
missing. This does not claim public sites permit automated harvesting.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math
from urllib.parse import urlsplit

from .comprehensive_four_sport_models import feature_inventory
from .keirin_field_acquisition import acquisition_summary
from .keirin_preflight import (
    SCHEMA as AUDIT_SCHEMA, RACE_ITEMS, RIDER_ITEMS, CRITICAL_RACE,
    CRITICAL_RIDER, audit_pre_race, expected_keys,
)
from .keirin_next_forecast_worker import _no_market_features
from .keirin_result_delivery import canonical, utc

DELIVERY_SCHEMA = "RACE_AI_KEIRIN_PERMISSIONED_DELIVERY_V1"
OUTER_SCHEMA = "RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1"

# Target model feature -> (source registry field, exact documented transform).
# "ratio" means the incoming evidence itself is a measured [0,1] ratio.
# "score100" is a documented, NOT LEARNED engineering scale, not a win chance.
RIDER_MAP = {
    "ability": ("race_score", "score100"),
    "recent_form": ("recent_strength_or_form_change", "ratio"),
    "start_reliability": ("start_or_line_reliability", "ratio"),
    "finishing_power": ("last_lap_acceleration", "ratio"),
    "course_compatibility": ("venue_and_distance_compatibility", "ratio"),
    "stamina": ("stamina_and_pace_resilience", "ratio"),
    "tactical_adaptability": ("position_flexibility_and_solo_behavior", "ratio"),
    "consistency": ("top_three_rate", "ratio"),
    "line_coordination": ("teammate_pair_history", "ratio"),
    "sprint_acceleration": ("last_lap_acceleration", "ratio"),
    "attack_success": ("lead_attempt_and_success", "ratio"),
    "bank_fit": ("venue_and_distance_compatibility", "ratio"),
    "escape_style": ("style_escape", "ratio"),
    "makuri_style": ("style_makuri", "ratio"),
    "sashi_style": ("style_sashi", "ratio"),
    "start_count_form": ("start_S_count", "count_rate"),
    "home_count_form": ("home_H_count", "count_rate"),
    "back_count_form": ("back_B_count", "count_rate"),
    "hsb_form": ("back_B_count", "count_rate"),
    "recent_points": ("race_score", "score100"),
    "recent_win_form": ("win_rate", "ratio"),
    "teammate_synergy": ("teammate_pair_history", "ratio"),
    "last_lap_kick": ("last_lap_acceleration", "ratio"),
    "bank_angle_fit": ("venue_and_distance_compatibility", "ratio"),
    "crosswind_resilience": ("wind_and_surface_compatibility", "ratio"),
    "schedule_recovery": ("rest_days_and_fatigue", "ratio"),
    "position_versatility": ("position_flexibility_and_solo_behavior", "ratio"),
    "opponent_tactical_fit": ("opponent_style_matchup", "ratio"),
}
ENV_MAP = {
    "wind_mps": ("wind_speed", "physical"),
    "rain_mm_h": ("rainfall", "physical"),
    "humidity_pct": ("humidity", "physical"),
    "air_temp_c": ("air_temperature", "physical"),
    "surface_wetness": ("surface_wetness", "ratio"),
    "bank_steepness": ("bank_cant_and_corner_shape", "ratio"),
    "wind_exposure": ("track_weather_effect_history", "ratio"),
    "track_roughness": ("track_surface_and_condition", "ratio"),
    "line_complexity": ("line_competition_and_lead_candidates", "ratio"),
}
MODEL_REQUIRED = set(feature_inventory("keirin")["common_required"] +
                     feature_inventory("keirin")["sport_required"])
ENV_REQUIRED = set(feature_inventory("keirin")["environment_required"])


class PermittedDeliveryError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise PermittedDeliveryError(code)


def _iso(value):
    _require(type(value) is str, "TIMESTAMP_INVALID")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PermittedDeliveryError("TIMESTAMP_INVALID") from exc
    _require(stamp.tzinfo is not None and stamp.utcoffset() is not None,
             "TIMESTAMP_MISSING_TZ")
    return stamp


def _valid_url(value):
    if type(value) is not str or not 0 < len(value) <= 256:
        return False
    try:
        parts = urlsplit(value)
        return (parts.scheme == "https" and bool(parts.hostname) and
                not parts.username and not parts.password)
    except ValueError:
        return False


def _number(value, low, high):
    _require(type(value) in (int, float) and math.isfinite(value) and
             low <= value <= high, "NONFINITE_OR_UNDOCUMENTED_NORMALIZATION")
    return float(value)


def _convert(value, sample_n, method):
    if method == "ratio":
        return _number(value, 0, 1)
    if method == "score100":
        return _number(value, 0, 100) / 100
    if method == "count_rate":
        _require(type(value) is int and type(sample_n) is int and sample_n > 0,
                 "COUNT_AND_SAMPLE_MUST_BE_INTEGERS")
        return _number(value, 0, sample_n) / sample_n
    if method == "physical":
        return _number(value, -30, 150)
    raise PermittedDeliveryError("TRANSFORM_NOT_APPROVED")


def _allow_source(check, source_url, rights_ref):
    # A caller-supplied callback MUST independently verify actual source grant,
    # exact purposes and expiry. This wrapper is not legal authorization.
    if not callable(check):
        return False
    try:
        return all(check(source_url, rights_ref, p) is True
                   for p in ("analysis", "model_inference", "private_retention"))
    except Exception:
        return False


def _status_for_item(row, cutoff, as_of, grant):
    if not isinstance(row, dict):
        raise PermittedDeliveryError("OBSERVATION_NOT_OBJECT")
    _require(set(row) == {"key", "value", "source_url", "rights_ref",
                          "published_at", "captured_at", "sample_n"},
             "OBSERVATION_SHAPE_INVALID")
    _no_market_features(row["value"])
    src, rights = row["source_url"], row["rights_ref"]
    _require(_valid_url(src) and type(rights) is str and
             1 <= len(rights) <= 256 and
             type(row["sample_n"]) is int and 1 <= row["sample_n"] <= 10_000_000,
             "OBSERVATION_PROVENANCE_INVALID")
    published = _iso(row["published_at"])
    captured = _iso(row["captured_at"])
    _require(published <= captured, "OBSERVATION_PUBLISH_AFTER_CAPTURE")
    # Data published late or collected after the input snapshot is unusable,
    # even if the race itself has yet to start.
    if captured > as_of or published >= cutoff:
        return "stale", "PUBLISHED_OR_CAPTURED_AFTER_AS_OF"
    if not _allow_source(grant, src, rights):
        return "rights_blocked", "INDEPENDENT_PURPOSE_GRANT_NOT_VERIFIED"
    return "verified", None


def _missing(key, status, reason):
    return {
        "key": key, "status": status, "reason": reason,
        "source_url": None, "published_at": None, "captured_at": None,
        "rights_ref": None, "observation_sha256": None,
    }


def _stored(key, row):
    return {
        "key": key, "status": "verified", "reason": None,
        "source_url": row["source_url"], "published_at": row["published_at"],
        "captured_at": row["captured_at"], "rights_ref": row["rights_ref"],
        "observation_sha256": sha256(canonical(row)).hexdigest(),
    }


def _model_observation(row, value, transform):
    return {
        "value": value,
        "published_at": row["published_at"],
        "captured_at": row["captured_at"],
        "source_ref": row["source_url"],
        "source_rights_ref": row["rights_ref"],
        "sample_n": row["sample_n"],
        "transform_id": "keirin-audit-" + transform + "-v1",
    }



def _bind_roster_and_lines(race, approved):
    """Prevent verified-but-unrelated source rows from certifying a roster."""
    roster = race["starters"]
    by_number = {p["number"]: p for p in roster}
    current = sorted(by_number)
    for key, expected in (
        ("race/race_id_date_venue_no",
         {"race_id": race["race_id"], "event_date_jst": race["event_date_jst"],
          "venue": race["venue"]}),
        ("race/official_sales_cutoff", race["official_cutoff_at"]),
        ("race/race_distance", race["distance_m"]),
    ):
        if key not in approved:
            continue
        actual = approved[key]["value"]
        if isinstance(expected, dict):
            _require(isinstance(actual, dict) and
                     all(actual.get(k) == v for k, v in expected.items()),
                     "RACE_SOURCE_IDENTITY_MISMATCH")
        else:
            _require(actual == expected, "RACE_SOURCE_TIMING_OR_DISTANCE_MISMATCH")
    key = "race/all_entrants_and_vehicle_numbers"
    if key in approved:
        entries = approved[key]["value"]
        _require(type(entries) is list and
                 entries == [{"number": n, "identity": by_number[n]["identity"]}
                             for n in current],
                 "SOURCE_ENTRANT_LIST_DISAGREEMENT")
    key = "race/late_scratches_substitutions_revisions"
    if key in approved:
        revision = approved[key]["value"]
        _require(type(revision) is dict and
                 revision.get("race_revision") == race["race_revision"] and
                 revision.get("active_numbers") == current,
                 "SOURCE_REVISION_OR_SCRATCH_MISMATCH")
    key = "race/line_order_all_riders"
    if key in approved:
        topology = approved[key]["value"]
        _require(type(topology) is dict and
                 set(topology) == {"lines", "solos"} and
                 type(topology["lines"]) is list and
                 type(topology["solos"]) is list,
                 "LINE_TOPOLOGY_INVALID")
        seen = []
        for line in topology["lines"]:
            _require(type(line) is dict and
                     set(line) == {"group_id", "order"} and
                     type(line["group_id"]) is str and
                     1 <= len(line["group_id"]) <= 30 and
                     type(line["order"]) is list and
                     2 <= len(line["order"]) <= len(current),
                     "LINE_SHAPE_INVALID")
            for n in line["order"]:
                _require(type(n) is int and n in by_number and
                         by_number[n]["group_id"] == line["group_id"],
                         "LINE_GROUP_DISAGREEMENT")
                seen.append(n)
        for n in topology["solos"]:
            _require(type(n) is int and n in by_number and
                     by_number[n]["group_id"] is None,
                     "SOLO_RIDER_DISAGREEMENT")
            seen.append(n)
        _require(sorted(seen) == current and len(seen) == len(set(seen)),
                 "LINE_ROSTER_COVERAGE_INVALID")


def assemble_permitted_pre_race(delivery, *, grant_check, checked_at):
    """Build one private model input, with complete per-key audit and lineage.

    The incoming delivery is generated by a *separately permitted* source feed.
    It may include only source observations. Values are NEVER looked up online
    by this module and raw observations are not written to a public repository.

    Returns private_snapshot=None when source rights/core/model requirements fail.
    The caller must store the audit report privately as a rejected event.
    """
    _require(type(delivery) is dict and set(delivery) == {
        "schema", "race", "observations"
    } and delivery["schema"] == DELIVERY_SCHEMA,
             "DELIVERY_SCHEMA_INVALID")
    _no_market_features(delivery)
    race = delivery["race"]
    keys = {"race_id", "venue", "event_date_jst", "race_kind", "race_revision",
            "distance_m", "as_of", "official_cutoff_at", "permission_ref",
            "starters"}
    _require(type(race) is dict and set(race) == keys,
             "RACE_KEYS_INVALID")
    entrants = race["starters"]
    _require(type(entrants) is list and len(entrants) in (7, 9),
             "MODEL_SUPPORTS_SEVEN_OR_NINE_RIDERS")
    _require(all(type(e) is dict and set(e) == {
        "number", "identity", "style", "group_id"
    } for e in entrants), "ENTRANT_SHAPE_INVALID")
    starters = [e["number"] for e in entrants]
    expected = set(expected_keys(starters))
    _require(type(race["race_id"]) is str and
             type(race["venue"]) is str and
             type(race["event_date_jst"]) is str and
             type(race["permission_ref"]) is str and
             len(race["permission_ref"]) > 0 and
             type(race["race_revision"]) is int and
             race["race_revision"] >= 1 and
             type(race["race_kind"]) is str and
             len(race["race_kind"]) > 0,
             "RACE_IDENTITY_INCOMPLETE")
    as_of = _iso(race["as_of"])
    cutoff = _iso(race["official_cutoff_at"])
    checked = _iso(checked_at)
    _require(as_of <= checked < cutoff, "INSPECTION_NOT_PRE_CUTOFF")
    _require(as_of.astimezone(cutoff.tzinfo).date() ==
             cutoff.astimezone(cutoff.tzinfo).date(),
             "RACE_AS_OF_DAY_MISMATCH")
    _number(race["distance_m"], 100, 10000)
    _require(type(delivery["observations"]) is list and
             len(delivery["observations"]) <= len(expected),
             "DELIVERY_TOO_MANY_OBSERVATIONS")
    rows = {}
    states = {}
    for row in delivery["observations"]:
        key = row.get("key") if isinstance(row, dict) else None
        _require(type(key) is str and key in expected and key not in rows,
                 "UNKNOWN_OR_DUPLICATE_SOURCE_FIELD")
        state, reason = _status_for_item(row, cutoff, as_of, grant_check)
        rows[key] = row
        states[key] = (state, reason)
    items = []
    approved = {}
    for key in expected_keys(starters):
        if key not in rows:
            items.append(_missing(key, "unavailable", "NO_AUTHORIZED_OBSERVATION_DELIVERED"))
            continue
        state, reason = states[key]
        if state != "verified":
            items.append(_missing(key, state, reason))
            continue
        items.append(_stored(key, rows[key]))
        approved[key] = rows[key]
    _bind_roster_and_lines(race, approved)
    required_missing = [
        i["key"] for i in items if
        ((i["key"].startswith("race/") and i["key"].split("/")[1] in CRITICAL_RACE) or
         (i["key"].startswith("rider/") and i["key"].split("/")[2] in CRITICAL_RIDER))
        and i["status"] != "verified"
    ]
    consumed = {}
    missing_features = []
    participant_rows = []
    inv = feature_inventory("keirin")
    allowed_model = set(inv["common_required"] + inv["sport_required"] +
                        inv["sport_optional"])
    _require(set(RIDER_MAP) <= allowed_model, "FEATURE_MAP_UNKNOWN_TARGET")
    for entrant in sorted(entrants, key=lambda e: e["number"]):
        n = entrant["number"]
        _require(type(n) is int and 1 <= n <= 9 and
                 type(entrant["identity"]) is str and entrant["identity"] and
                 entrant["style"] in ("front", "stalker", "closer",
                                     "allround", "unknown") and
                 (entrant["group_id"] is None or
                  type(entrant["group_id"]) is str),
                 "ENTRANT_INVALID")
        # The roster and line must bind to admitted core observations. No
        # fake identities/line assignments from unverified delivery headers.
        rider_key = "rider/%d/identity_number_and_grade" % n
        line_key = "race/line_order_all_riders"
        if rider_key in approved:
            rawid = approved[rider_key]["value"]
            _require(type(rawid) is dict and
                     rawid.get("number") == n and
                     rawid.get("identity") == entrant["identity"],
                     "ROSTER_OBSERVATION_DISAGREEMENT")
        fields = {}
        for feature in sorted(allowed_model):
            if feature not in RIDER_MAP:
                continue
            origin, method = RIDER_MAP[feature]
            source = "rider/%d/%s" % (n, origin)
            if source not in approved:
                if feature in MODEL_REQUIRED:
                    missing_features.append("rider/%d/%s" % (n, feature))
                continue
            row = approved[source]
            fields[feature] = _model_observation(
                row, _convert(row["value"], row["sample_n"], method), method)
            consumed["rider/%d/%s" % (n, feature)] = source
        participant_rows.append({
            "number": n, "identity": entrant["identity"], "draw": n,
            "style": entrant["style"], "group_id": entrant["group_id"],
            "features": fields,
        })
    env = {}
    for feature in sorted(ENV_REQUIRED):
        origin, method = ENV_MAP[feature]
        source = "race/" + origin
        if source not in approved:
            missing_features.append("environment/" + feature)
            continue
        row = approved[source]
        env[feature] = _model_observation(
            row, _convert(row["value"], row["sample_n"], method), method)
        consumed["environment/" + feature] = source
    base_status = {
        "schema": "RACE_AI_KEIRIN_PERMISSIONED_FEED_STATUS_V1",
        "race_id": race["race_id"],
        "checked_count": len(items),
        "acquisition_type_counts": acquisition_summary(starters)["categories"],
        "all_checklist_fields_have_public_raw_values": False,
        "verified_items": len(approved),
        "unavailable_items": len(items) - len(approved),
        "unverified_critical_keys": sorted(required_missing),
        "missing_model_inputs": sorted(missing_features),
        "model_inputs_generated": len(consumed),
        "unique_verified_source_items_consumed": len(set(consumed.values())),
        "verified_audit_only_items": len(set(approved) - set(consumed.values())),
        "source_items_checked_but_not_used_as_numeric_features":
            sorted(set(approved) - set(consumed.values())),
        "network_requests": 0,
        "model_status": "NOT_RUN",
        "rights_certified_by_this_module": False,
        "real_provider_connected_by_this_module": False,
    }
    audit = {
        "schema": AUDIT_SCHEMA,
        "race_id": race["race_id"],
        "starters": starters,
        "official_cutoff_at": race["official_cutoff_at"],
        "evidence_sha256": "0" * 64,
        "checked_at": checked_at,
        "items": items,
    }
    if required_missing or missing_features:
        base_status["state"] = "BLOCKED_MISSING_CRITICAL_OR_MODEL_INPUTS"
        return {"status": base_status, "audit": audit, "private_snapshot": None,
                "consumed_feature_origins": consumed}
    model_evidence = {
        "schema": "RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1",
        "scope": "OPERATOR_SUPPLIED_RESEARCH",
        "race": {
            "race_id": race["race_id"], "sport": "keirin",
            "venue": race["venue"], "event_date_jst": race["event_date_jst"],
            "race_kind": race["race_kind"], "race_revision": race["race_revision"],
            "distance_m": race["distance_m"], "surface": "velodrome",
            "as_of": race["as_of"],
            "sales_cutoff_at": race["official_cutoff_at"],
        },
        "participants": participant_rows,
        "environment": env,
    }
    audit["evidence_sha256"] = sha256(canonical(model_evidence)).hexdigest()
    verdict = audit_pre_race(
        audit, race_id=race["race_id"], starters=starters,
        cutoff_at=race["official_cutoff_at"], snapshot_as_of=race["as_of"],
        issued_at=checked_at, evidence_sha256=audit["evidence_sha256"])
    _require(verdict["full_forecast_gate_passed"], "CORE_AUDIT_FAILURE")
    snapshot = {
        "schema": OUTER_SCHEMA,
        "race_id": race["race_id"], "as_of": race["as_of"],
        "starters": starters,
        "permission_ref": race["permission_ref"],
        "official_cutoff_at": race["official_cutoff_at"],
        "facts": {"pr71_evidenced_snapshot": model_evidence,
                  "keirin_pre_race_audit_v1": audit},
    }
    base_status["state"] = "PRIVATE_PR71_INPUT_READY_RIGHTS_AND_FREEZE_STILL_EXTERNAL"
    base_status["model_status"] = "READY_NOT_EXECUTED"
    base_status["model_input_snapshot_sha256"] = sha256(canonical(snapshot)).hexdigest()
    return {"status": base_status, "audit": audit,
            "private_snapshot": snapshot,
            "consumed_feature_origins": consumed}
