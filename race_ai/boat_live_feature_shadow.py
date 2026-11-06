"""C-lite additional official racer features, separately versioned from A/B.

Uses verified *today-available* local win-rate and average race ST from the
same pre-cutoff racelist, and the optional official exhibition ST. Young or
sparse racers are NEVER assigned a negative age bonus. This is an untrained,
uncalibrated 120-ticket shadow, not player-specific tactics history.
"""
from __future__ import annotations

from .boat_ab_shadow import _valid,_rank,_digest,_time,COURSE_LOG_BONUS,MOTOR_LOG_PER_PERCENT_POINT
from datetime import timedelta
import math
import re

MODEL_ID="boat-local-start-course-shadow-v0.1-UNTRAINED"


def _need(p,msg):
    if not p:raise ValueError(msg)


def build_live_feature_shadow(base_source, extra, generated_at, *, parameters=None):
    if parameters is not None:
        from .existing_boat_parameter_adapters import validate_parameters
        parameters = validate_parameters(MODEL_ID, parameters)
    boats=_valid(base_source,generated_at)
    _need(isinstance(extra,dict) and set(extra)=={
        "race_id","observed_at","source_sha256","participants"},
          "exact same current-race extra feature evidence required")
    _need(extra["race_id"]==base_source["race_id"]
          and re.fullmatch(r"[a-f0-9]{64}",extra["source_sha256"] or "")
          and _time(extra["observed_at"])<=_time(generated_at)
          and _time(extra["observed_at"])< _time(base_source["cutoff_at"]),
          "new features must be observed before the prediction")
    values=extra["participants"]
    _need(isinstance(values,list) and len(values)==6,
          "six current official racer facts required")
    by_lane={}
    for r in values:
        _need(isinstance(r,dict) and set(r)=={
             "lane","racer_id","local_win_rate","average_st",
             "exhibition_st","exhibition_st_status"},
              "exact observed source features required")
        lane=r["lane"]
        _need(type(lane) is int and lane in range(1,7) and lane not in by_lane
              and isinstance(r["racer_id"],str) and re.fullmatch(r"\d{4}",r["racer_id"]),
              "identical official six entrants required")
        for key,low,high in (("local_win_rate",0,10),
                             ("average_st",0,1),("exhibition_st",0,1)):
            n=r[key]
            _need(n is None or type(n) in (float,int) and math.isfinite(n) and low<=n<=high,
                  "unsupported or nonfinite official feature")
        _need(r["exhibition_st_status"] in ("OK","PENDING","F","L"),
              "official exhibition start status must be explicit")
        _need((r["exhibition_st_status"]=="OK")==(r["exhibition_st"] is not None),
              "exhibition ST missing is not numeric zero")
        by_lane[lane]=r
    _need(set(by_lane)==set(range(1,7)) and
          all(by_lane[b["lane"]]["racer_id"]==b["racer_id"] for b in boats),
          "racelist and exhibition ST racer IDs disagree")
    motor_mean=math.fsum(x["motor_two_place_rate_percent"] for x in boats)/6
    exhibit_mean=math.fsum(x["exhibition_time_seconds"] for x in boats)/6
    observed_race_st=[r["average_st"] for r in by_lane.values() if r["average_st"] is not None]
    observed_preview_st=[r["exhibition_st"] for r in by_lane.values() if r["exhibition_st"] is not None]
    average_st_mean=math.fsum(observed_race_st)/len(observed_race_st) if len(observed_race_st)>=2 else None
    preview_st_mean=math.fsum(observed_preview_st)/len(observed_preview_st) if len(observed_preview_st)>=2 else None
    strengths=[]
    status=[]
    for b in boats:
        item=by_lane[b["lane"]]
        national=b["national_win_rate"]
        base_rate=max(national if national is not None else 1.0,.01)
        score=(math.log(base_rate)+exhibit_mean-b["exhibition_time_seconds"]
                +COURSE_LOG_BONUS[b["lane"]-1]
                +MOTOR_LOG_PER_PERCENT_POINT*(b["motor_two_place_rate_percent"]-motor_mean))
        if parameters is not None:
            score=(parameters['log_national_rate']*math.log(base_rate) +
                   parameters['exhibition_delta']*(exhibit_mean-b['exhibition_time_seconds']) +
                   parameters['course_log_bonus_'+str(b['lane'])] +
                   parameters['motor_deviation']*(b['motor_two_place_rate_percent']-motor_mean))
        used=[]
        if item["local_win_rate"] is not None and national is not None:
            score+=(.08 if parameters is None else parameters['local_rate_delta'])*(item["local_win_rate"]-national)
            used.append("LOCAL_WIN_RATE")
        if average_st_mean is not None and item["average_st"] is not None:
            score+=(2. if parameters is None else parameters['average_st_delta'])*(average_st_mean-item["average_st"])
            used.append("ACTUAL_AVERAGE_ST")
        if preview_st_mean is not None and item["exhibition_st"] is not None:
            score+=(.65 if parameters is None else parameters['exhibition_st_delta'])*(preview_st_mean-item["exhibition_st"])
            used.append("EXHIBITION_ST_OBSERVATION")
        # Missing data are neutral to this *experimental* model, explicitly
        # reported per racer, not assumed to be zero or a disqualifier.
        strengths.append(math.exp(max(-20.,min(20.,score))))
        status.append({"lane":b["lane"],"racer_id":b["racer_id"],
                       "features_used":used,
                       "historic_course_tactics_available":False})
    full=_rank(strengths,stable=parameters is not None)
    output={"schema":"RACE_AI_BOAT_CURRENT_FEATURE_SHADOW_V1",
            "model_id":MODEL_ID,"race_id":base_source["race_id"],
            "cutoff_at":base_source["cutoff_at"],"as_of":generated_at,
            "source_snapshot_sha256":_digest(base_source),
            "extra_source_sha256":extra["source_sha256"],
            "features":status,
            "full_120":[{"ticket":"-".join(map(str,r["ticket"])),
                         "score":r["score"]} for r in full],
            "top8":[{"ticket":"-".join(map(str,r["ticket"])),
                     "score":r["score"]} for r in full[:8]],
            "top8_model_score_mass":math.fsum(x["score"] for x in full[:8]),
            "method_and_entry_historical_truth":"NOT_AVAILABLE_TO_THIS_MODEL",
            "untrained":True,"calibrated":False,"odds_used":False,
            "auto_promoted":False,"betting_decision":"NO_BET"}
    if parameters is not None:
        output['research_parameters']=dict(parameters)
    output["bundle_sha256"]=_digest(output)
    return output
