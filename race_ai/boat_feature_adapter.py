"""Offline adapter for existing PR64 race-list facts + independently supplied past form.

No provider networking, no implied permission from verified_source=True,
no historical-result leakage into forecast day, no fabricated missing values.
"""
from datetime import datetime
import math

from .boat_multi_feature_models import (
    SCHEMA, FeatureModelError, validate_snapshot, _finite, _instant
)
from .actions_contract import digest


def _safe_source(value, *, cutoff, admit_source):
    if (not isinstance(value, dict) or
        not all(key in value for key in ("source_ref","published_at","captured_at"))):
        raise FeatureModelError("source evidence missing")
    if _instant(value["published_at"],"source published") > _instant(value["captured_at"],"source captured"):
        raise FeatureModelError("publication after capture")
    if _instant(value["captured_at"],"source captured") > cutoff:
        raise FeatureModelError("source is not prior to forecast")
    if not isinstance(value["source_ref"],str) or not value["source_ref"]:
        raise FeatureModelError("source_ref missing")
    if admit_source is None or admit_source(value, "analysis") is not True:
        raise FeatureModelError("source use not admitted for analysis")
    return value["source_ref"]


def _historical_past(history, current_day, cutoff):
    if not isinstance(history, list) or not 5 <= len(history) <= 30:
        raise FeatureModelError("5..30 actual prior races required")
    stamps=[]
    positions=[]
    starts=[]
    for x in history:
        if not isinstance(x, dict) or set(x)!={"race_id","race_day","finish_position","start_seconds"}:
            raise FeatureModelError("historical fields invalid")
        day=x["race_day"]
        if not isinstance(day,str) or not "2000-01-01" <= day < current_day or not x["race_id"]:
            raise FeatureModelError("future/current-day historical result leakage")
        finish=x["finish_position"]
        if type(finish) is not int or not 1 <= finish <= 6:
            raise FeatureModelError("uncertain historical finish; no imputation allowed")
        start=_finite(x["start_seconds"],0,1,"historical start seconds")
        stamps.append(x["race_id"])
        positions.append(finish)
        starts.append(start)
    if len(stamps)!=len(set(stamps)):
        # Multiple races on the same day need stronger unique IDs than date alone.
        raise FeatureModelError("duplicate historical day; explicit stable race identity required")
    if history != sorted(history,key=lambda row:(row["race_day"],str(row["race_id"])),reverse=True):
        raise FeatureModelError("history must be newest-first")
    weights=[1/(i+1) for i in range(len(history))]
    relative=math.fsum(w*(7-f)/6 for w,f in zip(weights,positions))/sum(weights)
    mean=math.fsum(starts)/len(starts)
    deviation=math.sqrt(math.fsum((x-mean)**2 for x in starts)/len(starts))
    return 100*relative,100*max(0,1-min(1,deviation/.12))


def _reject_market_fields(node):
    """Market/settlement info may not even accompany prediction snapshots."""
    if isinstance(node,dict):
        for k,v in node.items():
            if any(text in str(k).lower() for text in
                   ("odds", "popularity", "payout", "market", "actual_finish",
                    "winning_trifecta", "race_result")):
                raise FeatureModelError("market or result field in pre-race input")
            _reject_market_fields(v)
    elif isinstance(node,list):
        for v in node:
            _reject_market_fields(v)


def from_approved_features(racelist,auxiliary,*,admit_source=None):
    """Build a full six-boat input snapshot from permitted, as-of facts.

    Expects PR64's normalized race-list fields; auxiliary structures are
    independent operator-supplied historical/motor/exhibition/conditions
    data carrying provenance. Does not fetch any of them.
    """
    _reject_market_fields(racelist)
    _reject_market_fields(auxiliary)
    if (not isinstance(racelist,dict) or
        not isinstance(auxiliary,dict) or
        set(auxiliary)!={"as_of","history_by_racer","motor_by_number",
                        "exhibition_by_lane","weather"}):
        raise FeatureModelError("complete auxiliary feature schema required")
    as_of=_instant(auxiliary["as_of"],"as_of")
    cutoff=_instant(racelist.get("closed_at"),"sales cutoff")
    if as_of >= cutoff:
        raise FeatureModelError("cannot use data after sales cutoff")
    if not isinstance(racelist.get("boats"),list) or len(racelist["boats"])!=6:
        raise FeatureModelError("official six-entrant racelist required")
    if not isinstance(racelist.get("source_url"),str):
        raise FeatureModelError("racelist evidence missing")
    primary={"source_ref":racelist["source_url"],
             "published_at":racelist.get("first_observed_at"),
             "captured_at":racelist.get("first_observed_at")}
    _safe_source(primary,cutoff=as_of,admit_source=admit_source)
    rows=[]
    for boat in racelist["boats"]:
        if (not isinstance(boat,dict) or
            not all(k in boat for k in ("lane","racer_registration_id","motor_no","national_win_rate","local_win_rate"))):
            raise FeatureModelError("entrant information incomplete")
        pid=str(boat["racer_registration_id"])
        motor=str(boat["motor_no"])
        lane=boat["lane"]
        h=auxiliary["history_by_racer"].get(pid)
        m=auxiliary["motor_by_number"].get(motor)
        e=auxiliary["exhibition_by_lane"].get(str(lane))
        if any(not isinstance(v,dict) for v in (h,m,e)):
            raise FeatureModelError("historical/motor/exhibition evidence missing")
        sources=[primary,h,m,e]
        refs=[_safe_source(v,cutoff=as_of,admit_source=admit_source) for v in sources]
        first,consistency=_historical_past(h.get("last_races"),racelist["date_jst"],as_of)
        win=_finite(boat["national_win_rate"],0,10,"national win rating")
        local=_finite(boat["local_win_rate"],0,10,"local win rating")
        motor_rate=_finite(m.get("motor_two_place_rate_percent"),0,100,"motor rate")
        time=_finite(e.get("exhibition_time_seconds"),1,20,"exhibition time")
        st=_finite(e.get("exhibition_start_seconds"),0,1,"exhibition start")
        rows.append({
            "lane":lane,"participant_id":pid,
            "features":{
                "ability_rating":win*10,
                "recent_form_rating":first,
                "motor_rating":motor_rate,
                "course_suitability_rating":local*10,
                "exhibition_time_seconds":time,
                "exhibition_start_seconds":st,
                "start_consistency_rating":consistency
            },
            "source_ref":"feature-lineage-sha256:"+digest(refs),
            "published_at":max((v["published_at"] for v in sources),key=lambda value:_instant(value,"published")),
            "captured_at":max((v["captured_at"] for v in sources),key=lambda value:_instant(value,"captured"))
        })
    weather=auxiliary["weather"]
    _safe_source(weather,cutoff=as_of,admit_source=admit_source)
    conditions={k:weather.get(k) for k in ("wind_speed_mps","wave_height_cm",
                                          "wind_relative_to_course","wet_surface_factor")}
    snapshot={
        "schema":SCHEMA,"scope":"OPERATOR_SUPPLIED_RESEARCH",
        "race_id":racelist["race_id"],"venue":racelist["venue"],
        "event_date_jst":racelist["date_jst"],
        "sales_cutoff_at":racelist["closed_at"],"as_of":auxiliary["as_of"],
        "entrants":rows,"conditions":conditions,
        "conditions_source":weather["source_ref"],
        "conditions_published_at":weather["published_at"],
        "conditions_captured_at":weather["captured_at"]
    }
    validate_snapshot(snapshot)
    return snapshot
