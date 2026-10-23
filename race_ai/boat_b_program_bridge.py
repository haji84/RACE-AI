"""Offline bridge for the existing PR #64 BOATRACE official B-program adapter.

Input is the ALREADY EXTRACTED output of
race_ai.official_b_snapshot_adapter.normalize_b_snapshot on PR #64.
It never fetches BOATRACE, decodes archives, invents missing features or
treats an operator's rights flag as evidence of permission.
No forecast is official or time-attested by this module.
"""
from __future__ import annotations

from datetime import date, timezone, timedelta
import re

from .comprehensive_four_sport_models import (
    COMMON_REQUIRED, SPORT_REQUIRED, moment, RESEARCH, digest
)
from .permissioned_source_delivery import (
    PermissionPolicy, SourceDeliveryError, _https, deliver,
)

HANDOFF_SCHEMA = "RACE_AI_OFFICIAL_B_EXTRACT_HANDOFF_V1"
STAGE_SCHEMA = "RACE_AI_BOAT_B_IDENTITY_STAGE_V1"
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
RACE_ID = re.compile(r"(\d{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])\Z")
VENUE = re.compile(r"0[1-9]|1[0-9]|2[0-4]")
RACER = re.compile(r"\d{4}\Z")
BOAT_KEYS = {
    "lane", "racer_registration_id", "motor_no", "name", "average_st",
    "display_time", "preview_course", "boat_no", "grade",
    "national_win_rate", "local_win_rate", "national_top2_rate",
    "local_top2_rate", "motor_top2_rate", "boat_top2_rate",
}
EXTRACT_KEYS = {
    "date_jst", "source_url", "source_sha256", "extracted_text_sha256",
    "source_hash_scope", "first_observed_at", "venues", "races",
    "complete_six_boat_races",
}
REQUIRED_MISSING = tuple(COMMON_REQUIRED + SPORT_REQUIRED["boat"])


def _fail(reason):
    raise SourceDeliveryError(reason)


def _finite(value, lo, hi):
    import math
    return type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi


def _source_window(stamp, day, now):
    try:
        observed = moment(stamp)
    except (ValueError, TypeError):
        _fail("official B observation timestamp invalid")
    if observed > moment(now):
        _fail("source observation is in the future")
    if observed.astimezone(timezone(timedelta(hours=9))).date() != date.fromisoformat(day):
        _fail("source observation does not match JST program day")
    return observed


