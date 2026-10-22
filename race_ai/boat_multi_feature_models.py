"""Two independent, odds-free boat trifecta research models.

Offline deterministic inference only. No upstream fetch, source permission grant,
fitted weights, official-prediction claim, receipt signing or auto-betting.

Strict as-of and feature provenance are required; the model NEVER fills
missing values with invented mean data. The training/evaluation data and odds
cannot enter the snapshot through this schema.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
import itertools
import math
import re

from .actions_contract import canonical, digest, stamp

JST = timezone(timedelta(hours=9))
MODEL_IDS = ("boat-comprehensive-v1", "boat-scenario-mixture-v1")
# Expected as-of numeric rating normalized by an independently approved
# provider. No coefficient here has been trained or validated with real races.
FEATURE_RANGES = {
    "ability_rating": (0, 100),
    "recent_form_rating": (0, 100),
    "motor_rating": (0, 100),
    "course_suitability_rating": (0, 100),
    "exhibition_time_seconds": (1, 20),
    "exhibition_start_seconds": (0, 1),
    "start_consistency_rating": (0, 100),
}
CONDITIONS = {"wind_speed_mps": (0, 35), "wave_height_cm": (0, 200),
              "wind_relative_to_course": (-1, 1), "wet_surface_factor": (0, 1)}
EXACT_ENTRANTS = {"lane", "participant_id", "features", "source_ref",
                  "published_at", "captured_at"}
EXACT_ROOT = {"schema", "scope", "race_id", "venue", "event_date_jst",
              "sales_cutoff_at", "as_of", "entrants", "conditions",
              "conditions_source", "conditions_published_at",
              "conditions_captured_at"}
SCHEMA = "RACE_AI_BOAT_MULTI_FEATURE_SNAPSHOT_V1"


class FeatureModelError(ValueError):
    pass


def _only(value, fields, name):
    if not isinstance(value, dict) or set(value) != fields:
        raise FeatureModelError(name + ": exact fields required")


def _finite(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise FeatureModelError("invalid or missing " + name)
    return float(value)


def _instant(value, name):
    try:
        return stamp(value)
    except (TypeError, ValueError) as exc:
        raise FeatureModelError("invalid time: " + name) from exc


def validate_snapshot(raw):
    """Accept only locally supplied source-attested feature snapshots.

    This verifies syntax, as-of availability and numeric ranges but CANNOT
    itself establish source rights or whether a provider's ratings are true.
    """
    _only(raw, EXACT_ROOT, "boat snapshot")
    if raw["schema"] != SCHEMA:
        raise FeatureModelError("snapshot schema mismatch")
    if raw["scope"] not in ("SYNTHETIC_ONLY", "OPERATOR_SUPPLIED_RESEARCH"):
        raise FeatureModelError("only explicitly supplied offline research snapshots")
    if not isinstance(raw["race_id"], str) or not re.fullmatch(r"[a-zA-Z0-9:_-]{8,128}", raw["race_id"]):
        raise FeatureModelError("race identity missing")
    if not isinstance(raw["venue"], str) or not 1 <= len(raw["venue"]) <= 64:
        raise FeatureModelError("venue required")
    try:
        day=date.fromisoformat(raw["event_date_jst"])
        if day.isoformat()!=raw["event_date_jst"]:
            raise ValueError("noncanonical day")
    except (ValueError, TypeError) as exc:
        raise FeatureModelError("event_date_jst invalid") from exc
    cutoff=_instant(raw["sales_cutoff_at"], "sales cutoff")
    as_of=_instant(raw["as_of"], "as_of")
    if not as_of < cutoff or cutoff.astimezone(JST).date()!=day:
        raise FeatureModelError("as_of must be before JST sales cutoff")
    rows=raw["entrants"]
    if not isinstance(rows,list) or len(rows)!=6:
        raise FeatureModelError("exactly six confirmed entrants required")
    seen=set()
    for row in rows:
        _only(row, EXACT_ENTRANTS, "entrant")
        lane=row["lane"]
        if type(lane) is not int or lane not in range(1,7) or lane in seen:
            raise FeatureModelError("entrants must be unique lanes 1..6")
        seen.add(lane)
        if not isinstance(row["participant_id"],str) or not re.fullmatch(r"\d{4}",row["participant_id"]):
            raise FeatureModelError("four-digit racer identity required")
        source=row["source_ref"]
        if not isinstance(source,str) or not 1<=len(source)<=256:
            raise FeatureModelError("source reference missing")
        published=_instant(row["published_at"],"entrant published")
        captured=_instant(row["captured_at"],"entrant captured")
        if not published<=captured<=as_of:
            raise FeatureModelError("entrant feature after as_of")
        _only(row["features"],set(FEATURE_RANGES),"entrant features")
        for name,(low,high) in FEATURE_RANGES.items():
            _finite(row["features"][name],low,high,name)
    _only(raw["conditions"],set(CONDITIONS),"race conditions")
    for name,(low,high) in CONDITIONS.items():
        _finite(raw["conditions"][name],low,high,name)
    if not isinstance(raw["conditions_source"],str) or not raw["conditions_source"]:
        raise FeatureModelError("conditions source missing")
    published=_instant(raw["conditions_published_at"],"conditions published")
    captured=_instant(raw["conditions_captured_at"],"conditions captured")
    if not published<=captured<=as_of:
        raise FeatureModelError("weather / conditions after as_of")
    # No permissive field filtering: unsupported odds, predictions,
    # postrace winner and current-race outcome fields always fail.
    return raw


def _scores(snapshot):
    """Two deliberately distinct feature weighting assumptions, not fitted."""
    weather=snapshot["conditions"]
    breeze=weather["wind_speed_mps"]/12.0
    swell=weather["wave_height_cm"]/50.0
    headwind=weather["wind_relative_to_course"]
    result=[]
    for row in sorted(snapshot["entrants"],key=lambda r:r["lane"]):
        f=row["features"]
        lane=row["lane"]
        ability=f["ability_rating"]/100
        recent=f["recent_form_rating"]/100
        motor=f["motor_rating"]/100
        course=f["course_suitability_rating"]/100
        start=f["start_consistency_rating"]/100
        # Exhibition clock and exhibition ST are lower-is-better,
        # centered on *fixed* research anchors, not derived from race results.
        exhibition=(7.0-f["exhibition_time_seconds"])*0.6
        st=(0.20-f["exhibition_start_seconds"])*3
        lane_prior=(7-lane)/6
        # Model A prioritizes persistent ability + recent trajectory.
        comprehensive=(1.25*ability+1.0*recent+0.75*motor+0.65*course
                       +0.35*start+0.35*exhibition+0.2*st+0.3*lane_prior)
        # Model B uses a mixture of mutually different plausible starts:
        # strong-front, aggressive attack and rough-water resilience.
        calm_front=(0.55*ability+0.45*recent+0.55*motor+0.5*course
                    +0.8*lane_prior+0.55*start+0.55*st+0.25*exhibition)
        attack=(0.75*ability+0.8*recent+0.5*motor+0.35*course
                +0.9*start+0.7*exhibition+0.5*st-0.2*lane_prior)
        rough=(0.9*ability+0.45*recent+0.95*course+0.45*motor
               +0.3*start+0.25*exhibition+0.55*lane_prior
               -0.15*breeze*(7-lane)/6-0.10*swell*lane/6)
        result.append({"lane":lane,"comprehensive":comprehensive,
                       "calm_front":calm_front,"attack":attack,"rough":rough})
    # Weather changes scenario likelihood, never enters features from results.
    # Larger wind / waves increases the rough-weather mixture.
    rough_share=min(0.60,0.15+0.12*breeze+0.10*swell+0.06*abs(headwind))
    attack_share=max(0.12,0.32-0.05*swell+0.04*(1-abs(headwind)))
    calm_share=1-rough_share-attack_share
    if calm_share < 0:
        raise FeatureModelError("invalid scenario weights")
    return result,{"calm_front":calm_share,"attack":attack_share,"rough":rough_share}


def _pl(strengths):
    universe=[]
    total=math.fsum(strengths.values())
    for a,b,c in itertools.permutations(sorted(strengths),3):
        p=(strengths[a]/total)*(strengths[b]/(total-strengths[a]))*(
            strengths[c]/(total-strengths[a]-strengths[b]))
        universe.append(([a,b,c],p))
    if len(universe)!=120 or not math.isclose(math.fsum(p for _,p in universe),1,abs_tol=1e-10):
        raise FeatureModelError("candidate universe not normalized")
    return {tuple(triple): p for triple,p in universe}


def run_models(raw):
    """Return two scored *research* Top8s; NO persistence or betting assertion."""
    s=validate_snapshot(raw)
    by_lane, scenario_shares=_scores(s)
    component={}
    for name in ("comprehensive","calm_front","attack","rough"):
        vals={r["lane"]:math.exp(r[name]) for r in by_lane}
        component[name]=_pl(vals)
    output={}
    for model in MODEL_IDS:
        if model==MODEL_IDS[0]:
            dist=component["comprehensive"]
        else:
            dist={triple:math.fsum(scenario_shares[k]*component[k][triple]
                     for k in scenario_shares) for triple in component["comprehensive"]}
        norm=math.fsum(dist.values())
        candidates=sorted(({"combination":list(triple),"score":p/norm}
                            for triple,p in dist.items()),
                          key=lambda r:(-r["score"],r["combination"]))
        result={
            "model_id":model,
            "model_version":"0.1.0-UNTRAINED",
            "model_status":"RESEARCH_UNTRAINED_NOT_CALIBRATED",
            "validation_status":"UNVALIDATED",
            "scope":s["scope"],
            "race_id":s["race_id"],
            "as_of":s["as_of"],
            "cutoff_at":s["sales_cutoff_at"],
            "snapshot_sha256":digest(s),
            "feature_allowlist_sha256":digest({"entrants":FEATURE_RANGES,"weather":CONDITIONS}),
            "odds_independent":True,
            "official_prediction":False,
            "purchase_decision":"NO_BET",
            "candidates":candidates,
            "ordered_top8":[r["combination"] for r in candidates[:8]],
            "scenario_weights":scenario_shares if model==MODEL_IDS[1] else None,
            "explanation":"Fixed, untrained multi-feature PL ranking" if model==MODEL_IDS[0]
                          else "Three-scenario weather/start/course PL mixture",
            "prediction_probabilities_calibrated":False,
            "persistence_receipt":None,
            "official_result":None,
        }
        result["prediction_sha256"]=digest(result)
        output[model]=result
    return output
