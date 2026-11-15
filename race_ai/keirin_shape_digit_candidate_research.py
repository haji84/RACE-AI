"""Research-only evidence join: frozen color blobs + weak wheel shape + OCR.

Not a real person detector. Numeric OCR observes the same tiny, untrusted
source crop in two preprocessings, NOT independent human or frame truth.
No model training, bookmaker requests, rank, line, official PDCA, or real ID.
"""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import math
import re

from .keirin_bicycle_shape_context import analyze_frame, _frozen_bounds

SCHEMA='RACE_AI_KEIRIN_SHAPE_DIGIT_CANDIDATE_RESEARCH_V1'
SHA=re.compile(r'^[0-9a-f]{64}$')
UNKNOWN='UNKNOWN'
MIN_RAW_BBOX_HEIGHT=8
MIN_OCR_CONF=60.0

class ShapeDigitResearchError(ValueError):
    pass


def check(ok,reason):
    if not ok:raise ShapeDigitResearchError(reason)


def _ocr_output(raw):
    check(type(raw) is dict and set(raw)=={'digit','confidence'},
          'UNTRUSTED_OCR_CALLBACK_SCHEMA')
    digit=raw['digit'];confidence=raw['confidence']
    check(digit==UNKNOWN or (type(digit) is int and 1<=digit<=9),
          'INVALID_OCR_DIGIT')
    if digit==UNKNOWN:
        check(confidence is None,'UNKNOWN_OCR_CONFIDENCE_MUST_BE_NULL')
    else:
        check(type(confidence) in (float,int) and
              math.isfinite(confidence) and 0<=confidence<=100,
              'OCR_CONFIDENCE_INVALID')
    return digit,confidence


def _box_patch(bgr,candidate):
    import cv2
    x,y,w,h=_frozen_bounds(candidate)
    H,W=bgr.shape[:2]
    # _frozen_bounds uses reference coordinate 1024x584; pixel crop input
    # remains the ORIGINAL 515x292 BGR array, never the public screenshot.
    ratio_x=W/1024;ratio_y=H/584
    sx,sy,sw,sh=x*ratio_x,y*ratio_y,w*ratio_x,h*ratio_y
    if sh<MIN_RAW_BBOX_HEIGHT:
        return None
    x0=max(0,int(sx-sw))
    x1=min(W,int(math.ceil(sx+sw*2)))
    y0=max(0,int(sy-sh))
    y1=min(H,int(math.ceil(sy+sh*3)))
    if x1<=x0 or y1<=y0:return None
    crop=bgr[y0:y1,x0:x1]
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    gray=cv2.resize(gray,None,fx=5,fy=5,
                    interpolation=cv2.INTER_CUBIC)
    # Two preprocessing views of SAME pixel evidence. This is NOT
    # statistically independent recognition or proof of correct digits.
    threshold=cv2.threshold(gray,0,255,
            cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]
    return (gray,threshold)


