"""AUTORACE two-phase, odds-free orchestration and prospective PDCA.

Pure control layer over the existing four-sport research model and cutoff queue.
It NEVER fetches official pages, grants data rights, creates a trusted timestamp,
operates a live schedule, edits a frozen forecast, trains on future results or
places bets. Runtime adapters must be independently reviewed and permissioned.
"""
from __future__ import annotations

from datetime import timedelta
import re

from .cutoff_job_queue import plan
from .exhibition_autorun import _moment, MARGIN, _safe_state
from .comprehensive_four_sport_models import digest
from .four_sport_model_suite import ALL_MODELS, run_suite, verify_suite

SCHEMA = "RACE_AI_AUTORACE_AB_PDCA_V1"
PHASES = ("A_PRE_TRIAL", "B_POST_TRIAL")
TRIAL_KEYS = frozenset({"trial_performance", "trial_time_quality", "trial_rank_quality"})
SOURCE_STATES = frozenset({"AVAILABLE", "PENDING", "UNAVAILABLE", "RIGHTS_BLOCKED"})
RESULT_STATES = frozenset({"FINAL_NORMAL", "CANCELLED", "NO_TRIFECTA", "PENDING", "REFUND_OR_SPECIAL"})
SHA = re.compile(r"[0-9a-f]{64}\Z")


def _state(race_id, phase, state, **details):
    return {"race_id": race_id, "phase": phase, "state": state, **details}


def _race_match(row, snap, phase, instant):
    if not isinstance(snap, dict) or not isinstance(snap.get("race"), dict):
        return False
    race = snap["race"]
    try:
        okay = (race.get("sport") == "autorace" and
                race.get("race_id") == row["race_id"] and
                race.get("venue") == row["venue"] and
                _moment(race["sales_cutoff_at"]) == _moment(row["cutoff_at"]) and
                _moment(race["as_of"]) <= instant < _moment(row["cutoff_at"]) and
                snap.get("scope") == "OPERATOR_SUPPLIED_RESEARCH" and
                3 <= len(snap.get("participants", [])) <= 8)
        if not okay:
            return False
        entrants = snap["participants"]
        if len({p["number"] for p in entrants}) != len(entrants):
            return False
        if phase == PHASES[0]:
            return all(not (TRIAL_KEYS & set(p["features"])) for p in entrants)
        # A numeric, participant-bound trial observation is mandatory for every
        # registered competitor. A page heading or generic label is NOT enough.
        return all("trial_time_quality" in p["features"] for p in entrants)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return False


def _primary(suite, model_id, phase, instant):
    if not verify_suite(suite) or model_id not in ALL_MODELS:
        raise ValueError("research suite/model unverified")
    prediction = suite["models"][model_id]
    universe = prediction["candidates"]
    top8 = prediction["ordered_top8"]
    expected = min(8, len(universe))
    if len(top8) != expected or [x["combination"] for x in universe[:expected]] != top8:
        raise ValueError("model ranking and fixed top8 differ")
    extra = [x["combination"] for x in universe[8:12]]
    if len({tuple(x) for x in top8 + extra}) != len(top8 + extra):
        raise ValueError("duplicate or overlapping additional four")
    record = {
        "schema": SCHEMA, "record_type": "PRE_CUTOFF_RESEARCH_FORECAST",
        "phase": phase, "race_id": suite["race_id"],
        "generated_at": instant.isoformat(), "as_of": suite["as_of"],
        "cutoff_at": suite["sales_cutoff_at"], "model_id": model_id,
        "model_version": prediction["model_version"],
        "model_prediction_sha256": prediction["prediction_sha256"],
        "input_sha256": suite["input_sha256"],
        "ordered_top8": top8, "supplemental_four": extra,
        "candidate_count": prediction["candidate_count"],
        "estimated_probabilities_calibrated": False,
        "supplemental_four_counts_towards_hit_at_8": False,
        "external_pre_cutoff_receipt": None,
        "official_prediction": False, "purchase_decision": "NO_BET",
        "formal_hit_at_8_eligible": False,
    }
    record["prediction_sha256"] = digest(record)
    return record