def stage_official_b_handoff(handoff, policy, *, now, race_id):
    """Stage verified *structure* and source lineage for one prospective race.

    Policy signature establishes only reviewed policy document provenance.
    It does not authenticate the origin bytes of a caller-provided extract, nor
    independently prove that a rightsholder granted the rights.
    """
    if not isinstance(policy, PermissionPolicy):
        _fail("independent purpose-scoped policy required")
    if not isinstance(handoff, dict) or set(handoff) != {
        "schema", "rights_ref", "parser_ref", "extract"
    } or handoff["schema"] != HANDOFF_SCHEMA:
        _fail("B handoff schema invalid")
    if (not isinstance(handoff["parser_ref"], str)
        or not handoff["parser_ref"].startswith("haji84/RACE-AI@")
        or len(handoff["parser_ref"]) > 256):
        _fail("versioned B extraction parser reference required")
    x = handoff["extract"]
    if not isinstance(x, dict) or set(x) != EXTRACT_KEYS:
        _fail("B extract keys missing or unexpected")
    try:
        day = date.fromisoformat(x["date_jst"])
    except (TypeError, ValueError):
        _fail("B day invalid")
    if day.isoformat() != x["date_jst"]:
        _fail("B day not canonical")
    source = _https(x["source_url"])
    if not isinstance(handoff["rights_ref"], str):
        _fail("rights reference missing")
    for purpose in ("analysis", "private_storage", "private_derived"):
        if not policy.authorize(source, handoff["rights_ref"], purpose):
            _fail("SOURCE_PERMISSION_NOT_ADMITTED:" + purpose)
    if (not isinstance(x["source_sha256"], str)
        or not SHA64.fullmatch(x["source_sha256"])
        or not isinstance(x["extracted_text_sha256"], str)
        or not SHA64.fullmatch(x["extracted_text_sha256"])
        or x["source_hash_scope"] not in ("downloaded_archive", "extracted_program_text")):
        _fail("B source hash/provenance missing")
    observed = _source_window(x["first_observed_at"], x["date_jst"], now)
    if (not isinstance(x["venues"], list) or not x["venues"]
        or len(x["venues"]) > 24 or
        type(x["races"]) is not int or not 1 <= x["races"] <= 288 or
        type(x["complete_six_boat_races"]) is not int or
        x["complete_six_boat_races"] != x["races"]):
        _fail("B extract race coverage invalid")

    seen_venues, known_races, matched = set(), set(), None
    race_count = 0
    for venue_row in x["venues"]:
        if not isinstance(venue_row, dict) or set(venue_row) != {"venue", "races"}:
            _fail("B venue schema invalid")
        venue = venue_row["venue"]
        if (not isinstance(venue, str) or not VENUE.fullmatch(venue)
            or venue in seen_venues or not isinstance(venue_row["races"], list)
            or not venue_row["races"] or len(venue_row["races"]) > 12):
            _fail("B venue identity/race list invalid")
        seen_venues.add(venue)
        for event in venue_row["races"]:
            if not isinstance(event, dict) or set(event) != {
                "race_id", "boats", "closed_at", "preview_available"
            }:
                _fail("B event schema invalid")
            rid = event["race_id"]
            m = RACE_ID.fullmatch(rid) if isinstance(rid, str) else None
            if (not m or m.group(1) != day.strftime("%Y%m%d")
                or m.group(2) != venue or rid in known_races
                or event["preview_available"] is not False):
                _fail("B race identity/preview invalid")
            known_races.add(rid)
            race_count += 1
            fleet = event["boats"]
            if not isinstance(fleet, list) or len(fleet) != 6:
                _fail("B expected exactly 6 boats")
            ids, lanes, motors, boats = set(), set(), set(), set()
            for b in fleet:
                if not isinstance(b, dict) or not {"lane", "racer_registration_id"}.issubset(b) or set(b) - BOAT_KEYS:
                    _fail("B boat schema invalid")
                ln, racer = b["lane"], b["racer_registration_id"]
                if (type(ln) is not int or ln not in range(1, 7)
                    or ln in lanes or not isinstance(racer, str)
                    or not RACER.fullmatch(racer) or racer in ids):
                    _fail("B racer/lane identity mismatch")
                lanes.add(ln)
                ids.add(racer)
                for field, registry in (("motor_no", motors), ("boat_no", boats)):
                    v = b.get(field)
                    if v is not None:
                        if type(v) is not int or not 1 <= v <= 999 or v in registry:
                            _fail("duplicate or invalid equipment allocation")
                        registry.add(v)
                for field in ("national_win_rate", "local_win_rate"):
                    v = b.get(field)
                    if v is not None and not _finite(v, 0, 10):
                        _fail("official B win rate invalid")
                for field in ("national_top2_rate", "local_top2_rate",
                              "motor_top2_rate", "boat_top2_rate"):
                    v = b.get(field)
                    if v is not None and not _finite(v, 0, 100):
                        _fail("official B two-place rate invalid")
                if b.get("average_st") is not None or b.get("display_time") is not None:
                    _fail("B program cannot authenticate exhibition/ST values")
            if lanes != set(range(1, 7)):
                _fail("incomplete lane set")
            if rid == race_id:
                matched = (venue, event)
    if race_count != x["races"] or len(known_races) != x["races"]:
        _fail("B declared and actual race counts differ")
    if matched is None:
        _fail("requested race not in B handoff")
    venue, event = matched
    cutoff = event["closed_at"]
    if cutoff is not None:
        try:
            ts = moment(cutoff)
        except (TypeError, ValueError):
            _fail("invalid official B cutoff")
        if ts.astimezone(timezone(timedelta(hours=9))).date() != day:
            _fail("official B cutoff not on JST race date")
    else:
        ts = None
    status = ("SALES_CUTOFF_MISSING" if ts is None else
              "MISSED_DEADLINE" if ts <= moment(now) else
              "AWAITING_VERIFIED_PRE_RACE_FEATURES")
    known = []
    for b in sorted(event["boats"], key=lambda r: r["lane"]):
        known.append({
            "number": b["lane"],
            "racer_registration_id": b["racer_registration_id"],
            "motor_no": b.get("motor_no"),
            "boat_no": b.get("boat_no"),
            "grade": b.get("grade"),
            "national_win_rate": b.get("national_win_rate"),
            "local_win_rate": b.get("local_win_rate"),
            "national_top2_rate": b.get("national_top2_rate"),
            "local_top2_rate": b.get("local_top2_rate"),
            "motor_top2_rate": b.get("motor_top2_rate"),
            "boat_top2_rate": b.get("boat_top2_rate"),
        })
    stage = {
        "schema": STAGE_SCHEMA, "race_id": race_id,
        "event_date_jst": x["date_jst"], "venue": venue,
        "cutoff_at": cutoff,
        "source_url": source,
        "source_rights_ref": handoff["rights_ref"],
        "source_sha256": x["source_sha256"],
        "source_extracted_text_sha256": x["extracted_text_sha256"],
        "source_hash_scope": x["source_hash_scope"],
        "observed_at": x["first_observed_at"],
        "parser_ref": handoff["parser_ref"],
        "participants": known,
        "program_day_declared_races": x["races"],
        "known_b_races": race_count,
        "missing_model_required_features": list(REQUIRED_MISSING),
        "model_eligible": False,
        "status": status,
        "official_schedule_completeness_verified": False,
        "official_bytes_independently_authenticated": False,
        "external_freeze_receipt": None,
        "official_prediction": False,
    }
    stage["stage_sha256"] = digest(stage)
    return stage


