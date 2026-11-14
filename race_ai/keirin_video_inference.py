"""Convert private ML scene scores into reviewable, non-self-attested lap events.

Never infer four laps just from a scheduled four-lap race or the elapsed time.
Camera cuts, same-corner shots and repeated replays remain uncertain until a
separate model/human reviewer confirms actual line crossings.
"""
from __future__ import annotations
from itertools import groupby
import math

from .keirin_video_learning import (
    FEATURE_SCHEMA, MODEL_SCHEMA, predict_scene, SceneLearningError)
from .keirin_video_events import SCHEMA, audit

LABEL_TO_EVENT={
    "START":"START","HOME_PASS":"HOME_PASS","GOAL":"GOAL",
    "RESULT":"RESULT","REPLAY":"REPLAY_START"
}
THRESHOLD={"START":.90,"HOME_PASS":.86,"GOAL":.90,
           "REPLAY":.80,"RESULT":.88}

def _collapse(predictions, samples, *, spacing):
    """Only persistent, high-score clusters; ignore isolated camera edits."""
    candidates=[]
    for row,p in zip(samples,predictions):
        label=p["label"]
        if label not in LABEL_TO_EVENT:
            continue
        if p["score"]<THRESHOLD[label]:
            continue
        candidates.append((row,p))
    segments=[]
    current=[]
    for pair in candidates:
        if (current and (pair[1]["label"]!=current[-1][1]["label"]
            or pair[0]["t"]-current[-1][0]["t"]>spacing*1.7)):
            segments.append(current)
            current=[]
        current.append(pair)
    if current:segments.append(current)
    return [x for x in segments if len(x)>=2]

def to_review_queue(feature_doc, model, *, source="WINTICKET_LIVE"):
    """Return unapproved AI event candidates and a fail-closed audit.

    All frames/hashes stay within the owner runtime. Public repository must not
    receive real feature observations or inferred video event lists.
    """
    if feature_doc.get("schema")!=FEATURE_SCHEMA or model.get("schema")!=MODEL_SCHEMA:
        raise SceneLearningError("FEATURE_OR_MODEL_SCHEMA_MISMATCH")
    if feature_doc.get("feature_version")!=model.get("feature_version"):
        raise SceneLearningError("FEATURE_VERSION_MISMATCH")
    if feature_doc.get("race_id") in model.get("train_races",[]):
        raise SceneLearningError("TRAINING_RACE_CANNOT_SELF_VERIFY_LAPS")
    samples=feature_doc["features"]
    if len(samples)<10:
        raise SceneLearningError("INSUFFICIENT_VIDEO_SAMPLES")
    stride=feature_doc["sampling_seconds"]
    if not 1<=stride<=10:
        raise SceneLearningError("INVALID_STRIDE")
    predictions=[predict_scene(model,row) for row in samples]
    groups=_collapse(predictions,samples,spacing=stride)
    events=[]
    replay_open=False
    for group in groups:
        label=group[0][1]["label"]
        strongest=max(group,key=lambda x:x[1]["score"])
        row,p=strongest
        if label=="REPLAY":
            if not replay_open:
                events.append((group[0][0]["t"],{
                    "id":"replay-start-"+str(len(events)),"event":"REPLAY_START",
                    "scene":"REPLAY","item":group[0]}))
                replay_open=True
            continue
        if replay_open:
            events.append((group[0][0]["t"]-min(stride,0.5),{
                "id":"replay-end-"+str(len(events)),"event":"REPLAY_END",
                "scene":"REPLAY","item":group[0]}))
            replay_open=False
        events.append((row["t"],{
            "id":"scene-"+str(len(events)),
            "event":LABEL_TO_EVENT[label],
            "scene":"LIVE" if label!="RESULT" else "INTERMISSION",
            "item":strongest
        }))
    if replay_open and events:
        # No end marker: audit will consider the remainder a replay.
        pass
    observations=[]
    for t,entry in sorted(events,key=lambda x:x[0]):
        selected=entry["item"]
        if isinstance(selected,tuple):
            row,p=selected
            score=p["score"]
            replay_score=p["class_scores"].get("REPLAY",0.0)
        else:
            row,p=selected
            score=p["score"]
            replay_score=p["class_scores"].get("REPLAY",0.0)
        # Deduplicate timestamp collisions without creating invented frames.
        if observations and t<=observations[-1]["recording_sec"]:
            t=observations[-1]["recording_sec"]+0.001
        observations.append({
            "id":entry["id"],
            "recording_sec":round(float(t),3),
            "event":entry["event"],
            "confidence":score,
            "frame_sha256":row["frame_sha256"],
            "phash64":row["phash64"],
            "scene":entry["scene"],
            "replay_confidence":replay_score,
            "origin":"VISION_MODEL"
        })
    doc={
        "schema":SCHEMA,"race_id":feature_doc["race_id"],
        "recording_sha256":feature_doc["recording_sha256"],
        "duration_s":feature_doc["duration_s"],"expected_laps":4,
        "source":source,"inference_model":model["model_sha256"],
        "observations":observations
    }
    # A classifier cannot issue its own independent visual attestation.
    report=audit(doc)
    return {
        "input":doc,
        "audit":report,
        "private_review_required":True,
        "candidate_count":len(observations),
        "predicted_class_counts":{x:sum(p["label"]==x for p in predictions)
                                  for x in sorted(set(p["label"] for p in predictions))},
        "trained_and_calibrated":False,
        "model_may_self_certify_four_laps":False,
    }
