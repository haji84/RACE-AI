"""Cross-sport as-of-safe multi-scenario trifecta RESEARCH models.

This is NOT a fitted model, official forecast, live-source adapter, rights grant,
timestamp attestation, result-reconciliation service or betting product.
No network, storage, prices, market odds or actual results are used.
Every numeric input requires individually timestamped evidence; critical missing
inputs fail closed, optional absent features are logged and NEVER imputed.
"""
from __future__ import annotations

from datetime import datetime, date, timezone, timedelta
import hashlib
import itertools
import json
import math
import re

JST=timezone(timedelta(hours=9))
MODEL_IDS=("multisport-factor-interaction-v1","multisport-scenario-ensemble-v1")
SCHEMA="RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1"
KINDS=("boat","keirin","autorace","horse")
STYLES=("front","stalker","closer","allround","unknown")
# Raw categories must be normalized by explicit, documented pre-cutoff transforms
# as feature values in [0,1]. Coefficients below are engineering assumptions,
# not learned weights and must not be presented as measured probabilities.
COMMON_REQUIRED=("ability","recent_form","start_reliability","finishing_power",
                 "course_compatibility","stamina","tactical_adaptability","consistency")
SPORT_REQUIRED={
 "boat":("motor_form","exhibition_performance","start_timing","lane_course_fit"),
 "keirin":("line_coordination","sprint_acceleration","attack_success","bank_fit"),
 "autorace":("handicap_adjustment","trial_performance","machine_reliability","wet_track_fit"),
 "horse":("speed_figure","closing_sectional","jockey_fit","distance_surface_fit"),
}
SPORT_OPTIONAL={
 "boat":("grade_strength","national_win_rate","venue_win_rate","first_place_rate",
         "recent_3race_form","recent_10race_form","motor_place_rate","boat_equipment_form",
         "motor_exchange_effect","turning_performance","exhibition_start","practice_lane",
         "course_entry_prediction","local_course_history","wind_response","wave_response",
         "tide_response","draw_lane_bias","start_false_start_risk","rest_recency",
         "equipment_changes","pressure_handling"),
 "keirin":("line_role","line_depth","home_straight_fit","cornering_power",
           "sprint_peak","last_lap_kick","escape_style","makuri_style","sashi_style",
           "hsb_form","back_count","home_count","start_count","recent_points",
           "recent_win_form","teammate_synergy","opponent_tactical_fit","bank_angle_fit",
           "crosswind_resilience","equipment_fit","schedule_fatigue","position_versatility"),
 "autorace":("handicap_seconds","start_reaction","trial_time","trial_order",
             "dry_track_fit","rain_performance","race_lane_fit","corner_acceleration",
             "straight_speed","engine_form","tire_condition","vehicle_setup",
             "recent_form_3race","recent_form_10race","race_class_strength",
             "driver_risk_consistency","temperature_fit","handicap_traffic_handling",
             "opponent_matchup","track_temperature_response"),
 "horse":("recent_race_speed","recent_3race_form","recent_5race_form","closing_3f",
          "early_pace","middle_pace","pace_style_fit","predicted_pace_fit",
          "barrier_stall_bias","draw_distance_interaction","surface_history",
          "track_history","going_history","distance_history","horse_weight_change",
          "carried_weight_fit","rest_days_fitness","workout_form","paddock_observation",
          "jockey_recent_form","trainer_recent_form","jockey_horse_pair",
          "class_change_fit","age_profile","sex_allowance_fit","pedigree_surface_fit",
          "layoff_risk","running_style","traffic_resilience","field_size_fit",
          "rail_position_fit","track_direction_fit"),
}
ENV_COMMON=("wind_mps","rain_mm_h","humidity_pct","air_temp_c","surface_wetness")
ENV_SPORT={
 "boat":("wave_cm","water_current_strength","crosswind_factor","tide_activity"),
 "keirin":("bank_steepness","wind_exposure","track_roughness","line_complexity"),
 "autorace":("track_temp_c","wet_track_factor","grip_factor","starting_grid_bias"),
 "horse":("going_wetness","course_cushion","rail_position","pace_pressure"),
}
ENV_RANGES={
 "wind_mps":(0,40),"rain_mm_h":(0,150),"humidity_pct":(0,100),
 "air_temp_c":(-30,55),"surface_wetness":(0,1),"wave_cm":(0,250),
 "track_temp_c":(-10,85)
}
FORBIDDEN=("odds","market","payout","dividend","popularity","actual_finish",
           "race_result","winning_ticket","winning_combo","確定","配当","人気")
SYNTHETIC="SYNTHETIC_ONLY"
RESEARCH="OPERATOR_SUPPLIED_RESEARCH"

class ModelInputError(ValueError):
    pass

def canonical(value):
    try:
        return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    except (ValueError,TypeError) as exc:
        raise ModelInputError("canonical finite JSON required") from exc

