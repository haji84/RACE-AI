"""Blinded retrospective held-out video validation for RACE-AI.

Past means *past in calendar time*, not present in model training, tuning,
forecast originals, or scene-label inference. This module compares events
after a separate independent reviewer releases frame-verified labels.
No network, media retrieval, model fitting, result lookup or public file writes.
"""
from __future__ import annotations

from hashlib import sha256
from datetime import datetime
import json
import math
import re

BLIND="RACE_AI_KEIRIN_HISTORICAL_BLIND_EVENTS_V1"
TRUTH="RACE_AI_KEIRIN_HISTORICAL_INDEPENDENT_TRUTH_V1"
SCORE="RACE_AI_KEIRIN_HISTORICAL_HOLDOUT_SCORE_V1"
EVENTS=("START","HOME_PASS","GOAL","REPLAY_START","REPLAY_END","RESULT")
HEX=re.compile(r"^[a-f0-9]{64}$")

class HoldoutError(ValueError):
    pass

def check(ok,message):
    if not ok:raise HoldoutError(message)

def is_sha(s):
    return isinstance(s,str) and HEX.fullmatch(s) is not None

def canonical(doc):
    return json.dumps(doc,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"),allow_nan=False)

def sha(doc):
    return sha256(canonical(doc).encode("utf-8")).hexdigest()

def aware_epoch(s):
    check(isinstance(s,str) and bool(s),"TIMESTAMP_REQUIRED")
    try:
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
        check(dt.utcoffset() is not None,"TIMEZONE_REQUIRED")
        return dt.timestamp()
    except (TypeError,ValueError):
        raise HoldoutError("INVALID_TIMESTAMP") from None

def check_events(events, duration, *, truth):
    check(type(events) is list and len(events)<=3000,"INVALID_EVENT_LIST")
    seen=set()
    previous=-1.0
    for item in events:
        wanted=({"id","time_s","event","frame_sha256","confidence"}
                if not truth else
                {"id","time_s","event","frame_sha256","review_ref"})
        check(type(item) is dict and set(item)==wanted,"INVALID_EVENT_SHAPE")
        check(type(item["id"]) is str and
              re.fullmatch(r"[a-zA-Z0-9._-]{1,90}",item["id"]) is not None and
              item["id"] not in seen,"INVALID_EVENT_ID")
        seen.add(item["id"])
        t=item["time_s"]
        check(type(t) in (float,int) and math.isfinite(t) and
              previous<t<=duration,"EVENT_TIME_NOT_STRICTLY_INCREASING")
        previous=t
        check(item["event"] in EVENTS,"UNKNOWN_EVENT")
        check(is_sha(item["frame_sha256"]),"EVENT_FRAME_SHA_REQUIRED")
        if truth:
            check(type(item["review_ref"]) is str and
                  len(item["review_ref"])>=6,"INDEPENDENT_REVIEW_REF_MISSING")
        else:
            check(type(item["confidence"]) in (int,float) and
                  math.isfinite(item["confidence"]) and
                  0<=item["confidence"]<=1,"INVALID_UNCALIBRATED_SCORE")

def validate_predictions(p):
    check(type(p) is dict and set(p)=={
        "schema","race_id","source","recording_sha256","duration_s",
        "model_sha256","model_train_races","model_dev_races",
        "events","frozen_at","video_input_labels_used","forecast_modified",
        "prediction_sha256"},"INVALID_BLIND_SCHEMA")
    check(p["schema"]==BLIND,"INVALID_BLIND_VERSION")
    check(type(p["race_id"]) is str and 8<=len(p["race_id"])<=100,
          "RACE_ID_REQUIRED")
    check(p["source"]=="WINTICKET_LIVE","ONLY_REAL_LIVE_SOURCE_ALLOWED")
    check(all(is_sha(p[k]) for k in ("model_sha256","recording_sha256")),
          "MODEL_OR_VIDEO_DIGEST_MISSING")
    check(type(p["duration_s"]) in (int,float) and math.isfinite(p["duration_s"])
          and 60<=p["duration_s"]<=10000,"INVALID_VIDEO_LENGTH")
    check(type(p["model_train_races"]) is list and
          type(p["model_dev_races"]) is list and
          all(type(x) is str for x in p["model_train_races"]+
                                      p["model_dev_races"]),
          "MODEL_PROVENANCE_REQUIRED")
    check(p["race_id"] not in p["model_train_races"],
          "TEST_RACE_IN_TRAINING_DATA")
    check(p["race_id"] not in p["model_dev_races"],
          "TEST_RACE_ALREADY_USED_FOR_MODEL_TUNING")
    check(p["video_input_labels_used"] is False and
          p["forecast_modified"] is False,
          "POSTRACE_OR_FORECAST_LEAK")
    aware_epoch(p["frozen_at"])
    check_events(p["events"],p["duration_s"],truth=False)
    check(is_sha(p["prediction_sha256"]) and
          p["prediction_sha256"]==sha({k:v for k,v in p.items()
                       if k!="prediction_sha256"}),"BLIND_DIGEST_MISMATCH")
    return p

def validate_truth(t):
    check(type(t) is dict and set(t)=={
        "schema","race_id","recording_sha256","duration_s",
        "review_type","reviewed_at","events","review_sha256",
    },"INVALID_INDEPENDENT_TRUTH_SCHEMA")
    check(t["schema"]==TRUTH,"INVALID_TRUTH_VERSION")
    check(type(t["race_id"]) is str and t["race_id"],"TRUTH_RACE_MISSING")
    check(is_sha(t["recording_sha256"]),"TRUTH_VIDEO_DIGEST_MISSING")
    check(type(t["duration_s"]) in (int,float) and
          math.isfinite(t["duration_s"]) and t["duration_s"]>60,
          "TRUTH_VIDEO_LENGTH_INVALID")
    check(t["review_type"] in ("INDEPENDENT_FRAME_REVIEW","SYNTHETIC_FIXTURE"),
          "TRUTH_REVIEW_TYPE_INVALID")
    aware_epoch(t["reviewed_at"])
    check_events(t["events"],t["duration_s"],truth=True)
    check(is_sha(t["review_sha256"]) and t["review_sha256"]==
          sha({k:v for k,v in t.items() if k!="review_sha256"}),
          "TRUTH_DIGEST_MISMATCH")
    return t

def build_blind(queue, model, *, frozen_at):
    """Freeze model candidate events without loading ground truth.

    IMPORTANT: exclude any race previously used to tune the model, even if it
    was not literally in the training rows. Earlier Matsuyama 9R was inspected
    during algorithm development: it belongs in the DEV set, not a truly
    untouched evaluation cohort.
    """
    from .keirin_video_learning import MODEL_SCHEMA, digest
    check(type(queue) is dict and type(model) is dict,
          "CANDIDATES_AND_MODEL_REQUIRED")
    check(model.get("schema")==MODEL_SCHEMA and
          model.get("model_sha256")==digest(
              {k:v for k,v in model.items() if k!="model_sha256"}),
          "MODEL_INTEGRITY_UNVERIFIED")
    check(model.get("validation_status")=="RESEARCH_HOLDOUT_PASSED",
          "REAL_TRAINED_MODEL_NOT_VALIDATED")
    source=queue.get("input")
    check(type(source) is dict and
          source.get("inference_model")==model["model_sha256"],
          "SOURCE_MODEL_MISMATCH")
    check(source.get("source")=="WINTICKET_LIVE",
          "SOURCE_NOT_FULL_LIVE")
    train=model.get("train_races",[])
    # Declare dev races separately; do not silently treat this list as empty.
    dev=model.get("dev_races")
    check(type(dev) is list,"MODEL_DEV_COHORT_DECLARATION_REQUIRED")
    check(source.get("race_id") not in train+dev,
          "HOLDOUT_NOT_INDEPENDENT")
    events=[]
    for row in source.get("observations",[]):
        if row["event"] in EVENTS:
            events.append({
                "id":row["id"],"time_s":row["recording_sec"],
                "event":row["event"],"frame_sha256":row["frame_sha256"],
                "confidence":row["confidence"]})
    p={"schema":BLIND,"race_id":source["race_id"],
       "source":source["source"],
       "recording_sha256":source["recording_sha256"],
       "duration_s":source["duration_s"],
       "model_sha256":model["model_sha256"],
       "model_train_races":list(train),
       "model_dev_races":list(dev),
       "events":events,"frozen_at":frozen_at,
       "video_input_labels_used":False,"forecast_modified":False}
    p["prediction_sha256"]=sha(p)
    return validate_predictions(p)

def _greedy_match(p_items,t_items,tolerance):
    """One-to-one matching; replay duplicates cannot match multiple laps."""
    edges=sorted((abs(p["time_s"]-t["time_s"]),pi,ti)
                 for pi,p in enumerate(p_items) for ti,t in enumerate(t_items)
                 if abs(p["time_s"]-t["time_s"])<=tolerance)
    pm=set();tm=set();chosen=[]
    for dt,i,j in edges:
        if i not in pm and j not in tm:
            pm.add(i);tm.add(j)
            chosen.append((i,j,round(dt,3)))
    return chosen

def _replay_regions(events):
    out=[];start=None
    for row in events:
        if row["event"]=="REPLAY_START" and start is None:
            start=row["time_s"]
        elif row["event"]=="REPLAY_END" and start is not None:
            out.append((start,row["time_s"]));start=None
    if start is not None:out.append((start,float("inf")))
    return out

def score(p,t, *, frozen_prediction_attestor=None,
          independent_review_attestor=None, source_rights_attestor=None,
          tolerance_s=4.0):
    """Score only independently attested true history after predictions froze.

    Three host callbacks must independently approve the frozen prediction,
    the separately prepared frame labels and the intended private-use rights.
    """
    validate_predictions(p);validate_truth(t)
    check(p["race_id"]==t["race_id"] and
          p["recording_sha256"]==t["recording_sha256"] and
          abs(p["duration_s"]-t["duration_s"])<=.5,
          "VIDEO_OR_RACE_MISMATCH")
    check(aware_epoch(p["frozen_at"])<aware_epoch(t["reviewed_at"]),
          "TRUTH_REVIEWED_BEFORE_BLIND_PREDICTION_FREEZE")
    check(type(tolerance_s) in (int,float) and 0<tolerance_s<=8,
          "INVALID_TIME_TOLERANCE")
    check(all(callable(x) for x in (frozen_prediction_attestor,
             independent_review_attestor,source_rights_attestor)),
          "OUT_OF_BAND_WITNESSES_REQUIRED")
    check(frozen_prediction_attestor(p) is True and
          independent_review_attestor(t) is True and
          source_rights_attestor("WINTICKET_LIVE",
                                "private_historical_video_evaluation") is True,
          "UNVERIFIED_FREEZE_REVIEW_OR_RIGHTS")
    metrics={}
    matched={}
    for label in EVENTS:
        predicted=[x for x in p["events"] if x["event"]==label]
        actual=[x for x in t["events"] if x["event"]==label]
        pairs=_greedy_match(predicted,actual,tolerance_s)
        tp=len(pairs);fp=len(predicted)-tp;fn=len(actual)-tp
        precision=tp/(tp+fp) if tp+fp else None
        recall=tp/(tp+fn) if tp+fn else None
        f1=(2*precision*recall/(precision+recall)
            if precision is not None and recall is not None and
               precision+recall>0 else 0.0)
        metrics[label]={"true_positive":tp,"false_positive":fp,
                        "false_negative":fn,"precision":precision,
                        "recall":recall,"f1":round(f1,5),
                        "time_errors_s":[x[2] for x in pairs]}
        matched[label]=pairs
    replay=_replay_regions(t["events"])
    accidental=sum(
        1 for x in p["events"]
        if x["event"]=="HOME_PASS" and
           any(lo<=x["time_s"]<=hi for lo,hi in replay))
    actual_laps=[x for x in t["events"] if x["event"]=="HOME_PASS"]
    predicted_laps=[x for x in p["events"] if x["event"]=="HOME_PASS"]
    complete_laps=(len(actual_laps)==4 and
                   len(predicted_laps)==4 and
                   len(matched["HOME_PASS"])==4 and
                   accidental==0)
    start_ok=(metrics["START"]["true_positive"]==1 and
              metrics["START"]["false_positive"]==0)
    goal_ok=(metrics["GOAL"]["true_positive"]==1 and
             metrics["GOAL"]["false_positive"]==0)
    replay_label_count=sum(x["event"]=="REPLAY_START" for x in t["events"])
    replay_ok=(replay_label_count>0 and accidental==0 and
               metrics["REPLAY_START"]["false_negative"]==0 and
               metrics["REPLAY_END"]["false_negative"]==0 and
               metrics["REPLAY_START"]["false_positive"]==0 and
               metrics["REPLAY_END"]["false_positive"]==0)
    result_ok=(metrics["RESULT"]["true_positive"]==1 and
               metrics["RESULT"]["false_positive"]==0)
    # Synthetic fixtures test arithmetic only; never confer real model accuracy.
    real=t["review_type"]=="INDEPENDENT_FRAME_REVIEW"
    accepted=all((complete_laps,start_ok,goal_ok,replay_ok,result_ok,real))
    result={
        "schema":SCORE,"race_id":p["race_id"],
        "recording_sha256":p["recording_sha256"],
        "frozen_model_sha256":p["model_sha256"],
        "frozen_prediction_sha256":p["prediction_sha256"],
        "independent_truth_sha256":t["review_sha256"],
        "historical_race_known_only_to_evaluator":True,
        "training_and_development_races_excluded":True,
        "metrics":metrics,"lap_pass_all_four_matched":complete_laps,
        "replay_as_lap_false_positive_count":accidental,
        "start_matched":start_ok,"goal_matched":goal_ok,
        "replay_regions_matched":replay_ok,"result_matched":result_ok,
        "review_type":t["review_type"],
        "status":("BLIND_HISTORICAL_HOLDOUT_PASSED" if accepted
                  else "HISTORICAL_HOLDOUT_NOT_ACCEPTED"),
        "learning_policy":"DO_NOT_TRAIN_ON_HELDOUT_RACE",
        "prediction_original_modified":False}
    result["score_sha256"]=sha(result)
    return result
