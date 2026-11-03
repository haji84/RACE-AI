"""Strict official BOAT RACE numeric-fact normalizer, with NO model admission.

Accepts explicit small source fact observations; it does NOT contact sites.
Mappings are transparent engineering PROXIES, not learned model parameters.
Critically: an unknown original publication time or sample size stays UNKNOWN.
These values CANNOT be pushed into PR71's pre-cutoff, provenance-verified
model input until the separately signed source contract and every required
feature have passed their own validation.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

SCHEMA="RACE_AI_BOAT_FIRSTPARTY_STATS_V1"
OUTPUT="RACE_AI_BOAT_PARTIAL_FEATURE_CANDIDATES_V1"
SOURCE="https://boatrace-biwako.jp/sp/"
TOP={"schema","race_id","source_url","observed_at_claimed",
     "source_view_event_date_jst","source_view_race_no",
     "source_published_at","source_terms_basis","entrants"}
RUNNER={"lane","registration_no","national_score","local_score",
        "motor_number","motor_two_rate_percent"}
MAP={
 "national_score":("ability","points_divide_10_v1",10),
 "local_score":("course_compatibility","points_divide_10_v1",10),
 "motor_two_rate_percent":("motor_form","pct_divide_100_v1",100),
}
MUST_BE_PRE_REVIEW="PUBLIC_FACT_OBSERVATION_NO_AUTO_FETCH_APPROVAL"
class NormalizeError(ValueError):pass

def _dt(value):
    if not isinstance(value,str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)",value):
        raise NormalizeError("complete timezone-aware observation required")
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise NormalizeError("invalid observation timestamp") from exc
    if d.utcoffset() is None:
        raise NormalizeError("naive timestamp")
    return d

def _number(x,lo,hi):
    if type(x) not in (float,int) or not math.isfinite(x) or not lo<=x<=hi:
        raise NormalizeError("invalid official numeric unit/range")
    return float(x)

def candidate_features(observation, *, expected_registration_numbers):
    """Return candidate features only, never a real research model snapshot."""
    if not isinstance(observation,dict) or set(observation)!=TOP or observation.get("schema")!=SCHEMA:
        raise NormalizeError("unknown provider observation schema")
    if not isinstance(observation["race_id"],str) or not re.fullmatch(
            r"boat:\d{4}-\d\d-\d\d:boatrace-jcd-11:(?:[1-9]|1[0-2])",
            observation["race_id"]):
        raise NormalizeError("race identity must match official venue")
    # The venue homepage changes current races without a dated URL.
    # Demand a separately transcribed *page's own* event-day and race index.
    # These are still caller CLAIMS, never authenticated web capture.
    ident=observation["race_id"].split(":")
    if (observation["source_view_event_date_jst"]!=ident[1]
        or type(observation["source_view_race_no"]) is not int
        or observation["source_view_race_no"]!=int(ident[3])):
        raise NormalizeError("stale/mismatched official venue page day or race")
    url=observation["source_url"]
    if url!=SOURCE:
        raise NormalizeError("first-party venue URL must exactly match")
    if observation["source_terms_basis"]!=MUST_BE_PRE_REVIEW:
        raise NormalizeError("public viewing does not approve automated collection")
    captured=_dt(observation["observed_at_claimed"])
    # A page that is visible now may have been published/revised at an
    # unknown time. Never invent a published_at or a sample size.
    if observation["source_published_at"] is not None:
        raise NormalizeError("original provider publication time must be independently verified")
    if not isinstance(expected_registration_numbers,list) or len(expected_registration_numbers)!=6:
        raise NormalizeError("independent 6-entrant roster required")
    if len(set(expected_registration_numbers))!=6 or any(type(x) is not int for x in expected_registration_numbers):
        raise NormalizeError("invalid official expected registration numbers")
    runners=observation["entrants"]
    if not isinstance(runners,list) or len(runners)!=6:
        raise NormalizeError("all six numeric rows must be supplied")
    seen=set()
    out=[]
    for runner in runners:
        if not isinstance(runner,dict) or set(runner)!=RUNNER:
            raise NormalizeError("unrecognized official stats row")
        lane=runner["lane"]
        registration=runner["registration_no"]
        if type(lane) is not int or not 1<=lane<=6 or lane in seen:
            raise NormalizeError("duplicate/invalid boat lane")
        seen.add(lane)
        if type(registration) is not int or registration!=expected_registration_numbers[lane-1]:
            raise NormalizeError("registration number differs from prior official race list")
        motor=runner["motor_number"]
        if type(motor) is not int or not 1<=motor<=99:
            raise NormalizeError("invalid motor number")
        numbers={
            "national_score":_number(runner["national_score"],0,10),
            "local_score":_number(runner["local_score"],0,10),
            "motor_two_rate_percent":_number(runner["motor_two_rate_percent"],0,100)
        }
        candidates=[]
        for original,(key,transform,divisor) in MAP.items():
            normalized=round(numbers[original]/divisor,6)
            candidates.append({
                "feature_key":key,
                "source_field":original,
                "raw_unit":"points_0_to_10" if original!="motor_two_rate_percent" else "percentage_0_to_100",
                "normalized_value":normalized,
                "transform_id":transform,
                "model_value_is_heuristic_not_calibrated":True,
                "published_at":None,
                "captured_at_claimed":observation["observed_at_claimed"],
                "sample_n":None,
                "admitted_as_pre_cutoff_model_feature":False
            })
        out.append({"lane":lane,"registration_no":registration,
                    "motor_number":motor,"candidates":candidates})
    if seen!=set(range(1,7)):
        raise NormalizeError("missing lane")
    out.sort(key=lambda x:x["lane"])
    canonical=json.dumps(observation,sort_keys=True,ensure_ascii=False,
                         separators=(",",":"),allow_nan=False).encode()
    return {"schema":OUTPUT,"source_race_id":observation["race_id"],
            "source_url":url,"source_observation_sha256":hashlib.sha256(canonical).hexdigest(),
            "observed_at_claimed":captured.isoformat(),
            "source_original_published_at":None,
            "source_original_sample_sizes":None,
            "candidates":out,
            "candidate_normalized_value_count":len(out)*len(MAP),
            "source_access_authorized_by_this_code":False,
            "actual_official_sales_cutoff_verified":False,
            "full_model_feature_coverage":False,
            "eligible_for_pr71_model":False,
            "eligible_for_pre_cutoff_freeze":False,
            "eligible_for_official_hit_at_8":False,
            "status":"PARTIAL_AUDIT_ONLY_UNKNOWN_SOURCE_PUBLICATION_TIME"}
