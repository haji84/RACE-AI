"""Post-race video evidence -> private PDCA learning candidate.

No post-cutoff facts may enter a pre-cutoff prediction. The real forecast is
immutable; a candidate cannot train itself or authorize an unverified outcome.
"""
from __future__ import annotations
from datetime import datetime
from hashlib import sha256
import json
import math

from .keirin_video_events import REPORT, EvidenceError, valid_sha, canonical

CANDIDATE_SCHEMA="RACE_AI_KEIRIN_VIDEO_POSTRACE_CANDIDATE_V1"

def epoch(value):
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
        if d.utcoffset() is None:raise ValueError()
        return d.timestamp()
    except (AttributeError,ValueError,TypeError):
        raise EvidenceError("INVALID_TIMESTAMP") from None

def create_postrace_learning_candidate(
        audit_report,forecast_original,official_result,
        *, frozen_receipt_verifier=None, official_result_verifier=None,
        rights_checker=None):
    """Requires three OUT-OF-BAND trusted verifier callbacks.

    The callbacks must use independently stored objects/permissions; do NOT
    replace with lambda True in production. No source contents are exported.
    """
    if audit_report.get("schema")!=REPORT or audit_report.get(
            "status")!="FOUR_LAPS_VISUALLY_VERIFIED" or audit_report.get(
            "learning_admission")!="INDEPENDENTLY_VERIFIED_ONLY":
        raise EvidenceError("UNVERIFIED_VIDEO_MUST_NOT_TRAIN")
    before={k:v for k,v in audit_report.items() if k!="audit_sha256"}
    if audit_report.get("audit_sha256")!=sha256(canonical(
            before).encode("utf-8")).hexdigest():
        raise EvidenceError("VIDEO_AUDIT_DIGEST_MISMATCH")
    if any(not callable(f) for f in (frozen_receipt_verifier,
                                    official_result_verifier,rights_checker)):
        raise EvidenceError("INDEPENDENT_ATTESTORS_REQUIRED")
    if type(forecast_original) is not dict or type(official_result) is not dict:
        raise EvidenceError("INVALID_FORECAST_OR_RESULT")
    rid=audit_report["race_id"]
    if forecast_original.get("race_id")!=rid or official_result.get("race_id")!=rid:
        raise EvidenceError("RACE_ID_MISMATCH")
    if not valid_sha(forecast_original.get("original_sha256")):
        raise EvidenceError("MISSING_FROZEN_ORIGINAL_DIGEST")
    cutoff=epoch(forecast_original.get("official_cutoff_at"))
    saved=epoch(forecast_original.get("saved_at"))
    published=epoch(official_result.get("published_at"))
    if not saved<cutoff<published:
        raise EvidenceError("FORECAST_RESULT_TIME_LEAK")
    if frozen_receipt_verifier(forecast_original) is not True:
        raise EvidenceError("FROZEN_ORIGINAL_NOT_INDEPENDENTLY_ATTESTED")
    if official_result_verifier(official_result) is not True:
        raise EvidenceError("OFFICIAL_RESULT_NOT_ATTESTED")
    if rights_checker(audit_report["source"],"private_video_analysis_training") is not True:
        raise EvidenceError("TRAINING_RIGHTS_NOT_ADMITTED")
    order=official_result.get("ordered_top3")
    if not isinstance(order,list) or len(order)!=3 or any(
            type(i) is not int or not 1<=i<=9 for i in order
        ) or len(set(order))!=3:
        raise EvidenceError("INVALID_OFFICIAL_ORDER")
    laps=audit_report.get("evidence")
    if type(laps) is not list or len(laps)!=4 or any(
            x.get("lap")!=i+1 for i,x in enumerate(laps)):
        raise EvidenceError("FOUR_LAP_EVIDENCE_INCOMPLETE")
    stamps=[x["recording_sec"] for x in laps]
    gaps=[round(b-a,4) for a,b in zip(stamps,stamps[1:])]
    if any(x<18 or x>110 for x in gaps):
        raise EvidenceError("IMPLAUSIBLE_LAP_TIMES")
    # This is a post-race training label, NOT a future availability feature.
    candidate={
        "schema":CANDIDATE_SCHEMA,
        "race_id":rid,
        "cutoff_at":forecast_original["official_cutoff_at"],
        "prediction_original_sha256":forecast_original["original_sha256"],
        "prediction_original_untouched":True,
        "video_recording_sha256":audit_report["recording_sha256"],
        "video_audit_sha256":audit_report["audit_sha256"],
        "lap_pass_seconds":stamps,
        "lap_intervals_seconds":gaps,
        "official_ordered_top3":order,
        "official_result_published_at":official_result["published_at"],
        "feature_availability":"POST_RACE_ONLY",
        "future_prediction_feature":False,
        "used_for_same_race_forecast":False,
        "training_status":"PRIVATE_CANDIDATE_NOT_FITTED",
        "independently_admitted":True,
    }
    candidate["candidate_sha256"]=sha256(canonical(
        candidate).encode("utf-8")).hexdigest()
    return candidate
