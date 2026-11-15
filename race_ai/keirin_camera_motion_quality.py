"""Research-only camera background flow quality for exact KEIRIN source frames.

A source-bound two-frame sparse-LK / RANSAC partial affine estimate may help
investigate video transitions. It is NEVER proof of continuous athlete identity:
broadcast camera cuts, foreground cyclists, changing zoom and advertisements
may corrupt global flow. Below-quality windows stay UNKNOWN, not zero motion.

No automatically inferred car number, jersey identity, leader, second wheel,
attack, six-stage score or training output is emitted.
"""
from __future__ import annotations

from hashlib import sha256
import math

SCHEMA="RACE_AI_KEIRIN_CAMERA_FLOW_QUALITY_RESEARCH_V1"


class MotionQualityError(ValueError):
    pass


def need(ok,reason):
    if not ok:raise MotionQualityError(reason)


def assess_pair(previous_bgr,current_bgr,*,previous_sha,current_sha,
                gap_seconds=2):
    import cv2
    import numpy as np
    for source,h in ((previous_bgr,previous_sha),
                     (current_bgr,current_sha)):
        need(isinstance(source,np.ndarray) and
             source.dtype==np.uint8 and source.ndim==3 and
             source.shape[2]==3 and
             source.shape[0]>=100 and source.shape[1]>=150 and
             type(h) is str and len(h)==64 and
             sha256(source.tobytes()).hexdigest()==h,
             "SOURCE_IMAGE_SHA_OR_BGR_INVALID")
    need(previous_bgr.shape==current_bgr.shape,
         "FLOW_FRAME_SHAPES_DIFFER")
    need(type(gap_seconds) in (int,float) and
         math.isfinite(gap_seconds) and 0<gap_seconds<=10,
         "FRAME_TIME_GAP_INVALID")
    result={
        "schema":SCHEMA,
        "gap_seconds":gap_seconds,
        "tracked_features":0,"global_affine_inliers":0,
        "global_affine_inlier_fraction":None,
        "camera_transform_quality_state":"UNKNOWN",
        "reliable_for_person_id_or_tactics":False,
        "phase_scoring_admitted":False,
        "camera_cuts_independently_verified":False,
        "actual_rider_motion_or_number_verified":False,
    }
    if previous_sha==current_sha:
        result["camera_transform_quality_state"]="REPEATED_FRAME_NO_FLOW_PROOF"
        return result
    a=cv2.cvtColor(previous_bgr,cv2.COLOR_BGR2GRAY)
    b=cv2.cvtColor(current_bgr,cv2.COLOR_BGR2GRAY)
    pts=cv2.goodFeaturesToTrack(a,maxCorners=400,qualityLevel=.025,
                                minDistance=9,blockSize=5)
    if pts is None or len(pts)<20:
        result["camera_transform_quality_state"]="INSUFFICIENT_SOURCE_FEATURES"
        return result
    nxt,status,_=cv2.calcOpticalFlowPyrLK(
        a,b,pts,None,winSize=(31,31),maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,
                  35,.01))
    if nxt is None or status is None:
        result["camera_transform_quality_state"]="FLOW_TRACKING_FAILED"
        return result
    accepted=status.flatten()==1
    origin=pts[accepted].reshape(-1,2)
    moved=nxt[accepted].reshape(-1,2)
    n=len(origin)
    result["tracked_features"]=int(n)
    if n<20:
        result["camera_transform_quality_state"]="INSUFFICIENT_TRACKED_FEATURES"
        return result
    M,inliers=cv2.estimateAffinePartial2D(
        origin,moved,method=cv2.RANSAC,
        ransacReprojThreshold=4,maxIters=1800,confidence=.995)
    if M is None or inliers is None:
        result["camera_transform_quality_state"]="RANSAC_NO_GLOBAL_TRANSFORM"
        return result
    count=int(inliers.sum())
    ratio=count/n
    result["global_affine_inliers"]=count
    result["global_affine_inlier_fraction"]=round(float(ratio),4)
    scale=math.hypot(float(M[0,0]),float(M[1,0]))
    if count<20 or ratio<.5:
        result["camera_transform_quality_state"]="LOW_INLIER_GLOBAL_FLOW"
    elif not .8<=scale<=1.25 or not np.isfinite(M).all():
        result["camera_transform_quality_state"]="UNSTABLE_CAMERA_GEOMETRY"
    else:
        result["camera_transform_quality_state"]="" \
            "BACKGROUND_FLOW_GEOMETRY_CANDIDATE_ONLY"
    return result


def summarize_motion(rows,*,expected_transitions):
    need(type(rows) is list and len(rows)==expected_transitions and
         expected_transitions>=1 and expected_transitions<=600 and
         all(type(r) is dict and r.get("schema")==SCHEMA
             for r in rows),
         "MOTION_QUALITY_SOURCE_SET_INVALID")
    counts={}
    for r in rows:
        key=r["camera_transform_quality_state"]
        counts[key]=counts.get(key,0)+1
    candidate=counts.get("BACKGROUND_FLOW_GEOMETRY_CANDIDATE_ONLY",0)
    return {
        "schema":"RACE_AI_KEIRIN_CAMERA_MOTION_QUALITY_SUMMARY_V1",
        "source_frame_pairs":len(rows),
        "quality_states":dict(sorted(counts.items())),
        "background_geometry_candidate_pairs":candidate,
        "pairs_without_a_reliable_background_transform":
            len(rows)-candidate,
        "background_motion_quality_is_not_rider_identity":True,
        "qualified_rider_track_pairs":None,
        "race_position_or_line_coverage_pct":None,
        "independent_rider_accuracy_pct":None,
        "actual_phase_accuracy_pct":None,
        "actual_human_ground_truth_count":0,
        "model_weights_or_official_PDCA_changed":False,
    }
