"""Validate reviewer OFFLINE JSON export against its exact private blind packet.

An independently completed per-frame annotation is not made independent by
a script. This creates a SOURCE-BOUND PRIVATE review candidate for existing
Ed25519 signing and later independent owner/registry/video verification.
It does NOT call the model, read its predicted bounding boxes, or score.
"""
from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re

from race_ai.keirin_blind_rider_holdout_gate import (
    checked_proposal,checked_review,digest,
)
from scripts.keirin_private_blind_review_workbench import (
    checked_packet,DRAFT_SCHEMA,
)

SHA=re.compile(r"^[a-f0-9]{64}$")


class ReviewFinalizeError(ValueError):
    pass


def need(value,why):
    if not value:raise ReviewFinalizeError(why)


def private_file(path):
    p=Path(path)
    need(p.is_file() and not p.is_symlink() and
         p.stat().st_mode&0o077==0 and
         p.parent.is_dir() and p.parent.stat().st_mode&0o077==0,
         "PRIVATE_FILE_0600_REQUIRED")
    return p


def finalize(*,packet_dir,exported_draft,owner_frozen_proposal,
             private_completed_review,clock_now=None):
    """Exact per-frame ordering, source media and model SHA gate.

    This is executed by the owner AFTER the human has exported the blind
    draft. Only the owner-side tool receives model proposals, never reviewer.
    """
    packet=checked_packet(packet_dir)
    exported=private_file(exported_draft)
    proposal_file=private_file(owner_frozen_proposal)
    target=Path(private_completed_review)
    need(target.parent.is_dir() and
         target.parent.stat().st_mode&0o077==0 and
         not target.exists() and not target.is_symlink(),
         "PRIVATE_COMPLETED_REVIEW_MUST_BE_CREATE_ONCE")
    raw=exported.read_bytes()
    need(0<len(raw)<=2_000_000,"DRAFT_SIZE_INVALID")
    draft=json.loads(raw)
    need(type(draft) is dict and set(draft)=={
        "schema","race_id","recording_sha256","proposal_sha256",
        "reviewer_id","target_kind","packet_manifest_sha256","frames",
    } and draft["schema"]==DRAFT_SCHEMA,
         "PRIVATE_BLIND_EXPORT_SCHEMA_INVALID")
    for k in ("race_id","recording_sha256","proposal_sha256",
              "reviewer_id","target_kind","packet_manifest_sha256"):
        need(draft[k]==packet[k],"PRIVATE_BLIND_REVIEW_PACKET_MISMATCH")
    original=checked_proposal(json.loads(proposal_file.read_bytes()))
    need(original["race_id"]==packet["race_id"] and
         original["recording_sha256"]==packet["recording_sha256"] and
         original["proposal_sha256"]==packet["proposal_sha256"] and
         original["target_kind"]==packet["target_kind"],
         "FROZEN_MODEL_SOURCE_MISMATCH")
    rows=draft["frames"]
    need(type(rows) is list and len(rows)==len(packet["frames"]) and
         len(rows)==len(original["frames"]),
         "ALL_BLIND_FRAMES_MUST_BE_REVIEWED")
    output_frames=[]
    for meta,truth,original_frame in zip(packet["frames"],rows,
                                         original["frames"]):
        need(type(truth) is dict and set(truth)=={
            "frame_sha256","exhaustive_visible_targets","annotations"} and
             truth["frame_sha256"]==meta["frame_sha256"]==
             original_frame["frame_sha256"] and
             truth["exhaustive_visible_targets"] is True and
             type(truth["annotations"]) is list,
             "EXHAUSTIVE_SOURCE_FRAME_ANNOTATION_MISSING")
        # No sample-selection or post-hoc rule to skip 'difficult' frames.
        # Prevent an unlabelled rider twice in a frame with same known car.
        known_numbers=set()
        for a in truth["annotations"]:
            need(type(a) is dict and set(a)=={
                "bbox_xywh","car_number","number_evidence",
                "race_position","line_role"},
                "REVIEW_FRAME_ANNOTATION_SCHEMA_MISMATCH")
            number=a["car_number"]
            if type(number) is int:
                need(number not in known_numbers,
                     "KNOWN_RIDER_NUMBER_DUPLICATED_IN_FRAME")
                known_numbers.add(number)
        output_frames.append(truth)
    now=clock_now() if callable(clock_now) else datetime.now(timezone.utc)
    need(isinstance(now,datetime) and now.utcoffset() is not None,
         "ACTUAL_AWARE_COMPLETION_CLOCK_REQUIRED")
    review={
        "schema":"RACE_AI_KEIRIN_BLIND_HOLDOUT_INDEPENDENT_REVIEW_V1",
        "race_id":draft["race_id"],
        "recording_sha256":draft["recording_sha256"],
        "proposal_sha256":draft["proposal_sha256"],
        "reviewer_id":draft["reviewer_id"],
        "reviewed_at":now.isoformat(),
        "target_kind":draft["target_kind"],
        "independent_source_frame_read":True,
        "frames":output_frames,
    }
    review["review_sha256"]=digest(review)
    checked_review(review,original)
    payload=json.dumps(review,ensure_ascii=False,sort_keys=True,
                       separators=(",",":"),allow_nan=False).encode("utf-8")+b"\n"
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
    with os.fdopen(os.open(target,flags,0o600),"wb") as out:
        out.write(payload);out.flush();os.fsync(out.fileno())
    need(target.read_bytes()==payload,
         "COMPLETED_REVIEW_PRIVATE_READBACK_MISMATCH")
    return {
        "schema":"RACE_AI_KEIRIN_PRIVATE_REVIEW_FORM_FINALIZED_V1",
        "race_id":review["race_id"],
        "reviewer":review["reviewer_id"],
        "fully_reviewed_source_frames":len(review["frames"]),
        "private_completed_review_file_sha256":sha256(payload).hexdigest(),
        "review_sha256":review["review_sha256"],
        "independent_reviewer_identity_authenticated":False,
        "owner_video_pixel_adjudication_completed":False,
        "reviewer_signature_created":False,
        "other_reviewer_answer_read":False,
        "model_result_or_phase_score_modified":False,
        "public_coordinates_emitted":False,
    }


def main():
    p=ArgumentParser()
    p.add_argument("--private-packet-dir",type=Path,required=True)
    p.add_argument("--exported-draft",type=Path,required=True)
    p.add_argument("--owner-frozen-proposal",type=Path,required=True)
    p.add_argument("--private-completed-review",type=Path,required=True)
    x=p.parse_args()
    result=finalize(packet_dir=x.private_packet_dir,
                    exported_draft=x.exported_draft,
                    owner_frozen_proposal=x.owner_frozen_proposal,
                    private_completed_review=x.private_completed_review)
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