def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

def moment(v):
    if not isinstance(v,str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)",v):
        raise ModelInputError("explicit timezone-aware timestamp required")
    try:
        dt=datetime.fromisoformat(v.replace("Z","+00:00"))
        if dt.utcoffset() is None:raise ValueError("naive")
        return dt
    except ValueError as exc:
        raise ModelInputError("invalid timestamp") from exc

def exact(v,keys,what):
    if not isinstance(v,dict) or set(v)!=set(keys):
        raise ModelInputError(what+" schema or prohibited field mismatch")

def _number(v,lo,hi,what):
    if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:
        raise ModelInputError("missing / invalid "+what)
    return float(v)

def _no_market(node):
    if isinstance(node,dict):
        for key,val in node.items():
            if any(term in str(key).lower() for term in FORBIDDEN):
                raise ModelInputError("market/result leak in prediction input: "+str(key))
            _no_market(val)
    elif isinstance(node,list):
        for v in node:_no_market(v)

def feature_inventory(sport):
    if sport not in KINDS:raise ModelInputError("sport not supported")
    return {"common_required":COMMON_REQUIRED,
            "sport_required":SPORT_REQUIRED[sport],
            "sport_optional":SPORT_OPTIONAL[sport],
            "environment_required":ENV_COMMON+ENV_SPORT[sport]}

def _observation(item,*,name,asof,permission,scope,is_env=False):
    exact(item,{"value","published_at","captured_at","source_ref",
                "source_rights_ref","sample_n","transform_id"},name)
    bounds=ENV_RANGES.get(name,(0,1)) if is_env else (0,1)
    value=_number(item["value"],*bounds,name)
    pub=moment(item["published_at"]);capture=moment(item["captured_at"])
    if not pub<=capture<=asof:
        raise ModelInputError(name+" published/captured after as_of")
    if not all(isinstance(item[k],str) and 0<len(item[k])<=256 for k in
               ("source_ref","source_rights_ref","transform_id")):
        raise ModelInputError(name+" source and transform evidence absent")
    if type(item["sample_n"]) is not int or not 1<=item["sample_n"]<=10000000:
        raise ModelInputError(name+" sample support absent")
    if scope==RESEARCH and (permission is None or
             permission(item["source_ref"],item["source_rights_ref"],"analysis") is not True):
        raise ModelInputError(name+" analysis rights not externally admitted")
    return value

