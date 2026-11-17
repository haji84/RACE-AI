"""Admit independently evidenced tactical follow outcomes to existing C history.

A finished 3-ren-tan, racecard line prediction, outfit color or one screenshot
cannot establish HELD/GAPPED/SWITCHED. Evidence must bind real video source
SHA, ordered observations, roster IDs and two independent signed reviews.
All verification callbacks must be implemented by the trusted private runner.
Synthetic callbacks in tests provide NO independent real-world attestation.
No provider GET, production model update, plaintext public export or wager.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re

from . import keirin_line_cohesion as history
from . import keirin_round_motivation as stage
from . import keirin_round_six_phase_rank as six

PACKET_SCHEMA = "RACE_AI_KEIRIN_OBSERVED_FOLLOW_TWO_REVIEW_V1"
SUMMARY_SCHEMA = "RACE_AI_KEIRIN_OBSERVED_FOLLOW_ADMISSION_V1"
SHA = re.compile(r"^[a-f0-9]{64}$")
RELATIONS = frozenset(("FOLLOWING", "GAP_VISIBLE", "SWITCH_VISIBLE", "UNKNOWN"))
PHASES = frozenset(six.PHASES)


class FollowAdmissionError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise FollowAdmissionError(reason)


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def valid_sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def when(value):
    try:
        return stage._timestamp(value)
    except (stage.RoundError, TypeError, ValueError):
        raise FollowAdmissionError("AWARE_SOURCE_OR_REVIEW_TIMESTAMP_REQUIRED") from None


def checked_packet(packet):
    """Shape and coherence only. Does not certify people or pixels."""
    keys = {"schema", "race_id", "source_video_sha256", "event_ended_at",
            "source_published_at", "available_at", "leader_athlete_id",
            "follower_athlete_id", "leader_car", "follower_car",
            "role", "competition", "round_stage", "leader_tactic",
            "phase", "outcome", "observed_frames", "reviews"}
    require(type(packet) is dict and set(packet) == keys and
            packet.get("schema") == PACKET_SCHEMA,
            "TACTICAL_FOLLOW_PACKET_SCHEMA_REQUIRED")
    rid=packet["race_id"]
    require(type(rid) is str and history.RACE_ID.fullmatch(rid) and
            valid_sha(packet["source_video_sha256"]),
            "HISTORICAL_RACE_AND_VIDEO_SHA_REQUIRED")
    lead=packet["leader_athlete_id"]
    follow=packet["follower_athlete_id"]
    require(type(lead) is str and type(follow) is str and
            history.ATHLETE.fullmatch(lead) and history.ATHLETE.fullmatch(follow)
            and lead != follow,
            "PERSISTENT_DISTINCT_RIDER_REGISTRATION_IDS_REQUIRED")
    lc,fc=packet["leader_car"],packet["follower_car"]
    require(type(lc) is int and type(fc) is int and
            lc != fc and 1 <= lc <= 9 and 1 <= fc <= 9 and
            packet["role"] in history.ROLES and
            packet["competition"] in stage.CLASS and
            packet["round_stage"] in stage.ROUND and
            packet["leader_tactic"] in history.TACTICS and
            packet["phase"] in PHASES and
            packet["outcome"] in history.LABEL_OUTCOMES,
            "FOLLOW_RIDER_ROLE_PHASE_OR_TACTIC_INVALID")
    event,publication,available=map(
        when,(packet["event_ended_at"],packet["source_published_at"],
              packet["available_at"]))
    require(event<=publication<=available,
            "FUTURE_HISTORY_LABEL_OR_PRE_EVENT_PUBLICATION")
    frames=packet["observed_frames"]
    require(type(frames) is list and 3<=len(frames)<=120,
            "MULTIFRAME_REAL_TACTICAL_OBSERVATIONS_REQUIRED")
    last=-1.0
    frame_hashes=[]
    relations=[]
    for f in frames:
        require(type(f) is dict and set(f)=={
            "frame_sha256","video_second","phase","leader_car",
            "follower_car","relative_relation"},
            "TACTICAL_FRAME_PROVENANCE_SCHEMA")
        t=f["video_second"]
        require(valid_sha(f["frame_sha256"]) and type(t) in (int,float) and
                0<=t<=3600 and t>last and
                f["phase"]==packet["phase"] and
                f["leader_car"]==lc and f["follower_car"]==fc and
                f["relative_relation"] in RELATIONS,
                "TACTICAL_FRAME_TIME_PHASE_ID_OR_RELATION_INVALID")
        last=t
        frame_hashes.append(f["frame_sha256"])
        relations.append(f["relative_relation"])
    require(len(set(frame_hashes))==len(frame_hashes) and
            frames[-1]["video_second"]-frames[0]["video_second"]>=2,
            "TACTICAL_OBSERVATIONS_REUSED_OR_INSUFFICIENT_SPAN")
    outcome=packet["outcome"]
    # Explicit, image-backed labels: do not turn final result or same-colored
    # pixels into uninterrupted follow proof.
    if outcome=="HELD":
        require(all(x=="FOLLOWING" for x in relations),
                "HELD_REQUIRES_OBSERVED_CONTINUOUS_FOLLOWING")
    elif outcome=="GAPPED":
        require("GAP_VISIBLE" in relations,
                "GAPPED_REQUIRES_VISIBLE_GAP_NOT_FINISH_POSITION")
    elif outcome=="SWITCHED":
        require("SWITCH_VISIBLE" in relations,
                "SWITCH_REQUIRES_VISIBLE_TACTICAL_SWITCH")
    else:
        require(outcome=="UNKNOWN",
                "TACTICAL_OUTCOME_UNRECOGNIZED")
    reviews=packet["reviews"]
    require(type(reviews) is list and len(reviews)==2,
            "TWO_DISTINCT_SIGNED_REVIEW_DOCUMENTS_REQUIRED")
    reviewer_ids=set()
    receipt_shas=set()
    for review in reviews:
        require(type(review) is dict and set(review)=={
            "reviewer_id","reviewed_at","signed_review_receipt_sha256",
            "source_video_sha256","frame_sha256s","outcome"},
            "TACTICAL_REVIEW_SCHEMA_INVALID")
        rid0=review["reviewer_id"]
        require(type(rid0) is str and re.fullmatch(r"[A-Za-z0-9_.-]{5,80}",rid0)
                and valid_sha(review["signed_review_receipt_sha256"]) and
                review["source_video_sha256"]==packet["source_video_sha256"] and
                review["frame_sha256s"]==frame_hashes and
                review["outcome"]==outcome and
                event<=when(review["reviewed_at"])<=available,
                "TACTICAL_REVIEW_NOT_SOURCE_BOUND_OR_NOT_CONSENSUS")
        reviewer_ids.add(rid0)
        receipt_shas.add(review["signed_review_receipt_sha256"])
    require(len(reviewer_ids)==2 and len(receipt_shas)==2,
            "TWO_EXTERNALLY_DISTINCT_SIGNED_REVIEWS_REQUIRED")
    return packet


def _externally_verified(callback,packet):
    if not callable(callback):
        return False
    try:
        return callback(packet) is True
    except Exception:
        return False


def admit_for_C(*, packet, verify_owner_source_video=None,
                verify_roster_id_mapping=None,
                verify_independent_signed_reviewers=None):
    """Create an eligible *research history* row, never silently certify itself.

    The callbacks must validate source-video bytes and capture attestation,
    race roster registration IDs, and separate actual reviewers/signatures.
    Returns an existing history.make_label row plus redacted receipt.
    """
    checked_packet(packet)
    require(_externally_verified(verify_owner_source_video,packet),
            "OWNER_PRIVATE_VIDEO_SOURCE_NOT_INDEPENDENTLY_READ_BACK")
    require(_externally_verified(verify_roster_id_mapping,packet),
            "RIDER_AND_CAR_IDENTITY_NOT_INDEPENDENTLY_ATTESTED")
    require(_externally_verified(verify_independent_signed_reviewers,packet),
            "TWO_REVIEWER_SIGNATURES_NOT_EXTERNALLY_ATTESTED")
    raw_review_sha=digest({
        "schema":PACKET_SCHEMA,
        "video_sha256":packet["source_video_sha256"],
        "race_id":packet["race_id"],
        "frames":packet["observed_frames"],
        "reviews":packet["reviews"]})
    row=history.make_label(
        race_id=packet["race_id"],
        event_ended_at=packet["event_ended_at"],
        source_published_at=packet["source_published_at"],
        available_at=packet["available_at"],
        source_sha256=packet["source_video_sha256"],
        review_receipt_sha256=raw_review_sha,
        leader_athlete_id=packet["leader_athlete_id"],
        follower_athlete_id=packet["follower_athlete_id"],
        role=packet["role"],competition=packet["competition"],
        round_stage=packet["round_stage"],leader_tactic=packet["leader_tactic"],
        outcome=packet["outcome"])
    return {
        "schema":SUMMARY_SCHEMA,
        "race_id":packet["race_id"],
        "private_historical_label":row,
        "admitted_history_label_sha256":row["label_sha256"],
        "review_consensus_sha256":raw_review_sha,
        "source_video_sha256":packet["source_video_sha256"],
        "usable_only_if_available_before_target_as_of":True,
        "production_model_promoted":False,
        "original_PR71_weights_changed":False,
        "signed_review_independence_must_be_externally_verified":True,
    }
