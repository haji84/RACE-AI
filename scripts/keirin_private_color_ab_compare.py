"""Offline A(frozen) vs B(stricter HSV) private real-video sensitivity research.

Inputs: exact existing frozen PR291 proposals JSON, two previously generated
reviewer HTML files containing identical original frames (NO reviewer labels).
Outputs: aggregate counts only. Absolutely no fabricated reviewer signatures,
person bounding-box truth, OCR accuracy, rank or PDCA integration.

The method B is a stricter parameter variant of A, not an independent model,
reviewer, or independently adjudicated ground truth.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import base64
import json
import os
import re

from race_ai.keirin_blind_rider_holdout_gate import checked_proposal
from race_ai.keirin_color_ab_stability import (
    ABStabilityError,conservative_blobs,compare_a_b_regions,summarize_a_b,
)

PAYLOAD=re.compile(r'<script id="payload" type="application/json">(.*?)</script>',re.S)
IMAGE_PREFIX="data:image/png;base64,"
ALLOWED_KEYS=frozenset((
    "draft_schema","race_id","recording_sha256","proposal_sha256",
    "reviewer_id","target_kind","packet_manifest_sha256","frames",
))


def need(ok,reason):
    if not ok:raise ABStabilityError(reason)


def read_private_html(path,expected_sha):
    p=Path(path)
    need(p.is_file() and not p.is_symlink() and
         p.stat().st_size<=25_000_000,
         "PRIVATE_HTML_REQUIRED")
    raw=p.read_bytes()
    need(type(expected_sha) is str and
         sha256(raw).hexdigest()==expected_sha,
         "PRIVATE_HTML_BYTES_SHA_MISMATCH")
    # No scripts are executed: read only the fixed JSON script element.
    decoded=raw.decode("utf-8")
    m=PAYLOAD.search(decoded)
    need(m is not None,"PRIVATE_IMAGE_PAYLOAD_MISSING")
    obj=json.loads(m.group(1))
    need(type(obj) is dict and set(obj)==ALLOWED_KEYS and
         type(obj.get("frames")) is list and
         len(obj["frames"])<=600,
         "PRIVATE_IMAGE_PAYLOAD_SCHEMA_INVALID")
    return obj


def evaluate(*,original_frozen,private_html_a,private_html_b,
             html_a_sha256,html_b_sha256):
    import cv2
    import numpy as np

    frozen_file=Path(original_frozen)
    need(frozen_file.is_file() and not frozen_file.is_symlink(),
         "EXISTING_FROZEN_PROPOSAL_REQUIRED")
    frozen=checked_proposal(json.loads(frozen_file.read_bytes()))
    a=read_private_html(private_html_a,html_a_sha256)
    b=read_private_html(private_html_b,html_b_sha256)
    need(a["reviewer_id"]!=b["reviewer_id"] and
         a["race_id"]==b["race_id"]==frozen["race_id"] and
         a["recording_sha256"]==b["recording_sha256"]==
             frozen["recording_sha256"] and
         a["proposal_sha256"]==b["proposal_sha256"]==
             frozen["proposal_sha256"] and
         a["target_kind"]==b["target_kind"]==
             frozen["target_kind"]=="JERSEY_COLOR_REGION" and
         len(a["frames"])==len(b["frames"])==len(frozen["frames"]),
         "A_B_FROZEN_FRAME_SET_OR_OWNER_MISMATCH")
    counts=[]
    for fr_a,fr_b,frozen_row in zip(
            a["frames"],b["frames"],frozen["frames"]):
        need(type(fr_a) is dict and type(fr_b) is dict and
             set(fr_a)==set(fr_b)=={
                 "frame_sha256","recording_sec","image_data_url"} and
             fr_a["frame_sha256"]==fr_b["frame_sha256"]==
                 frozen_row["frame_sha256"] and
             fr_a["recording_sec"]==fr_b["recording_sec"]==
                 frozen_row["recording_sec"],
             "A_B_SOURCE_FRAME_SHA_OR_ORDER_MISMATCH")
        d1,d2=fr_a["image_data_url"],fr_b["image_data_url"]
        need(type(d1) is str and type(d2) is str and
             d1.startswith(IMAGE_PREFIX) and
             d2.startswith(IMAGE_PREFIX),
             "PRIVATE_IMAGE_DATA_URL_INVALID")
        try:
            raw_a=base64.b64decode(d1[len(IMAGE_PREFIX):],validate=True)
            raw_b=base64.b64decode(d2[len(IMAGE_PREFIX):],validate=True)
        except Exception:
            raise ABStabilityError("PRIVATE_PNG_BASE64_INVALID") from None
        need(raw_a==raw_b and
             raw_a.startswith(b"\x89PNG\r\n\x1a\n") and
             len(raw_a)<=2_000_000,
             "A_B_FRAME_PIXEL_BYTES_DIFFER")
        image=cv2.imdecode(np.frombuffer(raw_a,dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        need(image is not None and
             sha256(image.tobytes()).hexdigest()==
                 frozen_row["frame_sha256"],
             "SOURCE_PNG_DECODED_FRAME_SHA_MISMATCH")
        blobs=conservative_blobs(image,expected_frame_sha256=
                                 frozen_row["frame_sha256"])
        counts.append(compare_a_b_regions(frozen_row["proposals"],blobs))
    output=summarize_a_b(
        counts,race_id=frozen["race_id"],
        frozen_sha=frozen["proposal_sha256"],
        exact_frame_sha_count=len(counts))
    output["verified_html_A_file_sha256"]=html_a_sha256
    output["verified_html_B_file_sha256"]=html_b_sha256
    output["source_detector_sha256"]=frozen["model_code_sha256"]
    output["original_video_sha256"]=frozen["recording_sha256"]
    output["reviewer_A_and_B_are_only_unfilled_image_slots"]=True
    output["human_second_reviewer_completed"]=False
    return output


def main():
    parser=ArgumentParser()
    parser.add_argument("--frozen-proposals",required=True,type=Path)
    parser.add_argument("--private-html-A",required=True,type=Path)
    parser.add_argument("--private-html-B",required=True,type=Path)
    parser.add_argument("--html-A-sha256",required=True)
    parser.add_argument("--html-B-sha256",required=True)
    parser.add_argument("--redacted-output",required=True,type=Path)
    args=parser.parse_args()
    result=evaluate(
        original_frozen=args.frozen_proposals,
        private_html_a=args.private_html_A,
        private_html_b=args.private_html_B,
        html_a_sha256=args.html_A_sha256,
        html_b_sha256=args.html_B_sha256)
    out=args.redacted_output
    need(out.parent.is_dir() and not out.exists() and not out.is_symlink(),
         "REDACTED_REPORT_MUST_BE_CREATE_ONCE")
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
    with os.fdopen(os.open(out,flags,0o600),"wb") as f:
        f.write(json.dumps(result,ensure_ascii=False,
                           indent=2).encode("utf-8")+b"\n")
    # JSON only contains aggregate counts and public hashes.
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
