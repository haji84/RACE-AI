"""Offline real-source shape cues + camera scene-guard for existing PR291.

Replays the exact PRE-FROZEN A proposals and two private prediction-blind HTML
source-frame packets, enforcing both file SHA and decoded BGR frame SHA. Reuses:
  - existing conservative B HSV regions
  - weak local bicycle wheel-pair shape context
  - existing LK/RANSAC camera quality
  - existing color-track scene-break guard
Outputs only redacted count aggregates. No true riders or precision/recall.

NO HTTP, no new model, no public frame exports, no person/line/phase training.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import base64
import json
import os

from race_ai.keirin_blind_rider_holdout_gate import checked_proposal
from race_ai.keirin_bicycle_shape_context import (
    BicycleContextError,analyze_frame,summarize_shape_context,
)
from race_ai.keirin_camera_motion_quality import assess_pair,summarize_motion
from race_ai.keirin_color_track_flow_guard import color_scene_guarded_tracks
from scripts.keirin_private_color_ab_compare import (
    read_private_html,IMAGE_PREFIX,
)

def need(ok,code):
    if not ok:raise BicycleContextError(code)


def run(*,frozen_proposals,private_html_a,private_html_b,
        html_a_sha256,html_b_sha256,expected_baseline=None):
    import cv2
    import numpy as np

    original=Path(frozen_proposals)
    need(original.is_file() and not original.is_symlink() and
         original.stat().st_size<=5_000_000,
         "PRIVATE_FROZEN_A_PROPOSALS_REQUIRED")
    model=checked_proposal(json.loads(original.read_bytes()))
    a=read_private_html(private_html_a,html_a_sha256)
    b=read_private_html(private_html_b,html_b_sha256)
    need(a["reviewer_id"]!=b["reviewer_id"] and
         a["race_id"]==b["race_id"]==model["race_id"] and
         a["proposal_sha256"]==b["proposal_sha256"]==
         model["proposal_sha256"] and
         a["recording_sha256"]==b["recording_sha256"]==
         model["recording_sha256"] and
         a["target_kind"]==b["target_kind"]=="JERSEY_COLOR_REGION" and
         len(a["frames"])==len(b["frames"])==len(model["frames"]) and
         2<=len(a["frames"])<=300,
         "PRIVATE_A_B_SOURCE_IDENTITY_MISMATCH")

    shape_rows=[]
    track_frames=[]
    motion_rows=[]
    adjacent=[]
    previous_img=None
    previous_sha=None
    for reference,alternative,frozen in zip(
            a["frames"],b["frames"],model["frames"]):
        need(type(reference) is dict and type(alternative) is dict and
             reference["frame_sha256"]==alternative["frame_sha256"]==
             frozen["frame_sha256"] and
             reference["recording_sec"]==alternative["recording_sec"]==
             frozen["recording_sec"] and
             reference["image_data_url"]==alternative["image_data_url"],
             "A_B_FRAME_BYTE_OR_SHA_MISMATCH")
        data=reference["image_data_url"]
        need(type(data) is str and data.startswith(IMAGE_PREFIX),
             "FRAME_PNG_DATA_INVALID")
        try: png=base64.b64decode(data[len(IMAGE_PREFIX):],validate=True)
        except Exception:
            raise BicycleContextError("PRIVATE_PNG_BASE64_INVALID") from None
        need(len(png)<=2_000_000 and png.startswith(b"\x89PNG\r\n\x1a\n"),
             "PRIVATE_SOURCE_FRAME_NOT_PNG")
        img=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
        need(img is not None and
             sha256(img.tobytes()).hexdigest()==frozen["frame_sha256"],
             "DECODED_SOURCE_BRG_FRAME_SHA_MISMATCH")
        shape_rows.append(analyze_frame(
            img,frozen["proposals"],
            expected_sha256=frozen["frame_sha256"],
            second=frozen["recording_sec"]))
        proposals=[]
        for p in frozen["proposals"]:
            x,y,w,h=p["bbox_xywh"]
            proposals.append({
                "car_color_candidate":p["car_color_candidate"],
                "center_x_1024":(x+w/2)*1024,
                "center_y_584":(y+h/2)*584,
                "trust_tier":"UNTRUSTED_COLOR_BLOB_ONLY",
            })
        row={
            "sample_sec":frozen["recording_sec"],
            "source_crop_sha256":frozen["frame_sha256"],
            "proposals":proposals,
        }
        if previous_img is not None:
            gap=frozen["recording_sec"]-track_frames[-1]["sample_sec"]
            motion=assess_pair(
                previous_img,img,previous_sha=previous_sha,
                current_sha=frozen["frame_sha256"],
                gap_seconds=gap)
            motion_rows.append(motion)
            adjacent.append({
                "previous_frame_sha256":previous_sha,
                "current_frame_sha256":frozen["frame_sha256"],
                "motion":motion,
            })
        track_frames.append(row)
        previous_img=img
        previous_sha=frozen["frame_sha256"]

    if expected_baseline is None:
        expected_baseline=(222,114,99,96)
    need(type(expected_baseline) is tuple and
         len(expected_baseline)==4 and
         all(type(x) is int and x>=0 for x in expected_baseline),
         "BASELINE_COUNTS_REQUIRED")
    shape=summarize_shape_context(
        shape_rows,expected_frame_count=len(model["frames"]),
        expected_a_count=expected_baseline[0],
        expected_b_count=expected_baseline[1],
        expected_spatial_count=expected_baseline[2],
        expected_color_count=expected_baseline[3])
    motion=summarize_motion(
        motion_rows,expected_transitions=len(track_frames)-1)
    tracks=color_scene_guarded_tracks(track_frames,adjacent)
    return {
        "schema":"RACE_AI_KEIRIN_REAL_BICYCLE_CONTEXT_AND_SCENE_GUARD_AUDIT_V1",
        "race_id":model["race_id"],
        "recording_sha256":model["recording_sha256"],
        "original_frozen_A_proposal_sha256":model["proposal_sha256"],
        "private_source_HTML_A_SHA256":html_a_sha256,
        "private_source_HTML_B_SHA256":html_b_sha256,
        "original_source_bound_frame_hashes_verified":len(shape_rows),
        "bicycle_shape_context":shape,
        "camera_background_motion_quality":motion,
        "color_candidate_track_scene_break":tracks,
        "A_original_proposal_count_unchanged":True,
        "actual_rider_number_or_person_identity_proven":False,
        "validated_human_annotations_used":False,
        "confirmed_bicycle_shape_precision_pct":None,
        "true_rider_recall_or_precision_pct":None,
        "actual_race_position_line_accuracy_pct":None,
        "six_phase_scoring_accuracy_pct":None,
        "existing_model_or_official_PDCA_modified":False,
        "private_bbox_or_frame_pixels_exported":False,
    }


def main():
    parser=ArgumentParser()
    parser.add_argument("--frozen-proposals",required=True,type=Path)
    parser.add_argument("--private-html-A",required=True,type=Path)
    parser.add_argument("--private-html-B",required=True,type=Path)
    parser.add_argument("--html-A-sha256",required=True)
    parser.add_argument("--html-B-sha256",required=True)
    parser.add_argument("--redacted-output",required=True,type=Path)
    args=parser.parse_args()
    report=run(
        frozen_proposals=args.frozen_proposals,
        private_html_a=args.private_html_A,
        private_html_b=args.private_html_B,
        html_a_sha256=args.html_A_sha256,
        html_b_sha256=args.html_B_sha256)
    out=args.redacted_output
    need(out.parent.is_dir() and out.parent.stat().st_mode&0o077==0 and
         not out.exists() and not out.is_symlink(),
         "PRIVATE_REDACTED_REPORT_CREATE_ONCE_REQUIRED")
    flags=os.O_CREAT|os.O_WRONLY|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
    with os.fdopen(os.open(out,flags,0o600),"wb") as f:
        f.write((json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode())
        f.flush();os.fsync(f.fileno())
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
