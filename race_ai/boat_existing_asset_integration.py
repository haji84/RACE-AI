"""Reuse PR64 K history and PR71 existing multi-feature models, never retrain.

This adapter is an evidence-gated bridge, NOT a new prediction model.
Default deny: source publication, sample provenance, source-purpose permission
and selected race cutoff need independent checks before real model admission.
Never synthesize missing history, exhibition, motor stats or weather.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
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



def pr64_B_to_PR71_racelist(entries, details, deadlines, *, race_id,
                           source_url, archive_sha256, captured_at):
    """Convert already parsed PR64 real B fields to PR71's racelist shape.

    Records are source-derived candidates. The original B publish time is
    UNKNOWN: first_observed_at is a capture only, never a rights/publication
    certificate. This racelist cannot pass run_pr71_existing_multi_models()
    without an independent original-publication attestation.
    """
    if (not isinstance(race_id,str) or
        re.fullmatch(r"\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])",race_id) is None):
        raise ReuseGateError("noncanonical B race identity")
    if (not isinstance(source_url,str) or not source_url.startswith("https://")
        or not isinstance(archive_sha256,str) or
        re.fullmatch(r"[0-9a-f]{64}",archive_sha256) is None):
        raise ReuseGateError("archive source URL or SHA absent")
    _stamp(captured_at)
    if not isinstance(entries,list) or not isinstance(details,dict) or not isinstance(deadlines,dict):
        raise ReuseGateError("PR64 parsed B collections required")
    cutoff=deadlines.get(race_id)
    if cutoff is None or _stamp(captured_at) >= _stamp(cutoff):
        raise ReuseGateError("target B deadline missing or already elapsed")
    race_rows=[r for r in entries if isinstance(r,dict) and r.get("race_id")==race_id]
    if len(race_rows)!=6:
        raise ReuseGateError("six registered B entrants required")
    boats=[]
    for row in sorted(race_rows,key=lambda x:x["lane"]):
        lane=row.get("lane");pid=row.get("racer_id")
        if (type(lane) is not int or not 1<=lane<=6 or
            not isinstance(pid,str) or re.fullmatch(r"\d{4}",pid) is None):
            raise ReuseGateError("B racer identity invalid")
        d=details.get((race_id,lane))
        if not isinstance(d,dict) or d.get("racer_registration_id")!=pid:
            raise ReuseGateError("B detail identity mismatch")
        motor=d.get("motor_no")
        if type(motor) is not int or not 1<=motor<=999:
            raise ReuseGateError("B motor allocation missing")
        vals={key:d.get(key) for key in
              ("national_win_rate","local_win_rate","motor_top2_rate")}
        for key,value in vals.items():
            maximum=100 if key=="motor_top2_rate" else 10
            if (type(value) not in (int,float) or not math.isfinite(value)
                or not 0<=value<=maximum):
                raise ReuseGateError("B model-input candidate invalid: "+key)
        boats.append({"lane":lane,"racer_registration_id":pid,
                      "motor_no":motor,**vals})
    if {r["lane"] for r in boats}!=set(range(1,7)) or len({r["racer_registration_id"] for r in boats})!=6:
        raise ReuseGateError("B duplicate lane or racer")
    day=race_id[:4]+"-"+race_id[4:6]+"-"+race_id[6:8]
    return {
        "race_id":race_id, "venue":race_id[9:11],"date_jst":day,
        "closed_at":cutoff,"source_url":source_url,
        "first_observed_at":captured_at,
        "source_archive_sha256":archive_sha256,
        "source_original_published_at":None,
        "original_publication_verification":False,
        "source_rights_verified":False,
        "source_use_status":"CANDIDATE_NOT_ADMITTED",
        "boats":boats}


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


def _usable(value, low, high):
    # Check the range before isfinite: huge exact ints must not overflow float.
    return (type(value) in (int, float) and low <= value <= high
            and math.isfinite(value))


def _provenance_gaps(record, label, decision):
    """Document claims only. Missing is a gap; explicit future data is invalid."""
    record = record if isinstance(record, dict) else {}
    gaps = []
    if not isinstance(record.get("source_ref"), str) or not record["source_ref"].strip():
        gaps.append(label + "_SOURCE_REFERENCE_MISSING")
    times = {}
    for key, missing in (("published_at", "ORIGINAL_PUBLISHED_AT_UNKNOWN"),
                         ("captured_at", "CAPTURED_AT_UNKNOWN")):
        if record.get(key) is None:
            gaps.append(label + "_" + missing)
        else:
            times[key] = _stamp(record[key])
            if times[key] > decision:
                raise ReuseGateError(label + " source is after decision")
    if len(times) == 2 and times["published_at"] > times["captured_at"]:
        raise ReuseGateError(label + " publication after capture")
    return gaps


def _history_candidate(record, registration, target_day):
    if (not isinstance(record, dict) or record.get("racer_id") != registration
        or record.get("status") != "CANDIDATE_PENDING_INDEPENDENT_SOURCE_AND_RIGHTS"
        or type(record.get("sample_n")) is not int
        or not MIN_HISTORY <= record["sample_n"] <= MAX_HISTORY):
        return False
    rows = record.get("last_races")
    if not isinstance(rows, list) or len(rows) != record["sample_n"]:
        return False
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {
                "race_id", "race_day", "finish_position", "start_seconds"}):
            return False
        rid, day = row.get("race_id"), row.get("race_day")
        if (not isinstance(rid, str) or re.fullmatch(r"[0-9]{8}-[0-9]{2}-[0-9]{2}", rid) is None
            or rid in seen or day != rid[:4]+"-"+rid[4:6]+"-"+rid[6:8]
            or type(row.get("finish_position")) is not int
            or not 1 <= row["finish_position"] <= 6
            or not _usable(row.get("start_seconds"), 0, 1)):
            return False
        try:
            if not date(2000, 1, 1) <= date.fromisoformat(day) < target_day:
                return False
        except ValueError:
            return False
        seen.add(rid)
    return rows == sorted(rows, key=lambda row:(row["race_day"],row["race_id"]), reverse=True)


def _join_preview(snapshot, racelist, identities, as_of):
    from race_ai.boat_preview_weather_evidence import (
        PreviewGateError, normalize_existing_PR64_beforeinfo,
    )
    if (not isinstance(snapshot, dict) or snapshot.get("race_id") != racelist["race_id"]
        or _stamp(snapshot.get("closed_at")) != _stamp(racelist["closed_at"])):
        raise ReuseGateError("preview race or deadline differs from B")
    if snapshot.get("status") not in ("PENDING", "AVAILABLE"):
        # PR64 PARTIAL is real, but the unchanged normalizer does not accept it.
        raise ReuseGateError("unsupported preview status for existing normalizer")
    captured, decision = _stamp(snapshot.get("captured_at")), _stamp(as_of)
    publication = snapshot.get("upstream_published_at")
    if publication is not None and _stamp(publication) > captured:
        raise ReuseGateError("preview publication after capture")
    if snapshot.get("available_at") is not None:
        available = _stamp(snapshot["available_at"])
        if not captured <= available <= decision:
            raise ReuseGateError("preview availability conflicts with capture/decision")
    # A race-bound PENDING grid has identities but no numeric payload. An
    # unidentified/no-page-data response cannot stand in for that observation.
    rows = (snapshot.get("observed_racers") if snapshot["status"] == "PENDING" else
            snapshot.get("data", {}).get("boats") if isinstance(snapshot.get("data"),dict) else None)
    if (not isinstance(rows,list) or len(rows)!=6 or
        any(not isinstance(row,dict) or type(row.get("lane")) is not int for row in rows) or
        {row["lane"]:row.get("racer_registration_id") for row in rows} != identities):
        raise ReuseGateError("preview lane/registration differs from B")
    try:
        report = normalize_existing_PR64_beforeinfo(snapshot, as_of=as_of)
    except (PreviewGateError, KeyError, TypeError) as exc:
        raise ReuseGateError("invalid preview evidence") from exc
    # The report intentionally drops the timestamp envelope. Carry only the
    # actual capture and optional explicit publication claim; never replace
    # unknown publication with capture or authenticate the claim here.
    evidence = {"captured_at":snapshot.get("captured_at"),
                "source_ref":snapshot.get("source_url"), "published_at":publication}
    exhibition = {lane:{**row["features"], **evidence}
                  for lane,row in report["observed_exhibition_by_lane"].items()}
    return report, exhibition, {**report["observed_weather"], **evidence}


def build_readiness(racelist, histories_by_registration, *,
                    motor_by_number=None, exhibition_by_lane=None,
                    weather=None, as_of=None, preview_snapshot=None):
    """Legacy numeric candidates and evidence gaps; never admission or FULL input.

    Optional raw PR64 beforeinfo joins through the existing normalizer. A
    detached normalized report cannot establish its capture/cutoff envelope.
    """
    if (not isinstance(racelist,dict) or
        not isinstance(racelist.get("boats"),list) or len(racelist["boats"])!=6):
        raise ReuseGateError("six-entrant PR64 B snapshot required")
    decision = _stamp(as_of)
    if decision >= _stamp(racelist.get("closed_at")):
        raise ReuseGateError("forecast must precede scheduled cutoff")
    rid = racelist.get("race_id")
    try:
        target_day = date.fromisoformat(racelist.get("date_jst"))
    except (TypeError, ValueError) as exc:
        raise ReuseGateError("invalid B event date") from exc
    if (not isinstance(rid,str) or re.fullmatch(r"[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])",rid) is None
        or rid[:8] != target_day.strftime("%Y%m%d")
        or _stamp(racelist["closed_at"]).astimezone(timezone(timedelta(hours=9))).date() != target_day):
        raise ReuseGateError("B race and event date mismatch")
    if not isinstance(histories_by_registration, dict):
        raise ReuseGateError("per-racer K history collection required")
    for collection in (motor_by_number, exhibition_by_lane, weather):
        if collection is not None and not isinstance(collection,dict):
            raise ReuseGateError("auxiliary candidate collections must be mappings")
    identities = {}
    for boat in racelist["boats"]:
        if not isinstance(boat,dict):
            raise ReuseGateError("invalid B entrant")
        lane=boat.get("lane")
        pid=boat.get("racer_registration_id")
        if (type(lane) is not int or not 1<=lane<=6 or
            not isinstance(pid,str) or re.fullmatch(r"[0-9]{4}",pid) is None or
            lane in identities or pid in identities.values() or
            type(boat.get("motor_no")) is not int or not 1<=boat["motor_no"]<=999):
            raise ReuseGateError("invalid B identity or lane")
        identities[lane]=pid
    if set(identities)!=set(range(1,7)):
        raise ReuseGateError("missing B lane")
    primary_gaps = _provenance_gaps({"source_ref":racelist.get("source_url"),
        "published_at":racelist.get("source_original_published_at"),
        "captured_at":racelist.get("first_observed_at")}, "B", decision)
    motors=motor_by_number or {}
    exhibitions=exhibition_by_lane or {}
    environment=weather or {}
    preview = None
    if preview_snapshot is not None:
        if exhibition_by_lane is not None or weather is not None:
            raise ReuseGateError("preview and flat exhibition/weather evidence conflict")
        preview,exhibitions,environment = _join_preview(preview_snapshot,racelist,identities,as_of)
    readiness=[]
    for boat in sorted(racelist["boats"],key=lambda r:r["lane"]):
        lane=boat["lane"];pid=identities[lane];motor=boat["motor_no"]
        h=histories_by_registration.get(pid)
        m=motors.get(str(motor))
        e=exhibitions.get(str(lane))
        e = e if isinstance(e,dict) else {}
        m = m if isinstance(m,dict) else {}
        unresolved=[]
        history_ok = _history_candidate(h,pid,target_day)
        display_ok = _usable(e.get("exhibition_time_seconds"),1,20)
        st_ok = _usable(e.get("exhibition_start_seconds"),0,1)
        if not history_ok:
            unresolved.append("K_RECENT_FORM_AND_START_HISTORY_NOT_READY")
        if not _usable(m.get("motor_two_place_rate_percent"),0,100):
            unresolved.append("MOTOR_STAT_WITH_PROVENANCE_NOT_READY")
        if not display_ok or not st_ok:
            unresolved.append("EXHIBITION_TIME_AND_ST_NOT_READY")
        provenance = {label:_provenance_gaps(record,label,decision)
                      for label,record in (("HISTORY",h),("MOTOR",m),("EXHIBITION",e))}
        declared_n = h.get("sample_n") if isinstance(h,dict) else None
        readiness.append({
            "lane":lane, "registration_no":pid,
            "historical_sample_n":declared_n if type(declared_n) is int and 0<=declared_n<=MAX_HISTORY else None,
            "history_numeric_candidate":history_ok,
            "exhibition_display_candidate":display_ok,
            "exhibition_ST_candidate":st_ok,
            "exhibition_temporally_documented":display_ok and st_ok and not provenance["EXHIBITION"],
            "unresolved":unresolved, "provenance_gaps":[gap for gaps in provenance.values() for gap in gaps],
        })
    # Same units/ranges as the unchanged pinned PR71 legacy model. Normalizer
    # source observations (display .01..20) can be outside these legacy ranges.
    weather_ranges=((0,35),(0,200),(-1,1),(0,1))
    missing_weather=[key for key,bounds in zip(REQUIRED_WEATHER,weather_ranges)
                     if not _usable(environment.get(key),*bounds)]
    weather_gaps=_provenance_gaps(environment,"WEATHER",decision)
    # These are structural readiness counts, not independent rights grants.
    return {
        "schema":SCHEMA, "race_id":racelist.get("race_id"),
        "readiness_contract_version":2,
        "evaluated_model_contract":"PR71_LEGACY_BOAT_MULTI_FEATURE_V1",
        "full_pr71_input_readiness_evaluated":False,
        "legacy_multi_model_ids":["boat-comprehensive-v1","boat-scenario-mixture-v1"],
        "model_code_reused_not_reimplemented":True,
        "history_ready_lane_count":sum(x["history_numeric_candidate"] for x in readiness),
        "motor_candidate_lane_count":sum("MOTOR_STAT_WITH_PROVENANCE_NOT_READY" not in x["unresolved"] for x in readiness),
        "exhibition_candidate_lane_count":sum("EXHIBITION_TIME_AND_ST_NOT_READY" not in x["unresolved"] for x in readiness),
        "exhibition_display_candidate_lane_count":sum(x["exhibition_display_candidate"] for x in readiness),
        "exhibition_ST_candidate_lane_count":sum(x["exhibition_ST_candidate"] for x in readiness),
        "temporally_documented_exhibition_lane_count":sum(x["exhibition_temporally_documented"] for x in readiness),
        "source_observed_display_count":preview["observed_display_count"] if preview else None,
        "source_observed_ST_numeric_count":preview["observed_ST_numeric_count"] if preview else None,
        "preview_missing_by_lane":{key:dict(value) for key,value in preview["missing_by_lane"].items()} if preview else {},
        "independently_admitted_candidate_count":0,
        "primary_provenance_gaps":primary_gaps,
        "weather_provenance_gaps":weather_gaps,
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
    if original_published_verified is not True or racelist.get("original_publication_verification") is not True:
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


def explain_existing_PR71_boat_score(snapshot):
    """Read existing PR71 pre-race score components, never infer a new model.

    Same _scores implementation used by run_models; explanation is a
    disclosure of model intermediates, not a cause proven by race results.
    """
    from race_ai.boat_multi_feature_models import validate_snapshot, _scores
    checked = validate_snapshot(snapshot)
    lanes, scenario_shares = _scores(checked)
    if len(lanes) != 6 or {x["lane"] for x in lanes} != set(range(1,7)):
        raise ReuseGateError("existing model rationale missing lane")
    return {"schema":SCHEMA, "scope":"RESEARCH_RATIONALE_ONLY",
            "race_id":checked["race_id"],
            "explanation_source":"PR71_EXISTING_BOAT_MULTI_FEATURE_SCORES",
            "score_components_by_lane":[
                {k:x[k] for k in
                 ("lane","comprehensive","calm_front","attack","rough")}
                for x in lanes],
            "scenario_mixture_weights":scenario_shares,
            "observed_feature_names":sorted(next(iter(checked["entrants"]))["features"]),
            "observed_weather_names":sorted(checked["conditions"]),
            "rationale_is_postrace_causation":False,
            "weights_learned":False,
            "calibration_verified":False}


def run_PR71_existing_all_four_model_families(snapshot, *, source_admission=None):
    """Reuse PR71 four-sport FULL; 75 boat observations are still mandatory.

    Strict validate() fails closed for missing required data; there is no
    synthetic value filling, no second formula, and no formal freeze claim.
    """
    from race_ai.four_sport_model_suite import run_suite
    suite=run_suite(snapshot, allow_source=source_admission)
    expected={"multisport-factor-interaction-v1",
              "multisport-scenario-ensemble-v1",
              "multisport-conditional-duel-v1",
              "multisport-race-trajectory-v1"}
    if set(suite["models"]) != expected or suite.get("official_prediction") is not False:
        raise ReuseGateError("PR71 suite roster or safety contract changed")
    if suite.get("external_timestamp_receipts") is not None:
        raise ReuseGateError("untrusted external receipt present")
    return suite
