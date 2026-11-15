"""Private offline replay of SAVED historical browser video and jersey colors.

This is a CLI for an owner-private ephemeral runner with an already authorized,
already decrypted WebM. It makes NO HTTP requests, receives NO API keys, does
not upload frame pixels or private reviewed coordinates, and never changes PR71.
It cannot recover or infer a missing rider bounding box or a phase itself.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import json
import os
import re

from race_ai.keirin_historical_rider_color_eval import (
    HistoricalColorError, aggregate_historical_color_scores,
    classify_hsv_patch, need, valid_sha, sha_json,
)

MANUAL = "RACE_AI_KEIRIN_PRIVATE_SINGLE_REVIEWED_JERSEY_CROPS_V1"


def run(*, decrypted_private_dir, saved_frame_features, manual_review):
    """A real video is mandatory. No results can be manufactured from JSON."""
    import cv2
    base=Path(decrypted_private_dir).resolve()
    need(base.is_dir() and (base.stat().st_mode & 0o077)==0,
         "DECRYPTED_MEDIA_DIRECTORY_MUST_BE_PRIVATE")
    features=json.loads(Path(saved_frame_features).read_text())
    review=json.loads(Path(manual_review).read_text())
    need(type(features) is dict and type(features.get("sources")) is list,
         "PREVIOUS_SAVED_FRAME_FEATURES_REQUIRED")
    need(type(review) is dict and review.get("schema")==MANUAL and
         review.get("review_level")=="SINGLE_VISUAL_REVIEW_NOT_INDEPENDENT" and
         type(review.get("races")) is list,
         "PRIVATE_MANUAL_REVIEW_REQUIRED")
    indexed={r["race_id"]:r for r in features["sources"]}
    need(len(indexed)==len(features["sources"]) and
         len(indexed)==len(review["races"]),"REVIEWED_RACE_SET_MISMATCH")
    rows=[];checked=0;expected=0
    for case in review["races"]:
        need(type(case) is dict and set(case)=={
            "race_id","source_sha256","starters","labels"},
            "PRIVATE_REVIEW_RACE_FIELDS")
        rid=case["race_id"]
        need(type(rid) is str and re.fullmatch(r"\d{12}",rid),
             "UNTRUSTED_RACE_PATH_REJECTED")
        need(rid in indexed and case["source_sha256"]==indexed[rid]["source_sha256"]
             and valid_sha(case["source_sha256"]),
             "SOURCE_SHA_OR_RACE_NOT_VERIFIED")
        roster=case["starters"]
        need(type(roster) is list and
             3<=len(roster)<=9 and
             all(type(x) is int and 1<=x<=9 for x in roster) and
             len(set(roster))==len(roster),
             "PRIVATE_ROSTER_INVALID")
        need(type(case["labels"]) is list and len(case["labels"])<=3000,
             "PRIVATE_LABEL_ROWS_INVALID")
        p=base/(rid+".webm")
        need(p.is_file() and not p.is_symlink(),
             "ENCRYPTED_SOURCE_NOT_AVAILABLE_AS_PRIVATE_WEBM")
        raw=p.read_bytes()
        need(sha256(raw).hexdigest()==case["source_sha256"],
             "DECRYPTED_VIDEO_BYTES_SHA_MISMATCH")
        del raw
        cap=cv2.VideoCapture(str(p))
        need(cap.isOpened(),"DECODED_WEBM_REQUIRED")
        source=indexed[rid]
        saved=source["frames"]
        need(type(saved) is list and
             source["frame_count"]==len(saved),"PRIVATE_SAVED_FRAME_LIST_INVALID")
        bysec={f["second"]:f["source_frame_sha256"] for f in saved}
        need(len(bysec)==len(saved),"DUPLICATE_SAVED_FRAME_SAMPLE")
        frame_cache={}
        try:
            for second,h in bysec.items():
                need(type(second) is int and second>=0 and valid_sha(h),
                     "SAVED_FRAME_ROW_INVALID")
                cap.set(cv2.CAP_PROP_POS_MSEC,second*1000)
                ok,full=cap.read()
                need(ok,"SAVED_FRAME_CANNOT_BE_DECODED")
                height,width=full.shape[:2]
                crop=full[int(height*.303):int(height*.709),
                          int(width*.299):int(width*.701)]
                need(crop.size>0,"SOURCE_CROP_EMPTY")
                # Exactly reproduce existing private saved frame SHA.
                need(sha256(crop.tobytes()).hexdigest()==h,
                     "SAVED_SOURCE_FRAME_SHA_MISMATCH")
                checked+=1
                if second in {r["second"] for r in case["labels"]}:
                    frame_cache[second]=crop
            expected+=len(saved)
            dedupe=set()
            for label in case["labels"]:
                need(type(label) is dict and set(label)=={
                    "second","frame_sha256","car_number",
                    "center_x_1024","center_y_584"},
                    "PRIVATE_LABEL_SCHEMA_INVALID")
                second=label["second"];car=label["car_number"]
                x,y=label["center_x_1024"],label["center_y_584"]
                need(second in bysec and
                     label["frame_sha256"]==bysec[second] and
                     type(car) is int and car in roster and
                     type(x) is int and 8<=x<=1016 and
                     type(y) is int and 8<=y<=576,
                     "MANUAL_FRAME_CROP_REFERENCE_INVALID")
                key=(second,car)
                need(key not in dedupe,"DUPLICATE_SINGLE_REVIEW_LABEL")
                dedupe.add(key)
                # Labels locate a crop. The classifier sees only pixels,
                # NOT a manually supplied car number or result.
                enlarged=cv2.resize(frame_cache[second],(1024,584))
                patch=enlarged[y-8:y+8,x-8:x+8]
                hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
                color=classify_hsv_patch(
                    hsv.reshape(-1,3).tolist(),
                    allowed_car_numbers=roster,
                )
                rows.append({
                    "race_id":rid,"frame_sha256":bysec[second],
                    "sample_second":second,
                    "reviewed_car_number":car,
                    "candidate_car_number":color["candidate_car_number"],
                })
        finally:
            cap.release()
    out=aggregate_historical_color_scores(
        rows,race_ids=sorted(indexed),
        sample_frames_expected=expected,
        complete_frame_sha_matches=checked,
        single_review_ground_truth_only=True)
    out["source_frame_features_sha256"]=sha256(
        Path(saved_frame_features).read_bytes()).hexdigest()
    out["private_manual_review_sha256"]=sha256(
        Path(manual_review).read_bytes()).hexdigest()
    out["patch_method"]="HAND_LOCATED_16X16_UPSCALED_PLAYER_CROP_COLOR_ONLY"
    out["method_limit"]="NOT_AUTOMATIC_DETECTION_NOT_DIGIT_OCR_NOT_INDEPENDENT_TRUTH"
    out["no_private_frame_or_review_coordinate_exported"]=True
    # SHA must refer to the complete final aggregate.
    out.pop("report_sha256")
    out["report_sha256"]=sha_json(out)
    return out


def main():
    parser=ArgumentParser()
    parser.add_argument("--decrypted-private-dir",type=Path,required=True)
    parser.add_argument("--saved-frame-features",type=Path,required=True)
    parser.add_argument("--manual-review",type=Path,required=True)
    parser.add_argument("--aggregate-report",type=Path,required=True)
    args=parser.parse_args()
    result=run(decrypted_private_dir=args.decrypted_private_dir,
               saved_frame_features=args.saved_frame_features,
               manual_review=args.manual_review)
    dest=args.aggregate_report
    need(dest.parent.is_dir() and
         (dest.parent.stat().st_mode & 0o077)==0 and not dest.exists(),
         "PRIVATE_OUTPUT_MUST_BE_CREATE_ONCE")
    with dest.open("x",encoding="utf-8") as out:
        os.chmod(dest,0o600)
        json.dump(result,out,ensure_ascii=False,indent=2)
        out.write("\n")
    # No per-rider or source-frame IDs exposed in the console.
    print(json.dumps({k:result[k] for k in (
        "original_saved_frame_count","exact_saved_frame_sha_matches",
        "manually_localized_jersey_crops","color_car_candidates_decided",
        "color_car_candidates_matching_single_review",
        "candidate_decision_coverage_pct",
        "conditional_single_review_color_match_pct",
        "complete_automatic_car_detection_accuracy_pct",
        "position_accuracy_pct","line_accuracy_pct",
        "verified_six_phase_count","phase_weighted_accuracy_pct")},
        sort_keys=True))


if __name__=="__main__":
    main()
