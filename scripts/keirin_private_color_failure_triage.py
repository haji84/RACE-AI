"""Analyze the exact private Takeo2R A/B frames and immutable color proposals.

The output is safe aggregate counts only, not original pixel data, owner-private
review coordinates, a new racer predictor, third-party human signatures or
PDCA/training. Uses A and B original SHA-bound identical PNG data URLs.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import base64
import json
import os

from race_ai.keirin_blind_rider_holdout_gate import checked_proposal
from race_ai.keirin_color_ab_stability import ABStabilityError
from race_ai.keirin_color_failure_triage import (
    diagnose_frame,summarize_diagnosis,
)
from scripts.keirin_private_color_ab_compare import (
    read_private_html,IMAGE_PREFIX,
)


def need(ok,reason):
    if not ok:raise ABStabilityError(reason)


def run(*,frozen_proposals,private_html_A,private_html_B,
        expected_html_A_SHA,expected_html_B_SHA):
    import cv2
    import numpy as np

    frozen=checked_proposal(json.loads(Path(frozen_proposals).read_bytes()))
    A=read_private_html(private_html_A,expected_html_A_SHA)
    B=read_private_html(private_html_B,expected_html_B_SHA)
    need(A["race_id"]==B["race_id"]==frozen["race_id"] and
         A["recording_sha256"]==B["recording_sha256"]==
         frozen["recording_sha256"] and
         A["proposal_sha256"]==B["proposal_sha256"]==
         frozen["proposal_sha256"] and
         A["reviewer_id"]!=B["reviewer_id"] and
         len(A["frames"])==len(B["frames"])==len(frozen["frames"]),
         "A_B_SOURCE_OR_FROZEN_IDENTITY_MISMATCH")
    reports=[]
    for a,b,f in zip(A["frames"],B["frames"],frozen["frames"]):
        need(type(a) is dict and type(b) is dict and
             a["frame_sha256"]==b["frame_sha256"]==
             f["frame_sha256"] and
             a["recording_sec"]==b["recording_sec"]==
             f["recording_sec"] and
             a["image_data_url"]==b["image_data_url"],
             "A_B_PRIVATE_FRAME_BYTES_OR_SHA_DIFFER")
        img=a["image_data_url"]
        need(type(img) is str and img.startswith(IMAGE_PREFIX),
             "A_B_PRIVATE_FRAME_PNG_INVALID")
        try:
            buf=base64.b64decode(img[len(IMAGE_PREFIX):],validate=True)
        except Exception:
            raise ABStabilityError("A_B_PRIVATE_FRAME_BASE64_INVALID") from None
        need(len(buf)<2_000_000 and buf.startswith(b"\x89PNG\r\n\x1a\n"),
             "A_B_SOURCE_PNG_INVALID")
        decoded=cv2.imdecode(np.frombuffer(buf,np.uint8),
                             cv2.IMREAD_COLOR)
        need(decoded is not None and
             sha256(decoded.tobytes()).hexdigest()==f["frame_sha256"],
             "PRIVATE_FRAME_DECODED_SHA_MISMATCH")
        reports.append(diagnose_frame(
            decoded,f["proposals"],
            expected_sha256=f["frame_sha256"],
            second=f["recording_sec"]))
    output=summarize_diagnosis(
        reports,race_id=frozen["race_id"],
        expected_frame_count=len(frozen["frames"]),
        expected_A_count=222,expected_B_count=114,
        expected_spatial_count=99,expected_color_count=96)
    output.update({
        "original_frozen_proposal_sha256":frozen["proposal_sha256"],
        "original_source_video_sha256":frozen["recording_sha256"],
        "verified_private_html_A_sha256":expected_html_A_SHA,
        "verified_private_html_B_sha256":expected_html_B_SHA,
        "A_B_frames_byte_identical":True,
        "reviewer_A_or_B_human_annotations_used":False,
        "verified_rider_ground_truth_available":False,
        "all_46_saved_frame_SHA_reproduced":True,
    })
    return output


def main():
    p=ArgumentParser()
    p.add_argument("--frozen-proposals",required=True,type=Path)
    p.add_argument("--private-html-A",required=True,type=Path)
    p.add_argument("--private-html-B",required=True,type=Path)
    p.add_argument("--expected-html-A-SHA256",required=True)
    p.add_argument("--expected-html-B-SHA256",required=True)
    p.add_argument("--private-redacted-report",required=True,type=Path)
    args=p.parse_args()
    report=run(
        frozen_proposals=args.frozen_proposals,
        private_html_A=args.private_html_A,
        private_html_B=args.private_html_B,
        expected_html_A_SHA=args.expected_html_A_SHA256,
        expected_html_B_SHA=args.expected_html_B_SHA256)
    target=args.private_redacted_report
    need(target.parent.is_dir() and target.parent.stat().st_mode&0o077==0
         and not target.exists(),"RESEARCH_REPORT_OUTPUT_MUST_BE_PRIVATE_ONCE")
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
               getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        json.dump(report,out,ensure_ascii=False,indent=2)
        out.write("\n")
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
