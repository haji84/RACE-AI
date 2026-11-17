"""Dynamic nationwide KEIRIN calendar acceptance for ALL future JST days.

Never hardcode "50 HEX races", a venue count, a specific racing grade or
a 7/9 rider assumption. This adapter consumes externally verified venue
calendar facts supplied as read-only source records. It performs ZERO GETs.

A single provider's partial list cannot prove nationwide completeness.
A separate independently checked day-wide universe certificate is REQUIRED
to call nationwide_coverage_verified=True. Otherwise discovered entries are
kept with explicit HOLD for any potentially missing venues. Every year/day
is an independent cohort; no retrospective 'pre-cutoff' timestamp is invented.
"""
from __future__ import annotations

from datetime import date,datetime
from hashlib import sha256
import json
import re

SCHEMA="RACE_AI_KEIRIN_DYNAMIC_NATIONWIDE_REGISTERED_COHORT_V1"
DAY=re.compile(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
HEX=re.compile(r"^[0-9a-f]{64}$")
RACE=re.compile(r"^20[0-9]{10}$")
VENUE=re.compile(r"^[0-9]{2}$")


class DynamicDayError(ValueError):
    pass


def need(cond,reason):
    if not cond:
        raise DynamicDayError(reason)


def _as_aware(val):
    need(type(val) is str,"DAY_REGISTRATION_CLOCK_REQUIRED")
    try:
        t=datetime.fromisoformat(val.replace("Z","+00:00"))
    except ValueError:
        raise DynamicDayError("DAY_REGISTRATION_CLOCK_INVALID") from None
    need(t.utcoffset() is not None,"DAY_REGISTRATION_CLOCK_NEEDS_TIMEZONE")
    return t


def _verified(callback,*args):
    if not callable(callback):
        return False
    try:
        return callback(*args) is True
    except Exception:
        return False


def canonical(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def digest(obj):
    return sha256(canonical(obj)).hexdigest()


def create_day(*,day_jst,registered_at,
               venue_snapshots,expected_venue_codes=None,
               independently_verify_venue_snapshot=None,
               independently_verify_whole_day=None):
    need(type(day_jst) is str and DAY.fullmatch(day_jst),
         "DYNAMIC_DAY_JST_DATE_REQUIRED")
    try:
        parsed=date.fromisoformat(day_jst)
    except ValueError:
        raise DynamicDayError("DYNAMIC_DAY_INVALID_CALENDAR_DATE") from None
    registration=_as_aware(registered_at)
    need(type(venue_snapshots) is list and
         1<=len(venue_snapshots)<=43,
         "DYNAMIC_VENUE_RECORDS_REQUIRED")
    need(expected_venue_codes is None or
         (type(expected_venue_codes) is list and
          len(expected_venue_codes)==len(set(expected_venue_codes)) and
          all(type(x) is str and VENUE.fullmatch(x) for x in expected_venue_codes)),
         "DAY_VENUE_UNIVERSE_EXPECTATION_INVALID")
    seen=set()
    entries=[]
    sources=[]
    for block in venue_snapshots:
        need(type(block) is dict and set(block)=={
            "venue","venue_code","grade","source_url",
            "source_bytes_sha256","source_available_at",
            "race_numbers","source_race_day"},
            "VENUE_SOURCE_RECORD_SCHEMA_INVALID")
        code=block["venue_code"]
        nums=block["race_numbers"]
        need(type(code) is str and VENUE.fullmatch(code) and
             code not in seen and type(block["venue"]) is str and
             bool(block["venue"].strip()) and
             type(block["grade"]) is str and
             bool(block["grade"].strip()) and
             block["source_race_day"]==day_jst and
             type(block["source_url"]) is str and
             block["source_url"].startswith("https://") and
             type(block["source_bytes_sha256"]) is str and
             HEX.fullmatch(block["source_bytes_sha256"]) and
             type(nums) is list and 1<=len(nums)<=12 and
             all(type(n) is int and 1<=n<=12 for n in nums) and
             len(nums)==len(set(nums)),
             "VENUE_SOURCE_CODE_RACE_UNIVERSE_INVALID")
        available=_as_aware(block["source_available_at"])
        need(available<=registration,"VENUE_SOURCE_NOT_AVAILABLE_BEFORE_REGISTRATION")
        seen.add(code)
        if not _verified(independently_verify_venue_snapshot,block):
            raise DynamicDayError("VENUE_SOURCE_BYTES_NOT_INDEPENDENTLY_AUTHENTICATED")
        sources.append({
            "venue":block["venue"],"code":code,"grade":block["grade"],
            "source_url":block["source_url"],
            "source_bytes_sha256":block["source_bytes_sha256"],
            "source_available_at":block["source_available_at"],
            "race_count":len(nums)})
        for race_no in sorted(nums):
            entries.append({
                "race_id":parsed.strftime("%Y%m%d")+code+f"{race_no:02d}",
                "venue":block["venue"],"venue_code":code,"race_no":race_no,
                "grade":block["grade"],
                "official_cutoff_at":None,
                "A_forecast":"NO_FORECAST",
                "B_six_phase_forecast":"NO_FORECAST",
                "C_prior_follow":"HOLD_OPTIONAL",
                "official_result":"NOT_VERIFIED",
                "missing_forecast_is_not_loss":True})
    if expected_venue_codes is not None:
        need(set(expected_venue_codes)==seen,
             "DAY_SOURCE_MISSING_AN_EXPECTED_VENUE")
    nationwide = (expected_venue_codes is not None and
                  _verified(independently_verify_whole_day,
                            day_jst,sorted(seen),sources))
    document={
        "schema":SCHEMA,"day_jst":day_jst,
        "registered_at":registered_at,
        "captured_venue_count":len(seen),
        "captured_race_count":len(entries),
        "source_venues":sources,
        "expected_venue_codes":sorted(expected_venue_codes)
            if expected_venue_codes is not None else None,
        "nationwide_coverage_independently_verified":nationwide,
        "national_universe_unverified_hold":not nationwide,
        "races":sorted(entries,key=lambda r:(r["venue_code"],r["race_no"])),
        "old_PR71_four_model_dependency":False,
        "actual_forecasts_created_by_registration":0,
        "future_accuracy_claimed":False,
        "source_free_and_private_values_not_published":True,
    }
    document["registry_sha256"]=digest(document)
    return document


def checked_day(doc):
    need(type(doc) is dict and doc.get("schema")==SCHEMA and
         type(doc.get("registry_sha256")) is str and
         HEX.fullmatch(doc["registry_sha256"]),
         "DYNAMIC_DAY_SCHEMA_OR_SHA_REQUIRED")
    got={k:v for k,v in doc.items() if k!="registry_sha256"}
    need(digest(got)==doc["registry_sha256"],
         "DYNAMIC_DAY_IMMUTABLE_SHA_CHANGED")
    need(type(doc.get("races")) is list and
         type(doc.get("captured_race_count")) is int and
         len(doc["races"])==doc["captured_race_count"] and
         len({x["race_id"] for x in doc["races"]})==len(doc["races"]) and
         all(type(row) is dict and RACE.fullmatch(row["race_id"])
             for row in doc["races"]),
         "DYNAMIC_DAY_RACE_COVERAGE_CHANGED")
    return doc
