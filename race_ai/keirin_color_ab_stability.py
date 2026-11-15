"""A/B sensitivity check on existing frozen KEIRIN color regions, NOT true labels.

A = immutable existing HSV frozen blob proposals (PR #291).
B = a narrower HSV range and stronger saturation/brightness requirement on
EXACT SAME actual BGR frames. B is not an independent reviewer, not OCR and
not a new forecast model. Measurements are region/color AGREEMENT ONLY.

Never submit A/B agreement to the independently verified reviewer gate.
No precision, recall, rider identity, rank, six-phase accuracy or training
may be inferred from these values.
"""
from __future__ import annotations

from hashlib import sha256
import math

SUPPORTED = (3,4,5,6,7)
UNKNOWN = "UNKNOWN"
SIZE = (1024,584)
ROI_Y = (212,365)
NEAR_PX = 40

class ABStabilityError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise ABStabilityError(reason)


def conservative_blobs(bgr_crop, *, expected_frame_sha256):
    """Secondary deliberately stricter color-blob search (no rider labels).

    Requires source-bound original BGR crop; does not consult the stored A
    boxes while producing B. White/black and 8/9 intentionally abstain.
    """
    import cv2
    import numpy as np

    need(isinstance(bgr_crop,np.ndarray) and
         bgr_crop.dtype==np.uint8 and bgr_crop.ndim==3 and
         bgr_crop.shape[2]==3 and
         bgr_crop.shape[0]>=100 and bgr_crop.shape[1]>=150,
         "REAL_BGR_FRAME_REQUIRED")
    need(type(expected_frame_sha256) is str and
         len(expected_frame_sha256)==64 and
         sha256(bgr_crop.tobytes()).hexdigest()==expected_frame_sha256,
         "A_B_REAL_SOURCE_FRAME_SHA_MISMATCH")
    pixels=cv2.resize(bgr_crop,SIZE,interpolation=cv2.INTER_LINEAR)
    h,s,v=cv2.split(cv2.cvtColor(pixels,cv2.COLOR_BGR2HSV))
    masks={
        3:((h>=171)|(h<=3))&(s>90)&(v>100),
        4:(h>=90)&(h<=124)&(s>85)&(v>95),
        5:(h>=21)&(h<=32)&(s>85)&(v>95),
        6:(h>=39)&(h<78)&(s>85)&(v>105),
        7:(h>=7)&(h<16)&(s>95)&(v>110),
    }
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
    proposals=[]
    for n,boolean in masks.items():
        mask=boolean.astype("uint8")*255
        mask[:ROI_Y[0],:]=0
        mask[ROI_Y[1]:,:]=0
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,kernel)
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,kernel)
        count,_,stats,centroids=cv2.connectedComponentsWithStats(
            mask,8,cv2.CV_32S)
        for i in range(1,count):
            x,y,w,ht,area=map(int,stats[i])
            if not (95<=area<=2500 and 6<=w<=80 and
                    6<=ht<=50 and w/ht<=8):
                continue
            cx,cy=map(float,centroids[i])
            proposals.append({
                "color":n,
                "center_x":cx,"center_y":cy,
                "box_xywh":[x/1024,y/584,w/1024,ht/584],
                "area":area,
            })
    proposals.sort(key=lambda q:(
        -q["area"],q["color"],q["center_y"],q["center_x"]))
    selected=[]
    for p in proposals:
        if not any(q["color"]==p["color"] and
                   (q["center_x"]-p["center_x"])**2+
                   (q["center_y"]-p["center_y"])**2<28**2
                   for q in selected):
            selected.append(p)
    return selected


