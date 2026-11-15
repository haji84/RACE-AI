"""Two-independent-reviewer acceptance gate for private unseen KEIRIN footage.

Reuses the existing PR291 automatic color-region detector and frozen recording
SHA. This is an AUDIT, not a second racer detector, OCR model, forecast engine
or new self-training loop.

A provider result, race-card roster or user-controlled JSON cannot certify
a bounding box or rider identity. Two independently attested reviewers must
exhaustively annotate the SAME source frames. Incomplete annotations or any
disagreement remain HOLD, never auto-promote from detected jersey color.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from itertools import permutations
from pathlib import Path
import json
import math
import os
import re

PREDICTION_SCHEMA="RACE_AI_KEIRIN_BLIND_HOLDOUT_PROPOSALS_V1"
REVIEW_SCHEMA="RACE_AI_KEIRIN_BLIND_HOLDOUT_INDEPENDENT_REVIEW_V1"
AUDIT_SCHEMA="RACE_AI_KEIRIN_BLIND_HOLDOUT_AUDIT_V1"
HEX=re.compile(r"^[a-f0-9]{64}$")
RACE=re.compile(r"^\d{12}$")
KINDS=frozenset(("JERSEY_COLOR_REGION","RIDER_FULL_BODY"))
UNKNOWN="UNKNOWN"
INTER_REVIEW_IOU=0.5
DETECTION_IOU=0.3


class HoldoutGateError(ValueError):
    pass


def need(ok,code):
    if not ok:
        raise HoldoutGateError(code)


def json_bytes(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(json_bytes(value)).hexdigest()


def sha(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def clock(value):
    need(type(value) is str,"TIME_REQUIRED")
    try:
        t=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise HoldoutGateError("INVALID_AWARE_TIME") from None
    need(t.utcoffset() is not None,"INVALID_AWARE_TIME")
    return t.timestamp()


def box(value):
    need(type(value) is list and len(value)==4 and
         all(type(x) in (int,float) and math.isfinite(x) for x in value),
         "INVALID_NORMALIZED_BOX")
    x,y,w,h=value
    need(0<=x<=1 and 0<=y<=1 and 0<w<=1 and 0<h<=1 and
         x+w<=1+1e-9 and y+h<=1+1e-9,
         "NORMALIZED_BOX_OUTSIDE_FRAME")


def iou(a,b):
    ax,ay,aw,ah=a;bx,by,bw,bh=b
    ix=max(ax,bx);iy=max(ay,by)
    iw=max(0,min(ax+aw,bx+bw)-ix)
    ih=max(0,min(ay+ah,by+bh)-iy)
    overlap=iw*ih
    return overlap/(aw*ah+bw*bh-overlap) if overlap else 0.0


def checked_proposal(doc):
    need(type(doc) is dict and set(doc)=={
        "schema","race_id","recording_sha256","model_code_sha256",
        "model_train_race_ids","declared_cohort","frozen_at","target_kind",
        "frames","proposal_sha256"}, "INVALID_BLIND_PROPOSAL_ROOT")
    need(doc["schema"]==PREDICTION_SCHEMA and
         type(doc["race_id"]) is str and RACE.fullmatch(doc["race_id"]) and
         sha(doc["recording_sha256"]) and sha(doc["model_code_sha256"]) and
         doc["declared_cohort"]=="UNSEEN_HOLDOUT" and
         doc["target_kind"] in KINDS,
         "UNVERIFIED_HOLDOUT_IDENTITY")
    clock(doc["frozen_at"])
    history=doc["model_train_race_ids"]
    need(type(history) is list and len(history)<=2000 and
         len(history)==len(set(history)) and
         all(type(x) is str and RACE.fullmatch(x) for x in history) and
         doc["race_id"] not in history,
         "TRAIN_OR_HOLDOUT_RACE_LEAK")
    frames=doc["frames"]
    need(type(frames) is list and 1<=len(frames)<=600 and
         len(frames)==len({row["frame_sha256"] for row in frames}),
         "FRAMES_MISSING_OR_REUSED")
    last=-1.0
    for row in frames:
        need(type(row) is dict and set(row)=={
            "frame_sha256","recording_sec","proposals"},
            "INVALID_HOLDOUT_FRAME_RECORD")
        t=row["recording_sec"]
        need(sha(row["frame_sha256"]) and type(t) in (int,float) and
             math.isfinite(t) and t>last and 0<=t<=14400,
             "FRAME_SHA_OR_ORDER_INVALID")
        last=t
        propositions=row["proposals"]
        need(type(propositions) is list and len(propositions)<=100,
             "UNBOUNDED_DETECTION_PROPOSALS")
        for candidate in propositions:
            need(type(candidate) is dict and set(candidate)=={
                "bbox_xywh","car_color_candidate","identification_source"},
                "CANDIDATE_FIELDS_INVALID")
            box(candidate["bbox_xywh"])
            need(candidate["identification_source"] in (
                "COLOR_ONLY","NUMBER_DIGIT_OCR_CANDIDATE","UNKNOWN"),
                "UNTRUSTED_METHOD_INVALID")
            number=candidate["car_color_candidate"]
            need(number==UNKNOWN or type(number) is int and 1<=number<=9,
                 "CANDIDATE_CAR_INVALID")
    need(sha(doc["proposal_sha256"]) and doc["proposal_sha256"]==digest({
        k:v for k,v in doc.items() if k!="proposal_sha256"}),
        "UNTRUSTED_PREDICTION_TAMPERED")
    return doc


def make_proposals(*,race_id,recording_sha256,model_code_sha256,
                   model_train_race_ids,frames,frozen_at,target_kind):
    doc={
        "schema":PREDICTION_SCHEMA,"race_id":race_id,
        "recording_sha256":recording_sha256,
        "model_code_sha256":model_code_sha256,
        "model_train_race_ids":model_train_race_ids,
        "declared_cohort":"UNSEEN_HOLDOUT",
        "frozen_at":frozen_at,"target_kind":target_kind,"frames":frames,
    }
    doc["proposal_sha256"]=digest(doc)
    return checked_proposal(doc)


def freeze_private_once(path,doc):
    """Private, create-only predictions. Independent receipt still required."""
    checked_proposal(doc)
    p=Path(path)
    need(p.parent.is_dir() and not p.parent.is_symlink() and
         p.parent.stat().st_mode&0o077==0 and not p.exists() and
         not p.is_symlink(),
         "PRIVATE_PREDICTION_FREEZE_PATH_UNSAFE")
    payload=json_bytes(doc)+b"\n"
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
    with os.fdopen(os.open(p,flags,0o600),"wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    need(p.read_bytes()==payload,"PRIVATE_PREDICTION_READBACK_MISMATCH")
    return sha256(payload).hexdigest()


def checked_review(review,proposal):
    need(type(review) is dict and set(review)=={
        "schema","race_id","recording_sha256","proposal_sha256",
        "reviewer_id","reviewed_at","target_kind",
        "independent_source_frame_read","frames","review_sha256"},
        "INVALID_REVIEW_DOCUMENT")
    need(review["schema"]==REVIEW_SCHEMA and
         review["race_id"]==proposal["race_id"] and
         review["recording_sha256"]==proposal["recording_sha256"] and
         review["proposal_sha256"]==proposal["proposal_sha256"] and
         review["target_kind"]==proposal["target_kind"] and
         type(review["reviewer_id"]) is str and
         re.fullmatch(r"[A-Za-z0-9_.-]{5,80}",review["reviewer_id"]) and
         review["independent_source_frame_read"] is True and
         clock(review["reviewed_at"])>clock(proposal["frozen_at"]),
         "REVIEW_ID_TIME_OR_SOURCE_MISMATCH")
    expected=[x["frame_sha256"] for x in proposal["frames"]]
    rows=review["frames"]
    need(type(rows) is list and
         [x.get("frame_sha256") for x in rows]==expected,
         "REVIEW_FRAME_SET_NOT_COMPLETE")
    for row in rows:
        need(type(row) is dict and set(row)=={
            "frame_sha256","exhaustive_visible_targets","annotations"},
            "REVIEW_FRAME_FIELDS_INVALID")
        need(type(row["exhaustive_visible_targets"]) is bool and
             type(row["annotations"]) is list and len(row["annotations"])<=24,
             "REVIEW_ANNOTATIONS_INVALID")
        for ann in row["annotations"]:
            need(type(ann) is dict and set(ann)=={
                "bbox_xywh","car_number","number_evidence",
                "race_position","line_role"},
                "ANNOTATION_FIELDS_INVALID")
            box(ann["bbox_xywh"])
            need(ann["car_number"]==UNKNOWN or
                 type(ann["car_number"]) is int and
                 1<=ann["car_number"]<=9,
                 "REVIEW_NUMBER_INVALID")
            need(ann["number_evidence"] in (
                 "VISIBLE_DIGIT","INDEPENDENT_MULTIFRAME_ID",
                 "COLOR_ONLY","UNKNOWN") and
                 (ann["car_number"]!=UNKNOWN or
                  ann["number_evidence"]=="UNKNOWN"),
                 "INDEPENDENT_NUMBER_EVIDENCE_INVALID")
            need(ann["race_position"]==UNKNOWN or
                 type(ann["race_position"]) is int and
                 1<=ann["race_position"]<=9,
                 "POSITION_CANNOT_BE_INFERRED")
            need(ann["line_role"] in (
                 UNKNOWN,"LINE_FRONT","SECOND_WHEEL","THIRD_WHEEL",
                 "INDEPENDENT"),
                 "LINE_ROLE_INVALID")
    need(sha(review["review_sha256"]) and
         review["review_sha256"]==digest({
             k:v for k,v in review.items() if k!="review_sha256"}),
         "REVIEW_RECORD_TAMPERED")
    return review


def _trusted(cb,*args):
    if not callable(cb):return False
    try:return cb(*args) is True
    except Exception:return False


def _consensus(one,two):
    """Return consensus only when two full reviews match every target."""
    if not one["exhaustive_visible_targets"] or not two["exhaustive_visible_targets"]:
        return None,"NON_EXHAUSTIVE_REVIEW"
    a,b=one["annotations"],two["annotations"]
    pairs=[]
    for i,x in enumerate(a):
        for j,y in enumerate(b):
            overlap=iou(x["bbox_xywh"],y["bbox_xywh"])
            if overlap>=INTER_REVIEW_IOU:
                pairs.append((overlap,i,j))
    pairs.sort(reverse=True)
    used_a=set();used_b=set();matches=[]
    for overlap,i,j in pairs:
        if i in used_a or j in used_b:continue
        used_a.add(i);used_b.add(j)
        x,y=a[i],b[j]
        if (x["car_number"]!=y["car_number"] or
            x["number_evidence"]!=y["number_evidence"] or
            x["race_position"]!=y["race_position"] or
            x["line_role"]!=y["line_role"]):
            return None,"INDEPENDENT_REVIEW_DISAGREEMENT"
        matches.append(x)
    if len(matches)!=len(a) or len(matches)!=len(b):
        return None,"INDEPENDENT_REVIEW_DISAGREEMENT"
    return matches,None


def _pair_truth(proposed,truth):
    """One-to-one IoU matching; unmatched detections are FP only with complete GT."""
    choices=sorted(((iou(p["bbox_xywh"],t["bbox_xywh"]),i,j)
        for i,p in enumerate(proposed) for j,t in enumerate(truth)),
        reverse=True)
    used_p=set();used_t=set();matches=[]
    for overlap,i,j in choices:
        if overlap<DETECTION_IOU:break
        if i not in used_p and j not in used_t:
            used_p.add(i);used_t.add(j)
            matches.append((proposed[i],truth[j]))
    return len(matches),len(proposed)-len(matches),len(truth)-len(matches),matches


def audit(proposal,review_a=None,review_b=None,*,
          original_video_verifier=None,freeze_receipt_verifier=None,
          holdout_lineage_verifier=None,
          reviewer_receipt_verifier=None):
    """Do not let JSON content, user-supplied model scores or CI fixtures self-attest.

    Reviewer callback MUST check independent identities, source-frame bytes,
    and that review B did not consult review A or proposals. Fake callbacks
    demonstrate the code contract in CI but never authorize real deployment.
    """
    checked_proposal(proposal)
    reasons=[]
    if not _trusted(original_video_verifier,proposal):
        reasons.append("EXACT_PRIVATE_VIDEO_NOT_INDEPENDENTLY_ATTESTED")
    if not _trusted(freeze_receipt_verifier,proposal):
        reasons.append("FROZEN_DETECTOR_OUTPUT_NOT_INDEPENDENTLY_READBACK")
    if not _trusted(holdout_lineage_verifier,proposal):
        reasons.append("HOLDOUT_NOT_INDEPENDENTLY_PROVEN_UNUSED")
    if review_a is None or review_b is None:
        reasons.append("TWO_INDEPENDENT_REVIEWS_NOT_AVAILABLE")
    else:
        checked_review(review_a,proposal)
        checked_review(review_b,proposal)
        if review_a["reviewer_id"]==review_b["reviewer_id"]:
            reasons.append("REVIEWERS_NOT_INDEPENDENT")
        if not _trusted(reviewer_receipt_verifier,review_a,review_b,proposal):
            reasons.append("REVIEWER_SEPARATION_AND_FRAME_RECEIPTS_NOT_VERIFIED")
    tp=fp=fn=0
    color_ok=color_eligible=0
    all_target_boxes=0
    if not reasons:
        for p,ar,br in zip(proposal["frames"],review_a["frames"],review_b["frames"]):
            truth,reason=_consensus(ar,br)
            if reason:
                reasons.append(reason)
                break
            count,extra,missing,pairs=_pair_truth(p["proposals"],truth)
            tp+=count;fp+=extra;fn+=missing
            all_target_boxes+=len(truth)
            for guess,ref in pairs:
                if ref["car_number"]==UNKNOWN:continue
                # This is ONLY jersey-color category agreement, not a digit
                # OCR or a validated person's immutable identity.
                if guess["identification_source"]!="COLOR_ONLY":continue
                color_eligible+=1
                color_ok+=int(guess["car_color_candidate"]==ref["car_number"])
    ready=not reasons
    if not ready:
        tp=fp=fn=color_ok=color_eligible=all_target_boxes=None
    result={
        "schema":AUDIT_SCHEMA,
        "race_id":proposal["race_id"],
        "recording_sha256":proposal["recording_sha256"],
        "proposal_sha256":proposal["proposal_sha256"],
        "status":("TWO_REVIEW_TORSO_REGION_DETECTION_ADMITTED"
                  if ready and proposal["target_kind"]=="JERSEY_COLOR_REGION"
                  else "TWO_REVIEW_FULL_BODY_DETECTION_ADMITTED"
                  if ready else "HOLD_INDEPENDENT_GROUND_TRUTH_UNVERIFIED"),
        "hold_reasons":sorted(set(reasons)),
        "source_frames":len(proposal["frames"]),
        "untrusted_candidate_regions":sum(len(x["proposals"]) for x in
                                           proposal["frames"]),
        "independent_two_reviewer_ground_truth_boxes":all_target_boxes,
        "true_positive_region_boxes":tp,
        "false_positive_region_boxes":fp,
        "false_negative_region_boxes":fn,
        "independent_region_detection_precision_pct":(
            round(100*tp/(tp+fp),3) if ready and tp+fp else None),
        "independent_region_detection_recall_pct":(
            round(100*tp/(tp+fn),3) if ready and tp+fn else None),
        "independent_region_detection_f1_pct":(
            round(200*tp/(2*tp+fp+fn),3)
            if ready and 2*tp+fp+fn else None),
        "jersey_color_match_among_iou_matched_pct":(
            round(100*color_ok/color_eligible,3)
            if ready and color_eligible else None),
        "digit_OCR_accuracy_pct":None,
        "confirmed_rider_person_ID_accuracy_pct":None,
        "rank_accuracy_pct":None,
        "line_role_accuracy_pct":None,
        "independently_verified_six_phase_count":0,
        "official_phase_score_updated":False,
        "training_or_model_weights_modified":False,
        "same_race_results_used_for_prediction":False,
        "public_raw_frames_or_private_boxes_exported":False,
    }
    result["audit_sha256"]=digest(result)
    return result
