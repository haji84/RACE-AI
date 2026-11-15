"""Source-bound automatic jersey-color region proposals and untrusted short tracks.

Reuses the EXISTING frozen HSV palette from keirin_historical_rider_color_eval.
No manually supplied torso centers are consulted by the detector. These are
only color/blob PROPOSALS, not independently verified riders, OCR digits,
race positions, tactical labels or an extra forecasting engine.

All frame pixels, candidate boxes and tracks must remain in the owner-private
video runtime; only count-only redacted evaluation may reach public GitHub.
"""
from __future__ import annotations

from hashlib import sha256
import math
import re

from .keirin_historical_rider_color_eval import (
    UNKNOWN, HistoricalColorError, color_evidence,
)

SCHEMA="RACE_AI_KEIRIN_AUTOMATIC_JERSEY_COLOR_PROPOSALS_V1"
TRACK_SCHEMA="RACE_AI_KEIRIN_UNTRUSTED_COLOR_BLOB_TRACKS_V1"
SHA=re.compile(r"^[0-9a-f]{64}$")
# This is a fixed, deliberately narrow broadcast strip for the initial
# 1024x584 replay viewport, not a general-purpose cycling detector.
SIZE=(1024,584)
ROI_Y=(212,365)
MIN_AREA=95
MAX_AREA=2500
SUPPORTED_COLORS=frozenset((3,4,5,6,7))
# White/black overlap road markings, dark asphalt and shadow; pink/purple
# have no independent real-footage calibration in this research pilot.
EXCLUDED_UNCALIBRATED_COLORS=frozenset((1,2,8,9))
PAIRING_RADIUS_PX=40


class JerseyProposalError(ValueError):
    pass


def require(ok,code):
    if not ok:
        raise JerseyProposalError(code)


def _roster(roster):
    require(type(roster) in (list,tuple) and 3<=len(roster)<=9 and
            len(set(roster))==len(roster) and
            all(type(n) is int and 1<=n<=9 for n in roster),
            "PRIVATE_RACE_STARTERS_REQUIRED")
    return roster


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def detect_color_regions(bgr_crop, *, roster, source_crop_sha256=None):
    """Find candidate jersey-color connected components, no supplied boxes.

    The input must be the exact BGR crop extracted by the existing PR102
    recorder, before any resize. Its optional source SHA is verified BEFORE
    pixels are analyzed. No network, OCR, ML model or label file is accessed.
    """
    import cv2
    import numpy as np
    _roster(roster)
    require(isinstance(bgr_crop,np.ndarray) and bgr_crop.dtype==np.uint8 and
            bgr_crop.ndim==3 and bgr_crop.shape[2]==3 and
            bgr_crop.shape[0]>=100 and bgr_crop.shape[1]>=150,
            "REAL_BGR_SOURCE_CROP_REQUIRED")
    if source_crop_sha256 is not None:
        require(_sha(source_crop_sha256) and
                sha256(bgr_crop.tobytes()).hexdigest()==source_crop_sha256,
                "EXISTING_FRAME_SHA_MISMATCH")
    frame=cv2.resize(bgr_crop,SIZE,interpolation=cv2.INTER_LINEAR)
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    h,s,v=cv2.split(hsv)
    # The thresholds mirror the existing single-review color pilot;
    # changing them requires a separate evaluation split.
    masks={
        3:((h>=169)|(h<=4))&(s>65)&(v>78),
        4:(h>=88)&(h<=128)&(s>60)&(v>72),
        5:(h>=19)&(h<35)&(s>58)&(v>77),
        6:(h>=35)&(h<85)&(s>58)&(v>85),
        7:(h>=5)&(h<19)&(s>70)&(v>95),
    }
    # Guard palette drift without using independent truth labels.
    for number, pixel in ((3,(175,120,200)),(4,(105,120,200)),
                          (5,(25,120,200)),(6,(55,120,200)),
                          (7,(10,130,200))):
        require(color_evidence(*pixel)[number],
                "EXISTING_COLOR_PALETTE_CHANGED")
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
    candidates=[]
    for number in sorted(set(roster)&SUPPORTED_COLORS):
        mask=np.uint8(masks[number])*255
        mask[:ROI_Y[0],:]=0
        mask[ROI_Y[1]:,:]=0
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,kernel)
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,kernel)
        components,_,stats,centroids=cv2.connectedComponentsWithStats(
            mask,8,cv2.CV_32S)
        for index in range(1,components):
            x,y,w,ht,area=map(int,stats[index])
            if not (MIN_AREA<=area<=MAX_AREA and
                    6<=w<=80 and 6<=ht<=50 and w/ht<=8):
                continue
            cx,cy=map(float,centroids[index])
            candidates.append({
                "car_color_candidate":number,
                "center_x_1024":round(cx,3),
                "center_y_584":round(cy,3),
                "bbox_xywh_1024x584":[x,y,w,ht],
                "component_area_px":area,
                "rider_number_confirmed":False,
                "is_OCR_result":False,
                "rider_bounding_box_confirmed":False,
                "race_position_confirmed":False,
                "trust_tier":"UNTRUSTED_COLOR_BLOB_ONLY",
            })
    candidates.sort(key=lambda x:(
        -x["component_area_px"],x["car_color_candidate"],
        x["center_y_584"],x["center_x_1024"]))
    # A jersey may split into multiple same-color connected components.
    # Collapse duplicates by image center only, NOT by known/manual rider IDs.
    selected=[]
    for item in candidates:
        if not any(item["car_color_candidate"]==prior["car_color_candidate"]
            and (item["center_x_1024"]-prior["center_x_1024"])**2+
                (item["center_y_584"]-prior["center_y_584"])**2<28**2
                for prior in selected):
            selected.append(item)
    return {
        "schema":SCHEMA,
        "source_crop_sha256":source_crop_sha256,
        "input_crop_height":int(bgr_crop.shape[0]),
        "input_crop_width":int(bgr_crop.shape[1]),
        "roi_normalized_y":[round(ROI_Y[0]/SIZE[1],4),
                            round(ROI_Y[1]/SIZE[1],4)],
        "roster_count":len(roster),
        "uncalibrated_starters_excluded":sorted(
            set(roster)&EXCLUDED_UNCALIBRATED_COLORS),
        "proposals":selected,
        "manually_supplied_centers_used_for_detection":False,
        "untrusted_not_formal_rider_identity":True,
        "false_positives_not_independently_adjudicated":True,
        "video_phase_or_race_order_inferred":False,
    }


