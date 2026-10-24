"""Reuse PR64 K history and PR71 existing multi-feature models, never retrain.

This adapter is an evidence-gated bridge, NOT a new prediction model.
Default deny: source publication, sample provenance, source-purpose permission
and selected race cutoff need independent checks before real model admission.
Never synthesize missing history, exhibition, motor stats or weather.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
import re

SCHEMA = "RACE_AI_PR64_PR71_BOAT_REUSE_BRIDGE_V1"
MIN_HISTORY = 5
MAX_HISTORY = 30
REQUIRED_EXHIBITION = ("exhibition_time_seconds", "exhibition_start_seconds")
REQUIRED_WEATHER = ("wind_speed_mps", "wave_height_cm",
                    "wind_relative_to_course", "wet_surface_factor")


class ReuseGateError(ValueError):
    pass


def _stamp(x):
    if not isinstance(x, str):
        raise ReuseGateError("independently timestamped source required")
    try:
        d = datetime.fromisoformat(x.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReuseGateError("invalid source timestamp") from exc
    if d.utcoffset() is None:
        raise ReuseGateError("timestamp must carry timezone")
    return d


def _exact_datetime(d, cutoff):
    return _stamp(d) <= _stamp(cutoff)


def _source_sha(record):
    sha = record.get("sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        raise ReuseGateError("K source digest missing")
    return sha


def pr64_history_candidates(rows, *, racer_id, day, as_of):
    """Convert already imported K rows, never make a fake recent-five series.

    rows come from PR64's as-of latest-revision starts queries. Every row
    must carry original sha, published_at and captured_at. Invalid F/L,
    ambiguous/disqualified finish or absent ST is EXCLUDED from numeric
    multi-feature scoring, not turned into zero.
    """
    try:
        target_day = date.fromisoformat(day)
    except (ValueError, TypeError) as exc:
        raise ReuseGateError("invalid target day") from exc
    if not isinstance(racer_id, str) or re.fullmatch(r"\d{4}", racer_id) is None:
        raise ReuseGateError("four-digit racer ID required")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ReuseGateError("bounded K row list required")
    seen = set()
    valid = []
    excluded = {"after_as_of":0, "target_day_or_future":0,
                "invalid_finish_or_ST":0, "wrong_racer":0}
    for row in rows:
        if not isinstance(row, dict):
            raise ReuseGateError("invalid K row object")
        rid = row.get("race_id")
        if not isinstance(rid, str) or re.fullmatch(r"\d{8}-\d{2}-\d{2}", rid) is None:
            raise ReuseGateError("stable K race identity required")
        lane = row.get("lane")
        if type(lane) is not int or not 1 <= lane <= 6:
            raise ReuseGateError("invalid K lane")
        identity=(rid,lane)
        if identity in seen:
            raise ReuseGateError("PR64 K latest-revision query must deduplicate")
        seen.add(identity)
        digest = _source_sha(row)
        published = row.get("published_at")
        captured = row.get("captured_at")
        if published is None or captured is None:
            # Never replace missing original publication time with capture.
            excluded["after_as_of"] += 1
            continue
        if not _exact_datetime(published,as_of) or not _exact_datetime(captured,as_of):
            excluded["after_as_of"] += 1
            continue
        if _stamp(published) > _stamp(captured):
            raise ReuseGateError("claimed source published after capture")
        if date.fromisoformat(rid[:4]+"-"+rid[4:6]+"-"+rid[6:8]) >= target_day:
            excluded["target_day_or_future"] += 1
            continue
        if row.get("racer_id") != racer_id:
            excluded["wrong_racer"] += 1
            continue
        st=row.get("st")
        finish=row.get("finish")
        if (row.get("st_status") != "OK" or
            type(st) not in (int, float) or not math.isfinite(st) or not 0 <= st <= 1 or
            type(finish) is not int or not 1 <= finish <= 6):
            excluded["invalid_finish_or_ST"] += 1
            continue
        valid.append({
            "race_id":rid, "race_day":rid[:4]+"-"+rid[4:6]+"-"+rid[6:8],
            "finish_position":finish, "start_seconds":float(st),
            "sha":digest, "published_at":published, "captured_at":captured
        })
    valid.sort(key=lambda x:(x["race_day"],x["race_id"]),reverse=True)
    latest=valid[:MAX_HISTORY]
    # None of these timestamps, nor source purpose grants, have been
    # independently verified merely by this structural conversion.
    lineage = sorted(set(x["sha"] for x in latest))
    source_ref = ("k-archive-bundle-sha256:"+
                  hashlib.sha256(json.dumps(lineage,separators=(",",":")).encode()).hexdigest()
                  if latest else None)
    out={
        "racer_id":racer_id,
        "schema":SCHEMA,
        "sample_n":len(latest),
        "history_source_hashes":lineage,
        "source_ref":source_ref,
        "published_at":max((x["published_at"] for x in latest),key=_stamp,default=None),
        "captured_at":max((x["captured_at"] for x in latest),key=_stamp,default=None),
        "last_races":[{key:x[key] for key in
                      ("race_id","race_day","finish_position","start_seconds")}
                      for x in latest],
        "excluded_counts":excluded,
        "approved_for_model":False,
        "status":"CANDIDATE_PENDING_INDEPENDENT_SOURCE_AND_RIGHTS"
                 if len(latest)>=MIN_HISTORY else "INSUFFICIENT_VERIFIED_K_HISTORY"
    }
    return out



def from_pr64_imported_K(db, *, racer_id, day, as_of):
    """Reuse PR64's existing revision-aware DB reader, not a second K parser.

    Imported provenance remains UNVERIFIED even when K rows parse correctly.
    This function does not grant rights or fabricate provider publication.
    """
    try:
        from race_ai.core import _asof_rows, SourceError
    except ImportError as exc:
        raise ReuseGateError("pinned PR64 core checkout required") from exc
    rows = [dict(row) for row in _asof_rows(db, as_of, racer_id)]
    if len(rows) > 10000:
        raise ReuseGateError("too many imported K records")
    for row in rows:
        digest = _source_sha(row)
        metadata = db.execute(
            "SELECT kind, published_at, captured_at, verified_official "
            "FROM provenance WHERE sha=?", (digest,)
        ).fetchone()
        if (metadata is None or metadata["kind"] != "K"
            or metadata["published_at"] != row["published_at"]
            or metadata["captured_at"] != row["captured_at"]):
            raise ReuseGateError("K row and source provenance mismatch")
        # verified_official in PR64 is a structural storage field, not a
        # signed independent provider/rights certificate.
    report = pr64_history_candidates(rows, racer_id=racer_id, day=day, as_of=as_of)
    report["source_provenance_metadata_checked"] = True
    report["independent_official_publisher_attestation"] = False
    report["source_analysis_rights_granted_by_bridge"] = False
    return report


def build_readiness(racelist, histories_by_registration, *,
                    motor_by_number=None, exhibition_by_lane=None,
                    weather=None, as_of=None):
    """Feature-level audit only; no forecast and no fake defaults."""
    if (not isinstance(racelist,dict) or
        not isinstance(racelist.get("boats"),list) or len(racelist["boats"])!=6):
        raise ReuseGateError("six-entrant PR64 B snapshot required")
    if as_of is None or not _exact_datetime(as_of,racelist.get("closed_at")):
        raise ReuseGateError("as_of after or missing scheduled cutoff")
    if _stamp(as_of)>=_stamp(racelist["closed_at"]):
        raise ReuseGateError("forecast must precede scheduled cutoff")
    if not isinstance(histories_by_registration, dict):
        raise ReuseGateError("per-racer K history collection required")
    motors=motor_by_number if isinstance(motor_by_number,dict) else {}
    exhibitions=exhibition_by_lane if isinstance(exhibition_by_lane,dict) else {}
    environment=weather if isinstance(weather,dict) else {}
    readiness=[]
    reg_seen=set()
    for boat in sorted(racelist["boats"],key=lambda r:r["lane"]):
        lane=boat.get("lane")
        pid=str(boat.get("racer_registration_id"))
        motor=boat.get("motor_no")
        if (type(lane) is not int or not 1<=lane<=6 or
            re.fullmatch(r"\d{4}",pid) is None or pid in reg_seen):
            raise ReuseGateError("invalid B identity or lane")
        reg_seen.add(pid)
        h=histories_by_registration.get(pid)
        m=motors.get(str(motor))
        e=exhibitions.get(str(lane))
        unresolved=[]
        if (not isinstance(h,dict) or h.get("sample_n",0)<MIN_HISTORY or
            h.get("status")!="CANDIDATE_PENDING_INDEPENDENT_SOURCE_AND_RIGHTS"):
            unresolved.append("K_RECENT_FORM_AND_START_HISTORY_NOT_READY")
        if not isinstance(m,dict) or "motor_two_place_rate_percent" not in m:
            unresolved.append("MOTOR_STAT_WITH_PROVENANCE_NOT_READY")
        if not isinstance(e,dict) or any(k not in e for k in REQUIRED_EXHIBITION):
            unresolved.append("EXHIBITION_TIME_AND_ST_NOT_READY")
        readiness.append({
            "lane":lane, "registration_no":pid,
            "historical_sample_n":h.get("sample_n",0) if isinstance(h,dict) else 0,
            "unresolved":unresolved,
        })
    if set(b["lane"] for b in racelist["boats"])!=set(range(1,7)):
        raise ReuseGateError("missing B lane")
    missing_weather=[key for key in REQUIRED_WEATHER if key not in environment]
    # These are structural readiness counts, not independent rights grants.
    return {
        "schema":SCHEMA, "race_id":racelist.get("race_id"),
        "legacy_multi_model_ids":["boat-comprehensive-v1","boat-scenario-mixture-v1"],
        "model_code_reused_not_reimplemented":True,
        "history_ready_lane_count":sum(x["historical_sample_n"]>=MIN_HISTORY for x in readiness),
        "motor_candidate_lane_count":sum("MOTOR_STAT_WITH_PROVENANCE_NOT_READY" not in x["unresolved"] for x in readiness),
        "exhibition_candidate_lane_count":sum("EXHIBITION_TIME_AND_ST_NOT_READY" not in x["unresolved"] for x in readiness),
        "missing_weather_keys":missing_weather,
        "lane_gaps":readiness,
        "official_source_publication_independently_verified":False,
        "rights_for_model_analysis_admitted":False,
        "original_time_attestation_proven":False,
        "forecast_executed":False,
        "official_prediction":False,
        "status":"BLOCKED_INTEGRATION_SOURCE_GATES",
    }


def run_pr71_existing_multi_models(racelist, auxiliary, *,
                                   source_admission=None,
                                   original_published_verified=False):
    """Delegates directly to PR71 existing adapter+models; no new algorithm.

    Caller must separately establish that PR71's legacy 'first_observed_at'
    is the *actual* provider publication time. It currently uses that as
    'published_at', which is not generally justified for real sources.
    """
    if original_published_verified is not True:
        raise ReuseGateError("PR71 racelist original publication timestamp not verified")
    if not callable(source_admission):
        raise ReuseGateError("independent source-purpose rights verifier required")
    from race_ai.boat_feature_adapter import from_approved_features
    from race_ai.boat_multi_feature_models import run_models
    snapshot = from_approved_features(racelist,auxiliary,admit_source=source_admission)
    models=run_models(snapshot)
    if set(models)!={"boat-comprehensive-v1","boat-scenario-mixture-v1"}:
        raise ReuseGateError("existing model roster changed")
    if any(result.get("official_prediction") is not False or
           result.get("persistence_receipt") is not None for result in models.values()):
        raise ReuseGateError("existing model improperly asserted official proof")
    return {"schema":SCHEMA, "scope":"RESEARCH_NOT_FORMAL_FREEZE",
            "model_ids":list(models), "snapshot":snapshot, "models":models,
            "formal_hit_at_8_eligible":False}