def tick(records, *, clock, readback, acquire, claim, submit, verify,
         authorize_feature, model_id=ALL_MODELS[0], max_collect=24, margin=MARGIN):
    """Process A and B independently, oldest cutoff first, at most once.

    Required external adapters are identical in purpose to exhibition_autorun:
      readback(row, phase) -> {state: ABSENT|CLAIMED|UNRESOLVED_POST|VERIFIED}
      acquire(row, phase) -> {status, snapshot, source_rights_verified,
                              participant_ids_matched,
                              trial_not_published_verified, trial_race_bound_verified}
      authorize_feature(source_ref, rights_ref, 'analysis') -> bool
      claim/submit/verify(row, phase, forecast) -> durable receipt operations

    A callback claiming verification does not establish legal permission or
    an independently authenticated server timestamp by itself. Fail closed on
    any ambiguity, and NEVER retry an uncertain external POST.
    """
    callbacks = (clock, readback, acquire, claim, submit, verify, authorize_feature)
    if not isinstance(records, list) or not all(callable(f) for f in callbacks):
        raise ValueError("complete independently reviewed adapters required")
    if type(max_collect) is not int or not 1 <= max_collect <= 100:
        raise ValueError("bounded source budget required")
    if not isinstance(margin, timedelta) or margin < timedelta(seconds=60):
        raise ValueError("unsafe cutoff margin")
    if model_id not in ALL_MODELS:
        raise ValueError("unknown fixed model")
    start = _moment(clock())
    scheduled = plan(records, now=start.isoformat())["jobs"]
    by_id = {r["race_id"]: r for r in records}
    rows, collected = [], 0
    for job in scheduled:
        row, rid = by_id[job["race_id"]], job["race_id"]
        for phase in PHASES:
            if row.get("sport") != "autorace":
                rows.append(_state(rid, phase, "NOT_AUTORACE"))
                continue
            if job["state"] != "READY_FOR_AUTHORIZED_INPUT_AND_MODEL":
                rows.append(_state(rid, phase, job["state"]))
                continue
            try:
                stored = _safe_state(readback(row, phase))
            except (ValueError, KeyError, TypeError, OSError):
                rows.append(_state(rid, phase, "READBACK_UNAVAILABLE"))
                continue
            if stored != "ABSENT":
                rows.append(_state(rid, phase, "ALREADY_FROZEN" if stored == "VERIFIED"
                                   else "UNCERTAIN_OR_RESERVED_DO_NOT_REPOST"))
                continue
            if _moment(clock()) + margin >= _moment(row["cutoff_at"]):
                rows.append(_state(rid, phase, "TOO_LATE_FOR_SAFE_FORECAST"))
                continue
            if collected >= max_collect:
                rows.append(_state(rid, phase, "SOURCE_BUDGET_DEFERRED"))
                continue
            collected += 1
            try:
                source = acquire(row, phase)
            except (ValueError, KeyError, TypeError, OSError):
                rows.append(_state(rid, phase, "SOURCE_UNAVAILABLE"))
                continue
            if not isinstance(source, dict) or source.get("status") not in SOURCE_STATES:
                rows.append(_state(rid, phase, "SOURCE_INVALID"))
                continue
            if source["status"] != "AVAILABLE":
                rows.append(_state(rid, phase, "INPUT_" + source["status"]))
                continue
            if source.get("source_rights_verified") is not True or source.get("participant_ids_matched") is not True:
                rows.append(_state(rid, phase, "SOURCE_RIGHTS_OR_IDENTITY_NOT_VERIFIED"))
                continue
            if phase == PHASES[0] and source.get("trial_not_published_verified") is not True:
                rows.append(_state(rid, phase, "PRE_TRIAL_PUBLICATION_STATE_NOT_VERIFIED"))
                continue
            if phase == PHASES[1] and source.get("trial_race_bound_verified") is not True:
                rows.append(_state(rid, phase, "SAME_RACE_TRIAL_NOT_VERIFIED"))
                continue
            snap = source.get("snapshot")
            if not _race_match(row, snap, phase, _moment(clock())):
                rows.append(_state(rid, phase, "INCOMPLETE_OR_WRONG_PHASE_SNAPSHOT"))
                continue
            try:
                forecast = _primary(run_suite(snap, allow_source=authorize_feature),
                                    model_id, phase, _moment(clock()))
            except (ValueError, TypeError, KeyError, OverflowError):
                rows.append(_state(rid, phase, "MODEL_OR_PERMISSION_REJECTED"))
                continue
            if _moment(clock()) + margin >= _moment(row["cutoff_at"]):
                rows.append(_state(rid, phase, "MODEL_FINISHED_TOO_LATE"))
                continue
            try:
                reserved = claim(row, phase, forecast)
            except (ValueError, TypeError, OSError):
                rows.append(_state(rid, phase, "CLAIM_FAILED_NO_POST"))
                continue
            if not isinstance(reserved, dict) or reserved.get("state") != "CREATED":
                rows.append(_state(rid, phase, "CLAIM_NOT_CREATED_NO_POST"))
                continue
            if _moment(clock()) + margin >= _moment(row["cutoff_at"]):
                rows.append(_state(rid, phase, "CLAIMED_TOO_LATE_NO_POST"))
                continue
            try:
                posted = submit(row, phase, forecast)
                if not isinstance(posted, dict) or posted.get("state") != "SUBMITTED":
                    raise ValueError("unconfirmed POST")
                finished = verify(row, phase, forecast) is True
            except (ValueError, TypeError, KeyError, OSError):
                finished = False
            if finished:
                rows.append(_state(rid, phase, "FROZEN_READBACK_VERIFIED_BY_ADAPTER",
                                   model_id=model_id,
                                   prediction_sha256=forecast["prediction_sha256"],
                                   ordered_top8=forecast["ordered_top8"],
                                   supplemental_four=forecast["supplemental_four"],
                                   probabilities_calibrated=False))
            else:
                rows.append(_state(rid, phase, "POST_UNCERTAIN_DO_NOT_RETRY"))
    return {"schema": SCHEMA, "record_type": "CONTROL_TICK",
            "as_of": start.isoformat(), "all_known_races": len(records),
            "source_acquire_calls": collected, "states": rows,
            "real_provider_polling_enabled": False,
            "formal_prediction_guaranteed": False,
            "automatic_betting_enabled": False}