def match_single_review_after_detection(proposals,manual_centers,*,
                                        max_distance=PAIRING_RADIUS_PX):
    """Score nearest spatial matches AFTER detector completes.

    The manually assigned car number never influences detection, candidate
    filtering, or the one-to-one pairing. These labels have SINGLE REVIEW,
    so the return value is an exploratory reference agreement, not blind,
    independently authenticated rider recall/precision.
    """
    require(type(proposals) is list and len(proposals)<=200 and
            type(manual_centers) is list and len(manual_centers)<=30 and
            type(max_distance) in (int,float) and
            math.isfinite(max_distance) and 4<=max_distance<=80,
            "PRIVATE_LOCALIZATION_COMPARISON_INVALID")
    edges=[]
    for a,truth in enumerate(manual_centers):
        require(type(truth) is dict and
                type(truth.get("car_number")) is int and
                1<=truth["car_number"]<=9 and
                type(truth.get("center_x_1024")) is int and
                type(truth.get("center_y_584")) is int,
                "SINGLE_REVIEW_COORDINATES_INVALID")
        for b,p in enumerate(proposals):
            require(type(p) is dict and
                    type(p.get("car_color_candidate")) is int and
                    type(p.get("center_x_1024")) in (float,int) and
                    type(p.get("center_y_584")) in (float,int),
                    "UNTRUSTED_COLOR_PROPOSAL_INVALID")
            dist=math.hypot(
                p["center_x_1024"]-truth["center_x_1024"],
                p["center_y_584"]-truth["center_y_584"])
            if dist<=max_distance:
                edges.append((dist,a,b))
    edges.sort(key=lambda item:(item[0],item[1],item[2]))
    used_review=set()
    used_proposal=set()
    matches=[]
    for dist,a,b in edges:
        if a in used_review or b in used_proposal:
            continue
        used_review.add(a)
        used_proposal.add(b)
        matches.append({
            "private_manual_index":a,
            "private_proposal_index":b,
            "distance_px":round(dist,3),
            "single_review_car_color_agrees":(
                proposals[b]["car_color_candidate"]==
                manual_centers[a]["car_number"]),
        })
    matched=len(matches)
    correct=sum(m["single_review_car_color_agrees"] for m in matches)
    total=len(manual_centers)
    return {
        "manual_single_review_count":total,
        "automatic_color_proposal_count":len(proposals),
        "single_review_spatial_matches":matched,
        "single_review_spatially_matched_color_agreements":correct,
        "single_review_unmatched_truths":total-matched,
        "single_review_unmatched_proposals":len(proposals)-matched,
        "single_review_position_candidate_coverage_pct":(
            round(matched*100/total,3) if total else None),
        "single_review_joint_position_and_color_coverage_pct":(
            round(correct*100/total,3) if total else None),
        "color_agreement_given_spatial_match_pct":(
            round(correct*100/matched,3) if matched else None),
        "independent_detection_recall_pct":None,
        "independent_identity_accuracy_pct":None,
        "matching_pairs_private_not_for_public_export":matches,
        "unreviewed_objects_cannot_be_called_false_positives":True,
    }


