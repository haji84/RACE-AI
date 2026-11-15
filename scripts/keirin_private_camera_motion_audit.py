"""Read the existing private 46-frame authenticated video sample, diagnose flow.

This is a camera/global-feature QUALITY gate, not automatic rider tracking.
The review HTML is one of the previously generated original, prediction-blind
source frame packets; do not upload it, individual image crops or the decoder's
feature tracks to public GitHub.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import base64
import json
import os

from race_ai.keirin_blind_rider_holdout_gate import checked_proposal
from race_ai.keirin_camera_motion_quality import (
    MotionQualityError,assess_pair,summarize_motion,
)
from scripts.keirin_private_color_ab_compare import (
    read_private_html,IMAGE_PREFIX,
)


def need(ok,reason):
    if not ok:raise MotionQualityError(reason)


def run(*,frozen_proposals,private_html,expected_html_sha):
    import cv2
    import numpy as np

    frozen=checked_proposal(json.loads(Path(frozen_proposals).read_bytes()))
    image_manifest=read_private_html(private_html,expected_html_sha)
    need(image_manifest["race_id"]==frozen["race_id"] and
         image_manifest["recording_sha256"]==frozen["recording_sha256"] and
         image_manifest["proposal_sha256"]==frozen["proposal_sha256"] and
         len(image_manifest["frames"])==len(frozen["frames"]),
         "MOTION_SOURCE_OR_FROZEN_MODEL_MISMATCH")
    results=[]
    previous=None
    for meta,locked in zip(image_manifest["frames"],frozen["frames"]):
        need(meta["frame_sha256"]==locked["frame_sha256"] and
             meta["recording_sec"]==locked["recording_sec"],
             "MOTION_FRAME_BINDING_MISMATCH")
        url=meta["image_data_url"]
        need(type(url) is str and url.startswith(IMAGE_PREFIX),
             "MOTION_PRIVATE_PNG_MISSING")
        try:
            raw=base64.b64decode(url[len(IMAGE_PREFIX):],validate=True)
        except Exception:
            raise MotionQualityError("MOTION_FRAME_BASE64_INVALID") from None
        need(raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw)<2_000_000,
             "MOTION_PRIVATE_PNG_INVALID")
        frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        need(frame is not None and
             sha256(frame.tobytes()).hexdigest()==locked["frame_sha256"],
             "MOTION_ORIGINAL_FRAME_SHA_MISMATCH")
        if previous is not None:
            prior,prior_row=previous
            results.append(assess_pair(
                prior,frame,
                previous_sha=prior_row["frame_sha256"],
                current_sha=locked["frame_sha256"],
                gap_seconds=locked["recording_sec"]-
                            prior_row["recording_sec"]))
        previous=(frame,locked)
    need(len(results)==len(frozen["frames"])-1,
         "MOTION_FRAME_SET_NOT_COMPLETE")
    report=summarize_motion(results,expected_transitions=len(results))
    report["race_id"]=frozen["race_id"]
    report["original_source_video_sha256"]=frozen["recording_sha256"]
    report["original_frozen_proposal_sha256"]=frozen["proposal_sha256"]
    report["verified_private_html_file_sha256"]=expected_html_sha
    report["all_46_original_frame_SHA_verified"]=True
    report["independent_human_ground_truth_available"]=False
    report["camera_quality_not_to_be_used_to_count_rider_tracks"]=True
    return report


def main():
    p=ArgumentParser()
    p.add_argument("--frozen-proposals",required=True,type=Path)
    p.add_argument("--private-html",required=True,type=Path)
    p.add_argument("--expected-html-SHA256",required=True)
    p.add_argument("--private-redacted-report",required=True,type=Path)
    args=p.parse_args()
    out=run(frozen_proposals=args.frozen_proposals,
            private_html=args.private_html,
            expected_html_sha=args.expected_html_SHA256)
    dest=args.private_redacted_report
    need(dest.parent.is_dir() and dest.parent.stat().st_mode&0o077==0 and
         not dest.exists(),
         "MOTION_REPORT_MUST_BE_OWNER_PRIVATE_CREATE_ONCE")
    fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
               getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)
        f.write("\n")
    print(json.dumps(out,sort_keys=True))


if __name__=="__main__":
    main()
