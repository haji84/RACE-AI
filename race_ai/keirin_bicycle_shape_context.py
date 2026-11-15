"""Source-bound cyclist/bicycle SHAPE context for existing frozen color blobs.

Not a new object detector or rider identity model. Compare immutable A HSV
color-region candidates with existing conservative B on the exact source BGR.
Extract a weak, independently observed circular pair cue beneath candidate
upper-body regions using OpenCV HoughCircles, plus horizontal/upper-image
background-risk flags. Nothing here is labeled a real cyclist or a wrong
detection. Missing wheel evidence MUST remain UNKNOWN, never rejected.

Original A, PR71 forecasts, results, PDCA and model weights are unchanged.
No video pixels or private bounding boxes leave the owner-private runtime.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import math
import re

from .keirin_color_ab_stability import (
    conservative_blobs, SIZE, NEAR_PX, SUPPORTED,
)

SCHEMA = "RACE_AI_KEIRIN_BICYCLE_SHAPE_CONTEXT_RESEARCH_V1"
SUMMARY_SCHEMA = "RACE_AI_KEIRIN_BICYCLE_SHAPE_CONTEXT_AGGREGATE_V1"
SHA = re.compile(r"^[0-9a-f]{64}$")
# These are hypothesis-generating weak geometric cues on a fixed cropped
# broadcast viewport; they have NOT been calibrated to true rider labels.
CIRCLE_DP=1.2
CIRCLE_MIN_DIST=25
CIRCLE_PARAM1=110
CIRCLE_PARAM2=30
CIRCLE_MIN_RADIUS=15
CIRCLE_MAX_RADIUS=52
CIRCLE_Y_RANGE=(160,510)


class BicycleContextError(ValueError):
    pass


def need(ok, why):
    if not ok:
        raise BicycleContextError(why)


def _frozen_bounds(region):
    need(type(region) is dict and set(region)=={
        "bbox_xywh","car_color_candidate","identification_source"} and
        region["identification_source"]=="COLOR_ONLY" and
        type(region["car_color_candidate"]) is int and
        region["car_color_candidate"] in SUPPORTED,
        "EXISTING_A_CANDIDATE_REQUIRED")
    b=region["bbox_xywh"]
    need(type(b) is list and len(b)==4 and
         all(type(z) in (int,float) and math.isfinite(z) for z in b) and
         all(0<=z<=1 for z in b) and b[2]>0 and b[3]>0 and
         b[0]+b[2]<=1 and b[1]+b[3]<=1,
         "EXISTING_A_NORMALIZED_BBOX_INVALID")
    x,y,w,h=b
    return (x*SIZE[0],y*SIZE[1],w*SIZE[0],h*SIZE[1])


def _circle_pairs(circles,center):
    cx,cy=center
    # A local pair of possible wheel arcs BELOW the blob, with approximate
    # wheel center spacing. Parts of adverts / track curves can match too.
    # This cannot certify that the blob is an athlete.
    close=[
        (float(x),float(y),float(r))
        for x,y,r in circles
        if -120<=x-cx<=140 and 5<=y-cy<=145
    ]
    for i,a in enumerate(close):
        for b in close[i+1:]:
            if 32<=abs(a[0]-b[0])<=115 and abs(a[1]-b[1])<=55:
                return True
    return False


def analyze_frame(bgr, frozen_a, *, expected_sha256, second):
    """Check original frame hash BEFORE any color or wheel shape inference.

    Outputs private one-record-per-A hypothesis tags plus aggregate counts.
    Each A candidate gets one fixed status; manual rider labels and race
    results are neither read nor used to select boxes. A single wheel cue
    does not grant independent person tracking or accuracy.
    """
    import cv2
    import numpy as np

    need(isinstance(bgr,np.ndarray) and bgr.dtype==np.uint8 and
         bgr.ndim==3 and bgr.shape[2]==3 and
         bgr.shape[0]>=100 and bgr.shape[1]>=150 and
         type(expected_sha256) is str and
         SHA.fullmatch(expected_sha256) is not None and
         sha256(bgr.tobytes()).hexdigest()==expected_sha256,
         "SOURCE_BOUND_BGR_SHA_REQUIRED")
    need(type(second) in (int,float) and
         math.isfinite(second) and second>=0 and
         type(frozen_a) is list and len(frozen_a)<=100,
         "FROZEN_FRAME_OR_TIME_INVALID")
    boxes=[_frozen_bounds(a) for a in frozen_a]
    B=conservative_blobs(bgr,expected_frame_sha256=expected_sha256)
    edges=[]
    for i,(x,y,w,h) in enumerate(boxes):
        cx,cy=x+w/2,y+h/2
        for j,b in enumerate(B):
            distance=math.hypot(cx-b["center_x"],cy-b["center_y"])
            if distance<=NEAR_PX:
                edges.append((distance,i,j))
    edges.sort(key=lambda t:(t[0],t[1],t[2]))
    used_a=set();used_b=set();associations={}
    for distance,i,j in edges:
        if i in used_a or j in used_b:continue
        used_a.add(i);used_b.add(j)
        associations[i]=j

    gray=cv2.cvtColor(cv2.resize(bgr,SIZE,interpolation=cv2.INTER_LINEAR),
                      cv2.COLOR_BGR2GRAY)
    raw=cv2.HoughCircles(
        cv2.medianBlur(gray,5),cv2.HOUGH_GRADIENT,
        dp=CIRCLE_DP,minDist=CIRCLE_MIN_DIST,
        param1=CIRCLE_PARAM1,param2=CIRCLE_PARAM2,
        minRadius=CIRCLE_MIN_RADIUS,maxRadius=CIRCLE_MAX_RADIUS)
    circles=[] if raw is None else [
        tuple(float(z) for z in p)
        for p in raw[0]
        if CIRCLE_Y_RANGE[0]<=p[1]<=CIRCLE_Y_RANGE[1]
    ]
    stats=Counter()
    private_records=[]
    for i,(box,a) in enumerate(zip(boxes,frozen_a)):
        x,y,w,h=box
        candidate_b=associations.get(i)
        color_agree=(candidate_b is not None and
                     B[candidate_b]["color"]==a["car_color_candidate"])
        pair=_circle_pairs(circles,(x+w/2,y+h/2))
        risk=(w>3*h or y<240)
        if candidate_b is None:
            kind="A_ONLY_NO_B_SPATIAL_PAIR"
        elif color_agree:
            kind="A_B_SPATIAL_AND_COLOR_AGREEMENT"
        else:
            kind="A_B_SPATIAL_COLOR_DISAGREEMENT"
        stats[kind]+=1
        stats["A_CANDIDATES"]+=1
        stats["WEAK_WHEEL_PAIR_CONTEXT" if pair
              else "NO_WEAK_WHEEL_PAIR_EVIDENCE"]+=1
        if pair and candidate_b is None:
            stats["A_ONLY_WITH_POSSIBLE_BICYCLE_CONTEXT"]+=1
        if risk:
            stats["BROAD_IMAGE_BACKGROUND_RISK_FLAG"]+=1
            if not pair and candidate_b is None:
                stats["A_ONLY_BACKGROUND_RISK_WITHOUT_WHEEL_CUE"]+=1
        # These reasons are deliberately *not* false positive/true positive.
        private_records.append({
            "frozen_A_index":i,
            "color_candidate":a["car_color_candidate"],
            "research_color_pair_state":kind,
            "research_possible_wheel_pair_context":pair,
            "research_background_risk_flag":risk,
            "recognized_athlete":False,
            "number_or_tactics_independently_verified":False,
        })
    stats["B_CANDIDATES"]=len(B)
    stats["A_B_SPATIAL_PAIRS"]=len(associations)
    stats["A_B_SAME_COLOR_PAIRS"]=stats["A_B_SPATIAL_AND_COLOR_AGREEMENT"]
    # Counter omits zero-valued entries. Stable explicit zeros are essential
    # for trustworthy empty-source/abstention reporting and regression tests.
    required_counts=(
        "A_CANDIDATES","B_CANDIDATES","A_B_SPATIAL_PAIRS",
        "A_B_SAME_COLOR_PAIRS",
        "A_ONLY_NO_B_SPATIAL_PAIR",
        "A_B_SPATIAL_AND_COLOR_AGREEMENT",
        "A_B_SPATIAL_COLOR_DISAGREEMENT",
        "WEAK_WHEEL_PAIR_CONTEXT",
        "NO_WEAK_WHEEL_PAIR_EVIDENCE",
        "A_ONLY_WITH_POSSIBLE_BICYCLE_CONTEXT",
        "BROAD_IMAGE_BACKGROUND_RISK_FLAG",
        "A_ONLY_BACKGROUND_RISK_WITHOUT_WHEEL_CUE",
    )
    need(sum(stats[k] for k in (
         "A_ONLY_NO_B_SPATIAL_PAIR",
         "A_B_SPATIAL_AND_COLOR_AGREEMENT",
         "A_B_SPATIAL_COLOR_DISAGREEMENT"))==len(frozen_a),
         "SHAPE_CONTEXT_CANDIDATE_PARTITION_INVALID")
    return {
        "schema":SCHEMA,
        "second":second,
        "source_frame_sha256":expected_sha256,
        "counts":{k:int(stats.get(k,0)) for k in required_counts},
        "private_candidate_hypotheses_not_ground_truth":private_records,
        "automatically_removed_candidate_count":0,
        "missing_wheels_do_not_erase_riders":True,
        "circle_pairs_not_independently_verified_wheels":True,
        "original_color_proposals_modified":False,
        "person_detection_accuracy_pct":None,
        "car_number_OCR_accuracy_pct":None,
        "eligible_for_formal_phase_scoring":False,
    }


def summarize_shape_context(rows,*,expected_frame_count,
                            expected_a_count,expected_b_count,
                            expected_spatial_count,expected_color_count):
    need(type(rows) is list and len(rows)==expected_frame_count and
         type(expected_frame_count) is int and 1<=expected_frame_count<=600 and
         len({r["source_frame_sha256"] for r in rows})==len(rows) and
         all(type(r) is dict and r.get("schema")==SCHEMA for r in rows) and
         all(rows[i]["second"]<rows[i+1]["second"]
             for i in range(len(rows)-1)),
         "REAL_SAVED_SOURCE_FRAME_SET_REQUIRED")
    def total(k):return sum(x["counts"].get(k,0) for x in rows)
    baseline=(total("A_CANDIDATES"),total("B_CANDIDATES"),
              total("A_B_SPATIAL_PAIRS"),total("A_B_SAME_COLOR_PAIRS"))
    need(baseline==(expected_a_count,expected_b_count,
                     expected_spatial_count,expected_color_count),
         "FROZEN_A_B_COUNTS_CHANGED")
    must=(
      "A_ONLY_NO_B_SPATIAL_PAIR",
      "A_B_SPATIAL_AND_COLOR_AGREEMENT",
      "A_B_SPATIAL_COLOR_DISAGREEMENT",
      "WEAK_WHEEL_PAIR_CONTEXT",
      "NO_WEAK_WHEEL_PAIR_EVIDENCE",
      "A_ONLY_WITH_POSSIBLE_BICYCLE_CONTEXT",
      "BROAD_IMAGE_BACKGROUND_RISK_FLAG",
      "A_ONLY_BACKGROUND_RISK_WITHOUT_WHEEL_CUE")
    counts={key:total(key) for key in must}
    need(counts["WEAK_WHEEL_PAIR_CONTEXT"]+
         counts["NO_WEAK_WHEEL_PAIR_EVIDENCE"]==expected_a_count,
         "WHEEL_CONTEXT_PARTITION_DRIFT")
    special={}
    for t in (14,32,82):
        candidates=[x for x in rows if x["second"]==t]
        if candidates:
            r=candidates[0]
            special[str(t)]={
                "a_color_blobs":r["counts"].get("A_CANDIDATES",0),
                "possible_wheel_pair_support":
                    r["counts"].get("WEAK_WHEEL_PAIR_CONTEXT",0),
                "a_only_with_wheel_cue":
                    r["counts"].get("A_ONLY_WITH_POSSIBLE_BICYCLE_CONTEXT",0),
                "a_only_background_risk_without_wheel_cue":
                    r["counts"].get(
                      "A_ONLY_BACKGROUND_RISK_WITHOUT_WHEEL_CUE",0),
            }
    return {
        "schema":SUMMARY_SCHEMA,
        "verified_source_frames":len(rows),
        "frozen_A_color_regions":expected_a_count,
        "strict_B_color_regions":expected_b_count,
        "A_B_spatial_pairs":expected_spatial_count,
        "A_B_same_color_pairs":expected_color_count,
        "research_weak_bicycle_context_counts":counts,
        "priority_source_seconds":special,
        "removed_existing_A_regions":0,
        "no_person_labels_fabricated":True,
        "possible_wheel_pairs_may_include_background":True,
        "absence_of_wheel_pair_not_a_negative_rider_label":True,
        "rider_detection_precision_pct":None,
        "rider_detection_recall_pct":None,
        "car_number_accuracy_pct":None,
        "tracked_person_accuracy_pct":None,
        "six_phase_accuracy_pct":None,
        "formal_PDCA_and_training_updated":False,
        "original_prediction_model_unchanged":True,
        "public_private_box_coordinates_or_pixels_exported":False,
    }
