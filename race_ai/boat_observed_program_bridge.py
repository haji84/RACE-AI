"""Supplied parsed B facts -> separate P0 research snapshot, never admission.

The caller owns strict archive/body validation and actual capture. This pure
bridge does no acquisition, inference or persistence and grants no source,
withdrawal, cutoff, publication or freeze authenticity. An absent B withdrawal
field stays unknown; the model's fixed six-entrant contract rejects an explicit
withdrawal. P0 labels the input stage, not physical exhibition chronology.
"""
from datetime import date, datetime, timedelta, timezone
import math
import re

SCHEMA = "RACE_AI_BOAT_OBSERVED_PAIRWISE_V1"
JST = timezone(timedelta(hours=9))
SOURCE_FIELDS = {"source_id", "source_url", "source_sha256", "source_rights_ref",
                 "published_at", "captured_at", "evidence_basis"}
RACE_FIELDS = {"race_id", "closed_at", "boats", "preview_available"}
BOAT_FIELDS = {"lane", "racer_registration_id", "motor_no", "boat_no", "name", "grade",
    "national_win_rate", "local_win_rate", "national_top2_rate", "local_top2_rate",
    "motor_top2_rate", "boat_top2_rate", "average_st", "display_time", "preview_course",
    "entry_status"}
B_FEATURES = {
    "national_win_rate": (10, "official_B_national_win_rate_points_v1"),
    "motor_top2_rate": (100, "official_B_motor_top2_percent_v1"),
}
ABSENT = {"recent_mean_finish": "NO_PRIOR_SAMPLES", "recent_mean_st": "NO_PRIOR_SAMPLES",
    "course_mean_finish": "NO_VERIFIED_COURSE", "course_mean_st": "NO_VERIFIED_COURSE",
    "exhibition_time_seconds": "MISSING", "exhibition_start_seconds": "MISSING"}


class ProgramBridgeError(ValueError):
    """Malformed or inconsistent supplied program facts; no source values logged."""


def _fail():
    raise ProgramBridgeError("OBSERVED_PROGRAM_INPUT_REJECTED") from None


def _time(value):
    if type(value) is not str or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value):
        _fail()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail()
    if result.utcoffset() is None:
        _fail()
    return result


def _reference(value):
    if type(value) is not str or not 1 <= len(value) <= 256 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        _fail()


def build_program_snapshot(program_race, source, *, event_date_jst, as_of, race_revision):
    """Return a detached, exact observed-pairwise research snapshot from one B race.

    program_race is the selected race from pinned PR64 normalize_b_snapshot,
    with six complete lane/registration/allocation identities. Optional known
    rate fields may be None/absent. Rates remain in source units; their unknown
    denominators stay None. A fresh producer must independently check analysis
    permission. These CAPTURED_BY_CLAIM inputs are permanently research only.
    """
    try:
        day = date.fromisoformat(event_date_jst)
    except (TypeError, ValueError):
        _fail()
    if day.isoformat() != event_date_jst or type(race_revision) is not int or not 1 <= race_revision <= 10**9:
        _fail()
    if (type(program_race) is not dict or not RACE_FIELDS <= set(program_race)
            or set(program_race) - RACE_FIELDS - {"status"}
            or program_race["preview_available"] is not False
            or ("status" in program_race and program_race["status"] != "READY")):
        _fail()
    rid = program_race["race_id"]
    match = re.fullmatch(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])", rid) if type(rid) is str else None
    if match is None or match[1] != day.strftime("%Y%m%d"):
        _fail()
    cutoff, decision = _time(program_race["closed_at"]), _time(as_of)
    if cutoff.astimezone(JST).date() != day or decision >= cutoff:
        _fail()
    if type(source) is not dict or set(source) != SOURCE_FIELDS:
        _fail()
    expected = f"https://www1.mbrace.or.jp/od2/B/{day:%Y%m}/b{day:%y%m%d}.lzh"
    if (source["source_url"] != expected or type(source["source_sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", source["source_sha256"])
            or source["published_at"] is not None or source["evidence_basis"] != "CAPTURED_BY_CLAIM"
            or _time(source["captured_at"]) > decision):
        _fail()
    _reference(source["source_id"])
    _reference(source["source_rights_ref"])
    rows = program_race["boats"]
    if type(rows) is not list or len(rows) != 6:
        _fail()
    lanes, registrations, motors, boats = set(), set(), set(), set()
    participants = []
    for row in rows:
        if (type(row) is not dict or set(row) - BOAT_FIELDS
                or not {"lane", "racer_registration_id", "motor_no", "boat_no"} <= set(row)):
            _fail()
        lane, registration = row["lane"], row["racer_registration_id"]
        if (type(lane) is not int or not 1 <= lane <= 6 or lane in lanes
                or type(registration) is not str or not re.fullmatch(r"\d{4}", registration)
                or registration in registrations
                or ("entry_status" in row and row["entry_status"] != "listed")):
            _fail()
        for field, seen in (("motor_no", motors), ("boat_no", boats)):
            number = row[field]
            if type(number) is not int or not 1 <= number <= 999 or number in seen:
                _fail()
            seen.add(number)
        # B normalization has no such measurements. Reject injection rather
        # than converting a source column into exhibition or actual course.
        if any(row.get(key) is not None for key in ("average_st", "display_time", "preview_course")):
            _fail()
        lanes.add(lane)
        registrations.add(registration)
        features, missing = {}, dict(ABSENT)
        for feature, (maximum, transform) in B_FEATURES.items():
            value = row.get(feature)
            if value is None:
                missing[feature] = "MISSING"
            else:
                if type(value) not in (int, float) or not 0 <= value <= maximum or not math.isfinite(value):
                    _fail()
                features[feature] = {"value": value, "sample_n": None,
                    "source_id": source["source_id"], "transform_id": transform}
        participants.append({"lane": lane, "registration_no": registration,
                             "features": features, "missing": missing})
    venue = "boatrace-jcd-" + match[2]
    return {"schema": SCHEMA, "scope": "OPERATOR_SUPPLIED_RESEARCH",
        "race_id": f"boat:{event_date_jst}:{venue}:{int(match[3])}",
        "event_date_jst": event_date_jst, "venue": venue, "race_revision": race_revision,
        "race_source_id": source["source_id"],
        "sales_cutoff_at": program_race["closed_at"], "as_of": as_of, "stage": "P0",
        "sources": [{key: source[key] for key in sorted(SOURCE_FIELDS)}],
        "participants": sorted(participants, key=lambda item: item["lane"])}
