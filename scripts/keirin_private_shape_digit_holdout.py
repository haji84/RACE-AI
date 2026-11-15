"""Owner-private fixed-interval OCR feasibility on source-SHA-bound color blobs.

No official numbers, finish results, reviewed person boxes, network, paid
providers or prediction updates. Only two preprocessings of the same tiny
crop and weak wheel shape context are analyzed. Unresolved digits stay
UNKNOWN. Research prototype, NOT person identification accuracy.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import json
import os

from race_ai.keirin_blind_rider_holdout_gate import checked_proposal
from race_ai.keirin_shape_digit_candidate_research import (
    analyze_shape_digit_frame,summarize_shape_digit,UNKNOWN,
)

FIXED_SECONDS=(16,32,48,64,80)


def run(*,frozen_proposals,private_webm,expected_webm_sha256):
    import cv2
    import pytesseract

    p=Path(frozen_proposals)
    video=Path(private_webm)
    if (not p.is_file() or not video.is_file() or
        p.is_symlink() or video.is_symlink()):
        raise ValueError("PRIVATE_RESEARCH_VIDEO_AND_FROZEN_PROPOSAL_REQUIRED")
    doc=checked_proposal(json.loads(p.read_bytes()))
    if (sha256(video.read_bytes()).hexdigest()!=doc["recording_sha256"]
        or doc["recording_sha256"]!=expected_webm_sha256):
        raise ValueError("SOURCE_WEBM_VIDEO_SHA_MISMATCH")
    indexed={row["recording_sec"]:row for row in doc["frames"]}
    if not set(FIXED_SECONDS)<=set(indexed):
        raise ValueError("PREDECLARED_FRAME_SECONDS_NOT_FROZEN")
    calls=0
    def ocr_gray(image):
        nonlocal calls
        calls+=1
        try:
            data=pytesseract.image_to_data(
                image,
                config="--psm 10 --oem 3 -c tessedit_char_whitelist=123456789",
                output_type=pytesseract.Output.DICT,
                timeout=3)
            recognized=[]
            for text,conf in zip(data["text"],data["conf"]):
                digit=text.strip()
                if len(digit)==1 and digit in "123456789" and float(conf)>=60:
                    recognized.append((int(digit),float(conf)))
            if len(recognized)==1:
                return {"digit":recognized[0][0],
                        "confidence":recognized[0][1]}
        except Exception:
            pass
        return {"digit":UNKNOWN,"confidence":None}
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError("REAL_SOURCE_VIDEO_DECODER_REQUIRED")
    rows=[]
    try:
        for second in FIXED_SECONDS:
            cap.set(cv2.CAP_PROP_POS_MSEC,second*1000)
            ok,full=cap.read()
            if not ok:
                raise ValueError("REAL_SOURCE_FRAME_MISSING")
            H,W=full.shape[:2]
            crop=full[int(H*.303):int(H*.709),
                      int(W*.299):int(W*.701)]
            if sha256(crop.tobytes()).hexdigest()!=indexed[second]["frame_sha256"]:
                raise ValueError("SOURCE_FRAME_CROP_SHA_MISMATCH")
            rows.append(analyze_shape_digit_frame(
                crop,indexed[second]["proposals"],
                expected_sha256=indexed[second]["frame_sha256"],
                second=second,ocr_reader=ocr_gray))
    finally:
        cap.release()
    total=sum(row["frozen_A_candidate_count"] for row in rows)
    out=summarize_shape_digit(
        rows,race_id=doc["race_id"],expected_frame_count=len(FIXED_SECONDS),
        expected_A_candidates=total)
    out["fixed_predeclared_source_seconds"]=list(FIXED_SECONDS)
    out["original_video_sha256"]=doc["recording_sha256"]
    out["frozen_A_proposal_sha256"]=doc["proposal_sha256"]
    out["ocr_backend"]="LOCAL_OFFLINE_TESSERACT_PSM10_TWO_PIXEL_PREPROCESSINGS"
    out["ocr_subprocess_invocations"]=calls
    out["duplicate_human_reviewer_claimed"]=False
    out["real_binary_numeric_OCR_accuracy"]=None
    out["same_source_OCR_preprocessing_views_not_independent_ground_truth"]=True
    return out


def main():
    cli=ArgumentParser()
    cli.add_argument("--frozen-proposals",required=True,type=Path)
    cli.add_argument("--private-webm",required=True,type=Path)
    cli.add_argument("--expected-video-sha256",required=True)
    cli.add_argument("--redacted-output",required=True,type=Path)
    args=cli.parse_args()
    result=run(
        frozen_proposals=args.frozen_proposals,
        private_webm=args.private_webm,
        expected_webm_sha256=args.expected_video_sha256)
    dest=args.redacted_output
    if not dest.parent.is_dir() or dest.exists() or dest.is_symlink():
        raise ValueError("PRIVATE_AUDIT_OUTPUT_MUST_BE_CREATE_ONCE")
    fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as output:
        json.dump(result,output,sort_keys=True,indent=2)
        output.write("\n")
    print(json.dumps({
        "race_id":result["race_id"],
        "sampled_frame_count":result["source_sha_verified_frames"],
        "A_candidate_count":result["original_A_color_blobs"],
        "counts":result["shape_and_OCR_research_counts"],
        "ocr_subprocess_invocations":result["ocr_subprocess_invocations"],
        "formal_ground_truth":result["independent_human_labels"],
    }))


if __name__=="__main__":
    main()
