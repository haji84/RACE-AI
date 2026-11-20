"""Pre-cutoff condition evidence for existing KEIRIN A/B research predictions.

Records are supplied by an owner-authorized upstream collector, not inferred
from racecard win rates or fetched by this module. Validates dates and SHA
receipts, then measures finish-place changes. A fall, absence or quotation by
itself NEVER proves an injury, recovery, causal effect or ability loss.
This heuristic has not been calibrated against real forward results.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
import re

SCHEMA = "RACE_AI_KEIRIN_RIDER_FORM_FALL_EVIDENCE_V1"
SHA = re.compile(r"^[0-9a-f]{64}$")
RACE = re.compile(r"^20[0-9]{10}$")
RESULT_STATES = {"FINISHED", "FALL_FINISHED", "FALL_DNF", "OTHER_DNF", "DNS"}
STATEMENT_SPEAKERS = {"RIDER", "INTERVIEW", "MEDIA"}
TREND_THRESHOLD = 0.15


class FormEvidenceError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise FormEvidenceError(reason)


def instant(value):
    need(type(value) is str, "FORM_SOURCE_CLOCK_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise FormEvidenceError("FORM_SOURCE_CLOCK_INVALID") from None
    need(parsed.utcoffset() is not None, "FORM_SOURCE_CLOCK_AWARE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def day(value):
    need(type(value) is str, "FORM_DATE_REQUIRED")
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise FormEvidenceError("FORM_DATE_INVALID") from None
    need(d.isoformat() == value, "FORM_DATE_INVALID")
    return d


def _receipt(row, source_captures, cutoff):
    need(type(row.get("source_sha256")) is str and
         SHA.fullmatch(row["source_sha256"]) is not None and
         row["source_sha256"] in source_captures,
         "FORM_SOURCE_SHA_UNMATCHED")
    published = instant(row.get("published_at"))
    need(published <= cutoff,
         "FORM_PUBLISHED_AFTER_INPUT_CUTOFF")
    need(published <= source_captures[row["source_sha256"]],
         "FORM_PUBLISHED_AFTER_SOURCE_CAPTURE")


def validate(evidence, *, starters, source_pages, as_of, target_race_id):
    """Reject stale/mismatched/unwitnessed history, never use later results."""
    need(type(evidence) is dict and set(evidence) == {"schema", "as_of", "riders"}
         and evidence["schema"] == SCHEMA, "FORM_SCHEMA_INVALID")
    target = day(target_race_id[:4] + "-" + target_race_id[4:6] + "-" +
                 target_race_id[6:8])
    cutoff = instant(as_of)
    evidence_cutoff = instant(evidence["as_of"])
    need(evidence_cutoff <= cutoff,
         "FORM_CAPTURE_AFTER_PREDICTION_INPUT")
    need(all(type(p) is dict for p in source_pages),
         "FORM_SOURCE_CAPTURE_AFTER_EVIDENCE_ASOF")
    program_captures = {}
    for page in source_pages:
        if page.get("kind") != "PROGRAM":
            continue
        captured = instant(page.get("captured_at"))
        need(captured <= evidence_cutoff,
             "FORM_SOURCE_CAPTURE_AFTER_EVIDENCE_ASOF")
        digest = page["bytes_sha256"]
        program_captures[digest] = min(
            captured, program_captures.get(digest, captured))
    need(type(evidence["riders"]) is list and
         len(evidence["riders"]) <= len(starters),
         "FORM_RIDER_LIST_INVALID")
    seen = set()
    for rider in evidence["riders"]:
        need(type(rider) is dict and
             set(rider) == {"car", "results", "absences", "comments"},
             "FORM_RIDER_FIELDS_INVALID")
        car = rider["car"]
        need(type(car) is int and car in starters and car not in seen,
             "FORM_CAR_NOT_IN_ROSTER_OR_DUPLICATE")
        seen.add(car)
        results = rider["results"]
        need(type(results) is list and len(results) <= 40,
             "FORM_RESULT_COUNT_INVALID")
        observed = set()
        for record in results:
            need(type(record) is dict and set(record) == {
                "race_id", "race_date", "status", "place", "field_size",
                "published_at", "source_sha256"}, "FORM_RESULT_FIELDS_INVALID")
            rid = record["race_id"]
            d = day(record["race_date"])
            need(type(rid) is str and RACE.fullmatch(rid) is not None and
                 rid[:8] == d.strftime("%Y%m%d") and
                 rid != target_race_id and d < target and rid not in observed,
                 "FORM_FUTURE_DUPLICATE_OR_WRONG_RACE")
            observed.add(rid)
            status = record["status"]
            need(type(status) is str and status in RESULT_STATES,
                 "FORM_RESULT_STATUS_INVALID")
            field, place = record["field_size"], record["place"]
            need(type(field) is int and 5 <= field <= 9,
                 "FORM_FIELD_SIZE_INVALID")
            if status in ("FINISHED", "FALL_FINISHED"):
                need(type(place) is int and 1 <= place <= field,
                     "FORM_FINISH_POSITION_INVALID")
            else:
                need(place is None, "FORM_NON_FINISH_CANNOT_HAVE_PLACE")
            _receipt(record, program_captures, evidence_cutoff)
        absences = rider["absences"]
        need(type(absences) is list and len(absences) <= 8,
             "FORM_ABSENCE_COUNT_INVALID")
        for a in absences:
            need(type(a) is dict and set(a) == {
                "start", "end", "published_at", "source_sha256"},
                 "FORM_ABSENCE_FIELDS_INVALID")
            first, last = day(a["start"]), day(a["end"])
            need(first <= last < target and (last-first).days <= 365,
                 "FORM_ABSENCE_PERIOD_INVALID")
            _receipt(a, program_captures, evidence_cutoff)
        comments = rider["comments"]
        need(type(comments) is list and len(comments) <= 12,
             "FORM_COMMENT_COUNT_INVALID")
        for c in comments:
            need(type(c) is dict and set(c) == {
                "speaker", "text", "published_at", "source_sha256"},
                 "FORM_COMMENT_FIELDS_INVALID")
            need(type(c["speaker"]) is str and
                 c["speaker"] in STATEMENT_SPEAKERS and
                 type(c["text"]) is str and
                 1 <= len(c["text"]) <= 300 and
                 all(ord(ch) >= 32 for ch in c["text"]),
                 "FORM_COMMENT_INVALID")
            _receipt(c, program_captures, evidence_cutoff)
    return evidence


def _finish_index(result):
    # 1st -> 1.0, last -> 0.0; comparable only as exploratory result metric.
    return (result["field_size"] - result["place"]) / (result["field_size"] - 1)


def _three_split(rows):
    if len(rows) < 6:
        return None
    prev, recent = rows[-6:-3], rows[-3:]
    return round(sum(_finish_index(x) for x in recent) / 3 -
                 sum(_finish_index(x) for x in prev) / 3, 6)


def _label(change):
    if change is None:
        return "INSUFFICIENT_DATA"
    if change >= TREND_THRESHOLD:
        return "IMPROVING"
    if change <= -TREND_THRESHOLD:
        return "DECLINING"
    return "NO_CLEAR_CHANGE"


def assess(evidence, *, starters, source_pages, as_of, target_race_id):
    """Compute research-only effects. Never infer injury or crash causation."""
    validate(evidence, starters=starters, source_pages=source_pages,
             as_of=as_of, target_race_id=target_race_id)
    target = day(target_race_id[:4] + "-" + target_race_id[4:6] + "-" +
                 target_race_id[6:8])
    output = {}
    by_car = {r["car"]: r for r in evidence["riders"]}
    for car in sorted(starters):
        rider = by_car.get(car)
        if rider is None:
            output[car] = {
                "car": car, "trend": "INSUFFICIENT_DATA",
                "recent_result_change": None, "post_fall_change": None,
                "post_fall_trend": "INSUFFICIENT_DATA",
                "fall_on_record": False, "documented_absence_days": None,
                "return_after_absence_results": None, "comments_count": 0,
                "score_adjustment": 0.0, "effect_on_tactics":
                    "UNKNOWN_NO_ADJUSTMENT"}
            continue
        results = sorted(rider["results"],
                         key=lambda x: (x["race_date"], x["race_id"]))
        # A crash-affected finish is retained as a fall event but is not a
        # normal performance observation. It cannot alone lower form.
        finished = [r for r in results
                    if r["status"] == "FINISHED" and
                    (target - day(r["race_date"])).days <= 180]
        recent_change = _three_split(finished)
        falls = [r for r in results if r["status"] in ("FALL_DNF", "FALL_FINISHED") and
                 (target - day(r["race_date"])).days <= 180]
        last_fall = falls[-1] if falls else None
        fall_change = None
        if last_fall is not None:
            prior = [r for r in finished
                     if r["race_date"] < last_fall["race_date"]]
            after = [r for r in finished
                     if r["race_date"] > last_fall["race_date"]]
            if len(prior) >= 3 and len(after) >= 3:
                fall_change = round(
                    sum(_finish_index(r) for r in after[:3]) / 3 -
                    sum(_finish_index(r) for r in prior[-3:]) / 3, 6)
        # Both are small, explicitly uncalibrated weights. No crash-only
        # penalty: post-fall performance change is observed results, not a
        # medical diagnosis or evidence that the fall caused that change.
        change = 0.0 if recent_change is None else recent_change
        fall_effect = 0.0 if fall_change is None else fall_change
        adjust = round(max(-0.08, min(0.08, .10 * change + .03 * fall_effect)), 6)
        absence_days = None
        returns = None
        if rider["absences"]:
            recent_absence = max(rider["absences"], key=lambda a: a["end"])
            absence_days = (day(recent_absence["end"]) -
                            day(recent_absence["start"])).days + 1
            returns = sum(r["status"] in ("FINISHED", "FALL_FINISHED") and
                          day(r["race_date"]) > day(recent_absence["end"])
                          for r in results)
        output[car] = {
            "car": car, "trend": _label(recent_change),
            "recent_result_change": recent_change,
            "post_fall_change": fall_change,
            "post_fall_trend": _label(fall_change),
            "fall_on_record": last_fall is not None,
            "documented_absence_days": absence_days,
            "return_after_absence_results": returns,
            "comments_count": len(rider["comments"]),
            "score_adjustment": adjust,
            "effect_on_tactics": (
                "OBSERVED_RESULTS_UPWEIGHT_RESEARCH" if adjust > 0
                else "OBSERVED_RESULTS_DOWNWEIGHT_RESEARCH" if adjust < 0
                else "UNKNOWN_NO_ADJUSTMENT"),
        }
    return output
