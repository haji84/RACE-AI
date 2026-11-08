"""Fail-closed four-lap video evidence audit for RACE-AI.

Consumes only timestamped visual event predictions, never a result, odds, or
race outcomes. The calling host owns raw frames and the independent model
validation receipt. An outcome file is NEVER an allowed source of laps.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re

SCHEMA="RACE_AI_KEIRIN_LAP_EVIDENCE_V1"
REPORT="RACE_AI_KEIRIN_LAP_AUDIT_V1"
TYPES={"START","HOME_PASS","GOAL","REPLAY_START","REPLAY_END","RESULT","UNKNOWN"}
DIGEST=re.compile(r"^[0-9a-f]{64}$")
PHASH=re.compile(r"^[0-9a-f]{16}$")

class EvidenceError(ValueError):
    pass

def require(ok,code):
    if not ok:
        raise EvidenceError(code)

def valid_sha(val):
    return isinstance(val,str) and DIGEST.fullmatch(val) is not None

def phash_distance(a,b):
    return (int(a,16)^int(b,16)).bit_count()

def canonical(item):
    return json.dumps(item,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False)

def validate(doc):
    require(type(doc) is dict and set(doc)=={
        "schema","race_id","recording_sha256","duration_s",
        "expected_laps","observations","source","inference_model"},
        "INVALID_ROOT_SCHEMA")
    require(doc["schema"]==SCHEMA,"INVALID_SCHEMA")
    require(isinstance(doc["race_id"],str) and
            re.fullmatch(r"\d{8}-matsuyama-\d{1,2}R",doc["race_id"]) is not None,
            "INVALID_RACE_ID")
    require(valid_sha(doc["recording_sha256"]),"INVALID_RECORDING_DIGEST")
    require(type(doc["duration_s"]) in (float,int) and
            math.isfinite(doc["duration_s"]) and 90<=doc["duration_s"]<=10000,
            "INVALID_RECORDING_DURATION")
    require(type(doc["expected_laps"]) is int and doc["expected_laps"]==4,
            "FOUR_LAPS_REQUIRED")
    require(doc["source"] in ("WINTICKET_LIVE","OTHER_AUTHORIZED_LIVE",
                             "SYNTHETIC_FIXTURE"),"INVALID_SOURCE")
    require(isinstance(doc["inference_model"],str) and
            0<len(doc["inference_model"])<=150,"MISSING_MODEL_ID")
    require(type(doc["observations"]) is list and
            len(doc["observations"])<=10000,"INVALID_OBSERVATIONS")
    previous=-1.0
    ids=set()
    for item in doc["observations"]:
        require(type(item) is dict and set(item)=={
            "id","recording_sec","event","confidence","frame_sha256",
            "phash64","scene","replay_confidence","origin"},
            "INVALID_OBSERVATION_SCHEMA")
        require(isinstance(item["id"],str) and
                re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}",item["id"]) is not None
                and item["id"] not in ids, "INVALID_EVENT_ID")
        ids.add(item["id"])
        t=item["recording_sec"]
        require(type(t) in (int,float) and math.isfinite(t) and
                previous < t <= doc["duration_s"],"INVALID_EVENT_TIME_ORDER")
        previous=t
        require(item["event"] in TYPES,"UNKNOWN_EVENT_TYPE")
        require(item["scene"] in ("LIVE","REPLAY","INTERMISSION","UNCERTAIN"),
                "INVALID_SCENE")
        for name in ("confidence","replay_confidence"):
            n=item[name]
            require(type(n) in (float,int) and math.isfinite(n) and 0<=n<=1,
                    "INVALID_CONFIDENCE")
        require(valid_sha(item["frame_sha256"]),"INVALID_FRAME_DIGEST")
        require(isinstance(item["phash64"],str) and PHASH.fullmatch(
            item["phash64"]) is not None,"INVALID_PHASH")
        require(item["origin"] in ("VISION_MODEL","VERIFIED_FRAME_LABEL",
                                   "SYNTHETIC_FIXTURE"),"INVALID_ORIGIN")
    return doc

def find_replay_intervals(items, duration):
    intervals=[]
    open_start=None
    for item in items:
        if item["event"]=="REPLAY_START" and open_start is None:
            open_start=item["recording_sec"]
        elif item["event"]=="REPLAY_END" and open_start is not None:
            intervals.append((open_start,item["recording_sec"]))
            open_start=None
    if open_start is not None:
        intervals.append((open_start,duration))
    return intervals

def is_replay(item, intervals):
    t=item["recording_sec"]
    return (item["scene"]!="LIVE" or item["replay_confidence"]>0.20
            or any(a<=t<=b for a,b in intervals))

def audit(doc, *, independent_visual_receipt=False):
    """Do not let the untrusted prediction document attest its own quality.

    independent_visual_receipt=True may be provided ONLY by a separate trusted
    reviewer/validated visual-model gateway after source and model checks.
    """
    validate(doc)
    items=doc["observations"]
    duration=doc["duration_s"]
    intervals=find_replay_intervals(items,duration)
    starts=[x for x in items if x["event"]=="START"]
    goals=[x for x in items if x["event"]=="GOAL"]
    results=[x for x in items if x["event"]=="RESULT"]
    reasons=[]
    if len(starts)!=1: reasons.append("START_NOT_UNIQUE")
    if len(goals)!=1: reasons.append("GOAL_NOT_UNIQUE")
    start=starts[0] if len(starts)==1 else None
    goal=goals[0] if len(goals)==1 else None
    if start and is_replay(start,intervals): reasons.append("START_IN_REPLAY")
    if goal and is_replay(goal,intervals): reasons.append("GOAL_IN_REPLAY")
    if start and goal and not start["recording_sec"]+30<goal["recording_sec"]:
        reasons.append("GOAL_BEFORE_START_OR_TOO_EARLY")
    if not results or goal and not any(x["recording_sec"]>goal["recording_sec"]
                                     for x in results):
        reasons.append("POST_GOAL_RESULT_NOT_OBSERVED")
    candidates=[x for x in items if x["event"]=="HOME_PASS"]
    eligible=[]
    excluded=[]
    for item in candidates:
        cause=None
        if is_replay(item,intervals):
            cause="REPLAY_OR_SCENE_UNCERTAIN"
        elif item["confidence"]<0.86:
            cause="LOW_CONFIDENCE"
        elif not start or not goal or not (start["recording_sec"]<
                                             item["recording_sec"]<=goal["recording_sec"]):
            cause="OUTSIDE_START_GOAL"
        elif any((item["frame_sha256"]==earlier["frame_sha256"] or
                   phash_distance(item["phash64"],earlier["phash64"])<=1)
                  for earlier in eligible):
            cause="REPEATED_IMAGE"
        elif eligible and item["recording_sec"]-eligible[-1]["recording_sec"]<18:
            cause="TOO_CLOSE_TO_PREVIOUS_PASS"
        if cause:
            excluded.append({"id":item["id"],"recording_sec":item["recording_sec"],
                             "reason":cause})
        else:
            eligible.append(item)
    if len(eligible)!=4: reasons.append("NOT_FOUR_DISTINCT_LIVE_PASSES")
    if start and eligible:
        gap=eligible[0]["recording_sec"]-start["recording_sec"]
        if not 6<=gap<=110: reasons.append("FIRST_PASS_INTERVAL_IMPLAUSIBLE")
    for left,right in zip(eligible,eligible[1:]):
        if right["recording_sec"]-left["recording_sec"]>110:
            reasons.append("LAP_INTERVAL_TOO_LONG")
    if goal and eligible and not 0<=goal["recording_sec"]-eligible[-1]["recording_sec"]<=15:
        reasons.append("FINAL_PASS_NOT_NEAR_GOAL")
    if start and start["confidence"]<0.90:
        reasons.append("START_LOW_CONFIDENCE")
    if goal and goal["confidence"]<0.90:
        reasons.append("GOAL_LOW_CONFIDENCE")
    if doc["source"]=="SYNTHETIC_FIXTURE":
        reasons.append("SYNTHETIC_SOURCE_NOT_REAL_EVIDENCE")
    if not independent_visual_receipt:
        reasons.append("INDEPENDENT_VISUAL_RECEIPT_MISSING")
    # This document may suggest lap boundaries but may not approve itself.
    status=("FOUR_LAPS_VISUALLY_VERIFIED" if not reasons else
            "FOUR_LAPS_UNVERIFIED")
    report={
        "schema":REPORT,"race_id":doc["race_id"],
        "recording_sha256":doc["recording_sha256"],
        "source":doc["source"],"inference_model":doc["inference_model"],
        "status":status,"expected_laps":4,"pass_count":len(eligible),
        "candidate_count":len(candidates),"replay_intervals":intervals,
        "excluded_passes":excluded,"reasons":sorted(set(reasons)),
        "evidence":[
            {"lap":k+1,"recording_sec":x["recording_sec"],"event_id":x["id"],
             "frame_sha256":x["frame_sha256"],"confidence_score":x["confidence"]}
            for k,x in enumerate(eligible)
        ],
        "learning_admission":("INDEPENDENTLY_VERIFIED_ONLY" if not reasons
                              else "BLOCKED_UNVERIFIED"),
        "prediction_original_modified":False,
        "source_results_used_for_lap_inference":False,
    }
    report["audit_sha256"]=sha256(canonical(report).encode("utf-8")).hexdigest()
    return report