def validate(raw,*,allow_source=None):
    """No real-source admission without a caller-supplied independent checker.

    The callback is only an interface; passing a fictional always-True gate
    does NOT constitute real rights approval.
    """
    root={"schema","scope","race","participants","environment"}
    exact(raw,root,"snapshot")
    _no_market(raw)
    if raw["schema"]!=SCHEMA or raw["scope"] not in (SYNTHETIC,RESEARCH):
        raise ModelInputError("unadmitted scope/schema")
    race=raw["race"]
    exact(race,{"race_id","sport","venue","event_date_jst","sales_cutoff_at",
                "as_of","distance_m","surface","race_kind","race_revision"},"race")
    sport=race["sport"]
    if sport not in KINDS:raise ModelInputError("unknown sport")
    if not isinstance(race["race_id"],str) or not 8<=len(race["race_id"])<=200:
        raise ModelInputError("stable race ID required")
    if not isinstance(race["venue"],str) or not race["venue"] or len(race["venue"])>128:
        raise ModelInputError("venue required")
    try:
        day=date.fromisoformat(race["event_date_jst"])
        if day.isoformat()!=race["event_date_jst"]:raise ValueError("bad date")
    except (ValueError,TypeError) as exc:
        raise ModelInputError("JST race day invalid") from exc
    asof=moment(race["as_of"]);cutoff=moment(race["sales_cutoff_at"])
    if not asof<cutoff or cutoff.astimezone(JST).date()!=day:
        raise ModelInputError("as_of must precede official sales cutoff on race day")
    if type(race["race_revision"]) is not int or race["race_revision"]<1:
        raise ModelInputError("race revision missing")
    if not isinstance(race["race_kind"],str) or len(race["race_kind"])>90:
        raise ModelInputError("race type invalid")
    if race["surface"] not in {"water","velodrome","track","turf","dirt","synthetic"}:
        raise ModelInputError("unsupported course surface")
    if (sport=="boat" and race["surface"]!="water" or
        sport=="keirin" and race["surface"]!="velodrome" or
        sport=="autorace" and race["surface"]!="track" or
        sport=="horse" and race["surface"] not in ("turf","dirt","synthetic")):
        raise ModelInputError("sport/course mismatch")
    _number(race["distance_m"],100,10000,"distance")
    participants=raw["participants"]
    if not isinstance(participants,list):raise ModelInputError("participants required")
    n=len(participants)
    if sport=="boat" and n!=6 or sport=="keirin" and n not in (7,9) or (
        sport=="autorace" and not 3<=n<=8) or (
        sport=="horse" and not 3<=n<=18):
        raise ModelInputError("sport field size unsupported")
    seen=set()
    missing_by_runner={}
    for p in participants:
        exact(p,{"number","identity","draw","style","group_id","features"},"participant")
        if type(p["number"]) is not int or not 1<=p["number"]<=99 or p["number"] in seen:
            raise ModelInputError("participant number repeated/out of range")
        seen.add(p["number"])
        if not isinstance(p["identity"],str) or len(p["identity"])<1 or len(p["identity"])>100:
            raise ModelInputError("participant identity absent")
        if type(p["draw"]) is not int or not 1<=p["draw"]<=n:
            raise ModelInputError("draw outside declared field")
        if p["style"] not in STYLES:
            raise ModelInputError("unknown/pre-result running style")
        if p["group_id"] is not None and (not isinstance(p["group_id"],str)
                                         or len(p["group_id"])>30):
            raise ModelInputError("group identity invalid")
        if sport!="keirin" and p["group_id"] is not None:
            raise ModelInputError("non-keirin participant group not admitted")
        f=p["features"]
        allowed=set(COMMON_REQUIRED+SPORT_REQUIRED[sport]+SPORT_OPTIONAL[sport])
        if not isinstance(f,dict) or any(k not in allowed for k in f):
            raise ModelInputError("prohibited participant feature")
        mandatory=set(COMMON_REQUIRED+SPORT_REQUIRED[sport])
        missing=mandatory-set(f)
        if missing:
            raise ModelInputError("required features missing: "+",".join(sorted(missing)))
        missing_by_runner[p["number"]]=sorted(allowed-set(f))
        for key,value in f.items():
            _observation(value,name=key,asof=asof,permission=allow_source,scope=raw["scope"])
    env=raw["environment"]
    allowed_environment=set(ENV_COMMON+ENV_SPORT[sport])
    exact(env,allowed_environment,"race environment")
    for key,value in env.items():
        _observation(value,name=key,asof=asof,permission=allow_source,
                     scope=raw["scope"],is_env=True)
    # A sorted order guarantees consistent hash independent of input ordering.
    participants=sorted(participants,key=lambda r:r["number"])
    return {"snapshot":raw,"participants":participants,
            "missing_optional":missing_by_runner,
            "snapshot_sha256":digest(raw),"as_of":asof,"cutoff":cutoff,
            "sport":sport}

def _strength(u):
    return math.exp(max(-8,min(8,u)))

def _utility(participant,*,sport,scenario,conditions,n):
    f={key:item["value"] for key,item in participant["features"].items()}
    env={key:item["value"] for key,item in conditions.items()}
    # All [0,1] input features are observed/normalized before the model.
    # Optional missing features contribute no term; their absence is reported.
    weight={
        "ability":1.35,"recent_form":1.05,"start_reliability":.40,
        "finishing_power":.75,"course_compatibility":.85,"stamina":.30,
        "tactical_adaptability":.65,"consistency":.40,
    }
    per_sport={
      "boat":{"motor_form":.95,"exhibition_performance":.70,"start_timing":.62,
              "lane_course_fit":.75,"motor_place_rate":.15,"wind_response":.12,
              "wave_response":.12,"course_entry_prediction":.12},
      "keirin":{"line_coordination":.85,"sprint_acceleration":.74,"attack_success":.85,
                "bank_fit":.55,"last_lap_kick":.20,"hsb_form":.14,
                "teammate_synergy":.18,"crosswind_resilience":.12},
      "autorace":{"handicap_adjustment":.80,"trial_performance":.83,
                 "machine_reliability":.85,"wet_track_fit":.70,
                 "start_reaction":.20,"dry_track_fit":.15,"temperature_fit":.15},
      "horse":{"speed_figure":1.10,"closing_sectional":.92,"jockey_fit":.53,
               "distance_surface_fit":.82,"early_pace":.15,"workout_form":.16,
               "paddock_observation":.13,"track_history":.14,
               "carried_weight_fit":.14,"pedigree_surface_fit":.13},
    }
    weight.update(per_sport[sport])
    score=math.fsum(weight.get(k,0)*v for k,v in f.items())
    draw=1.0-(participant["draw"]-1)/max(1,n-1)
    wet=max(env["surface_wetness"],
            env.get("wet_track_factor",0),env.get("going_wetness",0))
    rough=min(1,(env["wind_mps"]/24+env["rain_mm_h"]/40+wet)/3)
    if scenario=="FRONT":
        score+=.8*f["start_reliability"]+.4*draw+.30*f.get("early_pace",0)
        if participant["style"]=="front":score+=.22
    elif scenario=="CLOSING":
        score+=.9*f["finishing_power"]+.38*f["stamina"]+.35*f.get("closing_3f",0)
        if participant["style"]=="closer":score+=.25
    elif scenario=="DISRUPTION":
        score+=.9*f["tactical_adaptability"]+.6*f["consistency"]-.25*f["start_reliability"]
        score+=rough*f.get("wet_track_fit",f.get("rain_performance",0))
        if participant["style"]=="allround":score+=.15
    elif scenario!="BASE":
        raise ModelInputError("scenario unknown")
    return _strength(score)