def _tickets(forecast, entrants):
    if not isinstance(forecast, dict) or forecast.get("schema") != SCHEMA:
        raise ValueError("forecast shape invalid")
    if forecast.get("prediction_sha256") != digest({k: v for k, v in forecast.items()
                                                    if k != "prediction_sha256"}):
        raise ValueError("prediction hash mismatch")
    base, extra = forecast.get("ordered_top8"), forecast.get("supplemental_four")
    if not isinstance(base, list) or not isinstance(extra, list):
        raise ValueError("ticket lists missing")
    if len(base) != min(8, len(entrants) * (len(entrants)-1) * (len(entrants)-2)) or len(extra) > 4:
        raise ValueError("ticket count invalid")
    all_tickets = base + extra
    if any(not isinstance(x, list) or len(x) != 3 or any(type(v) is not int or v not in entrants
           for v in x) or len(set(x)) != 3 for x in all_tickets):
        raise ValueError("non-entrant or duplicate trifecta")
    if len({tuple(x) for x in all_tickets}) != len(all_tickets):
        raise ValueError("ticket overlap")
    return base, extra


def audit_cycle(records, *, clock, load_forecast, load_result, verify_forecast,
                verify_result, latest_audit, append_audit, read_audit,
                max_closed=24):
    """Append-only A/B comparison for independently verified final results.

    No post-result model update is performed. Only future, previously unfrozen
    forecasts may be generated from subsequent authorized as-of snapshots.
    """
    callbacks = (clock, load_forecast, load_result, verify_forecast, verify_result,
                 latest_audit, append_audit, read_audit)
    if not isinstance(records, list) or not all(callable(f) for f in callbacks):
        raise ValueError("complete audit adapters required")
    if type(max_closed) is not int or not 1 <= max_closed <= 100:
        raise ValueError("bounded result budget required")
    now = _moment(clock())
    seen, closed, upcoming = set(), [], []
    for r in records:
        rid = r.get("race_id")
        if not isinstance(rid, str) or rid in seen or r.get("sport") != "autorace":
            raise ValueError("duplicate or non-autorace race")
        seen.add(rid)
        if r.get("cutoff_verified") is not True:
            continue
        (closed if _moment(r["cutoff_at"]) <= now else upcoming).append(r)
    closed.sort(key=lambda x: (_moment(x["cutoff_at"]), x["race_id"]))
    upcoming.sort(key=lambda x: (_moment(x["cutoff_at"]), x["race_id"]))
    events, scanned = [], 0
    for row in closed:
        rid = row["race_id"]
        if scanned >= max_closed:
            events.append({"race_id": rid, "state": "AUDIT_BUDGET_DEFERRED"})
            continue
        scanned += 1
        try:
            result = load_result(row)
            if not isinstance(result, dict) or verify_result(row, result) is not True:
                raise ValueError("result or provenance unverified")
            if result.get("race_id") != rid or result.get("status") not in RESULT_STATES:
                raise ValueError("result identity/status mismatch")
            if not (_moment(row["cutoff_at"]) < _moment(result["published_at"]) <=
                    _moment(result["captured_at"]) <= now):
                raise ValueError("result publication or capture chronology invalid")
            eligible = result["status"] == "FINAL_NORMAL" and row.get("trifecta_offered") is True
            winners = result.get("winning_triples", [])
            entrants = row.get("entrants")
            if (not isinstance(entrants, list) or not 3 <= len(entrants) <= 8 or
                len(set(entrants)) != len(entrants) or
                any(type(x) is not int or not 1 <= x <= 8 for x in entrants)):
                raise ValueError("verified entry roster missing")
            if not isinstance(winners, list) or (eligible and not winners) or (not eligible and winners):
                raise ValueError("result disposition invalid")
            win_set = {tuple(x) for x in winners}
            if (len(win_set) != len(winners) or
                any(len(x) != 3 or len(set(x)) != 3 or not set(x) <= set(entrants)
                    for x in win_set)):
                raise ValueError("invalid winners")
            # The score is 0 for a missing forecast ONLY when the verified
            # official outcome is formally evaluable, never on PENDING.
            phase_results = {}
            for phase in PHASES:
                original = load_forecast(row, phase)
                if original is None:
                    phase_results[phase] = {"status": "NO_FORECAST", "hit1": 0 if eligible else None,
                                            "hit8": 0 if eligible else None,
                                            "hit12": 0 if eligible else None}
                    continue
                if (original.get("phase") != phase or original.get("race_id") != rid or
                    _moment(original["generated_at"]) >= _moment(row["cutoff_at"]) or
                    original.get("cutoff_at") != row["cutoff_at"]):
                    raise ValueError("forecast race, phase or deadline mismatch")
                base, extra = _tickets(original, entrants)
                if verify_forecast(row, phase, original) is not True:
                    phase_results[phase] = {"status": "UNVERIFIED_FREEZE_RECEIPT",
                                            "hit1": 0 if eligible else None,
                                            "hit8": 0 if eligible else None,
                                            "hit12": 0 if eligible else None}
                    continue
                phase_results[phase] = {
                    "status": "EVALUATED" if eligible else "RESULT_NOT_SCORABLE",
                    "hit1": int(tuple(base[0]) in win_set) if eligible else None,
                    "hit8": int(any(tuple(t) in win_set for t in base)) if eligible else None,
                    "hit12": int(any(tuple(t) in win_set for t in base+extra)) if eligible else None,
                    "prediction_sha256": original["prediction_sha256"],
                }
            report = {"schema": SCHEMA, "race_id": rid,
                      "status": "EVALUATED" if eligible else "RESULT_NOT_SCORABLE",
                      "official_result_revision": result.get("revision"),
                      "official_source_sha256": result.get("source_sha256"),
                      "winning_triples": winners if eligible else [],
                      "A": phase_results[PHASES[0]], "B": phase_results[PHASES[1]],
                      "causal_reason_verified": False,
                      "automatic_model_promoted": False}
            current = latest_audit(rid)
            if current is not None:
                if (type(current.get("revision")) is not int or current["revision"] < 1 or
                    current.get("sha256") != digest(current.get("report"))):
                    raise ValueError("untrusted previous audit")
                if current["report"] == report:
                    events.append({"race_id": rid, "state": "ALREADY_SAVED",
                                   "revision": current["revision"], "report": report})
                    continue
            revision = 1 if current is None else current["revision"]+1
            new = {"race_id": rid, "revision": revision, "report": report,
                   "sha256": digest(report),
                   "previous_sha256": None if current is None else current["sha256"]}
            if append_audit(new) is not True or read_audit(rid, revision) != new:
                raise ValueError("unverified audit append")
            events.append({"race_id": rid, "state": "AUDIT_APPENDED_AND_READBACK",
                           "revision": revision, "report": report})
        except (ValueError, TypeError, KeyError, OSError, OverflowError):
            events.append({"race_id": rid, "state": "RESULT_OR_AUDIT_UNVERIFIED_NO_REPOST"})
    evaluated = [e["report"] for e in events if e["state"] in
                 ("AUDIT_APPENDED_AND_READBACK", "ALREADY_SAVED") and e["report"]["status"] == "EVALUATED"]
    kpis = {}
    for phase, key in ((PHASES[0], "A"), (PHASES[1], "B")):
        kpis[phase] = {"evaluable_races": len(evaluated),
                       "hit1_all": sum(x[key]["hit1"] for x in evaluated),
                       "hit8_all": sum(x[key]["hit8"] for x in evaluated),
                       "hit12_all_experimental": sum(x[key]["hit12"] for x in evaluated)}
    return {"schema": SCHEMA, "record_type": "RESULT_PDCA_TICK",
            "as_of": now.isoformat(), "known_races": len(records),
            "closed_races": len(closed), "closed_checked": scanned,
            "events": events, "kpis": kpis,
            "next_unfrozen_races": [{"race_id": r["race_id"], "cutoff_at": r["cutoff_at"],
                                     "plan": "FRESH_AUTHORIZED_AS_OF_INPUT_ONLY"}
                                    for r in upcoming[:12]],
            "future_model_promotion_requires_prospective_validation": True,
            "live_result_polling_enabled": False}
