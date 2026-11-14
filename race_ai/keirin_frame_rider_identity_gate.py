"""Review gate for rider-number/position evidence from EXISTING PR102 frames.

Not a second video model, OCR service, position detector or learning engine.
The existing recorder/reviewer supplies immutable per-frame SHA receipts and
independently reviewed OCR/track candidates. This gate refuses to infer leader
from camera pixel coordinates, jersey color, odds or the official finish.
A trusted host must independently inspect the exact private recording pixels
for EVERY admitted frame; metadata flags cannot attest themselves.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
import re

from .keirin_phase_overlay import (
    STAGES, UNKNOWN, checked_admission, checked_forecast, digest,
    checked_parts, valid_sha,
)

SCHEMA="RACE_AI_KEIRIN_RIDER_FRAME_CANDIDATES_V1"
REPORT="RACE_AI_KEIRIN_RIDER_FRAME_REVIEW_BRIDGE_V1"
PHASES=tuple(name for name,_ in STAGES)
TRACK=re.compile(r"^[A-Za-z0-9._-]{1,50}$")
RECOGNITION_KINDS=frozenset(("OCR_CANDIDATE","INDEPENDENT_FRAME_REVIEW"))
NUM_MIN_CONFIDENCE=0.92
POSITION_MIN_CONFIDENCE=0.90


class FrameIdentityError(ValueError):
    pass


def require(ok,code):
    if not ok:raise FrameIdentityError(code)


def _confirmed(callback,*args):
    if not callable(callback):return False
    try:return callback(*args) is True
    except Exception:return False


def _number(v):
    return type(v) is int and 1<=v<=9


def _confidence(v):
    return type(v) in (int,float) and math.isfinite(v) and 0<=v<=1


def _frame_receipts(admission):
    frames=admission["reviewed_scene_frames"]
    require(type(frames) is list and len(frames)<=10000,
            "INVALID_EXISTING_FRAME_RECEIPTS")
    out={}
    for row in frames:
        require(type(row) is dict and
                valid_sha(row.get("frame_sha256")) and
                type(row.get("review_ref")) is str and
                len(row["review_ref"])>=6 and
                type(row.get("time_s")) in (int,float) and
                math.isfinite(row["time_s"]) and
                0<=row["time_s"]<=admission["duration_s"],
                "INVALID_EXISTING_FRAME_RECEIPT")
        key=(row["frame_sha256"],row["review_ref"])
        require(key not in out, "DUPLICATE_EXISTING_FRAME_RECEIPT")
        out[key]=row
    return out


def _check_packet(row, admission, receipt, starters):
    require(type(row) is dict and set(row)=={
        "schema","phase","frame_sha256","review_ref","recording_sec",
        "scene","candidates"}, "FRAME_CANDIDATE_SCHEMA_INVALID")
    require(row["schema"]==SCHEMA and row["phase"] in PHASES,
            "FRAME_PHASE_NOT_ADMITTED")
    require(valid_sha(row["frame_sha256"]) and
            type(row["review_ref"]) is str and len(row["review_ref"])>=6,
            "FRAME_DIGEST_OR_REVIEW_REF_INVALID")
    require(row["scene"] in ("LIVE","REPLAY","UNKNOWN"),
            "FRAME_SCENE_UNKNOWN")
    sec=row["recording_sec"]
    require(type(sec) in (int,float) and math.isfinite(sec) and
            0<=sec<=admission["duration_s"], "FRAME_TIME_INVALID")
    source=receipt.get((row["frame_sha256"],row["review_ref"]))
    require(source is not None and
            abs(sec-source["time_s"])<=1.5,
            "FRAME_NOT_IN_EXISTING_VIDEO_REVIEW")
    require(type(row["candidates"]) is list and
            len(row["candidates"])<=9,"FRAME_CANDIDATE_LIMIT")
    ids=set(); numbers=set(); ranks=set()
    for item in row["candidates"]:
        require(type(item) is dict and set(item)=={
            "track_id","car_number_candidate","number_confidence",
            "rank_candidate","rank_confidence","bbox_xywh_normalized",
            "recognition_kind"}, "RIDING_CANDIDATE_SCHEMA_INVALID")
        track=item["track_id"];number=item["car_number_candidate"]
        rank=item["rank_candidate"];box=item["bbox_xywh_normalized"]
        require(type(track) is str and TRACK.fullmatch(track) and
                track not in ids,"TRACK_ID_INVALID_OR_DUPLICATE")
        ids.add(track)
        require(_number(number) or number==UNKNOWN,
                "OCR_NUMBER_NOT_ALLOWED")
        require(type(rank) is int and 1<=rank<=len(starters)
                or rank==UNKNOWN,"RANK_CANDIDATE_INVALID")
        require(_confidence(item["number_confidence"]) and
                _confidence(item["rank_confidence"]) and
                item["recognition_kind"] in RECOGNITION_KINDS,
                "OCR_OR_RANK_CONFIDENCE_INVALID")
        require(type(box) is list and len(box)==4 and
                all(type(x) in (int,float) and math.isfinite(x) for x in box) and
                box[2]>0 and box[3]>0 and box[0]>=0 and box[1]>=0 and
                box[0]+box[2]<=1 and box[1]+box[3]<=1,
                "RIDER_BOUNDING_BOX_INVALID")
        if number!=UNKNOWN:
            require(number in starters and number not in numbers,
                    "CAR_NOT_IN_AUTHENTICATED_ROSTER_OR_DUPLICATE")
            numbers.add(number)
        if rank!=UNKNOWN:
            require(rank not in ranks,"DUPLICATE_RACE_POSITION_IN_FRAME")
            ranks.add(rank)
    return row


def _two_frame_consensus(first,second,starters):
    """A rider/rank must match across two different independently reviewed frames.

    A track candidate without an independent pixel check may never score.
    A rider changing rank inside this small temporal window stays UNKNOWN.
    No bounding-box X/Y ordering is used as race position or line order.
    """
    a={x["track_id"]:x for x in first["candidates"]}
    b={x["track_id"]:x for x in second["candidates"]}
    rank_to_rider={}; conflicts=set()
    for track in set(a)&set(b):
        left,right=a[track],b[track]
        number=left["car_number_candidate"]
        position=left["rank_candidate"]
        if (number==UNKNOWN or position==UNKNOWN or
            number!=right["car_number_candidate"] or
            position!=right["rank_candidate"] or
            number not in starters or
            left["number_confidence"]<NUM_MIN_CONFIDENCE or
            right["number_confidence"]<NUM_MIN_CONFIDENCE or
            left["rank_confidence"]<POSITION_MIN_CONFIDENCE or
            right["rank_confidence"]<POSITION_MIN_CONFIDENCE):
            continue
        if position in rank_to_rider and rank_to_rider[position]!=number:
            conflicts.add(position)
        else:
            rank_to_rider[position]=number
    for position in conflicts:
        rank_to_rider.pop(position,None)
    # If a number is assigned to two different ranks it is not uniquely
    # located. This must not create a false leader or top-three success.
    repeated=[number for number,count in Counter(
        rank_to_rider.values()).items() if count>1]
    if repeated:
        for pos,num in list(rank_to_rider.items()):
            if num in repeated:rank_to_rider.pop(pos)
    return rank_to_rider




def bridge_from_existing_pr71_ledger(forecast,admission,saved,packets,*,
                                     ledger_readback_verifier=None,
                                     pixel_source_verifier=None):
    """Reuse the actual PR71 frozen private roster, not a user-typed roster.

    A separate owner-host verifier must attest the exact saved SQLite/Git
    ciphertext, model and source SHA. This method validates the joins but
    cannot independently open the video or certify third-party evidence.
    """
    checked_forecast(forecast)
    require(type(saved) is dict and
            type(saved.get("source")) is dict and
            type(saved.get("suite")) is dict,
            "EXISTING_PR71_LEDGER_REQUIRED")
    source=saved["source"];suite=saved["suite"]
    models=suite.get("models")
    require(type(models) is dict and
            forecast["model_id"] in models and
            type(models[forecast["model_id"]]) is dict,
            "EXISTING_PR71_MODEL_REQUIRED")
    model=models[forecast["model_id"]]
    require(source.get("race_id")==forecast["race_id"] and
            suite.get("race_id")==forecast["race_id"] and
            source.get("official_cutoff_at")==forecast["official_cutoff_at"] and
            source.get("as_of")==suite.get("as_of") and
            model.get("model_id")==forecast["model_id"] and
            model.get("prediction_sha256")==forecast["parent_prediction_sha256"] and
            model.get("snapshot_sha256")==forecast["pre_race_input_sha256"] and
            suite.get("input_sha256")==forecast["pre_race_input_sha256"] and
            source.get("starters") is not None,
            "PR71_PHASE_PARENT_OR_RACE_MISMATCH")
    roster=source["starters"]
    if not _confirmed(ledger_readback_verifier,saved,forecast):
        # Do not allow an unverified SQLite snapshot or user-supplied roster
        # to become "rider identity verified" through a successful OCR report.
        return bridge_reviewed_frames(
            forecast,admission,roster,packets,
            roster_original_verifier=None,
            pixel_source_verifier=None)
    return bridge_reviewed_frames(
        forecast,admission,roster,packets,
        roster_original_verifier=lambda _f,_r:True,
        pixel_source_verifier=pixel_source_verifier)

def bridge_reviewed_frames(forecast,admission,roster,packets,*,
                           roster_original_verifier=None,
                           pixel_source_verifier=None):
    """Return candidate-stage observations for the existing scorer.

    Both callbacks must independently inspect the original private snapshot,
    rider roster, exact recording bytes, frame crops and numeric rank evidence.
    An OCR candidate is NEVER the same as a proven rider identity. If callbacks
    are absent or the video has no complete two-frame consensus, report UNKNOWN.
    """
    checked_forecast(forecast)
    checked_admission(admission,forecast["race_id"])
    require(type(roster) is list and len(roster) in (7,9) and
            all(_number(x) for x in roster) and
            len(set(roster))==len(roster),
            "EXISTING_PR71_ROSTER_REQUIRED")
    require(type(packets) is list and len(packets)<=300,
            "UNBOUNDED_FRAME_REVIEW")
    receipts=_frame_receipts(admission)
    by_phase={x:[] for x in PHASES}
    seen_sha=set()
    for packet in packets:
        _check_packet(packet,admission,receipts,set(roster))
        require(packet["frame_sha256"] not in seen_sha,
                "FRAME_REUSED_ACROSS_PHASES")
        seen_sha.add(packet["frame_sha256"])
        by_phase[packet["phase"]].append(packet)
    roster_ok=_confirmed(roster_original_verifier,forecast,roster)
    # A PR102 reviewer may have verified scene frames without confirming
    # a rider's car number. The caller's pixel verifier must attest the
    # number and race position specifically, not merely screen appearance.
    access=(admission.get("training_eligible") is True and
            admission.get("admitted_coverage") in (
                "FULL_FOUR_LAPS","PARTIAL_HIGHLIGHTS"))
    observations=[];stages=[];previous_time=-1.0
    for phase,weight in STAGES:
        rows=sorted(by_phase[phase],key=lambda x:x["recording_sec"])
        usable=[]
        if access and roster_ok:
            for packet in rows:
                ref=receipts[(packet["frame_sha256"],packet["review_ref"])]
                if (packet["scene"]=="LIVE" and ref.get("label")!="REPLAY" and
                    _confirmed(pixel_source_verifier,packet,admission,roster)):
                    usable.append(packet)
        pair=None
        for a,first in enumerate(usable):
            for second in usable[a+1:]:
                if 0.01 < second["recording_sec"]-first["recording_sec"]<=6:
                    pair=(first,second)
                    break
            if pair:break
        if pair is None:
            stages.append({"phase":phase,"state":"UNKNOWN",
                           "reason":"NO_TWO_INDEPENDENT_LIVE_FRAMES",
                           "confirmed_position_count":0})
            continue
        ranks=_two_frame_consensus(*pair,set(roster))
        leader=ranks.get(1,UNKNOWN)
        top3=([ranks[1],ranks[2],ranks[3]]
              if all(i in ranks for i in (1,2,3)) else UNKNOWN)
        if leader==UNKNOWN and top3==UNKNOWN:
            stages.append({"phase":phase,"state":"UNKNOWN",
                           "reason":"NO_TWO_FRAME_POSITION_CONSENSUS",
                           "confirmed_position_count":len(ranks)})
            continue
        midpoint=round((pair[0]["recording_sec"]+
                        pair[1]["recording_sec"])/2,3)
        if midpoint<=previous_time:
            stages.append({"phase":phase,"state":"UNKNOWN",
                           "reason":"PHASE_TIME_ORDER_CONFLICT",
                           "confirmed_position_count":len(ranks)})
            continue
        # A race-position rank is not equivalent to 2nd wheel in a LINE.
        # Camera projection cannot reveal actual line continuity/tactics
        # without further independent motion/line annotation.
        measured={
            "leader":leader,"top3":top3,
            "line_groups":UNKNOWN,"second_wheel":UNKNOWN,"attack":UNKNOWN,
        }
        checked_parts(measured)
        observations.append({
            "phase":phase,"recording_sec":midpoint,"scene":"LIVE",
            "frame_sha256":[x["frame_sha256"] for x in pair],
            "review_refs":[x["review_ref"] for x in pair],
            "measured":measured,
        })
        previous_time=midpoint
        stages.append({"phase":phase,"state":"TWO_FRAME_RANK_CANDIDATE",
                       "reason":"LINE_AND_TACTICS_UNVERIFIED",
                       "confirmed_position_count":len(ranks)})
    result={
        "schema":REPORT,"race_id":forecast["race_id"],
        "phase_forecast_sha256":forecast["phase_forecast_sha256"],
        "recording_sha256":admission["recording_sha256"],
        "video_admission_sha256":admission["admission_sha256"],
        "roster_verifier_accepted":roster_ok,
        "pixel_verifier_supplied":callable(pixel_source_verifier),
        "candidate_frames_received":len(packets),
        "phase_observations":observations,
        "stage_status":stages,
        "registered_starter_count":len(roster),
        "no_position_inferred_from_image_coordinates":True,
        "line_or_second_wheel_verified":False,
        "attack_or_success_verified":False,
        "real_rider_recognition_accuracy_established":False,
        "same_race_training_or_forecast_modified":False,
        "research_only_not_formal_evidence":True,
    }
    result["bridge_sha256"]=digest(result)
    return result
