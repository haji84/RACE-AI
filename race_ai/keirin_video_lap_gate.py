"""Fail-closed, broadcast-agnostic race-video coverage and lap-evidence gates.

All timestamps timezone-aware. Never infer four actual laps from a screen
recording's length, a model forecast, odds, or a synthetic cue alone.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
import re
from urllib.parse import urlparse

PLAN_SCHEMA = "RACE_AI_KEIRIN_LIVE_SCREEN_CAPTURE_PLAN_V1"
VISUAL_SCHEMA = "RACE_AI_KEIRIN_VIDEO_VISUAL_EVIDENCE_V1"
GATE_SCHEMA = "RACE_AI_KEIRIN_FOUR_LAP_GATE_V1"
SOURCE = "https://www.winticket.jp/keirin/matsuyama/live"
REQUIRED_PLAN = {
    "schema", "race_id", "venue", "race_number", "race_start_at",
    "record_from_at", "record_until_at", "expected_laps", "source_url",
    "schedule_evidence_ref", "recording_rights_ref"
}


class VideoGateError(ValueError):
    pass


def timestamp(value):
    if not isinstance(value, str):
        raise VideoGateError("TIME_VALUE_REQUIRED")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VideoGateError("INVALID_TIMESTAMP") from exc
    if dt.utcoffset() is None:
        raise VideoGateError("TIMEZONE_REQUIRED")
    return dt


def validate_plan(plan, *, synthetic=False):
    if not isinstance(plan, dict) or set(plan) != REQUIRED_PLAN:
        raise VideoGateError("CAPTURE_PLAN_SCHEMA_MISMATCH")
    if plan["schema"] != PLAN_SCHEMA:
        raise VideoGateError("CAPTURE_PLAN_VERSION")
    if plan["venue"] != "matsuyama" or (
        not isinstance(plan["race_number"], int) or
        isinstance(plan["race_number"], bool) or
        not 1 <= plan["race_number"] <= 12
    ):
        raise VideoGateError("RACE_SELECTOR_INVALID")
    if plan["expected_laps"] != 4:
        raise VideoGateError("FOUR_LAPS_REQUIRED")
    if not isinstance(plan["race_id"], str) or (
        not re.fullmatch(r"\d{8}-matsuyama-\d{2}", plan["race_id"])
    ):
        raise VideoGateError("RACE_ID_INVALID")
    n = int(plan["race_id"][-2:])
    if n != plan["race_number"]:
        raise VideoGateError("RACE_ID_NUMBER_MISMATCH")
    if plan["source_url"] != SOURCE:
        raise VideoGateError("SOURCE_NOT_ALLOWLISTED")
    if not isinstance(plan["schedule_evidence_ref"], str) or len(
        plan["schedule_evidence_ref"]
    ) < 8:
        raise VideoGateError("UNVERIFIED_SCHEDULE")
    rights = plan["recording_rights_ref"]
    if not synthetic and (
        not isinstance(rights, str) or len(rights) < 12
    ):
        raise VideoGateError("RECORDING_RIGHTS_UNVERIFIED")
    start, begin, end = (
        timestamp(plan[k]) for k in (
            "race_start_at", "record_from_at", "record_until_at"
        )
    )
    # Race date is always JST, including when the timestamp is written in UTC.
    from datetime import timezone
    jst = timezone(timedelta(hours=9))
    if plan["race_id"][:8] != start.astimezone(jst).strftime("%Y%m%d"):
        raise VideoGateError("RACE_JST_DATE_MISMATCH")
    pre = (start - begin).total_seconds()
    post = (end - start).total_seconds()
    if not 90 <= pre <= 600 or not 300 <= post <= 960 or (
        end-begin
    ).total_seconds() > 1200:
        raise VideoGateError("CAPTURE_WINDOW_UNSAFE_OR_INCOMPLETE")
    return {
        "race_id":plan["race_id"], "race_number":n,
        "start":start, "begin":begin, "end":end,
        "source":SOURCE, "pre_seconds":pre, "post_seconds":post,
        "synthetic":bool(synthetic)
    }


def coverage_gate(plan, runtime, *, synthetic=False):
    """Check delivery start/end, player health and continuity. No lap claim."""
    validated=validate_plan(plan, synthetic=synthetic)
    if not isinstance(runtime,dict):
        return {"status":"MISSING_RUNTIME", "capture_window_complete":False}
    try:
        begin=timestamp(runtime["recording_started_at"])
        end=timestamp(runtime["recording_ended_at"])
    except (KeyError,VideoGateError):
        return {"status":"MISSING_OR_INVALID_CAPTURE_TIMES",
                "capture_window_complete":False}
    if begin > validated["begin"] + timedelta(seconds=3):
        return {"status":"STARTED_TOO_LATE","capture_window_complete":False}
    if end < validated["end"] - timedelta(seconds=3):
        return {"status":"STOPPED_TOO_EARLY","capture_window_complete":False}
    if end <= begin:
        return {"status":"RECORDING_DURATION_INVALID",
                "capture_window_complete":False}
    samples=runtime.get("media_samples",[])
    if not isinstance(samples,list) or len(samples)<4:
        return {"status":"INSUFFICIENT_PLAYER_SAMPLES",
                "capture_window_complete":False}
    previous_at=None
    previous_media=None
    for sample in samples:
        if not isinstance(sample,dict) or set(sample)!={
            "observed_at", "media_time", "ready_state", "paused",
            "video_width", "video_height","media_error"
        }:
            return {"status":"INVALID_MEDIA_SAMPLE", "capture_window_complete":False}
        try:
            at=timestamp(sample["observed_at"])
            media=float(sample["media_time"])
            ready=sample["ready_state"]
            width=sample["video_width"]
            height=sample["video_height"]
        except (TypeError,ValueError,VideoGateError):
            return {"status":"INVALID_MEDIA_SAMPLE","capture_window_complete":False}
        if not math.isfinite(media) or media<0 or (
            not isinstance(ready,int) or isinstance(ready,bool)
        ) or not isinstance(width,int) or not isinstance(height,int):
            return {"status":"INVALID_MEDIA_SAMPLE","capture_window_complete":False}
        if sample["media_error"] is not None or (
            sample["paused"] is not False or ready < 2 or
            width < 160 or height < 120
        ):
            return {"status":"PLAYER_UNHEALTHY","capture_window_complete":False}
        if previous_at is not None:
            delta=(at-previous_at).total_seconds()
            if not 0.1<delta<=12.0:
                return {"status":"HEARTBEAT_GAP","capture_window_complete":False}
            if not 0.05<=media-previous_media<=delta+8:
                return {"status":"PLAYER_STALLED_OR_SEEKED","capture_window_complete":False}
        previous_at,previous_media=at,media
    if timestamp(samples[0]["observed_at"]) > begin+timedelta(seconds=15) or (
        end-timestamp(samples[-1]["observed_at"])
    ).total_seconds() > 15:
        return {"status":"COVERAGE_EDGE_UNOBSERVED","capture_window_complete":False}
    if runtime.get("video_container_ok") is not True:
        return {"status":"RECORDING_FILE_INVALID",
                "capture_window_complete":False}
    return {
        "status":"CAPTURE_WINDOW_HEALTHY",
        "capture_window_complete":True,
        "four_laps_verified":False
    }


def lap_visual_gate(capture_result, evidence, *, synthetic=False):
    """Accept independent visual timestamp/frame observations ONLY.

    The observation/recognition engine must be independently validated on real
    race footage. This verifier does not label frames itself.
    """
    result={"schema":GATE_SCHEMA,"capture_window_complete":False,
            "four_laps_verified":False,
            "cause_of_finish":"UNDETERMINED","status":"NOT_EVALUATED"}
    if not isinstance(capture_result,dict) or (
        capture_result.get("capture_window_complete") is not True
    ):
        result["status"]="CAPTURE_WINDOW_NOT_VERIFIED"
        return result
    result["capture_window_complete"]=True
    if not isinstance(evidence,dict) or evidence.get("schema")!=VISUAL_SCHEMA:
        result["status"]="VISUAL_EVIDENCE_NOT_AVAILABLE"
        return result
    if evidence.get("synthetic_only") is True or synthetic is True:
        result["status"]="SYNTHETIC_VISUAL_EVIDENCE_ONLY"
        return result
    if evidence.get("source") != "INDEPENDENT_VERIFIED_VISION" or (
        evidence.get("validator_version") is None
    ):
        result["status"]="INDEPENDENT_VISION_NOT_VERIFIED"
        return result
    observations=evidence.get("observations")
    if not isinstance(observations,list):
        result["status"]="VISUAL_OBSERVATIONS_MISSING"
        return result
    expected=["race_start","lap4","lap3","lap2","lap1","finish"]
    # Actual labels are determined from frames, never inserted from race
    # result, odds or pre-race model assumptions.
    labels=[o.get("event") for o in observations if isinstance(o,dict)]
    if labels!=expected:
        result["status"]="FOUR_LAP_VISUAL_SEQUENCE_MISSING"
        return result
    last=-1.0
    for o in observations:
        t=o.get("recording_sec")
        confidence=o.get("confidence")
        frame=o.get("frame_sha256")
        if type(t) not in (int,float) or not math.isfinite(t) or t<=last or (
            type(confidence) not in (float,int) or confidence<0.9 or
            confidence>1 or not isinstance(frame,str) or
            not re.fullmatch(r"[0-9a-f]{64}",frame)
        ):
            result["status"]="VISUAL_FRAME_PROOF_INVALID"
            return result
        last=t
    # Even with observations, independent visual model verification and
    # actual footage provenance are external obligations.
    if evidence.get("real_capture_sha256") is None or (
        evidence.get("identity_attested") is not True
    ):
        result["status"]="RACE_VIDEO_IDENTITY_NOT_VERIFIED"
        return result
    result["status"]="FOUR_LAPS_VISUALLY_EVIDENCED"
    result["four_laps_verified"]=True
    return result
