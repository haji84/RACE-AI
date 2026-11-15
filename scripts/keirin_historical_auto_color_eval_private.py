"""Offline actual-media validation of automatic jersey COLOR blob proposals.

Three already-saved replay recordings, 153 source-bound BGR crop frames and a
private one-review label manifest. Reads NO source website or betting outcome.
The detector gets ONLY pixels and the starting roster. Manual rider centers
are used AFTER inference solely to measure one-review candidate agreement.

Owner-private frames, decoded video, private key, and individual coordinates
MUST NEVER be published as GitHub artifacts. Counts and SHA only.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import json
import os
import re

from race_ai.keirin_historical_rider_color_eval import (
    need, valid_sha, sha_json,
)
from race_ai.keirin_visual_jersey_proposals import (
    detect_color_regions, match_single_review_after_detection,
    link_untrusted_color_blobs,
)

REVIEW_SCHEMA="RACE_AI_KEIRIN_PRIVATE_SINGLE_REVIEWED_JERSEY_CROPS_V1"
REPORT="RACE_AI_KEIRIN_HISTORICAL_AUTOMATIC_COLOR_PROPOSAL_RESEARCH_V1"


def run(*, decrypted_private_dir, saved_frame_features, manual_review):
    import cv2
    root=Path(decrypted_private_dir).resolve()
    need(root.is_dir() and root.stat().st_mode & 0o077==0,
         "SOURCE_VIDEO_DIRECTORY_MUST_BE_OWNER_PRIVATE")
    source_file=Path(saved_frame_features)
    manual_file=Path(manual_review)
    features=json.loads(source_file.read_text())
    review=json.loads(manual_file.read_text())
    need(type(features) is dict and
         type(features.get("sources")) is list and
         type(review) is dict and
         review.get("schema")==REVIEW_SCHEMA and
         review.get("review_level")=="SINGLE_VISUAL_REVIEW_NOT_INDEPENDENT" and
         type(review.get("races")) is list,
         "HISTORICAL_SOURCE_AND_SINGLE_REVIEW_REQUIRED")
    sources={x["race_id"]:x for x in features["sources"]}
    reviewed={x["race_id"]:x for x in review["races"]}
    need(len(sources)==len(features["sources"]) and
         len(reviewed)==len(review["races"]) and
         sources.keys()==reviewed.keys() and
         1<=len(sources)<=30,
         "SAVED_RACE_SETS_DO_NOT_MATCH")
    report_rows=[]
    for race_id in sorted(sources):
        src=sources[race_id];case=reviewed[race_id]
        need(type(race_id) is str and re.fullmatch(r"\d{12}",race_id),
             "UNTRUSTED_VIDEO_PATH")
        need(valid_sha(src["source_sha256"]) and
             src["source_sha256"]==case["source_sha256"],
             "SAVED_VIDEO_SOURCE_IDENTITY_MISMATCH")
        roster=case["starters"]
        need(type(roster) is list and 3<=len(roster)<=9 and
             len(set(roster))==len(roster) and
             all(type(n) is int and 1<=n<=9 for n in roster),
             "HISTORICAL_RESEARCH_ROSTER_INVALID")
        saved=src["frames"]
        need(type(saved) is list and 1<=len(saved)<=1800 and
             src["frame_count"]==len(saved),
             "SAVED_PRIVATE_FRAMES_MISSING")
        labels=case["labels"]
        need(type(labels) is list and len(labels)<=50 and
             len(set((x["second"],x["car_number"]) for x in labels))==
             len(labels), "SINGLE_REVIEW_LABELS_DUPLICATE_OR_MISSING")
        by_second={}
        for x in labels:
            need(type(x) is dict and set(x)=={
                "second","frame_sha256","car_number",
                "center_x_1024","center_y_584"} and
                type(x["second"]) is int and x["second"]>=0 and
                type(x["car_number"]) is int and x["car_number"] in roster and
                type(x["center_x_1024"]) is int and
                type(x["center_y_584"]) is int and
                0<=x["center_x_1024"]<=1024 and
                0<=x["center_y_584"]<=584,
                "SINGLE_REVIEW_LABEL_FIELDS_INVALID")
            by_second.setdefault(x["second"],[]).append(x)
        path=root/(race_id+".webm")
        need(path.is_file() and not path.is_symlink(),
             "HISTORICAL_PRIVATE_WEBM_MISSING")
        # Real video bytes, not only a manifest SHA. This is run in a
        # private ephemeral process, and raw media is NEVER emitted.
        need(sha256(path.read_bytes()).hexdigest()==src["source_sha256"],
             "REPLAY_SOURCE_VIDEO_SHA_MISMATCH")
        capture=cv2.VideoCapture(str(path))
        need(capture.isOpened(), "REPLAY_REAL_VIDEO_DECODING_REQUIRED")
        frame_count=0
        total_proposals=0
        no_proposal=0
        reviewed_proposals=0
        located=0
        agree=0
        tracker=[]
        seen_second=set()
        try:
            for row in saved:
                sec=row["second"];expect=row["source_frame_sha256"]
                need(type(sec) is int and sec>=0 and
                     sec not in seen_second and valid_sha(expect),
                     "INVALID_SAVED_FRAME_SECOND_OR_HASH")
                seen_second.add(sec)
                capture.set(cv2.CAP_PROP_POS_MSEC,sec*1000)
                ok,frame=capture.read()
                need(ok,"REPLAY_SAVED_FRAME_NOT_DECODED")
                h,w=frame.shape[:2]
                crop=frame[int(h*.303):int(h*.709),
                           int(w*.299):int(w*.701)]
                need(crop.size>0,"RECORDED_BROWSER_CROP_EMPTY")
                match=sha256(crop.tobytes()).hexdigest()
                need(match==expect,"REPLAY_SAVED_FRAME_SHA_MISMATCH")
                frame_count+=1
                det=detect_color_regions(
                    crop,roster=roster,source_crop_sha256=expect)
                proposals=det["proposals"]
                total_proposals+=len(proposals)
                no_proposal+=not bool(proposals)
                tracker.append({"sample_sec":sec,
                                "source_crop_sha256":expect,
                                "proposals":proposals})
                if sec in by_second:
                    # A private previous one-review file is the evaluation
                    # reference ONLY, not an input to the proposal detector.
                    for ref in by_second[sec]:
                        need(ref["frame_sha256"]==expect,
                             "SINGLE_REVIEW_FRAME_SHA_NOT_AUTHENTICATED")
                    score=match_single_review_after_detection(
                        proposals,by_second[sec])
                    reviewed_proposals+=len(proposals)
                    located+=score["single_review_spatial_matches"]
                    agree+=score["single_review_spatially_matched_color_agreements"]
            need(set(by_second)<=seen_second,
                 "SINGLE_REVIEW_FRAME_NOT_IN_SAVED_VIDEO")
        finally:
            capture.release()
        tracks=link_untrusted_color_blobs(tracker)
        report_rows.append({
            "race_id":race_id,
            "source_sha256":src["source_sha256"],
            "saved_source_frames_expected":len(saved),
            "saved_source_frames_sha_matched":frame_count,
            "candidate_color_blobs_all_saved_frames":total_proposals,
            "saved_frames_without_color_blob":no_proposal,
            "untrusted_blob_tracks_seen_once_or_more":
                tracks["untrusted_track_candidates_total"],
            "untrusted_blob_tracks_seen_twice_or_more":
                tracks["track_candidates_seen_in_at_least_two_frames"],
            "single_review_jersey_labels":len(labels),
            "auto_blob_proposals_on_single_reviewed_frames":reviewed_proposals,
            "single_review_spatial_matches_within_40px":located,
            "spatial_matches_with_correct_jersey_color":agree,
        })
    total=sum(x["single_review_jersey_labels"] for x in report_rows)
    matched=sum(x["single_review_spatial_matches_within_40px"]
                for x in report_rows)
    correct=sum(x["spatial_matches_with_correct_jersey_color"]
                for x in report_rows)
    proposed=sum(x["auto_blob_proposals_on_single_reviewed_frames"]
                 for x in report_rows)
    output={
        "schema":REPORT,
        "scope":"EXISTING_OWNER_PRIVATE_HISTORICAL_WEBM_AND_ONE_REVIEW_REFERENCE",
        "source_features_sha256":sha256(source_file.read_bytes()).hexdigest(),
        "single_reviewer_private_reference_sha256":
            sha256(manual_file.read_bytes()).hexdigest(),
        "source_frame_hashes_matched":sum(
            x["saved_source_frames_sha_matched"] for x in report_rows),
        "source_frame_hashes_expected":sum(
            x["saved_source_frames_expected"] for x in report_rows),
        "manual_center_supplied_to_detector":False,
        "manual_reference_used_only_after_image_detection":True,
        "single_review_jerseys":total,
        "auto_color_blobs_on_reviewed_frames":proposed,
        "spatial_matches_within_40px":matched,
        "spatial_matches_with_matching_car_color":correct,
        "unmatched_auto_blobs_are_not_adjudicated_false_positives":
            proposed-matched,
        "spatial_one_review_agreement_pct":
            round(100*matched/total,3) if total else None,
        "joint_spatial_and_color_one_review_agreement_pct":
            round(100*correct/total,3) if total else None,
        "correct_color_among_spatial_matches_pct":
            round(100*correct/matched,3) if matched else None,
        "independent_rider_detection_recall_pct":None,
        "independent_car_id_accuracy_pct":None,
        "actual_digit_ocr_accuracy_pct":None,
        "position_accuracy_pct":None,
        "line_accuracy_pct":None,
        "formal_phase_coverage_pct":0.0,
        "formal_phase_accuracy_pct":None,
        "six_phase_required_slots":len(report_rows)*6,
        "independently_verified_phase_slots":0,
        "untrusted_color_blob_tracks_are_not_verified_riders":True,
        "source_frame_scoring_is_exploratory_not_blind":True,
        "white_black_pink_purple_color_classes_deferred":True,
        "forecast_sha_or_model_parameters_modified":False,
        "formal_results_or_training_enabled":False,
        "public_report_contains_no_pixel_data_or_exact_boxes":True,
        "races":report_rows,
    }
    output["report_sha256"]=sha_json(output)
    return output


def main():
    p=ArgumentParser()
    p.add_argument("--decrypted-private-dir",type=Path,required=True)
    p.add_argument("--saved-frame-features",type=Path,required=True)
    p.add_argument("--single-review",type=Path,required=True)
    p.add_argument("--redacted-report",type=Path,required=True)
    a=p.parse_args()
    result=run(
        decrypted_private_dir=a.decrypted_private_dir,
        saved_frame_features=a.saved_frame_features,
        manual_review=a.single_review,
    )
    target=a.redacted_report
    need(target.parent.is_dir() and not target.exists(),
         "CREATE_ONCE_RESEARCH_REPORT_REQUIRED")
    with target.open("x",encoding="utf-8") as f:
        os.chmod(target,0o600)
        json.dump(result,f,ensure_ascii=False,indent=2)
        f.write("\n")
    print(json.dumps({key:result[key] for key in (
        "source_frame_hashes_expected","source_frame_hashes_matched",
        "single_review_jerseys","auto_color_blobs_on_reviewed_frames",
        "spatial_matches_within_40px",
        "spatial_matches_with_matching_car_color",
        "independent_rider_detection_recall_pct",
        "independent_car_id_accuracy_pct","independently_verified_phase_slots",
    )},sort_keys=True))


if __name__=="__main__":
    main()
