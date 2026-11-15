"""Private historical jersey-color candidate experiment, NOT rider OCR.

Use the existing decoded PR102 recording and an independently located
rider-upper-torso crop. Classify only the jersey's color evidence. No racer
detection, no official rider-ID truth, no track position, no line inference,
no six-stage AI proof, no feature leakage into existing PR71 forecasts.

This is a baseline for comparing against separately reviewed held-out frames,
not a model trained on the evaluated race or a calibrated probability.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re

SCHEMA = "RACE_AI_KEIRIN_HISTORICAL_COLOR_PATCH_CANDIDATE_V1"
REPORT_SCHEMA = "RACE_AI_KEIRIN_HISTORICAL_RESEARCH_VISUAL_SCORE_V1"
UNKNOWN = "UNKNOWN"
SHA = re.compile(r"^[a-f0-9]{64}$")
# Frozen BEFORE evaluating the separate 18 held-out rider crops. HSV ranges
# use OpenCV 0-179 hue scale. The evidence fraction is NOT a probability.
MIN_EVIDENCE_FRACTION = 0.35
MIN_TOP_MARGIN = 0.05


class HistoricalColorError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise HistoricalColorError(reason)


def valid_sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def canonical(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"),allow_nan=False)


def sha_json(obj):
    return sha256(canonical(obj).encode("utf-8")).hexdigest()


def color_evidence(h, s, v):
    """Unsigned HSV integer, as decoded by cv2.cvtColor(BGR2HSV)."""
    return {
        1: s < 37 and v > 165,      # white
        2: s < 38 and v < 91,       # black (often occluded/track-like)
        3: (h >= 169 or h <= 4) and s > 65 and v > 78,  # red
        4: 88 <= h <= 128 and s > 60 and v > 72,       # blue
        5: 19 <= h < 35 and s > 58 and v > 77,         # yellow
        6: 35 <= h < 85 and s > 58 and v > 85,         # green
        7: 5 <= h < 19 and s > 70 and v > 95,          # orange
        8: 145 <= h < 169 and s > 65 and v > 90,       # pink: UNVALIDATED
        9: 129 <= h < 145 and s > 65 and v > 90,       # purple: UNVALIDATED
    }


def classify_hsv_patch(pixels, *, allowed_car_numbers, min_fraction=MIN_EVIDENCE_FRACTION,
                       min_margin=MIN_TOP_MARGIN):
    """Candidate classification for an ALREADY located rider crop.

    Expects an iterable of H,S,V triples (nested or flat). Its ratio is a
    color-evidence fraction. Do not present as model confidence/probability.
    """
    need(type(allowed_car_numbers) in (list,tuple,set) and
         3 <= len(allowed_car_numbers) <= 9 and
         all(type(x) is int and 1 <= x <= 9 for x in allowed_car_numbers) and
         len(set(allowed_car_numbers)) == len(allowed_car_numbers),
         "VALIDATED_RACE_STARTERS_REQUIRED")
    need(type(pixels) is list and 1 <= len(pixels) <= 4096,
         "INVALID_PIXEL_ARRAY")
    # The caller passes a flat row-major list. No player overlay is accepted
    # as independently verified rider localization by this classifier.
    sums = {n: 0 for n in allowed_car_numbers}
    for color in pixels:
        need(type(color) in (list,tuple) and len(color) == 3 and
             all(type(k) is int and 0 <= k <= (179 if i==0 else 255)
                 for i,k in enumerate(color)), "INVALID_HSV_VALUE")
        indicators = color_evidence(*color)
        for n in sums:
            sums[n] += bool(indicators[n])
    ranked = sorted(((n,s/len(pixels)) for n,s in sums.items()),
                    key=lambda x:(-x[1],x[0]))
    highest = ranked[0]
    runner_up = ranked[1][1] if len(ranked)>1 else 0.0
    accept = (highest[1] >= min_fraction and
              highest[1]-runner_up >= min_margin)
    return {
        "schema":SCHEMA,
        "candidate_car_number":highest[0] if accept else UNKNOWN,
        "color_evidence_fraction":round(highest[1],6),
        "next_best_fraction":round(runner_up,6),
        "margin_fraction":round(highest[1]-runner_up,6),
        "abstained":not accept,
        "candidate_source":"MANUALLY_LOCALIZED_JERSEY_COLOR_NOT_OCR",
        "probability_calibrated":False,
        "automatic_rider_detection":False,
        "position_or_line_verified":False,
        "official_result_used":False,
    }


def aggregate_historical_color_scores(records, *, race_ids, sample_frames_expected,
                                      complete_frame_sha_matches,
                                      single_review_ground_truth_only=True):
    """Count only externally provided crop labels, never invent missing truth.

    records contain {race_id, truth_car_number, candidate_car_number}.
    The upstream private runtime must verify exact SHA and clip/frame bytes,
    and assure no result/prediction was used to invent candidate labels.
    """
    need(type(race_ids) is list and 1<=len(race_ids)<=100 and
         all(type(r) is str and re.fullmatch(r"\d{12}",r) for r in race_ids) and
         len(set(race_ids))==len(race_ids), "RACE_IDS_REQUIRED")
    need(type(records) is list and len(records)<=30000,
         "INVALID_REVIEWED_LABEL_COUNT")
    need(type(sample_frames_expected) is int and sample_frames_expected>=0 and
         type(complete_frame_sha_matches) is int and
         0<=complete_frame_sha_matches<=sample_frames_expected,
         "FRAME_SHA_COUNT_INVALID")
    seen=set();summaries=[]
    for rid in race_ids:
        rows=[]
        for row in records:
            need(type(row) is dict and set(row)=={
                "race_id","frame_sha256","sample_second",
                "reviewed_car_number","candidate_car_number"},
                 "UNEXPECTED_REVIEW_ROW_FIELDS")
            need(row["race_id"] in race_ids and
                 valid_sha(row["frame_sha256"]) and
                 type(row["sample_second"]) is int and row["sample_second"]>=0 and
                 type(row["reviewed_car_number"]) is int and
                 1<=row["reviewed_car_number"]<=9 and
                 (row["candidate_car_number"]==UNKNOWN or
                  type(row["candidate_car_number"]) is int and
                  1<=row["candidate_car_number"]<=9),
                 "INVALID_REVIEW_ROW")
            key=(row["race_id"],row["frame_sha256"],row["reviewed_car_number"])
            need(key not in seen, "DUPLICATE_REVIEWED_CAR_FRAME")
            seen.add(key)
            if row["race_id"]==rid:
                rows.append(row)
        decided=[x for x in rows if x["candidate_car_number"]!=UNKNOWN]
        hits=sum(x["candidate_car_number"]==x["reviewed_car_number"]
                 for x in decided)
        summaries.append({
            "race_id":rid,"manually_located_car_crops":len(rows),
            "color_candidates_decided":len(decided),"matches_with_single_review":hits,
            "candidate_coverage_pct":(round(100*len(decided)/len(rows),3)
                                      if rows else None),
            "conditional_single_review_match_pct":(
                round(100*hits/len(decided),3) if decided else None),
        })
    reviews=len(records)
    decisions=sum(x["color_candidates_decided"] for x in summaries)
    matches=sum(x["matches_with_single_review"] for x in summaries)
    report={
        "schema":REPORT_SCHEMA,
        "races":summaries,
        "exact_saved_frame_sha_matches":complete_frame_sha_matches,
        "original_saved_frame_count":sample_frames_expected,
        "saved_frame_readback_coverage_pct":(
            round(100*complete_frame_sha_matches/sample_frames_expected,3)
            if sample_frames_expected else None),
        "manually_localized_jersey_crops":reviews,
        "color_car_candidates_decided":decisions,
        "color_car_candidates_matching_single_review":matches,
        "candidate_decision_coverage_pct":(
            round(100*decisions/reviews,3) if reviews else None),
        "conditional_single_review_color_match_pct":(
            round(100*matches/decisions,3) if decisions else None),
        "complete_automatic_car_detection_accuracy_pct":None,
        "independently_verified_rider_id_accuracy_pct":None,
        "position_accuracy_pct":None,
        "line_accuracy_pct":None,
        "phase_weighted_accuracy_pct":None,
        "verified_six_phase_count":0,
        "six_phase_gates_requiring_true_phase_annotations":len(race_ids)*6,
        "independently_verified_phase_coverage_pct":0.0,
        "reference_quality":("SINGLE_REVIEW_RESEARCH_NOT_SECOND_REVIEWED"
                             if single_review_ground_truth_only else
                             "OUTSIDE_ATTESTATION_REQUIRES_PROOF"),
        "eligible_for_official_accuracy_or_training":False,
        "existing_PR71_model_weights_modified":False,
        "pre_cutoff_forecast_reconstructed":False,
        "predictions_cannot_retroactively_train_on_same_race":True,
        "public_raw_video_or_reviewed_boxes_exported":False,
    }
    report["report_sha256"]=sha_json(report)
    return report
