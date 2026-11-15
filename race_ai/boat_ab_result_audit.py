"""Read a previously frozen A/B pair and score the independent official result.

Never rescore an invented/mutable forecast and never upgrade a model based on
one result. This is a pure contract. Source capture and real freeze receipt
must be externally verified by the cloud caller.
"""
from datetime import datetime, timedelta
import itertools
import math
import re
from .boat_ab_shadow import MODEL_IDS, _digest, _time

TICKETS={"-".join(map(str,t)) for t in itertools.permutations(range(1,7),3)}

def score_pair(original, winner, observed_at, server_saved_at):
    if not isinstance(original,dict) or original.get("schema")!="RACE_AI_BOAT_LIVE_AB_RESEARCH_V1" \
       or original.get("status")!="REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT" \
       or original.get("result_used") is not False:
        raise ValueError("original paired research forecast required")
    bundle=original.get("paired_forecast")
    if not isinstance(bundle,dict) or bundle.get("schema")!="RACE_AI_BOAT_PRE_CUTOFF_AB_PAIR_V1" \
       or bundle.get("actual_result_at_forecast_time") is not None:
        raise ValueError("pre-result paired forecast contract required")
    expected=_digest({k:v for k,v in bundle.items() if k!="bundle_sha256"})
    if bundle.get("bundle_sha256")!=expected:
        raise ValueError("forecast bundle integrity mismatch")
    if original.get("race_id")!=bundle.get("race_id") or original.get("cutoff_at")!=bundle.get("cutoff_at"):
        raise ValueError("frozen race identity and cutoff mismatch")
    cutoff=_time(bundle["cutoff_at"])
    captured=_time(bundle["source_captured_at"])
    generated=_time(bundle["generated_at"])
    saved=_time(server_saved_at)
    # GitHub REST artifact.created_at has second precision. The archive may
    # legitimately be generated at e.g. 02:09:50.181Z and server-created at
    # 02:09:50Z. Accept only this same-second truncation, never an earlier
    # whole second or an artifact at/after the official closing time.
    generation_precedes_receipt=(generated<=saved or
        (saved.microsecond==0 and saved<=generated<saved+timedelta(seconds=1)))
    if not (captured<=generated<cutoff and generation_precedes_receipt
            and saved<cutoff<=_time(observed_at)):
        raise ValueError("independent freeze/result chronology invalid")
    if type(winner) is not str or winner not in TICKETS:
        raise ValueError("unverified result triple")
    models=bundle.get("models")
    if not isinstance(models,list) or len(models)!=2 or [m.get("model_id") for m in models]!=list(MODEL_IDS):
        raise ValueError("baseline and challenger model must both be frozen")
    output=[]; active_lanes=None
    for m in models:
        if m.get("model_sha256")!=_digest({k:v for k,v in m.items() if k!="model_sha256"}):
            raise ValueError("model bytes changed after forecast")
        if (m.get("trained") is not False or m.get("calibrated") is not False
            or m.get("odds_independent") is not True or m.get("purchase_decision")!="NO_BET"):
            raise ValueError("unsafe research model claims")
        rows=m.get("full_120",[])
        picks=m.get("top8",[])
        if (not isinstance(rows,list) or not all(type(row) is dict and type(row.get('ticket')) is str
                and re.fullmatch(r'[1-6]-[1-6]-[1-6]',row['ticket']) for row in rows)):
            raise ValueError("valid physical ranked tickets required")
        lanes=sorted({int(n) for row in rows for n in row['ticket'].split('-')})
        if not 3<=len(lanes)<=6 or active_lanes is not None and active_lanes!=lanes:
            raise ValueError("same active roster required for both models")
        active_lanes=lanes
        tickets={'-'.join(map(str,t)) for t in itertools.permutations(lanes,3)}
        if winner not in tickets:
            raise ValueError("result triple outside frozen active roster")
        if (len(rows)!=len(tickets) or not isinstance(picks,list)
                or picks!=rows[:8] or len(picks)!=min(8,len(tickets))):
            raise ValueError("full ranked distribution and top eight required")
        if ({x["ticket"] for x in rows}!=tickets
                or not all(type(x["score"]) in (int,float) and math.isfinite(x["score"])
                           and 0<x["score"]<1 for x in rows)
                or not math.isclose(math.fsum(x["score"] for x in rows),1,abs_tol=1e-9)
                or rows!=sorted(rows,key=lambda x:(-x["score"],x["ticket"]))):
            raise ValueError("forecast distribution integrity invalid")
        winning_score=next(x["score"] for x in rows if x["ticket"]==winner)
        brier=math.fsum((x["score"]-int(x["ticket"]==winner))**2 for x in rows)
        output.append({"model_id":m["model_id"],"hit_at_1":int(picks[0]["ticket"]==winner),
                       "hit_at_8":int(any(x["ticket"]==winner for x in picks)),
                       "winning_combination_rank":next(i+1 for i,x in enumerate(rows) if x["ticket"]==winner),
                       "model_top1_mass_uncalibrated":picks[0]["score"],
                       "model_top8_mass_uncalibrated":math.fsum(x["score"] for x in picks),
                       "top8_model_scores_uncalibrated":[{"ticket":x["ticket"],"score":x["score"]} for x in picks],
                       "winner_model_score_uncalibrated":winning_score,
                       "multiclass_brier":brier,"log_loss":-math.log(winning_score),
                       "top8":[x["ticket"] for x in picks],
                       "model_sha256":m["model_sha256"]})
    return {"schema":"RACE_AI_BOAT_AB_INDEPENDENT_RESULT_AUDIT_V1",
            "race_id":bundle["race_id"],"cutoff_at":bundle["cutoff_at"],
            "forecast_server_saved_at":server_saved_at,"result_observed_at":observed_at,
            "official_top3":winner,"research_only":True,"model_calibrated":False,
            "result_fed_back_into_prior_forecasts":False,
            "next_model_auto_promoted":False,
            "pair_bundle_sha256":bundle["bundle_sha256"],"models":output}
