"""Qualify complete or partial historical KEIRIN footage for *different* learning tasks.

The source owner's permission, independently inspected frames, and source hash
are mandatory for REAL training admission. A 60-90 second highlights replay
may teach visible attacks, finishing and replay scenes, but MUST NOT be used
to assert four distinct race laps or that an unseen action did not happen.

This is a private data gate, not a web scraper, license grant, or prediction.
"""
from __future__ import annotations

from hashlib import sha256
from datetime import datetime
from urllib.parse import urlparse
import json
import math
import re

CLIP_SCHEMA="RACE_AI_KEIRIN_CLIP_REVIEW_V1"
ADMISSION_SCHEMA="RACE_AI_KEIRIN_CLIP_TRAINING_ADMISSION_V1"
SHA=re.compile(r"^[0-9a-f]{64}$")
EVENTS=frozenset({
    "ATTACK","POSITION_GAIN","LINE_SPLIT","FINAL_SPRINT",
    "GOAL","FINISH","REPLAY","RACING","START","HOME_PASS",
})
LEARNABLE=frozenset({"ATTACK","POSITION_GAIN","LINE_SPLIT",
                     "FINAL_SPRINT","GOAL","FINISH"})
TACTICAL=frozenset({"ATTACK","POSITION_GAIN","LINE_SPLIT","FINAL_SPRINT"})
CLASSES=("ATTACK","POSITION_GAIN","LINE_SPLIT","FINAL_SPRINT",
         "GOAL","FINISH","REPLAY","RACING")
PRIORITY={"FULL_FOUR_LAPS":2,"PARTIAL_HIGHLIGHTS":1}

class ClipPolicyError(ValueError):
    pass

def insist(ok,code):
    if not ok:raise ClipPolicyError(code)

def digest(obj):
    return sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,
        separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()

def validate(clip):
    insist(type(clip) is dict and set(clip)=={
        "schema","race_id","source_url","source_kind","recording_sha256",
        "duration_s","claimed_coverage","reviewed_at","events"},
        "INVALID_CLIP_REVIEW_SCHEMA")
    insist(clip["schema"]==CLIP_SCHEMA,"INVALID_CLIP_REVIEW_VERSION")
    insist(isinstance(clip["race_id"],str) and
           re.fullmatch(r"[a-zA-Z0-9._-]{4,110}",clip["race_id"]),
           "INVALID_RACE_ID")
    insist(clip["source_kind"] in ("WINTICKET_PAST_REPLAY","WINTICKET_LIVE",
            "AUTHORIZED_OTHER","SYNTHETIC_FIXTURE"),"INVALID_SOURCE_KIND")
    insist(clip["claimed_coverage"] in PRIORITY,"INVALID_COVERAGE_CLAIM")
    u=urlparse(clip["source_url"]) if isinstance(clip["source_url"],str) else None
    if clip["source_kind"]=="SYNTHETIC_FIXTURE":
        insist(clip["source_url"]=="synthetic://no-media","INVALID_SOURCE_URL")
    else:
        insist(u is not None and u.scheme=="https" and u.hostname and
               not u.username and not u.password and not u.fragment,
               "INVALID_SOURCE_URL")
        if clip["source_kind"].startswith("WINTICKET"):
            insist(u.hostname=="www.winticket.jp" and
                   u.path.startswith("/keirin/"),"SOURCE_HOST_MISMATCH")
    insist(isinstance(clip["recording_sha256"],str) and
           SHA.fullmatch(clip["recording_sha256"]),"INVALID_RECORDING_SHA")
    d=clip["duration_s"]
    insist(type(d) in (int,float) and math.isfinite(d) and 10<=d<=14400,
           "INVALID_VIDEO_DURATION")
    insist(isinstance(clip["reviewed_at"],str) and clip["reviewed_at"],
           "REVIEW_TIME_REQUIRED")
    try:
        dt=datetime.fromisoformat(clip["reviewed_at"].replace("Z","+00:00"))
        insist(dt.utcoffset() is not None,"REVIEW_TIMEZONE_REQUIRED")
    except ValueError:
        raise ClipPolicyError("INVALID_REVIEW_TIME") from None
    insist(type(clip["events"]) is list and
           len(clip["events"])<=10000,"INVALID_FRAME_EVENTS")
    ids=set(); actions=set(); prev=-1.
    for row in clip["events"]:
        insist(type(row) is dict and set(row)=={
            "id","time_s","label","rider_id","action_key",
            "frame_sha256","scene","review_ref"},
            "INVALID_EVENT_SCHEMA")
        insist(isinstance(row["id"],str) and
               re.fullmatch(r"[a-zA-Z0-9_.-]{1,90}",row["id"]) and
               row["id"] not in ids,"DUPLICATE_EVENT_ID")
        ids.add(row["id"])
        t=row["time_s"]
        insist(type(t) in (int,float) and math.isfinite(t) and
               prev<t<=d,"OUT_OF_ORDER_EVENT_TIME")
        prev=t
        insist(row["label"] in EVENTS,"INVALID_EVENT_LABEL")
        insist(row["scene"] in ("LIVE","REPLAY","UNKNOWN"),"UNKNOWN_VIDEO_SCENE")
        insist(isinstance(row["frame_sha256"],str) and
               SHA.fullmatch(row["frame_sha256"]),"FRAME_SHA_REQUIRED")
        insist(isinstance(row["review_ref"],str) and
               len(row["review_ref"])>=6,"INDEPENDENT_FRAME_REFERENCE_REQUIRED")
        insist(isinstance(row["action_key"],str) and
               re.fullmatch(r"[a-zA-Z0-9_.-]{1,90}",row["action_key"]),
               "ACTION_KEY_REQUIRED")
        if row["label"] in TACTICAL:
            insist(isinstance(row["rider_id"],str) and
                   2<=len(row["rider_id"])<=90,"TACTIC_RIDER_REQUIRED")
        else:
            insist(row["rider_id"] is None or isinstance(row["rider_id"],str),
                   "INVALID_RIDER_ID")
        # A replay of the same attack is one action, NOT a second training
        # occurrence. Duplicated action keys may be present and are reduced
        # below; conflicting labels for one key require independent review.
        actions.add(row["action_key"])
    return clip

