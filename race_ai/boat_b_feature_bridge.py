"""Read-only bridge from parsed official BOAT RACE B rows to research feature CANDIDATES.

No source acquisition, external publication, prediction, odds, or permission
grant. A B rate value alone cannot satisfy PR71's published_at/sample_n/rights
contract. Callers MUST use public_audit only in public CI logs; the full
candidate object is transient source-derived working data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import math
import re

JST = timezone(timedelta(hours=9))
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"(?P<ymd>\d{8})-(?P<venue>0[1-9]|1\d|2[0-4])-(?P<race>0[1-9]|1[0-2])\Z")

# Official B program statistical columns from the pinned PR64 strict parser.
# Outputs are engineering proxy scores, not calibrated probabilities.
MAPPING = (
    ("national_win_rate", "ability", "points_0_to_10", 10.0, "B_NATIONAL_WIN_RATE_DIV10_V1"),
    ("local_win_rate", "course_compatibility", "points_0_to_10", 10.0, "B_LOCAL_WIN_RATE_DIV10_V1"),
    ("motor_top2_rate", "motor_form", "percent_0_to_100", 100.0, "B_MOTOR_TOP2_RATE_DIV100_V1"),
)

class BFeatureBridgeError(ValueError):
    """Reject incomplete or inconsistently identified source-derived inputs."""


def _observed(value):
    if not isinstance(value, str):
        raise BFeatureBridgeError("observation time absent")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BFeatureBridgeError("invalid capture time") from exc
    if moment.utcoffset() is None:
        raise BFeatureBridgeError("capture timezone absent")
    return moment


def _rate(value, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise BFeatureBridgeError("missing or invalid official rate")
    return float(value)


def _schema_inventory(keys, *, what):
    if (not isinstance(keys, (tuple, list)) or not keys or
        any(not isinstance(v, str) or not v for v in keys) or len(set(keys)) != len(keys)):
        raise BFeatureBridgeError("invalid pinned model " + what + " inventory")
    return tuple(keys)


def candidate_bridge(entries, details, deadlines, *, event_date_jst,
                     archive_url, archive_sha256, observed_at_claimed,
                     required_runner_keys, required_environment_keys):
    """Return transient partial features and an aggregate log-safe audit.

    No source result is asserted to have been published before the cutoff.
    No admissions/predictions are performed, regardless of capture clock.
    """
    try:
        day = date.fromisoformat(event_date_jst)
        if day.isoformat() != event_date_jst:
            raise ValueError("noncanonical date")
    except (TypeError, ValueError) as exc:
        raise BFeatureBridgeError("invalid event date") from exc
    expected_url = f"https://www1.mbrace.or.jp/od2/B/{day:%Y%m}/b{day:%y%m%d}.lzh"
    if archive_url != expected_url or not isinstance(archive_sha256, str) or not HEX64.fullmatch(archive_sha256):
        raise BFeatureBridgeError("unverified daily B source identity or archive digest")
    observed = _observed(observed_at_claimed)
    required_runner = _schema_inventory(required_runner_keys, what="runner")
    required_environment = _schema_inventory(required_environment_keys, what="environment")
    model_candidate_keys = {m[1] for m in MAPPING}
    if not model_candidate_keys.issubset(required_runner):
        raise BFeatureBridgeError("B mappings no longer match pinned model inventory")
    if (not isinstance(entries, list) or not entries or len(entries) > 24 * 12 * 6
        or not isinstance(details, dict) or not isinstance(deadlines, dict)):
        raise BFeatureBridgeError("invalid B entrant/detail/deadline collection")
    by_race = {}
    seen = set()
    for entrant in entries:
        if not isinstance(entrant, dict):
            raise BFeatureBridgeError("invalid B entrant")
        rid, lane, racer = entrant.get("race_id"), entrant.get("lane"), entrant.get("racer_id")
        match = ID.fullmatch(rid) if isinstance(rid, str) else None
        if (match is None or match.group("ymd") != day.strftime("%Y%m%d")
            or type(lane) is not int or not 1 <= lane <= 6
            or not isinstance(racer, str) or not re.fullmatch(r"\d{4}", racer)):
            raise BFeatureBridgeError("B race/lane/registration identity mismatch")
        key = (rid, lane)
        if key in seen:
            raise BFeatureBridgeError("duplicate source entrant")
        seen.add(key)
        item = details.get(key)
        if (not isinstance(item, dict) or item.get("racer_registration_id") != racer
            or type(item.get("motor_no")) is not int or not 1 <= item["motor_no"] <= 999
            or type(item.get("boat_no")) is not int or not 1 <= item["boat_no"] <= 999):
            raise BFeatureBridgeError("B entrant-to-details/motor assignment mismatch")
        candidates = []
        for source_field, target, unit, divisor, transform in MAPPING:
            numerator = _rate(item.get(source_field), divisor)
            candidates.append({
                "feature_key": target,
                "source_field": source_field,
                "raw_unit": unit,
                "normalized_value": round(numerator / divisor, 6),
                "transform_id": transform,
                "source_ref": archive_url,
                "archive_sha256": archive_sha256,
                "published_at": None,
                "captured_at_claimed": observed.isoformat(),
                "sample_n": None,
                "source_rights_ref": None,
                "independently_admitted_for_pr71": False,
            })
        by_race.setdefault(rid, {})[lane] = {
            "lane": lane, "racer_registration_id": racer, "candidates": candidates
        }
    if not by_race or set(by_race) != set(deadlines):
        raise BFeatureBridgeError("B scheduled races differ from entrant races")
    internal = []
    historical_after_cutoff = 0
    for rid, lanes in sorted(by_race.items()):
        if set(lanes) != set(range(1, 7)):
            raise BFeatureBridgeError("incomplete six-lane B race")
        cutoff = _observed(deadlines[rid])
        if cutoff.astimezone(JST).date() != day:
            raise BFeatureBridgeError("B scheduled cutoff day mismatch")
        if observed >= cutoff:
            historical_after_cutoff += 1
        internal.append({
            "race_id": rid,
            "scheduled_cutoff_from_B_unverified": deadlines[rid],
            "participants": [lanes[i] for i in range(1, 7)],
            "missing_required_runner_keys": sorted(set(required_runner) - model_candidate_keys),
            "missing_required_environment_keys": list(required_environment),
            "model_prediction_executed": False,
        })
    race_count = len(internal)
    candidate_count = sum(
        len(participant["candidates"])
        for row in internal for participant in row["participants"]
    )
    missing_in_b = race_count * (6 * (len(required_runner) - len(MAPPING)) + len(required_environment))
    unadmitted = race_count * (6 * len(required_runner) + len(required_environment))
    aggregate = {
        "schema": "RACE_AI_B_PARTIAL_FEATURE_BRIDGE_AUDIT_V1",
        "scope": "AUDIT_ONLY_NOT_FORECAST",
        "event_date_jst": event_date_jst,
        "archive_sha256": archive_sha256,
        "source_url": archive_url,
        "source_capture_clock_is_independent_receipt": False,
        "source_original_published_at_verified": False,
        "source_use_rights_verified": False,
        "model_input_sample_sizes_verified": False,
        "official_live_cutoff_verified": False,
        "complete_parsed_races": race_count,
        "complete_parsed_entrant_rows": len(entries),
        "source_numeric_candidates_created": candidate_count,
        "required_per_race": 6 * len(required_runner) + len(required_environment),
        "model_required_fields_with_no_B_candidate_total": missing_in_b,
        "required_observations_admitted_to_model": 0,
        "required_observations_not_admitted": unadmitted,
        "captured_at_or_after_scheduled_cutoff_races": historical_after_cutoff,
        "model_prediction_executed": False,
        "formal_hit_at_8_eligible": False,
        "status": "CANDIDATES_MAPPED_BUT_PRE_CUTOFF_MODEL_INPUT_BLOCKED",
    }
    return {"public_audit": aggregate, "private_candidate_projection": internal}