def compare_a_b_regions(frozen_a,b_regions,*,distance_px=NEAR_PX):
    """One-to-one region stability; not a comparison against correct riders.

    Spatial pairing does NOT use car color. The color agreement count is
    calculated AFTER spatial pairs are chosen, to expose disagreement.
    """
    need(type(frozen_a) is list and len(frozen_a)<=100 and
         type(b_regions) is list and len(b_regions)<=100 and
         type(distance_px) in (int,float) and
         1<=distance_px<=100 and math.isfinite(distance_px),
         "A_B_REGIONS_INVALID")
    edges=[]
    for i,a in enumerate(frozen_a):
        need(type(a) is dict and
             set(a)=={"bbox_xywh","car_color_candidate",
                      "identification_source"} and
             a["identification_source"]=="COLOR_ONLY" and
             type(a["car_color_candidate"]) is int and
             1<=a["car_color_candidate"]<=9,
             "FROZEN_A_COLOR_BLOB_SCHEMA_INVALID")
        bounds=a["bbox_xywh"]
        need(type(bounds) is list and len(bounds)==4 and
             all(type(v) in (int,float) and math.isfinite(v) for v in bounds) and
             all(0<=v<=1 for v in bounds) and
             bounds[0]+bounds[2]<=1 and
             bounds[1]+bounds[3]<=1,
             "FROZEN_A_BOX_UNTRUSTED")
        acx=(bounds[0]+bounds[2]/2)*SIZE[0]
        acy=(bounds[1]+bounds[3]/2)*SIZE[1]
        for j,b in enumerate(b_regions):
            need(type(b) is dict and
                 b.get("color") in SUPPORTED and
                 type(b.get("center_x")) in (int,float) and
                 type(b.get("center_y")) in (int,float) and
                 math.isfinite(b["center_x"]) and
                 math.isfinite(b["center_y"]),
                 "CONSERVATIVE_B_COLOR_BLOB_SCHEMA_INVALID")
            dist=math.hypot(acx-b["center_x"],acy-b["center_y"])
            if dist<=distance_px:
                edges.append((dist,i,j))
    edges.sort(key=lambda e:(e[0],e[1],e[2]))
    a_ids=set();b_ids=set();spatial=same=0
    for dist,i,j in edges:
        if i in a_ids or j in b_ids:
            continue
        a_ids.add(i);b_ids.add(j);spatial+=1
        same+=frozen_a[i]["car_color_candidate"]==b_regions[j]["color"]
    return {
        "a_frozen_blob_count":len(frozen_a),
        "b_stricter_blob_count":len(b_regions),
        "a_b_spatially_paired_color_blobs":spatial,
        "a_b_spatial_and_color_consistent_blobs":same,
        "a_b_disagreed_color_within_spatial_pairs":spatial-same,
        "not_confirmed_riders":True,
    }


def summarize_a_b(results,*,race_id,frozen_sha,exact_frame_sha_count):
    need(type(results) is list and 1<=len(results)<=600 and
         type(exact_frame_sha_count) is int and
         exact_frame_sha_count==len(results),
         "A_B_EXACT_SOURCE_FRAMES_REQUIRED")
    keys=("a_frozen_blob_count","b_stricter_blob_count",
          "a_b_spatially_paired_color_blobs",
          "a_b_spatial_and_color_consistent_blobs")
    need(all(type(r) is dict and all(type(r.get(k)) is int and r[k]>=0
                                  for k in keys) for r in results),
         "A_B_COUNTS_INVALID")
    sums={k:sum(r[k] for r in results) for k in keys}
    a=sums["a_frozen_blob_count"]
    b=sums["b_stricter_blob_count"]
    both=sums["a_b_spatial_and_color_consistent_blobs"]
    need(both<=sums["a_b_spatially_paired_color_blobs"]<=min(a,b),
         "A_B_MATCH_COUNT_IMPOSSIBLE")
    return {
        "schema":"RACE_AI_KEIRIN_A_B_COLOR_STABILITY_RESEARCH_V1",
        "race_id":race_id,
        "frozen_A_proposal_sha256":frozen_sha,
        "exact_sha_matched_source_frames":exact_frame_sha_count,
        **sums,
        "A_blob_color_confirmation_by_B_pct":round(100*both/a,3) if a else None,
        "B_blob_color_confirmation_by_A_pct":round(100*both/b,3) if b else None,
        "definition":"TWO_HSV_PARAMETERIZATIONS_SAME_SOURCE_FRAMES_NOT_GROUND_TRUTH",
        "independent_person_ground_truth_reviewers":0,
        "independent_person_detection_precision_pct":None,
        "independent_person_detection_recall_pct":None,
        "actual_rider_car_number_accuracy_pct":None,
        "actual_rider_tracking_accuracy_pct":None,
        "six_phase_accuracy_pct":None,
        "production_PDCA_or_model_training_authorized":False,
        "source_pixels_or_private_annotated_boxes_in_public_result":False,
    }