def _reviewed_unique_actions(clip):
    chosen={};conflicts=set()
    for row in clip["events"]:
        if row["label"] not in LEARNABLE or row["scene"]=="UNKNOWN":
            continue
        k=row["action_key"]
        if k in chosen and (chosen[k]["label"]!=row["label"] or
                            chosen[k]["rider_id"]!=row["rider_id"]):
            conflicts.add(k)
        elif k not in chosen or (chosen[k]["scene"]=="REPLAY" and
                                  row["scene"]=="LIVE"):
            chosen[k]=row
    for k in conflicts:
        chosen.pop(k,None)
    return list(chosen.values()),sorted(conflicts)

def assess_clip(clip, *, independent_visual_verifier=None,
                rights_verifier=None, full_lap_audit=None,
                lap_audit_verifier=None):
    """Return a research-learning admission, never a grant of rights.

    Both callbacks must be independent of the user-provided metadata.
    A certified 4-lap audit upgrades the tier; otherwise inspected short
    scenes fall back to partial learning without inventing missing laps.
    """
    validate(clip)
    external_frame_ok=False;rights_ok=False
    if callable(independent_visual_verifier):
        try:external_frame_ok=independent_visual_verifier(clip) is True
        except Exception:pass
    if callable(rights_verifier):
        try:rights_ok=rights_verifier(
            clip["source_url"],"private_keirin_video_scene_training") is True
        except Exception:pass
    is_synthetic=clip["source_kind"]=="SYNTHETIC_FIXTURE"
    unique,conflicts=_reviewed_unique_actions(clip)
    useful=[e for e in unique if e["label"] in LEARNABLE]
    full_ok=False
    if clip["claimed_coverage"]=="FULL_FOUR_LAPS" and callable(lap_audit_verifier):
        try:
            full_ok=(type(full_lap_audit) is dict and
                     full_lap_audit.get("status")=="FOUR_LAPS_VISUALLY_VERIFIED" and
                     full_lap_audit.get("recording_sha256")==clip["recording_sha256"] and
                     full_lap_audit.get("race_id")==clip["race_id"] and
                     lap_audit_verifier(full_lap_audit,clip) is True)
        except Exception:pass
    reasons=[]
    if is_synthetic: reasons.append("SYNTHETIC_NOT_REAL_TRAINING")
    if not external_frame_ok: reasons.append("INDEPENDENT_FRAME_REVIEW_MISSING")
    if not rights_ok: reasons.append("TRAINING_RIGHTS_NOT_CONFIRMED")
    if not useful: reasons.append("NO_VISIBLE_LEARNABLE_ACTION")
    if conflicts: reasons.append("CONFLICTING_DUPLICATE_ACTION_LABELS")
    admitted=(not reasons)
    tier=("FULL_FOUR_LAPS" if full_ok else "PARTIAL_HIGHLIGHTS")
    if clip["claimed_coverage"]=="FULL_FOUR_LAPS" and not full_ok:
        reasons.append("FOUR_LAPS_NOT_INDEPENDENTLY_ATTESTED")
        # Do not withhold genuinely reviewed visible actions simply because
        # coverage is not fully verified. The tier remains PARTIAL.
    eligible_labels=sorted({e["label"] for e in useful}) if admitted else []
    result={
        "schema":ADMISSION_SCHEMA,"race_id":clip["race_id"],
        "recording_sha256":clip["recording_sha256"],
        "source_kind":clip["source_kind"],
        "claimed_coverage":clip["claimed_coverage"],
        "admitted_coverage":tier if admitted else "NONE",
        "training_eligible":admitted,
        "learnable_labels":eligible_labels,
        "evidence_event_count":len(useful) if admitted else 0,
        "deduplicated_replay_count":max(0,sum(e["label"] in LEARNABLE
            and e["scene"]=="REPLAY" for e in clip["events"])-
            sum(e["scene"]=="REPLAY" for e in useful)),
        "conflicting_action_keys":conflicts,
        "all_four_laps_verified":bool(admitted and full_ok),
        "allowed_tasks":(["LAP_PASS_COUNT","TACTICS","GOAL",
                         "REPLAY_DISCRIMINATION"] if admitted and full_ok
                         else ["VISIBLE_TACTICS","VISIBLE_GOAL",
                               "REPLAY_DISCRIMINATION"] if admitted else []),
        "unseen_actions_mean_negative":False,
        "confidence_source":"INDEPENDENT_FRAME_REVIEW_REQUIRED",
        "reasons":sorted(set(reasons)),
        "reviewed_scene_frames":([{
             "label":("REPLAY" if row["scene"]=="REPLAY" else row["label"]),
             "frame_sha256":row["frame_sha256"],
             "review_ref":row["review_ref"],
             "time_s":row["time_s"]}
             for row in clip["events"] if row["scene"]!="UNKNOWN" and
             ("REPLAY" if row["scene"]=="REPLAY" else row["label"]) in CLASSES]
             if admitted else []),
        "reviewed_events":([{
             "id":row["id"],"time_s":row["time_s"],
             "label":row["label"],"rider_id":row["rider_id"],
             "action_key":row["action_key"],
             "frame_sha256":row["frame_sha256"],"scene":row["scene"],
             "review_ref":row["review_ref"]}
             for row in useful] if admitted else []),
        "source_video_exported":False,
        "same_race_pre_cutoff_prediction_modified":False,
    }
    result["admission_sha256"]=digest(result)
    return result

