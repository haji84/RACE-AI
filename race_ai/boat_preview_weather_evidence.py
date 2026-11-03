"""Pre-race exhibition/ST, wind-angle and wave evidence for existing PR71.

No changes to PR71 feature meanings or heuristics. Explicit null/missing
states and source/geometry attestations. A wind icon number is NOT degrees.
Water 'wet_surface_factor' is undefined until separately documented.
"""
from __future__ import annotations

from datetime import datetime
import math

SCHEMA = "RACE_AI_BOAT_PREVIEW_WEATHER_EVIDENCE_GATE_V1"
ST_MISSING={"F","L","MISSING","ABSENT","PENDING","UNKNOWN"}
MISSING_TYPES={"NOT_PUBLISHED","NON_NUMERIC_F_L","NOT_APPLICABLE",
               "RIGHTS_BLOCKED","SOURCE_NOT_VERIFIED",
               "SOURCE_TIMESTAMP_UNKNOWN","GEOMETRY_UNKNOWN"}
class PreviewGateError(ValueError):pass

def _moment(v):
    if not isinstance(v,str):raise PreviewGateError("time missing")
    try:t=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as e:raise PreviewGateError("invalid timestamp") from e
    if t.utcoffset() is None:raise PreviewGateError("offset required")
    return t

def _num(v,lo,hi):
    if type(v) not in (float,int) or not math.isfinite(v) or not lo<=v<=hi:
        raise PreviewGateError("out-of-range or absent observed feature")
    return float(v)

def normalize_existing_PR64_beforeinfo(snapshot, *, as_of, source_published_at=None,
                                       reviewed_source_rights=None):
    """Return candidate values + missingness, without source promotion.

    Existing PR64 parse_update output is accepted only when capture <= as_of.
    Unknown upstream published_at does NOT default to captured_at. Rights for
    analytical use need an actual reviewed reference, not a yes/no flag.
    """
    if not isinstance(snapshot,dict):
        raise PreviewGateError("PR64 beforeinfo snapshot required")
    if snapshot.get("kind")!="beforeinfo" or snapshot.get("status") not in ("PENDING","AVAILABLE"):
        raise PreviewGateError("actual beforeinfo parse_update contract required")
    if snapshot.get("body_identity_verified") is not True:
        raise PreviewGateError("source body race/date identity unproven")
    captured=_moment(snapshot.get("captured_at"))
    cutoff=_moment(snapshot.get("closed_at"))
    decision=_moment(as_of)
    if not captured<=decision<cutoff:
        raise PreviewGateError("beforeinfo not available by decision before cutoff")
    source_ok=False
    if source_published_at is not None:
        source_ok=_moment(source_published_at)<=captured
    if source_published_at is not None and not source_ok:
        raise PreviewGateError("source publication after capture")
    rights_ok=(isinstance(reviewed_source_rights,str)
               and bool(reviewed_source_rights.strip()))
    if snapshot["status"]=="PENDING":
        return {"schema":SCHEMA,"race_id":snapshot["race_id"],
                "observed_display_count":0,"observed_ST_numeric_count":0,
                "missing_by_lane":{str(i):{"exhibition_time_seconds":"NOT_PUBLISHED",
                                           "exhibition_start_seconds":"NOT_PUBLISHED"}
                                   for i in range(1,7)},
                "observed_exhibition_by_lane":{},
                "observed_weather":{},
                "actual_publication_verified_by_module":False,
                "actual_rights_verified_by_module":False,
                "fully_admitted_for_PR71":False}
    data=snapshot.get("data")
    if not isinstance(data,dict) or not isinstance(data.get("boats"),list):
        raise PreviewGateError("six beforeinfo participants required")
    rows=data["boats"]
    if len(rows)!=6 or {r.get("lane") for r in rows}!=set(range(1,7)):
        raise PreviewGateError("six unique lanes required")
    observed={}
    missing={}
    numeric_st=0
    for row in rows:
        lane=row["lane"]
        pid=row.get("racer_registration_id")
        if not isinstance(pid,str) or len(pid)!=4 or not pid.isdecimal():
            raise PreviewGateError("source participant identity missing")
        found={}
        gaps={}
        timing=row.get("display_time")
        if timing is not None:
            found["exhibition_time_seconds"]=_num(timing,.01,20)
        else:gaps["exhibition_time_seconds"]="NOT_PUBLISHED"
        st_status=row.get("preview_st_status")
        st=row.get("preview_st")
        if st_status=="OK":
            found["exhibition_start_seconds"]=_num(st,0,1)
            numeric_st+=1
        elif st_status in ST_MISSING and st is None:
            gaps["exhibition_start_seconds"]=(
                "NON_NUMERIC_F_L" if st_status in ("F","L")
                else "NOT_PUBLISHED")
        else:
            raise PreviewGateError("ST disposition conflicts with numeric source")
        observed[str(lane)]={"registration_id":pid,"features":found}
        missing[str(lane)]=gaps
    weather=data.get("weather") or {}
    wind=weather.get("wind_speed_mps")
    waves=weather.get("wave_height_cm")
    metrics={}
    if wind is not None:metrics["wind_speed_mps"]=_num(wind,0,35)
    if waves is not None:metrics["wave_height_cm"]=_num(waves,0,200)
    # 'is-windN' source-class is not a true north-referenced bearing.
    direction_code=weather.get("wind_direction_source_code")
    report={
        "schema":SCHEMA,"race_id":snapshot["race_id"],
        "observed_display_count":sum(
            "exhibition_time_seconds" in x["features"] for x in observed.values()),
        "observed_ST_numeric_count":numeric_st,
        "missing_by_lane":missing,
        "observed_exhibition_by_lane":observed,
        "observed_weather":metrics,
        "source_wind_direction_code_uninterpreted":direction_code,
        "missing_environment":{
            **({"wind_speed_mps":"NOT_PUBLISHED"} if wind is None else {}),
            **({"wave_height_cm":"NOT_PUBLISHED"} if waves is None else {}),
            "wind_relative_to_course":"GEOMETRY_UNKNOWN",
            "wet_surface_factor":"SOURCE_NOT_VERIFIED"},
        "source_publication_time_available":source_ok,
        "source_purpose_rights_reference_present":rights_ok,
        "actual_publication_verified_by_module":False,
        "actual_rights_verified_by_module":False,
        "fully_admitted_for_PR71":False
    }
    return report

