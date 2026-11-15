"""Build two separate, private, prediction-blind frame-review packets.

Uses the EXISTING frozen proposal SHA and decrypted PRIVATE video; does not
scrape, classify, fetch a new model, share footage, or submit any results.
Reviewers see original frame crops WITHOUT prediction boxes, colors, rider
numbers, or each other's answers. The resulting blank forms are NOT truth.
A separate identity/provenance witness is still required by the holdout gate.
"""
from __future__ import annotations

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import json
import os
import re

from race_ai.keirin_blind_rider_holdout_gate import (
    checked_proposal,REVIEW_SCHEMA,HoldoutGateError,
)


def need(ok,code):
    if not ok:raise HoldoutGateError(code)


def safe_write(path,data):
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return sha256(data).hexdigest()


def generate(*,frozen_proposal,source_video,private_output,
             reviewer_ids,selected_seconds=None):
    """Verify real source bytes/framed SHA before writing private unlabeled PNG."""
    import cv2
    doc=checked_proposal(json.loads(Path(frozen_proposal).read_text()))
    source=Path(source_video)
    base=Path(private_output)
    need(source.is_file() and not source.is_symlink() and
         source.suffix.lower()==".webm",
         "DECRYPTED_OWNER_PRIVATE_WEBM_REQUIRED")
    need(base.is_dir() and not base.is_symlink() and
         base.stat().st_mode&0o077==0,
         "PRIVATE_REVIEW_DIRECTORY_REQUIRED")
    need(type(reviewer_ids) in (list,tuple) and len(reviewer_ids)==2 and
         reviewer_ids[0]!=reviewer_ids[1] and
         all(type(x) is str and
             re.fullmatch(r"[A-Za-z0-9_.-]{5,80}",x) for x in reviewer_ids),
         "TWO_DISTINCT_REVIEWER_IDS_REQUIRED")
    need(sha256(source.read_bytes()).hexdigest()==doc["recording_sha256"],
         "SOURCE_PRIVATE_VIDEO_SHA_MISMATCH")
    raw=doc["frames"]
    if selected_seconds is None:
        chosen=raw
    else:
        need(type(selected_seconds) in (list,tuple) and
             len(selected_seconds)==len(set(selected_seconds)) and
             len(selected_seconds)>0 and
             all(type(x) in (int,float) for x in selected_seconds),
             "INVALID_PREDECLARED_REVIEW_SECONDS")
        selected=set(selected_seconds)
        chosen=[x for x in raw if x["recording_sec"] in selected]
        need(len(chosen)==len(selected),"REVIEW_SAMPLES_NOT_IN_FROZEN_SOURCE")
    cap=cv2.VideoCapture(str(source))
    need(cap.isOpened(),"REAL_VIDEO_DECODE_REQUIRED")
    media={}
    try:
        for row in chosen:
            second=row["recording_sec"]
            cap.set(cv2.CAP_PROP_POS_MSEC,second*1000)
            ok,frame=cap.read()
            need(ok,"FROZEN_PRIVATE_FRAME_UNREADABLE")
            h,w=frame.shape[:2]
            crop=frame[int(h*.303):int(h*.709),
                       int(w*.299):int(w*.701)]
            need(crop.size>0 and
                 sha256(crop.tobytes()).hexdigest()==row["frame_sha256"],
                 "PRIVATE_FRAME_SHA_REPLAY_MISMATCH")
            ok,png=cv2.imencode(".png",crop)
            need(ok and len(png)>0,"PRIVATE_FRAME_PNG_ENCODING_FAILED")
            media[row["frame_sha256"]]=png.tobytes()
    finally:
        cap.release()
    outputs=[]
    for reviewer_id in reviewer_ids:
        dest=base/("blind_"+reviewer_id)
        dest.mkdir(mode=0o700,exist_ok=False)
        frames=[]
        for ix,row in enumerate(chosen):
            # Only source frame hash and time; NEVER include candidate
            # bounding boxes or recognized colors in the reviewer packet.
            fn=f"source_{ix:03d}.png"
            sig=safe_write(dest/fn,media[row["frame_sha256"]])
            frames.append({
                "frame_sha256":row["frame_sha256"],
                "source_image_file":fn,"png_bytes_sha256":sig,
                "recording_sec":row["recording_sec"],
            })
        # Review form is deliberately UNFINISHED and does not satisfy the
        # checked_review() schema until a distinct reviewer fills the fields
        # and an external reviewer receipt attests the completed source.
        form={
            "schema":REVIEW_SCHEMA,
            "race_id":doc["race_id"],
            "recording_sha256":doc["recording_sha256"],
            "proposal_sha256":doc["proposal_sha256"],
            "reviewer_id":reviewer_id,
            "reviewed_at":None,
            "target_kind":doc["target_kind"],
            "independent_source_frame_read":False,
            "frames":[{
                "frame_sha256":f["frame_sha256"],
                "exhaustive_visible_targets":False,
                "annotations":[],
            } for f in frames],
            "review_sha256":None,
        }
        safe_write(dest/"review_UNFINISHED.json",json.dumps(
            form,ensure_ascii=False,indent=2).encode("utf-8")+b"\n")
        manifest={
            "schema":"RACE_AI_KEIRIN_PRIVATE_BLIND_REVIEW_PACKET_V1",
            "race_id":doc["race_id"],
            "recording_sha256":doc["recording_sha256"],
            "proposal_sha256":doc["proposal_sha256"],
            "reviewer_id":reviewer_id,
            "frozen_input_exact":True,
            "review_frame_count":len(frames),
            "frames":frames,
            "does_not_contain_model_predictions_or_rider_labels":True,
            "independent_review_completed":False,
            "not_for_public_GitHub_artifacts":True,
        }
        safe_write(dest/"manifest.json",json.dumps(
            manifest,ensure_ascii=False,indent=2).encode("utf-8")+b"\n")
        outputs.append({
            "reviewer":reviewer_id,
            "frame_count":len(frames),
            "packet_created":True,
            "independent_review_completed":False,
        })
    return {
        "schema":"RACE_AI_KEIRIN_PRIVATE_HOLDOUT_PACKET_SUMMARY_V1",
        "race_id":doc["race_id"],
        "source_recording_SHA_bound":True,
        "frozen_proposal_sha256":doc["proposal_sha256"],
        "separate_packets_created":len(outputs),
        "images_per_reviewer":len(chosen),
        "candidate_color_boxes_exposed_to_reviewers":False,
        "second_independent_review_completed":False,
        "admission_to_phase_scoring":False,
    }


def main():
    p=ArgumentParser()
    p.add_argument("--frozen-proposal",required=True,type=Path)
    p.add_argument("--source-video",required=True,type=Path)
    p.add_argument("--private-output",required=True,type=Path)
    p.add_argument("--reviewers",required=True,nargs=2)
    p.add_argument("--seconds",nargs="*",type=float)
    args=p.parse_args()
    report=generate(
        frozen_proposal=args.frozen_proposal,
        source_video=args.source_video,
        private_output=args.private_output,
        reviewer_ids=args.reviewers,
        selected_seconds=args.seconds)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