def choose_preferred_clips(admissions):
    """Prefer independently verified full recording per race; else highlights.

    Never mistake a candidate manifest/website video button for permission
    or a reviewed training datum. Same-race duplicates are never additive.
    """
    insist(type(admissions) is list,"INVALID_ADMISSIONS")
    selected={}; rejected=[]
    for item in admissions:
        insist(type(item) is dict and item.get("schema")==ADMISSION_SCHEMA and
               item.get("admission_sha256")==digest({
                   k:v for k,v in item.items() if k!="admission_sha256"}),
               "INVALID_ADMISSION_INTEGRITY")
        if not item.get("training_eligible"):
            rejected.append(item.get("race_id"))
            continue
        rank=PRIORITY[item["admitted_coverage"]]
        key=item["race_id"]
        if (key not in selected or
            rank>PRIORITY[selected[key]["admitted_coverage"]] or
            rank==PRIORITY[selected[key]["admitted_coverage"]] and
            item["evidence_event_count"]>selected[key]["evidence_event_count"]):
            selected[key]=item
    return {"selected":dict(sorted(selected.items())),
            "excluded_unverified":rejected,
            "full_count":sum(x["admitted_coverage"]=="FULL_FOUR_LAPS"
                             for x in selected.values()),
            "partial_count":sum(x["admitted_coverage"]=="PARTIAL_HIGHLIGHTS"
                                for x in selected.values())}
