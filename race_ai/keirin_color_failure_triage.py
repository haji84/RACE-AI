"""Source-bound A/B color-blob failure triage, NOT rider identity accuracy.

Reads an unchanged source BGR frame and previously FROZEN A region boxes.
B is the already-implemented stricter HSV filter, evaluated on the very same
image. For A-only boxes, count stricter HSV pixels inside that original A box
and separate threshold sensitivity from possible geometry/assignment issues.

The returned analysis is REDACTED aggregate counts only. No person bounding
boxes, names, OCR evidence, credentials, raw images or private exact positions
are exported. No auto-confirmation of riders or phase scoring is allowed.

Single-source colour changes do NOT prove false positives. A static billboard,
cyclist jersey, track paint and wheel reflection may all have similar colour.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import math

from .keirin_color_ab_stability import (
    ABStabilityError, conservative_blobs, need,
    SIZE, ROI_Y, SUPPORTED, NEAR_PX,
)

SCHEMA="RACE_AI_KEIRIN_COLOR_FAILURE_TRIAGE_V1"


def _mask_strict(h,s,v,car):
    if car==3:return ((h>=171)|(h<=3))&(s>90)&(v>100)
    if car==4:return (h>=90)&(h<=124)&(s>85)&(v>95)
    if car==5:return (h>=21)&(h<=32)&(s>85)&(v>95)
    if car==6:return (h>=39)&(h<78)&(s>85)&(v>105)
    if car==7:return (h>=7)&(h<16)&(s>95)&(v>110)
    raise ABStabilityError("UNSUPPORTED_FROZEN_COLOR_FOR_TRIAGE")


def _bounds(candidate):
    need(type(candidate) is dict and set(candidate)=={
        "bbox_xywh","car_color_candidate","identification_source"} and
        candidate["identification_source"]=="COLOR_ONLY" and
        type(candidate["car_color_candidate"]) is int and
        candidate["car_color_candidate"] in SUPPORTED and
        type(candidate["bbox_xywh"]) is list and
        len(candidate["bbox_xywh"])==4,
        "TRIAGE_FROZEN_CANDIDATE_INVALID")
    x,y,w,h=candidate["bbox_xywh"]
    need(all(type(z) in (int,float) and math.isfinite(z)
             for z in (x,y,w,h)) and
         0<=x<1 and 0<=y<1 and
         0<w<=1 and 0<h<=1 and x+w<=1+1e-9 and y+h<=1+1e-9,
         "TRIAGE_FROZEN_BBOX_INVALID")
    # A regions were originally constructed in 1024x584 pixels.
    px,py,pw,ph=[round(z*dim) for z,dim in zip(
        (x,y,w,h),(SIZE[0],SIZE[1],SIZE[0],SIZE[1]))]
    need(pw>=1 and ph>=1 and
         0<=px<SIZE[0] and 0<=py<SIZE[1] and
         px+pw<=SIZE[0] and py+ph<=SIZE[1],
         "TRIAGE_ROUNDED_BBOX_INVALID")
    return px,py,pw,ph


def _post_morph_mechanism(strict_mask, bbox):
    """Investigate the 95+ raw pixel but B-no-match subgroup, not people.

    Apply the EXACT conservative B morphology and track-strip ROI. Diagnose
    whether strict-color raw pixels break into components below B's minimum
    area, have no overlapping component, or remain big but fail geometry or
    spatial assignment. Intersection uses bounding boxes as a research proxy,
    never a verified segmentation mask for a real rider.
    """
    import cv2
    import numpy as np

    x,y,w,h=bbox
    mask=np.uint8(strict_mask)*255
    mask[:ROI_Y[0],:]=0
    mask[ROI_Y[1]:,:]=0
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,kernel)
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,kernel)
    count,_,stats,_=cv2.connectedComponentsWithStats(
        mask,8,cv2.CV_32S)
    intersections=[]
    for q in range(1,count):
        a,b,c,d,area=[int(z) for z in stats[q]]
        iw=max(0,min(x+w,a+c)-max(x,a))
        ih=max(0,min(y+h,b+d)-max(y,b))
        if iw*ih>0:
            intersections.append((a,b,c,d,area))
    if not intersections:
        return "NO_POST_MORPH_COMPONENT_OVERLAPS_A"
    if all(z[4]<95 for z in intersections):
        return "POST_MORPH_EACH_OVERLAPPING_COMPONENT_BELOW_95"
    eligible=any(
        95<=area<=2500 and 6<=cw<=80 and
        6<=ch<=50 and cw/ch<=8
        for _,_,cw,ch,area in intersections)
    if not eligible:
        return "POST_MORPH_COMPONENT_GEOMETRY_REJECTED"
    return "POST_MORPH_COMPONENT_EXISTS_BUT_NO_A_B_SPATIAL_PAIR"


def diagnose_frame(bgr, frozen_a, *, expected_sha256, second):
    """Research tier counts of frozen colour proposals against stricter B.

    Important:
    - greedy spatial association ignores color, exactly matching A/B baseline;
    - no matching A box is a confirmed false positive;
    - strict HSV pixels < 95 inside A box is an explanation for absent B
      components, but not a proof that a cyclist was absent;
    - 95+ HSV pixels without match may be fragmentation, centroid drift,
      morphology, duplicate suppression or camera content, NOT proven cause.
    """
    import cv2
    import numpy as np

    need(type(second) in (int,float) and
         math.isfinite(second) and second>=0,
         "FRAME_TIMESTAMP_INVALID")
    need(type(frozen_a) is list and len(frozen_a)<=100,
         "FROZEN_A_FRAME_INVALID")
    need(isinstance(bgr,np.ndarray) and bgr.dtype==np.uint8 and
         bgr.ndim==3 and bgr.shape[2]==3,
         "ACTUAL_SOURCE_BRG_FRAME_REQUIRED")
    need(type(expected_sha256) is str and
         sha256(bgr.tobytes()).hexdigest()==expected_sha256,
         "SOURCE_FRAME_SHA_MISMATCH")
    b=conservative_blobs(bgr,expected_frame_sha256=expected_sha256)
    boxes=[_bounds(x) for x in frozen_a]
    edges=[]
    for i,(x,y,w,h) in enumerate(boxes):
        cx=x+w/2;cy=y+h/2
        for j,z in enumerate(b):
            dist=math.hypot(cx-z["center_x"],cy-z["center_y"])
            if dist<=NEAR_PX:edges.append((dist,i,j))
    edges.sort(key=lambda x:(x[0],x[1],x[2]))
    assigned_a=set();assigned_b=set()
    color_agree=color_conflict=0
    for _,i,j in edges:
        if i in assigned_a or j in assigned_b:continue
        assigned_a.add(i);assigned_b.add(j)
        if frozen_a[i]["car_color_candidate"]==b[j]["color"]:
            color_agree+=1
        else:color_conflict+=1
    resized=cv2.resize(bgr,SIZE,interpolation=cv2.INTER_LINEAR)
    hsv=cv2.cvtColor(resized,cv2.COLOR_BGR2HSV)
    h,s,v=cv2.split(hsv)
    masks={color:_mask_strict(h,s,v,color) for color in SUPPORTED}
    cause=Counter();per_color=Counter()
    post_morph=Counter()
    wide=upper=0
    for i,(x,y,w,ht) in enumerate(boxes):
        if i in assigned_a:continue
        car=frozen_a[i]["car_color_candidate"]
        per_color[car]+=1
        # The ROI contains advertisements/track surface as well as riders:
        # shape+location are RESEARCH RISK FLAGS, not exclusion or labels.
        wide+=int(w>3*ht)
        upper+=int(y<240)
        strict=int(np.count_nonzero(masks[car][y:y+ht,x:x+w]))
        if strict==0:
            cause["ABSENT_STRICT_HSV_PIXEL_IN_FROZEN_A_BOX"]+=1
        elif strict<95:
            cause["STRICT_PIXEL_COUNT_BELOW_95_COMPONENT_MIN"]+=1
        else:
            cause["STRICT_PIXELS_95_PLUS_BUT_NO_SPATIAL_PAIR"]+=1
            post_morph[_post_morph_mechanism(
                masks[car],(x,y,w,ht))]+=1
    need(sum(post_morph.values())==
         cause["STRICT_PIXELS_95_PLUS_BUT_NO_SPATIAL_PAIR"],
         "POST_MORPH_TRIAGE_SUBTOTAL_CHANGED")
    need(sum(cause.values())==len(frozen_a)-len(assigned_a),
         "TRIAGE_COUNTS_INCONSISTENT")
    return {
        "schema":SCHEMA,
        "source_frame_sha256":expected_sha256,
        "second":second,
        "A_frozen_color_regions":len(frozen_a),
        "B_stricter_color_regions":len(b),
        "spatially_paired_regions":len(assigned_a),
        "same_color_pairs":color_agree,
        "spatial_pairs_different_color":color_conflict,
        "A_regions_no_spatial_partner":len(frozen_a)-len(assigned_a),
        "B_regions_no_spatial_partner":len(b)-len(assigned_b),
        "A_only_strict_pixel_categories":{
            key:int(cause[key]) for key in (
                "ABSENT_STRICT_HSV_PIXEL_IN_FROZEN_A_BOX",
                "STRICT_PIXEL_COUNT_BELOW_95_COMPONENT_MIN",
                "STRICT_PIXELS_95_PLUS_BUT_NO_SPATIAL_PAIR")
        },
        "A_only_raw95_plus_post_morph_causes":dict(sorted(post_morph.items())),
        "A_only_by_color":{str(c):int(per_color[c]) for c in SUPPORTED},
        "A_only_wider_than_3x_height":wide,
        "A_only_y_below_top_240_pixels":upper,
        "actual_rider_position_or_number_confirmed":False,
        "training_or_phase_scoring_eligible":False,
        "raw_image_or_bbox_exported":False,
    }


def summarize_diagnosis(rows, *, race_id, expected_frame_count,
                        expected_A_count, expected_B_count,
                        expected_spatial_count, expected_color_count):
    """Require the exact baseline totals before publishing any research counts."""
    need(type(rows) is list and
         len(rows)==expected_frame_count and
         1<=len(rows)<=600 and
         all(type(r) is dict and r.get("schema")==SCHEMA
             for r in rows),
         "EXACT_SAVED_RESEARCH_FRAME_SET_REQUIRED")
    need(len({r["source_frame_sha256"] for r in rows})==len(rows) and
         all(rows[i]["second"]<rows[i+1]["second"]
             for i in range(len(rows)-1)),
         "DUPLICATE_OR_REORDERED_RESEARCH_FRAMES")
    total=lambda k:sum(r[k] for r in rows)
    need((total("A_frozen_color_regions"),
          total("B_stricter_color_regions"),
          total("spatially_paired_regions"),
          total("same_color_pairs"))==
         (expected_A_count,expected_B_count,
          expected_spatial_count,expected_color_count),
         "A_B_FROZEN_BASELINE_DRIFT_REJECTED")
    causes=Counter()
    post_morph_causes=Counter()
    cars=Counter()
    for row in rows:
        causes.update(row["A_only_strict_pixel_categories"])
        post_morph_causes.update(
            row.get("A_only_raw95_plus_post_morph_causes",{}))
        cars.update(row["A_only_by_color"])
    need(sum(post_morph_causes.values())==
         causes["STRICT_PIXELS_95_PLUS_BUT_NO_SPATIAL_PAIR"],
         "POST_MORPH_TRIAGE_SUBTOTAL_CHANGED")
    return {
        "schema":"RACE_AI_KEIRIN_COLOR_FAILURE_TRIAGE_AGGREGATE_V1",
        "race_id":race_id,
        "original_source_frame_count":len(rows),
        "immutable_A_color_regions":total("A_frozen_color_regions"),
        "B_stricter_color_regions":total("B_stricter_color_regions"),
        "spatially_paired_regions":total("spatially_paired_regions"),
        "same_color_pairs":total("same_color_pairs"),
        "spatial_pairs_with_color_conflict":
            total("spatial_pairs_different_color"),
        "A_only_without_spatial_pair":
            total("A_regions_no_spatial_partner"),
        "B_only_without_spatial_pair":
            total("B_regions_no_spatial_partner"),
        "A_only_strict_pixel_categories":dict(sorted(causes.items())),
        "A_only_raw95_plus_post_morph_causes":
            dict(sorted(post_morph_causes.items())),
        "A_only_by_color":dict(sorted(cars.items())),
        "A_only_wider_than_3x_height":total("A_only_wider_than_3x_height"),
        "A_only_y_below_top_240_pixels":total(
            "A_only_y_below_top_240_pixels"),
        "research_priority_seconds":[x["second"] for x in sorted(
            rows,key=lambda x:(-x["A_regions_no_spatial_partner"],
                               x["second"]))[:5]],
        "actual_rider_detection_recall_pct":None,
        "actual_number_OCR_accuracy_pct":None,
        "real_rider_identity_accuracy_pct":None,
        "multi_frame_track_accuracy_pct":None,
        "motion_residuals_not_used_as_identity_proof":True,
        "actual_stage_or_line_accuracy_pct":None,
        "confirmed_independent_human_labels":0,
        "model_learning_or_formal_PDCA_updated":False,
        "public_frame_pixels_or_candidate_coordinates":False,
    }