def analyze_shape_digit_frame(bgr, frozen_a, *, expected_sha256,
                              second,ocr_reader):
    """Research join with exact source-frame SHA and immutable A proposals.

    ocr_reader(processed_grayscale) -> {'digit': int 1..9 or UNKNOWN,
                                       'confidence': 0..100 or None}
    Downstream MUST NOT treat a shared OCR glyph and jersey color as an
    independently confirmed rider. OCR has no authority to assign a rank.
    """
    import numpy as np
    check(isinstance(bgr,np.ndarray) and bgr.dtype==np.uint8 and
          bgr.ndim==3 and bgr.shape[2]==3 and
          type(expected_sha256) is str and SHA.fullmatch(expected_sha256) and
          sha256(bgr.tobytes()).hexdigest()==expected_sha256,
          'SOURCE_FRAME_BGR_SHA_REQUIRED')
    check(callable(ocr_reader) and type(frozen_a) is list and
          len(frozen_a)<=100 and type(second) in (int,float) and
          math.isfinite(second) and second>=0,
          'SOURCE_RESEARCH_OCR_INPUT_INVALID')
    shape=analyze_frame(bgr,frozen_a,expected_sha256=expected_sha256,
                        second=second)
    evidence=shape['private_candidate_hypotheses_not_ground_truth']
    check(len(evidence)==len(frozen_a),
          'FROZEN_A_CANDIDATE_SHAPE_COUNT_CHANGED')
    counters=Counter();counters['A_TOTAL']=len(frozen_a)
    for candidate,geom in zip(frozen_a,evidence):
        p=_box_patch(bgr,candidate)
        if p is None:
            counters['TOO_SMALL_FOR_EXPLORATORY_OCR']+=1
            digit=UNKNOWN
        else:
            counters['OCR_GEOMETRY_ELIGIBLE']+=1
            guesses=[]
            for variant in p:
                try:
                    guess,confidence=_ocr_output(ocr_reader(variant))
                except Exception:
                    # A malformed backend result is a HOLD, not an
                    # opportunity to invent a car number from uniform color.
                    counters['OCR_BACKEND_REJECTED']+=1
                    guess,confidence=UNKNOWN,None
                guesses.append(guess if confidence is not None and
                               confidence>=MIN_OCR_CONF else UNKNOWN)
            if (len(guesses)==2 and guesses[0]!=UNKNOWN and
                guesses[0]==guesses[1]):
                digit=guesses[0]
                counters['TWO_PREPROCESSINGS_SAME_DIGIT_UNTRUSTED']+=1
            else:
                digit=UNKNOWN
                counters['OCR_NO_AGREED_GLYPH']+=1
        wheel=geom['research_possible_wheel_pair_context']
        color=geom['research_color_pair_state']
        if wheel:
            counters['WEAK_WHEEL_SHAPE_CUE']+=1
        else:
            counters['NO_WHEEL_SHAPE_CUE_NOT_REJECTED']+=1
        if color=='A_B_SPATIAL_AND_COLOR_AGREEMENT':
            counters['A_B_COLOR_AGREEMENT']+=1
        if digit==UNKNOWN:
            counters['NO_VERIFIED_DIGIT']+=1
        elif digit==candidate['car_color_candidate']:
            counters['UNTRUSTED_DIGIT_AND_COLOR_CONSISTENT']+=1
            if wheel:
                counters['UNTRUSTED_THREE_SIGNAL_AGREEMENT']+=1
        else:
            counters['UNTRUSTED_DIGIT_AND_COLOR_CONFLICT_HOLD']+=1
    check(counters['TOO_SMALL_FOR_EXPLORATORY_OCR']+
          counters['OCR_GEOMETRY_ELIGIBLE']==len(frozen_a),
          'OCR_COVERAGE_DENOMINATOR_MISMATCH')
    check(counters['NO_VERIFIED_DIGIT']+
          counters['UNTRUSTED_DIGIT_AND_COLOR_CONSISTENT']+
          counters['UNTRUSTED_DIGIT_AND_COLOR_CONFLICT_HOLD']==len(frozen_a),
          'OCR_UNTRUSTED_NUMBER_ACCOUNTING_MISMATCH')
    return {
       'schema':SCHEMA,'second':second,'source_frame_sha256':expected_sha256,
       'counts':dict(sorted(counters.items())),
       'frozen_A_candidate_count':len(frozen_a),
       'pixel_data_or_candidate_boxes_in_public_result':False,
       'actual_person_detected_or_identified':False,
       'true_car_number_OCR_accuracy_pct':None,
       'true_same_rider_track_accuracy_pct':None,
       'official_phase_scoring_or_training_authorized':False,
    }


def summarize_shape_digit(rows, *, race_id, expected_frame_count,
                          expected_A_candidates):
    check(type(rows) is list and
          len(rows)==expected_frame_count and
          1<=len(rows)<=600 and
          all(type(x) is dict and x.get('schema')==SCHEMA for x in rows) and
          len({x['source_frame_sha256'] for x in rows})==len(rows) and
          all(rows[i]['second']<rows[i+1]['second'] for i in range(len(rows)-1)),
          'SOURCE_BOUND_UNIQUE_FRAME_SEQUENCE_REQUIRED')
    tallies=Counter()
    for row in rows:tallies.update(row['counts'])
    check(tallies['A_TOTAL']==expected_A_candidates,
          'FROZEN_A_CANDIDATES_CHANGED')
    return {
      'schema':'RACE_AI_KEIRIN_SHAPE_DIGIT_RESEARCH_SUMMARY_V1',
      'race_id':race_id,'source_sha_verified_frames':len(rows),
      'original_A_color_blobs':tallies['A_TOTAL'],
      'shape_and_OCR_research_counts':dict(sorted(tallies.items())),
      'true_rider_detection_precision_pct':None,
      'true_rider_detection_recall_pct':None,
      'actual_bib_digit_accuracy_pct':None,
      'same_rider_continuity_accuracy_pct':None,
      'actual_six_phase_accuracy_pct':None,
      'independent_human_labels':0,
      'original_frozen_A_unchanged':True,
      'real_traffic_or_model_results_modified':False,
      'eligible_for_PDCA_or_training':False,
      'no_source_pixels_or_private_region_details_exported':True,
    }