def link_untrusted_color_blobs(frames,*,max_gap_s=4,max_jump_px=85):
    """Associate candidates across source-bound consecutive frames.

    Detecting a similar color blob twice is a candidate track, not proof of
    rider identity. No video stage, leading rank or line is ever inferred.
    """
    require(type(frames) is list and len(frames)<=300 and
            type(max_gap_s) in (int,float) and 0<max_gap_s<=10 and
            type(max_jump_px) in (int,float) and 10<=max_jump_px<=250,
            "UNTRUSTED_TRACK_INPUT_INVALID")
    tracks=[]
    last_time=-1.0
    seen_sha=set()
    for frame in frames:
        require(type(frame) is dict and set(frame)=={
            "sample_sec","source_crop_sha256","proposals"},
            "TRACK_FRAME_SCHEMA_INVALID")
        sec=frame["sample_sec"]
        sid=frame["source_crop_sha256"]
        require(type(sec) in (float,int) and math.isfinite(sec) and
                last_time<sec and _sha(sid) and sid not in seen_sha and
                type(frame["proposals"]) is list and
                len(frame["proposals"])<=150,
                "TRACK_FRAME_SHA_TIME_OR_COUNT_INVALID")
        seen_sha.add(sid)
        last_time=sec
        # Nearest matching among same color without reusing a track.
        candidates=[]
        for i,p in enumerate(frame["proposals"]):
            require(type(p) is dict and p.get("trust_tier")==
                    "UNTRUSTED_COLOR_BLOB_ONLY" and
                    p.get("car_color_candidate") in SUPPORTED_COLORS and
                    type(p.get("center_x_1024")) in (int,float) and
                    type(p.get("center_y_584")) in (int,float),
                    "FORGED_TRUSTED_TRACK_PROPOSAL")
            for ti,t in enumerate(tracks):
                delta=sec-t["last_s"]
                if (p["car_color_candidate"]!=t["color"] or
                    not 0<delta<=max_gap_s):continue
                dist=math.hypot(p["center_x_1024"]-t["last_x"],
                                p["center_y_584"]-t["last_y"])
                if dist<=max_jump_px:
                    candidates.append((dist,ti,i))
        candidates.sort()
        used_t=set();used_p=set()
        for _,ti,i in candidates:
            if ti in used_t or i in used_p:
                continue
            used_t.add(ti);used_p.add(i)
            p=frame["proposals"][i]
            track=tracks[ti]
            track["observed_frame_count"]+=1
            track["last_s"]=sec
            track["last_x"]=p["center_x_1024"]
            track["last_y"]=p["center_y_584"]
        for i,p in enumerate(frame["proposals"]):
            if i not in used_p:
                tracks.append({
                    "color":p["car_color_candidate"],
                    "observed_frame_count":1,
                    "first_s":sec,
                    "last_s":sec,
                    "last_x":p["center_x_1024"],
                    "last_y":p["center_y_584"],
                })
    return {
        "schema":TRACK_SCHEMA,
        "source_frame_count":len(frames),
        "untrusted_track_candidates_total":len(tracks),
        "track_candidates_seen_in_at_least_two_frames":
            sum(t["observed_frame_count"]>=2 for t in tracks),
        "color_blob_track_details_private_only":tracks,
        "actual_rider_identity_confirmed":False,
        "track_order_and_line_position_confirmed":False,
        "phase_scoring_admitted":False,
        "model_weights_changed":False,
    }
