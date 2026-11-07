"""Observed-only adapters to the existing BOAT native model families.

Pure conversion: no collection, source grants, fitting during prediction, or
storage. Sparse schemas retain unavailable observations and source publication
times as unavailable. Fixed normalizations below are documented engineering
transforms, never fitted weights or measured probabilities.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re

from .actions_contract import digest, stamp
from .comprehensive_four_sport_models import (
    COMMON_REQUIRED, SPORT_REQUIRED, SPORT_OPTIONAL, ENV_COMMON, ENV_SPORT,
    SCHEMA_SPARSE, RESEARCH,
)
from .boat_multi_feature_models import FEATURE_RANGES, CONDITIONS
from .observed_p1_connection import RIGHTS, locator

SCHEMA = "RACE_AI_BOAT_ALL_NATIVE_INPUTS_V1"
FEATURES = set(COMMON_REQUIRED + SPORT_REQUIRED["boat"] + SPORT_OPTIONAL["boat"])
ENVIRONMENT = set(ENV_COMMON + ENV_SPORT["boat"])
RACE_ID = re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")


def _need(ok, reason):
    if not ok:
        raise ValueError("BOAT_NATIVE_" + reason)


def _time(value):
    if isinstance(value, datetime):
        _need(value.utcoffset() is not None, "AWARE_CLOCK_REQUIRED")
        return value
    return stamp(value)


def _finite(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _value(row, *keys):
    return next((row[k] for k in keys if row.get(k) is not None), None)


def _source(record, kind, rid, asof):
    inner = record.get("source") if isinstance(record.get("source"), dict) else record
    url = inner.get("source_url")
    locator(url, kind, rid)
    sha = _value(inner, "source_sha256", "sha256")
    at = _value(inner, "captured_at", "first_observed_at")
    published = _value(inner, "published_at", "upstream_published_at")
    _need(isinstance(sha, str) and re.fullmatch("[0-9a-f]{64}", sha), "SOURCE_HASH_REQUIRED")
    _need(_time(at) <= asof and (published is None or _time(published) <= _time(at)), "SOURCE_AFTER_AS_OF")
    return dict(source_ref=url, source_rights_ref=RIGHTS, source_sha256=sha,
                captured_at=at, published_at=published)


def _observation(value, source, transform, sample_n=None):
    return dict(value=value, published_at=source["published_at"], captured_at=source["captured_at"],
                source_ref=source["source_ref"], source_rights_ref=source["source_rights_ref"],
                source_sha256=source["source_sha256"], sample_n=sample_n, transform_id=transform)


def _composite(sources, namespace):
    manifest = sorted((deepcopy(s) for s in sources), key=lambda s: (s["source_ref"], s["source_sha256"], s["captured_at"]))
    sha = digest(manifest)
    return dict(source_ref="urn:race-ai:" + namespace + ":" + sha, source_rights_ref=RIGHTS,
                source_sha256=sha, published_at=None,
                captured_at=max((s["captured_at"] for s in sources), key=_time), source_members=manifest)


def _shared_race(rid, cutoff, asof, *, distance=None, kind="", revision=1):
    day, venue, number = rid.split("-")
    return dict(race_id=rid, sport="boat", venue="boatrace-jcd-" + venue,
                event_date_jst=day[:4]+"-"+day[4:6]+"-"+day[6:], sales_cutoff_at=cutoff,
                as_of=asof, distance_m=distance, surface="water", race_kind=kind, race_revision=revision)


def _snapshot(race, participants, environment, scope=RESEARCH):
    return dict(schema=SCHEMA_SPARSE, scope=scope, race=race, participants=participants,
                environment=environment,
                environment_missing={k: "NOT_AVAILABLE" for k in sorted(ENVIRONMENT - environment.keys())})


def _participant(lane, registration, features, missing=None):
    absent = {k: "NOT_AVAILABLE" for k in sorted(FEATURES - features.keys())}
    absent.update({k: v for k, v in (missing or {}).items() if k in absent})
    return dict(number=lane, identity=registration, draw=lane, style="unknown", group_id=None,
                features=features, missing=absent)


def _history_store(context):
    if isinstance(context, dict):
        return context.get("history_store")
    return context if context is not None and hasattr(context, "racer_profile") else None


def _historical_inputs(context, racers, asof):
    store = _history_store(context)
    if store is None:
        return {}, [], []
    days = store.visible_days(asof)
    sources = []
    records = []
    for day in days:
        _need(_time(day["available_at"]) < _time(asof), "HISTORY_AFTER_AS_OF")
        for source in day["history"]["source_proofs"].values():
            _need(_time(source["captured_at"]) < _time(asof), "HISTORY_AFTER_AS_OF")
            sources.append(dict(source_ref=source["source_url"], source_rights_ref=RIGHTS,
                                source_sha256=source["source_sha256"], captured_at=source["captured_at"],
                                published_at=None))
        records.extend(day["history"]["records"])
    return {r: store.racer_profile(r, asof) for r in racers}, sources, records


def _add_history_features(features, profile, source, lane):
    if not profile or source is None:
        return
    recent = profile["recent_10"]
    if recent.get("mean_finish") is not None and recent.get("normal_starts", 0) > 0:
        features["recent_form"] = _observation((6-recent["mean_finish"])/5, source,
                                               "official-last10-mean-finish-6-minus-over5-v1", recent["normal_starts"])
        features["recent_10race_form"] = deepcopy(features["recent_form"])
    course = profile["by_actual_course"][str(lane)]
    if course.get("mean_finish") is not None and course.get("normal_starts", 0) > 0:
        features["lane_course_fit"] = _observation((6-course["mean_finish"])/5, source,
            "official-prior-course-mean-finish-6-minus-over5-v1", course["normal_starts"])
        features["course_compatibility"] = deepcopy(features["lane_course_fit"])
    if course.get("mean_st") is not None and course.get("st_samples", 0) > 0:
        features["local_course_history"] = _observation(1-course["mean_st"], source,
            "official-prior-course-mean-st-one-minus-v1", course["st_samples"])
    dispositions = profile.get("st_dispositions", {})
    n = sum(dispositions.get(k, 0) for k in ("OK", "F", "L"))
    if n and not dispositions.get("MISSING", 0) and not profile.get("unresolved_opportunities", 0):
        features["start_reliability"] = _observation(dispositions.get("OK", 0)/n, source,
                                                      "prior-numeric-start-over-ok-f-l-count-v1", n)


def _tactical(profiles, records, source, venue_code, asof):
    """Project existing descriptive profiles; zeros are genuine count zeros."""
    from .boat_tactical_scenarios import MODES
    def methods(counts):
        out = {mode: counts.get(mode, 0) for mode in MODES if mode != "other"}
        out["other"] = sum(v for k, v in counts.items() if k not in out)
        return out
    histories = []
    for registration, profile in sorted(profiles.items()):
        p = profile["tendencies"]
        tendencies = {k: deepcopy(p["tendencies"][k]) for k in (
            "crossed_by_outer_frame", "crossed_by_outer_frame_top3", "in1_starts", "in1_wins")}
        tendencies["in1_losses_by_winner_method"] = methods(p["tendencies"]["in1_losses_by_winner_method"])
        histories.append(dict(racer_id=registration, as_of=asof, sample_races=p["sample_races"],
            actual_entry_course_history={k: {f: v[f] for f in ("starts", "wins", "top2", "top3")}
                                         for k, v in p["actual_entry_course_history"].items()},
            by_frame_actual_course_counts=deepcopy(p["by_frame_actual_course_counts"]),
            wins_by_actual_course_and_kimarite={k: methods(v) for k, v in p["wins_by_actual_course_and_kimarite"].items()},
            recent_form={k: {f: v[f] for f in ("starts", "wins", "top3")} for k, v in p["recent_form"].items()},
            tendencies=tendencies, source_receipt=dict(official_source_sha256=source["source_sha256"],
                captured_at=source["captured_at"], upstream_identity_verified=True)))
    selected = [r for r in records if r["race_id"][9:11] == venue_code]
    _need(selected, "VENUE_HISTORY_REQUIRED")
    matrix = [[0]*6 for _ in range(6)]
    starts = [0]*6; wins = [0]*6; top3 = [0]*6; modes = Counter()
    for race in selected:
        _need(_time(race["result_captured_at"]) < _time(asof), "HISTORY_AFTER_AS_OF")
        method = race["winner_method"] if race["winner_method"] in MODES else "other"
        modes[method] += 1
        for row in race["entries"]:
            f = row["frame"]-1; c = row["course"]-1
            matrix[f][c] += 1; starts[c] += 1
            wins[c] += row["finish"] == 1; top3[c] += row["finish"] <= 3
    _need(all(starts) and all(sum(row) for row in matrix), "VENUE_COURSE_SUPPORT_REQUIRED")
    venue = dict(venue_code=venue_code, captured_at=source["captured_at"],
                 official_source_sha256=source["source_sha256"], frame_course_counts=matrix,
                 course_win_rate=[w/n for w, n in zip(wins, starts)], course_top3_rate=[w/n for w, n in zip(top3, starts)],
                 winner_method_rates={k: modes[k]/len(selected) for k in MODES}, source_identity_verified=True)
    return histories, venue


def shared_snapshot_from_observed(snapshot):
    """Convert a saved observed original, without refreshing any source clock.

    Caller authenticates the saved original and separate result labels. This
    validates its native input contract, preserves each referenced source hash,
    scope and capture/publication times, and omits unsupported feature terms.
    The conversion is suitable for both P0 and P1 historical originals.
    """
    from .boat_observed_pairwise_models import _validate
    from .comprehensive_four_sport_models import validate
    _validate(snapshot)
    sources = {s["source_id"]: s for s in snapshot["sources"]}
    mappings = (
        ("national_win_rate", ("ability", "national_win_rate"), 0, 10,
         lambda v: v/10, "official-national-win-rate-over10-v1"),
        ("motor_top2_rate", ("motor_form", "motor_place_rate"), 0, 100,
         lambda v: v/100, "official-motor-top2-percent-over100-v1"),
        ("recent_mean_finish", ("recent_form", "recent_10race_form"), 1, 6,
         lambda v: (6-v)/5, "official-last10-mean-finish-6-minus-over5-v1"),
        ("course_mean_finish", ("course_compatibility", "lane_course_fit"), 1, 6,
         lambda v: (6-v)/5, "official-prior-course-mean-finish-6-minus-over5-v1"),
        ("recent_mean_st", ("start_timing",), 0, 1,
         lambda v: 1-v, "official-prior-recent-mean-st-one-minus-v1"),
        ("course_mean_st", ("local_course_history",), 0, 1,
         lambda v: 1-v, "official-prior-course-mean-st-one-minus-v1"),
        ("exhibition_time_seconds", ("exhibition_performance",), 4, 12,
         lambda v: (12-v)/8, "official-exhibition-12-minus-seconds-over8-v1"),
        ("exhibition_start_seconds", ("exhibition_start",), 0, 1,
         lambda v: 1-v, "official-exhibition-start-one-minus-v1"),
    )
    participants = []
    for row in sorted(snapshot["participants"], key=lambda p: p["lane"]):
        features = {}; missing = {}
        for old, names, low, high, transform, transform_id in mappings:
            feature = row["features"].get(old)
            if feature is None or not _finite(feature["value"], low, high):
                reason = row["missing"].get(old, "NOT_AVAILABLE")
                from .comprehensive_four_sport_models import MISSING_REASONS
                for name in names: missing[name] = reason if reason in MISSING_REASONS else "NOT_AVAILABLE"
                continue
            proof = sources[feature["source_id"]]
            source = dict(source_ref=proof["source_url"], source_sha256=proof["source_sha256"],
                          source_rights_ref=proof["source_rights_ref"], published_at=proof["published_at"],
                          captured_at=proof["captured_at"])
            observation = _observation(transform(feature["value"]), source, transform_id, feature["sample_n"])
            for name in names: features[name] = deepcopy(observation)
        participants.append(_participant(row["lane"], row["registration_no"], features, missing))
    race = dict(race_id=snapshot["race_id"], sport="boat", venue=snapshot["venue"],
                event_date_jst=snapshot["event_date_jst"], sales_cutoff_at=snapshot["sales_cutoff_at"],
                as_of=snapshot["as_of"], distance_m=None, surface="water", race_kind="",
                race_revision=snapshot["race_revision"])
    result = _snapshot(race, participants, {}, snapshot["scope"])
    refs = {(s["source_url"], s["source_rights_ref"]) for s in snapshot["sources"]}
    # A local structural replay; this neither grants source rights nor fits.
    validate(result, allow_source=lambda ref, rights, purpose: (ref, rights) in refs and purpose == "analysis")
    return result


def pdca_payload_from_history(facts, *, as_of, history_context, source_evidence):
    """Use distinct earlier verified archive outcomes in the local PDCA model.

    The legacy ``db_saved_at`` wire field is an availability bound here: the
    actual later B/K capture from the history import, never a fabricated D1
    save receipt. Explicit semantics travel with this privately saved payload.
    Source identity and personal-analysis review must be established upstream.
    This creates no fitted artifact; PDCA remains the original fixed prior.
    """
    _need(isinstance(history_context, dict) and history_context.get("history_identity_verified") is True,
          "PDCA_VERIFIED_HISTORY_REQUIRED")
    _need(history_context.get("owner_reviewed") is True or history_context.get("source_rights_verified") is True,
          "PDCA_OWNER_REVIEW_REQUIRED")
    store = _history_store(history_context)
    _need(store is not None, "PDCA_VERIFIED_HISTORY_REQUIRED")
    _need(isinstance(facts, dict) and isinstance(facts.get("race_id"), str) and RACE_ID.fullmatch(facts["race_id"]),
          "PDCA_CURRENT_FACTS_REQUIRED")
    rid = facts["race_id"]; captured = _time(facts["captured_at"])
    _need(captured <= _time(as_of) < _time(facts["cutoff_at"]), "PDCA_CURRENT_CLOCK_INVALID")
    locator(facts["source_url"], "beforeinfo", rid)
    _need(facts.get("rights_verified") is True and facts.get("license_purpose") == "private_analysis",
          "PDCA_OWNER_REVIEW_REQUIRED")
    _need(isinstance(source_evidence, list) and {facts["source_sha256"], facts["program_sha256"]}.issubset(
        {s.get("source_sha256") for s in source_evidence}), "PDCA_CURRENT_SOURCE_BINDING_REQUIRED")
    rows = []; evidence = deepcopy(source_evidence); seen = set()
    for day in store.visible_days(facts["captured_at"]):
        available = day["available_at"]
        _need(_time(available) < captured, "PDCA_HISTORY_AFTER_AS_OF")
        proofs = day["history"]["source_proofs"]
        k_source = proofs["K"]
        for race in day["history"]["records"]:
            if race["race_id"][9:11] != rid[9:11] or race["race_id"] == rid:
                continue
            _need(race["race_id"] not in seen, "PDCA_DISTINCT_RESULT_REQUIRED")
            _need(_time(race["cutoff_at"]) < _time(race["result_captured_at"]) < captured and
                  race["source_sha256"] == k_source["source_sha256"] and
                  _time(race["result_captured_at"]) == _time(k_source["captured_at"]), "PDCA_RESULT_SOURCE_BINDING_REQUIRED")
            seen.add(race["race_id"])
            top3 = [r["frame"] for r in sorted(race["entries"], key=lambda r: r["finish"])[:3]]
            report = dict(race_id=race["race_id"], official_top3=top3, source_sha256=race["source_sha256"],
                          captured_at=race["result_captured_at"], source_url=k_source["source_url"],
                          availability_basis="VERIFIED_ARCHIVE_CAPTURE_BOUND")
            wire = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            sha = hashlib.sha256(wire.encode()).hexdigest()
            rows.append(dict(report_json=wire, report_sha256=sha, db_saved_at=available))
            members = [dict(source_ref=p["source_url"], source_sha256=p["source_sha256"],
                            source_rights_ref=RIGHTS, published_at=None, captured_at=p["captured_at"])
                       for p in proofs.values()]
            evidence.extend(members)
            evidence.append(dict(source_ref="urn:race-ai:pdca-history-report:"+sha,
                                 source_sha256=sha, source_rights_ref=RIGHTS, source_members=members))
    rows.sort(key=lambda r: json.loads(r["report_json"])["race_id"])
    rows = rows[-240:]
    selected = {json.loads(r["report_json"])["source_sha256"] for r in rows} | {r["report_sha256"] for r in rows}
    selected.update((facts["source_sha256"], facts["program_sha256"]))
    unique = {}
    for e in evidence:
        if e["source_sha256"] in selected:
            unique[(e["source_ref"], e["source_sha256"])] = e
    return dict(scope=RESEARCH, facts=deepcopy(facts), rows=rows, source_evidence=list(unique.values()),
                history_availability_semantics="ARCHIVE_SOURCE_CAPTURE_BOUND_NOT_DATABASE_SAVE_ATTESTATION")


def build_native_inputs(program, beforeinfo, *, as_of, history_context=None, fitted_model=None):
    """Return native groups plus independent readiness records for each group.

    ``history_context`` may hold ``history_store``, an authenticated caller's
    ``history_identity_verified`` flag, and a separately prepared ``pdca``
    native payload. Missing learned artifacts and history never gate other
    ready groups. The result contains source evidence, not an authorization.
    """
    asof = _time(as_of); at = as_of if isinstance(as_of, str) else asof.isoformat()
    rid = program.get("race_id")
    _need(isinstance(rid, str) and RACE_ID.fullmatch(rid), "RACE_IDENTITY_REQUIRED")
    cutoff = program.get("closed_at")
    _need(asof < _time(cutoff), "AS_OF_BEFORE_CUTOFF_REQUIRED")
    _need(beforeinfo.get("race_id") == rid, "PREVIEW_RACE_MISMATCH")
    _need(_value(beforeinfo, "closed_at", "source_cutoff_at") in (None, cutoff), "PREVIEW_CUTOFF_MISMATCH")
    program_source = _source(program, "racelist", rid, asof)
    preview_source = _source(beforeinfo, "beforeinfo", rid, asof)
    roster = program.get("boats")
    _need(isinstance(roster, list), "CONFIRMED_ROSTER_REQUIRED")
    _need(all(r.get("entry_status") in ("listed", "withdrawn") for r in roster), "CONFIRMED_ROSTER_REQUIRED")
    active = sorted([r for r in roster if r["entry_status"] == "listed"], key=lambda r: r["lane"])
    lanes = [r["lane"] for r in active]
    registrations = [r["racer_registration_id"] for r in active]
    _need(3 <= len(active) <= 6 and len(set(lanes)) == len(active) and
          all(type(n) is int and n in range(1, 7) for n in lanes) and
          len(set(registrations)) == len(active) and
          all(isinstance(r, str) and re.fullmatch("[0-9]{4}", r) for r in registrations), "ACTIVE_ROSTER_INVALID")
    data = beforeinfo.get("data") or beforeinfo
    rows = data.get("boats", data.get("participants", []))
    _need(isinstance(rows, list), "PREVIEW_ROSTER_INVALID")
    measured = {}
    known = {r["lane"]: r["racer_registration_id"] for r in roster}
    for r in rows:
        lane = r.get("lane")
        reg = _value(r, "racer_registration_id", "registration_number", "registration_no")
        _need(lane in known and known[lane] == reg and lane not in measured, "PREVIEW_REGISTRATION_MISMATCH")
        measured[lane] = r
    profiles, history_sources, records = _historical_inputs(history_context, registrations, at)
    history_source = _composite(history_sources, "official-history") if history_sources else None
    evidence = [program_source, preview_source] + ([history_source] if history_source else [])
    composite = _composite(evidence, "boat-native-inputs")
    evidence.append(composite)
    participants = []; full_rows = []; base_rows = []; extra_rows = []
    exhibition_missing = []; motor_missing = []
    for r in active:
        lane = r["lane"]; reg = r["racer_registration_id"]; m = measured.get(lane, {})
        f = {}; full = {}; missing = {}
        rate = r.get("national_win_rate")
        if _finite(rate, 0, 10):
            f["ability"] = _observation(rate/10, program_source, "official-national-win-rate-over10-v1")
            f["national_win_rate"] = deepcopy(f["ability"]); full["ability_rating"] = rate*10
        local = r.get("local_win_rate")
        if _finite(local, 0, 10): f["venue_win_rate"] = _observation(local/10, program_source, "official-venue-win-rate-over10-v1")
        avg_st = r.get("average_st")
        if _finite(avg_st, 0, 1): f["start_timing"] = _observation(1-avg_st, program_source, "official-average-st-one-minus-v1")
        motor = _value(r, "motor_top2_rate", "motor_two_place_rate_percent", "motor_two_place_rate")
        if _finite(motor, 0, 100):
            f["motor_form"] = _observation(motor/100, program_source, "official-motor-top2-percent-over100-v1")
            f["motor_place_rate"] = deepcopy(f["motor_form"]); full["motor_rating"] = motor
        else: motor_missing.append(lane)
        clock = _value(m, "display_time", "exhibition_time_seconds")
        if _finite(clock, 4, 12):
            f["exhibition_performance"] = _observation((12-clock)/8, preview_source, "official-exhibition-12-minus-seconds-over8-v1", 1)
            full["exhibition_time_seconds"] = clock
        else: exhibition_missing.append(lane)
        st = _value(m, "preview_st", "exhibition_st", "exhibition_start_seconds")
        status = _value(m, "preview_st_status", "exhibition_st_status") or "PENDING"
        if status == "NOT_PUBLISHED": status = "PENDING"
        _need(status in ("OK", "F", "L", "PENDING"), "PREVIEW_START_STATUS_INVALID")
        _need(status == "OK" or st is None, "PREVIEW_START_STATUS_CONFLICT")
        if status == "OK":
            _need(_finite(st, 0, 1), "PREVIEW_START_MEASUREMENT_INVALID")
            f["exhibition_start"] = _observation(1-st, preview_source, "official-exhibition-start-one-minus-v1", 1)
            full["exhibition_start_seconds"] = st
        else: missing["exhibition_start"] = status if status in ("F", "L") else "NOT_YET_PUBLISHED"
        _add_history_features(f, profiles.get(reg), history_source, lane)
        if "recent_form" in f: full["recent_form_rating"] = f["recent_form"]["value"]*100
        if "course_compatibility" in f: full["course_suitability_rating"] = f["course_compatibility"]["value"]*100
        profile = profiles.get(reg)
        if profile and profile.get("st_stddev") is not None and profile.get("st_samples", 0) > 1:
            full["start_consistency_rating"] = 100*max(0, 1-profile["st_stddev"])
        _need(f, "NO_OBSERVED_PARTICIPANT_FEATURES")
        participants.append(_participant(lane, reg, f, missing))
        full_rows.append(dict(lane=lane, participant_id=reg, features=full,
                              missing={k: "NOT_AVAILABLE" for k in FEATURE_RANGES if k not in full},
                              source_ref=composite["source_ref"], published_at=None, captured_at=composite["captured_at"]))
        base_rows.append(dict(lane=lane, racer_id=reg, national_win_rate=rate,
                              exhibition_time_seconds=clock, motor_two_place_rate_percent=motor))
        extra_rows.append(dict(lane=lane, racer_id=reg, local_win_rate=local, average_st=avg_st,
                               exhibition_st=st, exhibition_st_status=status))
    environment = {}; conditions = {}; weather = data.get("weather") or beforeinfo.get("weather") or {}
    for field, shared, full, low, high in (("wind_speed_mps", "wind_mps", "wind_speed_mps", 0, 35),
                                         ("wave_height_cm", "wave_cm", "wave_height_cm", 0, 200),
                                         ("air_temperature_c", "air_temp_c", None, -30, 55)):
        value = weather.get(field)
        if _finite(value, low, high):
            environment[shared] = _observation(value, preview_source, "official-weather-identity-v1", 1)
            if full: conditions[full] = value
    race = _shared_race(rid, cutoff, at, distance=program.get("distance_m"))
    snapshot = _snapshot(race, participants, environment)
    native = {"shared": dict(snapshot=snapshot, source_evidence=deepcopy(evidence)), "boat_full": dict(scope=RESEARCH, source_evidence=deepcopy(evidence), snapshot=dict(
        schema="RACE_AI_BOAT_MULTI_FEATURE_SNAPSHOT_SPARSE_V1", scope=RESEARCH, race_id=rid,
        venue=race["venue"], event_date_jst=race["event_date_jst"], sales_cutoff_at=cutoff, as_of=at,
        entrants=full_rows, conditions=conditions, conditions_missing={k: "NOT_AVAILABLE" for k in CONDITIONS if k not in conditions},
        conditions_source=preview_source["source_ref"] if conditions else None, conditions_published_at=None,
        conditions_captured_at=preview_source["captured_at"] if conditions else None))}
    readiness = {g: dict(state="READY", reasons=[]) for g in native}
    base = None
    if not exhibition_missing:
        base = dict(race_id=rid, cutoff_at=cutoff, captured_at=max(program_source["captured_at"], preview_source["captured_at"], key=_time),
                    program_source_sha256=program_source["source_sha256"], beforeinfo_source_sha256=preview_source["source_sha256"], boats=base_rows)
    if base is not None and not motor_missing:
        native["boat_ab"] = dict(scope=RESEARCH, source=base, source_evidence=deepcopy(evidence))
        extra_sha = hashlib.sha256((program_source["source_sha256"]+preview_source["source_sha256"]).encode()).hexdigest()
        extra_source = dict(source_ref="urn:race-ai:boat-clite-extra:"+extra_sha,
            source_sha256=extra_sha, source_rights_ref=RIGHTS, published_at=None,
            captured_at=preview_source["captured_at"], source_members=deepcopy([program_source,preview_source]),
            transform_id="SHA256_UTF8_CONCAT_PROGRAM_AND_BEFOREINFO_HEX_V1")
        native["boat_clite"] = dict(scope=RESEARCH, base_source=base, extra=dict(race_id=rid,
            observed_at=preview_source["captured_at"], source_sha256=extra_sha, participants=extra_rows), source_evidence=deepcopy(evidence)+[extra_source])
        evidence.append(extra_source)
        readiness.update({g: dict(state="READY", reasons=[]) for g in ("boat_ab", "boat_clite")})
    else:
        reasons = (["ACTIVE_EXHIBITION_MEASUREMENTS_MISSING"] if exhibition_missing else []) + (["OBSERVED_MOTOR_RATE_MISSING"] if motor_missing else [])
        readiness.update({g: dict(state="INPUT_MISSING", reasons=reasons) for g in ("boat_ab", "boat_clite")})
    readiness["boat_observed"] = dict(state="INPUT_MISSING", reasons=["OBSERVED_CURRENT_RACE_NATIVE_INPUTS_REQUIRED"])
    if "boat_clite" in native:
        from .observed_p1_connection import build_bundle
        try:
            bundle = build_bundle(base, native["boat_clite"]["extra"], at,
                program_url=program_source["source_ref"], preview_url=preview_source["source_ref"],
                program_captured_at=program_source["captured_at"], preview_captured_at=preview_source["captured_at"],
                owner_reviewed=True)
            native["boat_observed"] = dict(snapshot=bundle["snapshot"])
            evidence.extend(dict(source_ref=s["source_url"], source_rights_ref=s["source_rights_ref"],
                source_sha256=s["source_sha256"], published_at=s["published_at"], captured_at=s["captured_at"])
                for s in bundle["snapshot"]["sources"])
            readiness["boat_observed"] = dict(state="READY", reasons=[])
        except ValueError:
            readiness["boat_observed"] = dict(state="INPUT_REJECTED", reasons=["OBSERVED_NATIVE_SOURCE_OR_CAPTURE_BINDING_REJECTED"])
    readiness["shared_learned"] = dict(state="TRAINED_ARTIFACT_MISSING", reasons=["FITTED_SPARSE_SHARED_MODEL_REQUIRED"])
    if fitted_model is not None:
        from .four_sport_learning import forecast
        try:
            refs = {(o["source_ref"], o["source_rights_ref"]) for p in participants for o in p["features"].values()}
            refs.update((o["source_ref"], o["source_rights_ref"]) for o in environment.values())
            # Structural replay only; the dispatch caller independently authorizes sources.
            forecast(snapshot, fitted_model, allow_source=lambda ref, rights, purpose: (ref, rights) in refs and purpose == "analysis")
            native["shared_learned"] = dict(snapshot=deepcopy(snapshot), learned_model=deepcopy(fitted_model),
                                           source_evidence=deepcopy(evidence))
            readiness["shared_learned"] = dict(state="READY", reasons=[])
        except ValueError:
            readiness["shared_learned"] = dict(state="TRAINED_ARTIFACT_MISSING", reasons=["FITTED_MODEL_SCHEMA_SCOPE_INTEGRITY_OR_CLOCK_REJECTED"])
    readiness["boat_tactical"] = dict(state="INPUT_MISSING", reasons=["VERIFIED_PRE_CUTOFF_RACER_AND_VENUE_HISTORY_REQUIRED"])
    if "boat_ab" in native and profiles and history_source and isinstance(history_context, dict) and history_context.get("history_identity_verified") is True:
        try:
            histories, venue = _tactical(profiles, records, history_source, rid[9:11], at)
            native["boat_tactical"] = dict(scope=RESEARCH, source=deepcopy(native["boat_ab"]["source"]), histories=histories,
                                           venue=venue, source_evidence=deepcopy(evidence))
            readiness["boat_tactical"] = dict(state="READY", reasons=[])
        except (KeyError, ValueError):
            readiness["boat_tactical"] = dict(state="INPUT_MISSING", reasons=["VERIFIED_VENUE_COURSE_SUPPORT_REQUIRED"])
    readiness["boat_pdca"] = dict(state="INPUT_MISSING", reasons=["SAVED_SAME_VENUE_RESULT_REPORTS_AND_NATIVE_FACTS_REQUIRED"])
    pdca = deepcopy(history_context.get("pdca")) if isinstance(history_context, dict) else None
    if pdca is None and _history_store(history_context) is not None:
        if base is None:
            readiness["boat_pdca"] = dict(state="INPUT_MISSING", reasons=["ACTIVE_EXHIBITION_MEASUREMENTS_MISSING"])
        else:
            facts = dict(schema="RACE_AI_BOAT_OBSERVATION_V1", phase="post_exhibition", race_id=rid,
                cutoff_at=cutoff, captured_at=base["captured_at"], source_url=preview_source["source_ref"],
                source_sha256=preview_source["source_sha256"], program_sha256=program_source["source_sha256"],
                rights_verified=isinstance(history_context, dict) and (history_context.get("owner_reviewed") is True or
                    history_context.get("source_rights_verified") is True), license_purpose="private_analysis",
                racers=[dict(lane=r["lane"], registration_no=r["racer_id"], national_win_rate=r["national_win_rate"],
                             exhibition_time_seconds=r["exhibition_time_seconds"]) for r in base_rows])
            try:
                pdca = pdca_payload_from_history(facts, as_of=at, history_context=history_context,
                                                source_evidence=[program_source, preview_source])
            except ValueError as exc:
                reason = str(exc)
                readiness["boat_pdca"] = dict(state="INPUT_MISSING", reasons=[reason.removeprefix("BOAT_NATIVE_")])
    if pdca is not None:
        if pdca.get("facts", {}).get("race_id") != rid:
            readiness["boat_pdca"] = dict(state="INPUT_REJECTED", reasons=["PDCA_RACE_MISMATCH"])
        elif not isinstance(pdca.get("rows"), list) or len(pdca["rows"]) < 24:
            readiness["boat_pdca"] = dict(state="INPUT_MISSING", reasons=["PDCA_REQUIRES_24_EARLIER_SAME_VENUE_RESULTS"])
        else:
            native["boat_pdca"] = pdca
            readiness["boat_pdca"] = dict(state="READY", reasons=[])
            evidence.extend(deepcopy(pdca.get("source_evidence", [])))
    return dict(schema=SCHEMA, race_id=rid, stage="P1", as_of=at, native_inputs=native,
                readiness=readiness, source_evidence=deepcopy(evidence),
                source_publication_times_inferred=False, source_requests=0)