def _pair_synergy(first,second,third,lookup,sport,scenario):
    # Correlation in 1-2-3 placing: same line in Keirin may follow each
    # other; other sports only use pre-race style-based relationships.
    a,b,c=lookup[first],lookup[second],lookup[third]
    val=0.0
    if sport=="keirin" and a["group_id"] is not None:
        if a["group_id"]==b["group_id"]:val+=.12
        if b["group_id"]==c["group_id"]:val+=.09
    if scenario=="FRONT" and a["style"]=="front" and b["style"] in ("stalker","allround"):
        val+=.07
    if scenario=="CLOSING" and c["style"]=="closer":val+=.11
    return math.exp(val)

def _distribution(rows,sport,scenario,env):
    n=len(rows)
    strengths={p["number"]:_utility(p,sport=sport,scenario=scenario,conditions=env,n=n) for p in rows}
    lookup={p["number"]:p for p in rows}
    total=math.fsum(strengths.values())
    choices=[]
    for a,b,c in itertools.permutations(sorted(strengths),3):
        wa,wb,wc=strengths[a],strengths[b],strengths[c]
        pr=wa/total*wb/(total-wa)*wc/(total-wa-wb)
        pr*=_pair_synergy(a,b,c,lookup,sport,scenario)
        choices.append(([a,b,c],pr))
    normalizer=math.fsum(x[1] for x in choices)
    return {tuple(x):p/normalizer for x,p in choices}

def _mix_weights(env):
    e={k:item["value"] for k,item in env.items()}
    wet=max(e["surface_wetness"],e.get("wet_track_factor",0),e.get("going_wetness",0))
    disruption=min(.58,.18+.20*min(1,e["wind_mps"]/20)+
                   .15*min(1,e["rain_mm_h"]/30)+.15*wet)
    closing=.28+.04*min(1,e.get("pace_pressure",e.get("line_complexity",0)))
    front=1-closing-disruption
    if front<0:raise ModelInputError("invalid scenario normalization")
    return {"FRONT":front,"CLOSING":closing,"DISRUPTION":disruption}

def predict(raw,*,allow_source=None):
    data=validate(raw,allow_source=allow_source)
    env=raw["environment"];rows=data["participants"];sport=data["sport"]
    baseline=_distribution(rows,sport,"BASE",env)
    scenarios={key:_distribution(rows,sport,key,env) for key in ("FRONT","CLOSING","DISRUPTION")}
    weights=_mix_weights(env)
    mixed={triple:math.fsum(weights[k]*scenarios[k][triple] for k in weights)
           for triple in baseline}
    outputs={}
    for model,values in ((MODEL_IDS[0],baseline),(MODEL_IDS[1],mixed)):
        ranked=sorted(({"combination":list(triple),"score":p} for triple,p in values.items()),
                      key=lambda x:(-x["score"],x["combination"]))
        expected=len(rows)*(len(rows)-1)*(len(rows)-2)
        if len(ranked)!=expected or len({tuple(v["combination"]) for v in ranked})!=expected or not math.isclose(math.fsum(v["score"] for v in ranked),1.0,rel_tol=0,abs_tol=1e-9):
            raise ModelInputError("full trifecta probability universe invalid")
        v={"model_id":model,"model_version":"0.1.0-UNTRAINED","sport":sport,
           "race_id":raw["race"]["race_id"],"race_revision":raw["race"]["race_revision"],
           "as_of":raw["race"]["as_of"],"cutoff_at":raw["race"]["sales_cutoff_at"],
           "snapshot_sha256":data["snapshot_sha256"],
           "scope":raw["scope"],"official_prediction":False,
           "odds_independent":True,"trained":False,"calibrated":False,
           "confidence_level":"UNVERIFIED",
           "missing_optional_by_participant":data["missing_optional"],
           "scenario_weights":weights if model==MODEL_IDS[1] else None,
           "candidate_count":expected,"candidates":ranked,
           "ordered_top8":[c["combination"] for c in ranked[:8]],
           "source_proof_not_equivalent_to_authorization":True,
           "external_pre_cutoff_receipt":None,"official_result":None,
           "purchase_decision":"NO_BET"}
        v["prediction_sha256"]=digest(v)
        outputs[model]=v
    return outputs