def relative_wind_to_course(*, wind_from_true_degrees,
                            outbound_race_course_true_degrees,
                            wind_evidence, course_geometry_evidence):
    """Physical headwind index cos(wind-from - course-heading), in [-1,+1].

    Positive = headwind, negative = tailwind. This requires true-degree
    compass readings and separately reviewed geometry records. It CANNOT
    derive a heading from CSS wind icons or wave height.
    """
    for evidence in (wind_evidence,course_geometry_evidence):
        if not isinstance(evidence,dict) or set(evidence)!={
            "source_ref","observed_or_valid_at","captured_at",
            "source_rights_ref","reviewed_by","review_reference","coordinate_system"
        }:
            raise PreviewGateError("independently documented coordinate evidence missing")
        if evidence["coordinate_system"]!="TRUE_NORTH_DEGREES":
            raise PreviewGateError("icon/code or magnetic heading not true bearing")
        if not all(isinstance(evidence[key],str) and evidence[key].strip() for key in (
            "source_ref","source_rights_ref","reviewed_by","review_reference")):
            raise PreviewGateError("coordinate source or review not documented")
        if not _moment(evidence["observed_or_valid_at"])<=_moment(evidence["captured_at"]):
            raise PreviewGateError("future wind/geometry provenance")
    a=_num(wind_from_true_degrees,0,360)
    b=_num(outbound_race_course_true_degrees,0,360)
    return {"wind_relative_to_course":round(math.cos(math.radians(a-b)),8),
            "provenance":{"wind_source_ref":wind_evidence["source_ref"],
                          "geometry_source_ref":course_geometry_evidence["source_ref"]},
            "model_input_meaning":"HEADWIND_POSITIVE_TAILWIND_NEGATIVE",
            "verified_for_model_admission":False}