def link_b_stage_to_features(stage, normalized_feed_bytes, policy, *, at):
    """Match six B registrations and official cutoff before model evaluation.

    Reuses existing signed-source delivery; every model feature retains its
    own per-purpose permission and pre-cutoff published/captured times.
    """
    if not isinstance(stage, dict) or stage.get("schema") != STAGE_SCHEMA:
        _fail("B stage schema invalid")
    if stage.get("stage_sha256") != digest({
        k: v for k, v in stage.items() if k != "stage_sha256"
    }):
        _fail("B stage hash changed")
    if stage.get("status") != "AWAITING_VERIFIED_PRE_RACE_FEATURES":
        _fail("B stage is not prospective")
    # deliver() provides exact JSON/schema validation and 4-model run.
    from .permissioned_source_delivery import read_json_bytes
    feed = read_json_bytes(normalized_feed_bytes)
    snapshot = feed.get("snapshot") if isinstance(feed, dict) else None
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("race"), dict):
        _fail("model feature input missing")
    race = snapshot["race"]
    if (snapshot.get("scope") != RESEARCH
        or race.get("race_id") != stage["race_id"]
        or race.get("sport") != "boat"
        or race.get("venue") != stage["venue"]
        or race.get("event_date_jst") != stage["event_date_jst"]
        or race.get("sales_cutoff_at") != stage["cutoff_at"]):
        _fail("B race/program/feature identity mismatch")
    if moment(race["as_of"]) < moment(stage["observed_at"]):
        _fail("model features claim as_of before B observation")
    members = snapshot.get("participants")
    if not isinstance(members, list) or len(members) != 6:
        _fail("B expected six model participants")
    identities = {r["number"]: r["racer_registration_id"] for r in stage["participants"]}
    seen = set()
    for row in members:
        if (not isinstance(row, dict) or
            type(row.get("number")) is not int or row["number"] in seen
            or row["number"] not in identities
            or str(row.get("identity")) != identities[row["number"]]
            or row.get("draw") != row["number"]):
            _fail("B extracted racer/draw mismatch")
        seen.add(row["number"])
    if seen != set(identities):
        _fail("B model participants incomplete")
    out = deliver(normalized_feed_bytes, policy, at=at)
    out["b_program_stage_sha256"] = stage["stage_sha256"]
    out["b_program_source_sha256"] = stage["source_sha256"]
    out["b_program_reconciled"] = True
    out["official_b_bytes_independently_authenticated"] = False
    out["delivery_sha256"] = digest({k: v for k, v in out.items()
                                    if k != "delivery_sha256"})
    return out
