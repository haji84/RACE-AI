"""Research-only KEIRIN: learn *prior* video tactics and test forecast lift.

Past race film can teach rider tendencies, but same-race film/results must NEVER
enter predictions for that race. This is an intentionally isolated research
ablation; never replaces PR71/official picks or claims measured profitability.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import itertools
import json
import math
import re

PAIR_SCHEMA = "RACE_AI_KEIRIN_PRE_AND_REVIEWED_VIDEO_HISTORY_V1"
PARAM_SCHEMA = "RACE_AI_KEIRIN_PRIOR_VIDEO_TACTICS_WEIGHTS_V1"
REPORT_SCHEMA = "RACE_AI_KEIRIN_PRIOR_VIDEO_TACTICS_ABLATION_V1"
PATTERN = re.compile(r"^[0-9a-f]{64}$")
TRAITS = ("attack", "initiative", "position_gain", "line_survival")
FIELD_NAMES = ("attack_first", "initiative_first", "position_gain_second",
               "line_survival_followers", "same_group_first_second",
               "same_group_all_three")

class VideoForecastError(ValueError):
    pass

def demand(condition, code):
    if not condition:
        raise VideoForecastError(code)

def digest(obj):
    return sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,
                    separators=(",",":"),allow_nan=False).encode()).hexdigest()

def when(s):
    try:
        value=datetime.fromisoformat(s.replace("Z","+00:00"))
        demand(value.utcoffset() is not None,"TIMEZONE_REQUIRED")
        return value.timestamp()
    except (ValueError,AttributeError,TypeError):
        raise VideoForecastError("TIMESTAMP_INVALID") from None

def verified_id(x):
    return isinstance(x,str) and PATTERN.fullmatch(x) is not None

def verify_record(r, *, trusted_source_admission=None):
    """Strictly separate pre-race facts from after-race labels and film."""
    demand(isinstance(r,dict) and set(r)=={
        "schema","race_id","source_scope","pre","post"},"PAIR_SCHEMA_INVALID")
    demand(r["schema"]==PAIR_SCHEMA,"PAIR_VERSION_INVALID")
    demand(r["source_scope"] in ("SYNTHETIC_ONLY","OPERATOR_SUPPLIED_RESEARCH"),
           "INVALID_SOURCE_SCOPE")
    if r["source_scope"]=="OPERATOR_SUPPLIED_RESEARCH":
        demand(callable(trusted_source_admission),
               "TRUSTED_SOURCE_ADMISSION_REQUIRED")
        try:
            admitted=trusted_source_admission(r) is True
        except Exception:
            admitted=False
        demand(admitted,"SOURCE_RIGHTS_AND_PROVENANCE_NOT_ATTESTED")
    pre,post=r["pre"],r["post"]
    demand(isinstance(pre,dict) and set(pre)=={
        "as_of","cutoff","snapshot_sha256","baseline_sha256",
        "participants","baseline_probabilities"},"PRE_SCHEMA_INVALID")
    demand(isinstance(post,dict) and set(post)=={
        "result_published_at","result_ordered_top3","video_reviewed_at",
        "video_sha256","visual_audit_sha256","visual_status",
        "source_use_admitted","tactics"},"POST_SCHEMA_INVALID")
    asof,cutoff=when(pre["as_of"]),when(pre["cutoff"])
    result_at,review_at=when(post["result_published_at"]),when(post["video_reviewed_at"])
    demand(asof<cutoff<result_at<=review_at,"RACE_TIMELINE_INVALID")
    demand(all(verified_id(pre[k]) for k in ("snapshot_sha256","baseline_sha256")),
           "FROZEN_PREDICTION_DIGEST_REQUIRED")
    demand(all(verified_id(post[k]) for k in ("video_sha256","visual_audit_sha256")),
           "VIDEO_SOURCE_DIGEST_REQUIRED")
    full=(post["visual_status"]=="FOUR_LAPS_VISUALLY_VERIFIED")
    partial=(post["visual_status"]=="PARTIAL_HIGHLIGHTS_POSITIVE_ONLY_VERIFIED")
    demand((full or partial) and post["source_use_admitted"] is True,
           "UNVERIFIED_FULL_VIDEO_OR_RIGHTS")
    riders=pre["participants"]
    demand(isinstance(riders,list) and 5<=len(riders)<=9,"STARTERS_INVALID")
    numbers=set(); identities=set(); by_number={}
    for item in riders:
        demand(isinstance(item,dict) and set(item)=={
            "number","rider_id","group_id","line_role"},"RIDER_PRE_SCHEMA_INVALID")
        n=item["number"]
        demand(type(n) is int and 1<=n<=9 and n not in numbers,"RIDER_NUMBER_INVALID")
        numbers.add(n)
        rid=item["rider_id"]
        demand(isinstance(rid,str) and 2<=len(rid)<=90 and rid not in identities,
               "RIDER_ID_INVALID")
        identities.add(rid)
        demand(isinstance(item["group_id"],str) and item["group_id"],
               "LINE_GROUP_REQUIRED")
        demand(item["line_role"] in ("LEADER","SECOND","THIRD","SOLO"),
               "LINE_ROLE_INVALID")
        by_number[n]=item
    candidate=pre["baseline_probabilities"]
    count=len(numbers)*(len(numbers)-1)*(len(numbers)-2)
    demand(isinstance(candidate,list) and len(candidate)==count,"COMPLETE_BASELINE_REQUIRED")
    combinations=set()
    total=0.
    for row in candidate:
        demand(isinstance(row,dict) and set(row)=={"order","probability"},
               "BASELINE_ROW_INVALID")
        order=row["order"]
        demand(isinstance(order,list) and len(order)==3 and
               all(type(x) is int and x in numbers for x in order) and
               len(set(order))==3, "BASELINE_ORDER_INVALID")
        triple=tuple(order)
        demand(triple not in combinations,"BASELINE_DUPLICATE")
        combinations.add(triple)
        prob=row["probability"]
        demand(type(prob) in (float,int) and math.isfinite(prob) and prob>0,
               "BASELINE_PROB_INVALID")
        total+=prob
    demand(abs(total-1.)<=1e-7,"BASELINE_MASS_NOT_ONE")
    demand(pre["baseline_sha256"]==digest(candidate),
           "BASELINE_PROBABILITIES_DIGEST_MISMATCH")
    order=post["result_ordered_top3"]
    demand(isinstance(order,list) and len(order)==3 and
           tuple(order) in combinations,"RESULT_ORDER_MISSING_IN_BASELINE")
    tactics=post["tactics"]
    demand(isinstance(tactics,list) and len(tactics)==len(riders),
           "INCOMPLETE_VISUAL_TACTICS")
    seen=set()
    for tr in tactics:
        demand(isinstance(tr,dict) and set(tr)=={"rider_id",*TRAITS},
               "TACTICAL_LABEL_SCHEMA_INVALID")
        rid=tr["rider_id"]
        demand(rid in identities and rid not in seen,"TACTICAL_RIDER_INVALID")
        seen.add(rid)
        for key in TRAITS:
            val=tr[key]
            if partial:
                demand(val is None or type(val) is int and val==1,
                       "UNSEEN_PARTIAL_ACTION_MUST_BE_UNKNOWN")
            else:
                demand(val is None or type(val) is int and val in (0,1),
                       "TACTICAL_LABEL_NOT_BINARY")
    if partial:
        demand(any(t[k] == 1 for t in tactics for k in TRAITS),
               "PARTIAL_CLIP_HAS_NO_VISIBLE_RIDER_TACTIC")
    return r

def _trait_history(previous, now, *, trusted_source_admission=None):
    """Only film already reviewed BEFORE the target as-of is available."""
    out={}
    for history in previous:
        verify_record(history,trusted_source_admission=trusted_source_admission)
        if when(history["post"]["video_reviewed_at"])>=now:
            continue
        for tr in history["post"]["tactics"]:
            rid=tr["rider_id"]
            if not any(tr[k] is not None for k in TRAITS):
                continue
            if rid not in out:
                out[rid]={k:[1,2] for k in TRAITS}  # Beta(1,1) smoothing
            for k in TRAITS:
                if tr[k] is not None:
                    out[rid][k][0]+=tr[k]
                    out[rid][k][1]+=1
    return {rid:{k:a/b for k,(a,b) in val.items()}
            for rid,val in out.items()}

def _pre_triplet_features(order,by_num,history):
    first,second,third=(by_num[i] for i in order)
    def feat(item,key):
        return history.get(item["rider_id"],{}).get(key,.5)-.5
    a,b,c=first["group_id"],second["group_id"],third["group_id"]
    return (
        feat(first,"attack"),
        feat(first,"initiative"),
        feat(second,"position_gain"),
        (feat(second,"line_survival")+feat(third,"line_survival"))/2,
        float(a==b),
        float(a==b==c),
    )

def score_one(record, earlier_verified, weights, *,
              trusted_source_admission=None):
    """Produce all-triple probabilities without reading THIS race video labels."""
    verify_record(record,trusted_source_admission=trusted_source_admission)
    demand(len(weights)==len(FIELD_NAMES) and
           all(type(x) in (int,float) and math.isfinite(x) and abs(x)<=2.0
               for x in weights),"WEIGHTS_INVALID")
    start=when(record["pre"]["as_of"])
    for earlier in earlier_verified:
        demand(earlier["race_id"]!=record["race_id"],"TARGET_VIDEO_LEAK")
        demand(when(earlier["post"]["video_reviewed_at"])<start,
               "FUTURE_VIDEO_LEAK")
    history=_trait_history(earlier_verified,start,
                           trusted_source_admission=trusted_source_admission)
    by_num={x["number"]:x for x in record["pre"]["participants"]}
    visible_rider_overlap=sum(x["rider_id"] in history
                              for x in record["pre"]["participants"])
    # The two final features are line structures already known before
    # the race. A "video" ablation must not claim line-only reweighting.
    # If zero riders have prior observed video tactics, B == A exactly.
    effective_weights=list(weights[:4])+[0.0,0.0]
    if visible_rider_overlap==0:
        effective_weights=[0.0]*len(weights)
    scores=[];features=[]
    for row in record["pre"]["baseline_probabilities"]:
        x=_pre_triplet_features(row["order"],by_num,history)
        score=math.log(row["probability"])+math.fsum(a*b for a,b in zip(effective_weights,x))
        scores.append(score)
        features.append(x)
    shift=max(scores)
    exp=[math.exp(s-shift) for s in scores]
    total=math.fsum(exp)
    ps=[v/total for v in exp]
    demand(abs(math.fsum(ps)-1)<1e-10,"CANDIDATE_NOT_NORMALIZED")
    return {
        "race_id":record["race_id"],"as_of":record["pre"]["as_of"],
        "source_snapshot_sha256":record["pre"]["snapshot_sha256"],
        "prior_video_races_used":len(earlier_verified),
        "prior_rider_profiles_used":len(history),
        "prior_riders_on_target_card":visible_rider_overlap,
        "sparse_positive_only_supported":True,
        "ordered_candidates":[{"order":list(row["order"]),
                               "base_probability":row["probability"],
                               "candidate_probability":p}
                              for row,p in zip(record["pre"]["baseline_probabilities"],ps)],
        "_features":features,
    }

def outcome_metric(record, pred):
    actual=record["post"]["result_ordered_top3"]
    c=pred["ordered_candidates"]
    selected=next(x for x in c if x["order"]==actual)
    ranked=sorted(c,key=lambda x:(-x["candidate_probability"],x["order"]))
    return {
        "race_id":record["race_id"],
        "hit_at_8":int(any(item["order"]==actual for item in ranked[:8])),
        "log_loss":-math.log(selected["candidate_probability"]),
        "multiclass_brier":1-2*selected["candidate_probability"]+
            math.fsum(p["candidate_probability"]**2 for p in c),
        "top8": [p["order"] for p in ranked[:8]],
        "actual":actual,
    }

def _gradient(record, pred):
    actual=record["post"]["result_ordered_top3"]
    c=pred["ordered_candidates"];x=pred["_features"]
    i=next(j for j,p in enumerate(c) if p["order"]==actual)
    avg=[math.fsum(p["candidate_probability"]*xi[k] for p,xi in zip(c,x))
         for k in range(len(FIELD_NAMES))]
    return [x[i][k]-avg[k] for k in range(len(FIELD_NAMES))]

def fit_earlier_historical(records, *, min_races=20, epochs=60,
                           rate=.07, regularization=.3, trusted_source_admission=None):
    """Train sequentially without incorporating target film into its features.

    Training outcome can update coefficients AFTER its stored frozen pre-race
    baseline was computed; train and final test histories remain separated.
    """
    demand(type(records) is list and len(records)>=min_races,
           "NOT_ENOUGH_REAL_TRAINING_RACES")
    ordered=sorted(records,key=lambda r:when(r["pre"]["as_of"]))
    demand(len({r["race_id"] for r in ordered})==len(ordered),
           "DUPLICATE_RACES")
    for r in ordered:
        verify_record(r,trusted_source_admission=trusted_source_admission)
    w=[0.]*len(FIELD_NAMES)
    for epoch in range(epochs):
        gradient=[0.]*len(w)
        used=0
        for i,r in enumerate(ordered):
            prev=[p for p in ordered[:i]
                  if when(p["post"]["video_reviewed_at"])<when(r["pre"]["as_of"])]
            if not prev:continue
            pred=score_one(r,prev,w,
                trusted_source_admission=trusted_source_admission)
            if pred["prior_riders_on_target_card"]==0:
                continue
            g=_gradient(r,pred)
            for k in range(4):gradient[k]+=g[k]
            used+=1
        demand(used>0,"NO_SAME_RIDER_PRIOR_REVIEWED_VIDEO_BEFORE_TARGET")
        for k in range(len(w)):
            # Bounded coefficients and ridge penalty prevent runaway bets.
            w[k]=max(-2.,min(2.,w[k]+rate*(
                   gradient[k]/used-regularization*w[k])))
    model={"schema":PARAM_SCHEMA,"weights":dict(zip(FIELD_NAMES,w)),
           "train_race_ids":[r["race_id"] for r in ordered],
           "trained_data_until":max(r["post"]["video_reviewed_at"] for r in ordered),
           "train_count":len(ordered),
           "source_scope":("OPERATOR_SUPPLIED_RESEARCH"
                           if any(r["source_scope"]!="SYNTHETIC_ONLY" for r in ordered)
                           else "SYNTHETIC_ONLY"),
           "source_type":"REVIEWED_HISTORIC_VIDEO_AND_FROZEN_PRE_RACE",
           "sparse_positive_only_supported":True,
           "line_only_coefficients_are_not_video_evidence":True,
           "calibrated":False,"official_prediction":False,
           "model_version":"0.2-SPARSE_POSITIVE_RESEARCH-UNPROMOTED"}
    model["model_sha256"]=digest(model)
    return model

def evaluate_chronological(train, test, model, *, minimum_test=10,
                           trusted_source_admission=None):
    """Paired heldout comparison; no real improvement claim without support."""
    demand(type(test) is list and len(test)>=minimum_test,
           "NOT_ENOUGH_OUT_OF_TIME_TEST_RACES")
    demand(model.get("schema")==PARAM_SCHEMA and
           model.get("model_sha256")==digest({
             k:v for k,v in model.items() if k!="model_sha256"}),
           "INVALID_MODEL_ARTIFACT")
    demand(model.get("official_prediction") is False and
           model.get("calibrated") is False,"PROMOTED_UNCALIBRATED_MODEL")
    all_records=train+test
    ids=[x["race_id"] for x in all_records]
    demand(len(ids)==len(set(ids)),"TRAIN_TEST_DUPLICATE_RACE")
    demand(set(ids[:len(train)])==set(model["train_race_ids"]),
           "TRAINING_COHORT_CONFLICT")
    for r in all_records:
        verify_record(r,trusted_source_admission=trusted_source_admission)
    demand(model.get("source_scope")==(
        "OPERATOR_SUPPLIED_RESEARCH" if any(
         r["source_scope"]!="SYNTHETIC_ONLY" for r in all_records)
         else "SYNTHETIC_ONLY"),"TRAIN_TEST_SOURCE_SCOPE_CONFLICT")
    max_train_time=max(when(r["post"]["video_reviewed_at"]) for r in train)
    min_test_time=min(when(r["pre"]["as_of"]) for r in test)
    demand(max_train_time<min_test_time,
           "TRAINING_POSTRACE_LABELS_LEAK_INTO_TEST")
    # The candidate can use only verified films known before each test as-of.
    # Previously seen test video can be used for LATER test races only, after
    # independent review, but this conservative test uses TRAIN history only.
    weight=[model["weights"][name] for name in FIELD_NAMES]
    results=[]
    for target in test:
        prev=[r for r in train if when(r["post"]["video_reviewed_at"])<
              when(target["pre"]["as_of"])]
        pred_a=score_one(target,prev,[0.]*len(weight),
             trusted_source_admission=trusted_source_admission)
        pred_b=score_one(target,prev,weight,
             trusted_source_admission=trusted_source_admission)
        base=outcome_metric(target,pred_a)
        cand=outcome_metric(target,pred_b)
        results.append({"race_id":target["race_id"],
                        "prior_riders_on_target_card":pred_b[
                            "prior_riders_on_target_card"],
                        "baseline_hit":base["hit_at_8"],
                        "candidate_hit":cand["hit_at_8"],
                        "baseline_loss":base["log_loss"],
                        "candidate_loss":cand["log_loss"],
                        "baseline_brier":base["multiclass_brier"],
                        "candidate_brier":cand["multiclass_brier"]})
    n=len(results)
    hit_base=sum(r["baseline_hit"] for r in results)
    hit_candidate=sum(r["candidate_hit"] for r in results)
    base_loss=math.fsum(r["baseline_loss"] for r in results)/n
    candidate_loss=math.fsum(r["candidate_loss"] for r in results)/n
    base_brier=math.fsum(r["baseline_brier"] for r in results)/n
    candidate_brier=math.fsum(r["candidate_brier"] for r in results)/n
    # Strict paired uplift gate. Uncalibrated probabilities cannot be
    # called calibrated and ROI needs separate pre-cutoff market evidence.
    eligible_video_test_races=sum(r["prior_riders_on_target_card"]>0
                                  for r in results)
    better=(eligible_video_test_races>=max(5,n//2)
            and hit_candidate>hit_base and candidate_loss<base_loss
            and candidate_brier<base_brier
            and model["source_scope"]=="OPERATOR_SUPPLIED_RESEARCH")
    out={
        "schema":REPORT_SCHEMA,"model_sha256":model["model_sha256"],
        "train_count":len(train),"test_count":n,
        "baseline_top8_hits":hit_base,"candidate_top8_hits":hit_candidate,
        "baseline_mean_logloss":base_loss,
        "candidate_mean_logloss":candidate_loss,
        "baseline_mean_multiclass_brier":base_brier,
        "candidate_mean_multiclass_brier":candidate_brier,
        "observed_top8_uplift":(hit_candidate-hit_base)/n,
        "research_promotion_gate":("BETTER_ON_HELDOUT_BUT_NOT_PRODUCTION_READY"
                                   if better else "NO_VERIFIED_IMPROVEMENT"),
        "source_scope":model["source_scope"],
        "test_races_with_proven_prior_video_rider_overlap":eligible_video_test_races,
        "no_clips_are_automatically_assigned_negative_traits":True,
        "calibration_verified":False,"roi_verified":False,
        "prediction_originals_modified":False,"results":results,
    }
    out["report_sha256"]=digest(out)
    return out
