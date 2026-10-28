"""Pure supplied-beforeinfo projection, not source admission or inference.

The original decision is caller data. No live clock, source, model, receipt or
journal is consulted. Existing publication and durable-receipt gates stay closed.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import re

from .boat_existing_asset_integration import ReuseGateError, build_readiness

SCHEMA = "RACE_AI_BOAT_BEFOREINFO_DISPLAY_CASE_V1"
RIGHTS_REF = "user-confirmation-2026-10-15-official-facts"
JST = timezone(timedelta(hours=9))
MAX_BYTES = 1_048_576
ST_MISSING = {"F", "L", "MISSING", "ABSENT", "PENDING", "UNKNOWN"}


class BeforeinfoCaseError(ValueError):
    """The supplied source objects cannot safely form this research case."""


def _require(condition, reason):
    if not condition:
        raise BeforeinfoCaseError(reason)


def _copy(value):
    """Reject unsupported trees before JSON can coerce keys or values."""
    active, count = set(), 0

    def visit(node, depth):
        nonlocal count
        count += 1
        _require(depth <= 12 and count <= 10000, "input complexity exceeds bound")
        kind = type(node)
        if kind in (dict, list):
            _require(id(node) not in active, "cyclic input")
            active.add(id(node))
            if kind is dict:
                for key, item in node.items():
                    _require(type(key) is str, "string JSON keys required")
                    visit(key, depth + 1)
                    visit(item, depth + 1)
            else:
                for item in node:
                    visit(item, depth + 1)
            active.remove(id(node))
        elif kind is str:
            _require(len(node) <= 4096, "input string exceeds bound")
        elif kind is int:
            _require(abs(node) <= 10**15, "input integer exceeds bound")
        elif kind is float:
            _require(math.isfinite(node), "finite input required")
        else:
            _require(node is None or kind is bool, "plain JSON types required")

    visit(value, 0)
    try:
        raw = _canonical(value)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise BeforeinfoCaseError("canonical JSON required") from exc
    _require(len(raw) <= MAX_BYTES, "input bytes exceed bound")
    return json.loads(raw)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _keys(value, required, optional=()):
    _require(type(value) is dict and set(required) <= set(value)
             and not set(value) - set(required) - set(optional), "unexpected source fields")


def _text(value, maximum=200):
    _require(type(value) is str and 0 < len(value) <= maximum, "invalid source text")


def _hex(value):
    _require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None,
             "invalid source digest")


def _number(value, low, high):
    _require(type(value) in (int, float) and low <= value <= high
             and math.isfinite(value), "invalid observed number")


def _integer(value, low, high):
    _require(type(value) is int and low <= value <= high, "invalid source integer")


def _stamp(value):
    _require(type(value) is str, "timestamp required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BeforeinfoCaseError("invalid timestamp") from exc
    _require(result.utcoffset() is not None, "timestamp offset required")
    return result


def _jst_day(value):
    try:
        return value.astimezone(JST).date()
    except OverflowError as exc:
        raise BeforeinfoCaseError("timestamp outside JST calendar") from exc


def _identities(rows):
    _require(type(rows) is list and len(rows) == 6, "six source participants required")
    seen = {}
    for row in rows:
        _require(type(row) is dict, "participant object required")
        lane, pid = row.get("lane"), row.get("racer_registration_id")
        _integer(lane, 1, 6)
        _require(type(pid) is str and re.fullmatch(r"[0-9]{4}", pid) is not None,
                 "ASCII registration required")
        _require(lane not in seen and pid not in seen.values(), "duplicate participant")
        seen[lane] = pid
    return seen


def _program(b, decision):
    _keys(b, {"race_id", "venue", "date_jst", "closed_at", "source_url",
        "first_observed_at", "source_archive_sha256", "source_original_published_at",
        "original_publication_verification", "source_rights_verified", "source_use_status", "boats"})
    rid = b["race_id"]
    _require(type(rid) is str and re.fullmatch(
        r"[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])", rid) is not None,
        "canonical race ID required")
    day_text = rid[:4] + "-" + rid[4:6] + "-" + rid[6:8]
    try:
        day = date.fromisoformat(day_text)
    except ValueError as exc:
        raise BeforeinfoCaseError("invalid event date") from exc
    _require(b["date_jst"] == day_text and b["venue"] == rid[9:11], "B event identity conflict")
    captured, cutoff = _stamp(b["first_observed_at"]), _stamp(b["closed_at"])
    _require(captured <= decision < cutoff and _jst_day(cutoff) == day
             and _jst_day(decision) == day, "B decision/cutoff conflict")
    _require(b["source_url"] == f"https://www1.mbrace.or.jp/od2/B/{rid[:6]}/b{rid[2:8]}.lzh",
             "B source URL differs")
    _hex(b["source_archive_sha256"])
    if b["source_original_published_at"] is not None:
        _require(_stamp(b["source_original_published_at"]) <= captured, "B publication after capture")
    _require(b["original_publication_verification"] is False and b["source_rights_verified"] is False
             and b["source_use_status"] == "CANDIDATE_NOT_ADMITTED", "B authority claim unsupported")
    identities = _identities(b["boats"])
    for row in b["boats"]:
        _keys(row, {"lane", "racer_registration_id", "motor_no", "national_win_rate",
                    "local_win_rate", "motor_top2_rate"})
        _integer(row["motor_no"], 1, 999)
        _number(row["national_win_rate"], 0, 10)
        _number(row["local_win_rate"], 0, 10)
        _number(row["motor_top2_rate"], 0, 100)
    return day, cutoff, identities


def _st(row):
    status, value = row["preview_st_status"], row["preview_st"]
    _require(type(status) is str and status in ST_MISSING | {"OK"}, "invalid ST status")
    if status == "OK":
        _number(value, 0, 1)
    else:
        _require(value is None, "missing ST cannot carry a number")
    if "preview_raw_st" in row:
        raw = row["preview_raw_st"]
        _require(type(raw) is str and len(raw) <= 16, "invalid raw ST")
        if status == "OK":
            _require(re.fullmatch(r"0?\.[0-9]{2}", raw) is not None
                     and float(raw) == value, "raw/numeric ST conflict")
        elif status in {"F", "L"}:
            _require(re.fullmatch(status + r"(?:0?\.[0-9]{2})?", raw) is not None,
                     "raw F/L disposition conflict")
        else:
            _require(raw in {"", "-", "--", "―", "－"}, "raw missing ST conflict")


def _weather(weather):
    fields = {"air_temperature_c", "water_temperature_c", "wind_speed_mps", "wave_height_cm",
        "wind_direction_source_code", "weather_label", "source_reported_local_time",
        "reported_at", "freshness_status"}
    _keys(weather, set(), fields)
    for key, low, high in (("air_temperature_c", -40, 60), ("water_temperature_c", -10, 60),
                           ("wind_speed_mps", 0, 35), ("wave_height_cm", 0, 200)):
        if weather.get(key) is not None:
            _number(weather[key], low, high)
    if weather.get("wind_direction_source_code") is not None:
        _integer(weather["wind_direction_source_code"], 0, 99)
    if weather.get("weather_label") is not None:
        _text(weather["weather_label"], 60)
    local = weather.get("source_reported_local_time")
    if local is not None:
        _require(type(local) is str and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", local) is not None,
                 "invalid source weather clock")
    _require(weather.get("reported_at") is None and weather.get("freshness_status",
        "UNKNOWN_SOURCE_TIME_HAS_NO_DATE") == "UNKNOWN_SOURCE_TIME_HAS_NO_DATE",
        "weather publication claim unsupported")


def _preview(p, b, identities, decision, day, cutoff):
    _keys(p, {"race_id", "kind", "status", "body_identity_verified", "closed_at", "captured_at",
        "source_url", "source_sha256", "information_phase", "data"},
        {"schema_version", "snapshot_id", "available_at", "saved_at", "upstream_published_at",
         "rights_review", "eligible_pre_race", "storage_eligible_pre_race", "observed_racers", "missing_reason"})
    _require(p["race_id"] == b["race_id"] and p["kind"] == "beforeinfo"
             and p["status"] in ("AVAILABLE", "PENDING")
             and p["body_identity_verified"] is True
             and p["information_phase"] == "pre_race_observation", "beforeinfo identity/phase invalid")
    rid = b["race_id"]
    _require(p["source_url"] == "https://www.boatrace.jp/owpc/pc/race/beforeinfo"
             + f"?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}", "beforeinfo URL differs")
    _hex(p["source_sha256"])
    if "snapshot_id" in p:
        _hex(p["snapshot_id"])  # Retained ID shape, not provider/receipt authentication.
    if "schema_version" in p:
        _integer(p["schema_version"], 1, 1)
    if "rights_review" in p:
        _require(p["rights_review"] == RIGHTS_REF, "unsupported declared rights reference")
    for flag in ("eligible_pre_race", "storage_eligible_pre_race"):
        if flag in p:
            _require(p[flag] is True, "contradictory pre-race eligibility claim")
    if "missing_reason" in p:
        _require(p["status"] == "PENDING" and p["missing_reason"] == "OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID",
                 "unsupported missing reason")
    captured = _stamp(p["captured_at"])
    _require(_stamp(p["closed_at"]) == cutoff and captured <= decision < cutoff
             and _jst_day(captured) == day, "preview timing conflict")
    if p.get("upstream_published_at") is not None:
        _require(_stamp(p["upstream_published_at"]) <= captured, "preview publication after capture")
    clocks = {}
    for key in ("available_at", "saved_at"):
        if key in p:
            clocks[key] = _stamp(p[key])
            _require(captured <= clocks[key] <= decision, "preview availability/save conflict")
    if len(clocks) == 2:
        _require(clocks["available_at"] <= clocks["saved_at"], "preview save precedes availability")
    if p["status"] == "PENDING":
        observed = p.get("observed_racers")
        _require(_identities(observed) == identities, "pending identity grid conflict")
        for row in observed:
            _keys(row, {"lane", "racer_registration_id"}, {"name"})
            if "name" in row:
                _text(row["name"])
    else:
        _require("observed_racers" not in p, "unexpected observed grid")
    data = p["data"]
    if data is None:
        _require(p["status"] == "PENDING", "available preview needs data")
        return
    _keys(data, {"boats", "weather"})
    _require(_identities(data["boats"]) == identities, "preview participant conflict")
    for row in data["boats"]:
        _keys(row, {"lane", "racer_registration_id", "display_time", "preview_st", "preview_st_status"},
              {"name", "tilt", "preview_raw_st", "preview_course", "actual_course"})
        if row["display_time"] is not None:
            _number(row["display_time"], .01, 20)
        _st(row)
        if "name" in row:
            _text(row["name"])
        if row.get("tilt") is not None:
            _number(row["tilt"], -10, 10)
        if row.get("preview_course") is not None:
            _integer(row["preview_course"], 1, 6)
        _require(row.get("actual_course") is None, "actual course is not pre-race input")
    _weather(data["weather"])


def project_beforeinfo_display_case(racelist, preview_snapshot, *, as_of,
                                    input_pins, source_rights_ref):
    """Bind supplied identities and observations to a static display-only case.

    Input pins hash canonical objects, not original file or HTML bytes. A caller
    must separately bind its retained containers/parents and source-purpose
    authority. This function grants none of those capabilities.
    """
    b, p, pins, as_of, source_rights_ref = _copy(
        [racelist, preview_snapshot, input_pins, as_of, source_rights_ref])
    _keys(pins, {"racelist_sha256", "preview_snapshot_sha256"})
    for value in pins.values():
        _hex(value)
    _require(pins == {"racelist_sha256": _hash(b), "preview_snapshot_sha256": _hash(p)},
             "input digest differs")
    _require(source_rights_ref == RIGHTS_REF, "unsupported declared rights reference")
    decision = _stamp(as_of)
    day, cutoff, identities = _program(b, decision)
    # Validate the WHOLE supplied tree before the normalizer's PENDING return.
    _preview(p, b, identities, decision, day, cutoff)
    try:
        readiness = build_readiness(b, {}, preview_snapshot=p, as_of=as_of)
    except (ReuseGateError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise BeforeinfoCaseError("existing preview readiness gate rejected input") from exc
    manifest = {"schema": SCHEMA, "input_pins": dict(pins), "race_id": b["race_id"],
        "event_date_jst": b["date_jst"], "sales_cutoff_at": b["closed_at"], "as_of": as_of,
        "source_rights_ref": source_rights_ref,
        "participants": [{"lane": lane, "registration_no": identities[lane]} for lane in range(1, 7)],
        "sources": {
            "B": {"source_url": b["source_url"], "source_sha256": b["source_archive_sha256"],
                  "captured_at": b["first_observed_at"], "published_at": b["source_original_published_at"]},
            "preview": {"source_url": p["source_url"], "source_sha256": p["source_sha256"],
                "captured_at": p["captured_at"], "published_at": p.get("upstream_published_at"),
                **{key: p[key] for key in ("available_at", "saved_at") if key in p}}}}
    observed = {r["lane"]: r for r in p["data"]["boats"]} if p["data"] is not None else {}
    st, missing, outside = {}, {}, []
    for lane in range(1, 7):
        row = observed.get(lane)
        status = row["preview_st_status"] if row else "PENDING"
        st[str(lane)] = {"status": status, "value": row["preview_st"] if row else None,
            "missing_reason": None if status == "OK" else
                "NON_NUMERIC_F_L" if status in {"F", "L"} else "NOT_PUBLISHED"}
        value = row["display_time"] if row else None
        if p["status"] == "PENDING" or value is None:
            missing[str(lane)] = "NOT_PUBLISHED"
        elif value < 1:
            outside.append(lane)
    status = ("BLOCKED_DISPLAY_NOT_COMPLETE" if missing else
              "BLOCKED_DISPLAY_OUTSIDE_PROJECTOR_RANGE" if outside else "READY_DISPLAY_RESEARCH_CASE")
    case = None
    if status == "READY_DISPLAY_RESEARCH_CASE":
        case = {"case_id": b["race_id"], "stage": "P1", "legacy": {"boats": [
            {"lane": r["lane"], "national_win_rate": r["national_win_rate"],
             "display_time_s": observed[r["lane"]]["display_time"]}
            for r in sorted(b["boats"], key=lambda r: r["lane"])]},
            "source_manifest_sha256": _hash(manifest)}
    return {"schema": SCHEMA, "status": status, "case": case, "source_manifest": manifest,
        "diagnostics": {"preview_st_by_lane": st, "display_missing_by_lane": missing,
            "display_outside_projector_range_lanes": outside,
            "legacy_readiness_status": readiness["status"]},
        "research_only": True, "forecast_executed": False, "official_prediction": False,
        "formal_hit_at_8_eligible": False, "historical_pre_cutoff_freeze_claimed": False,
        "actual_publication_verified_by_module": False, "actual_rights_verified_by_module": False,
        "individual_receipt_verified": False}
