"""Bridge PR #71's ordered race queue to PR #64's SERVER-SIDE forecast store.

PR64's POST computes the forecast itself. Never submit local probabilities to
its API or mistake an unsaved local prediction for the server's immutable one.

The callbacks are *not* implemented here: an approved service must provide
real PR64 Preview readback, a durable atomic claim, a preview-source readiness
check, a scoped OIDC POST, and PR64's pinned-receipt validators. No network,
cloud write, cron, token or wagering occurs on importing this module.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re

from .cutoff_job_queue import plan
from .exhibition_autorun import MARGIN, _moment

PR64_HEAD = "761247bee0209e37b1af6b8885e92cad3e9260a5"
REQUEST_ID = re.compile(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,3}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
TICKETS = {(a, b, c) for a in range(1, 7)
           for b in range(1, 7) if a != b
           for c in range(1, 7) if c not in (a, b)}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _stop(race_id, state):
    return {"race_id": race_id, "state": state, "frozen": False}


def _rank(receipt, race, at, validate_receipt):
    """Project real PR64 *readback*; validation callback must check its parents."""
    if not callable(validate_receipt) or not isinstance(receipt, dict):
        raise ValueError("PR64 receipt and validator required")
    # PR64 checked_receipt requires matching pinned B + official beforeinfo
    # receipts and validates the deterministic 120-combination replay.
    if validate_receipt(receipt, race, at) is not True:
        raise ValueError("PR64 receipt verification not accepted")
    snapshot = receipt.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("phase") != "post_exhibition":
        raise ValueError("not a PR64 post-exhibition snapshot")
    if snapshot.get("race_id") != race.get("race_id"):
        raise ValueError("PR64 race identity mismatch")
    cutoff = _moment(race["closed_at"])
    saved = _moment(receipt["cloud_saved_at"])
    created = _moment(snapshot["generated_at"])
    if not (created <= saved < cutoff and saved <= _moment(at)
            and receipt.get("cloud_eligible_pre_race") is True):
        raise ValueError("not independently saved before cutoff")
    model = snapshot.get("model")
    if not isinstance(model, dict) or model.get("model_id") != "official-beforeinfo-display-pl":
        raise ValueError("wrong PR64 exhibition model")
    triples = model.get("triples")
    if not isinstance(triples, list) or len(triples) != 120:
        raise ValueError("all 120 three-way outcomes required")
    seen = set()
    for row in triples:
        if not isinstance(row, dict) or set(row) != {"combination", "probability"}:
            raise ValueError("malformed prediction row")
        ticket = tuple(row["combination"]) if isinstance(row["combination"], list) else ()
        p = row["probability"]
        if ticket not in TICKETS or ticket in seen or type(p) not in (float, int) or not math.isfinite(p) or not 0 < p < 1:
            raise ValueError("illegal or repeated prediction row")
        seen.add(ticket)
    if seen != TICKETS or not math.isclose(math.fsum(row["probability"] for row in triples), 1.0, abs_tol=1e-10):
        raise ValueError("not a normalized full probability model")
    ranking = sorted(triples, key=lambda x: (-x["probability"], x["combination"]))
    return {
        "race_id": race["race_id"],
        "state": "PR64_CLOUD_FROZEN_VERIFIED",
        "frozen": True,
        "phase": "post_exhibition",
        "source_ref": f"PR64:{PR64_HEAD}",
        "model_id": model["model_id"],
        "model_version": model["model_version"],
        "as_of": snapshot["as_of"],
        "generated_at": snapshot["generated_at"],
        "cloud_saved_at": receipt["cloud_saved_at"],
        "cutoff_at": race["closed_at"],
        "prediction_snapshot_id": snapshot["snapshot_id"],
        "receipt_sha256": _digest(receipt),
        "beforeinfo_snapshot_id": snapshot["beforeinfo_link"]["snapshot_id"],
        "ordered_top8": [x["combination"] for x in ranking[:8]],
        "model_scores": [x["probability"] for x in ranking[:8]],
        "all_triples": [{"combination": x["combination"], "score": x["probability"]} for x in ranking],
        "scores_calibrated": False,
        "research_only": True,
        "official_result": None,
    }


def tick_one(race, *, clock, readback, exhibition_ready, claim,
             publish, validate_receipt, margin=MARGIN):
    """One new race. Reads PR64 state BEFORE claim or any POST.

    readback(race, request_id=None) returns actual PR64 store receipt or None.
    exhibition_ready(race) returns a data-verified bool; not a page-exists bool.
    claim(race) must atomically reserve one race/phase and return
      {"state":"CREATED", "request_id":"<runid>-<attempt>"}.
    publish(race, request_id) invokes the existing PR64 API with the fixed
    request_id; ONLY ONE invocation is possible. Any ambiguous outcome stops.
    validate_receipt(receipt, race, now) calls the real PR64 checked_receipt
    against pinned B/beforeinfo with durable blob readback.
    """
    funcs = (clock, readback, exhibition_ready, claim, publish, validate_receipt)
    if not all(callable(f) for f in funcs) or margin < timedelta(seconds=60):
        raise ValueError("verified runtime adapters and safe margin required")
    if not isinstance(race, dict) or race.get("sport") != "boat":
        raise ValueError("one BOAT race required")
    race_id = race["race_id"]
    if not re.fullmatch(r"[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])", race_id):
        raise ValueError("PR64 race identifier required")
    start = _moment(clock())
    q = plan([race], now=start.isoformat())["jobs"][0]
    if q["state"] != "READY_FOR_AUTHORIZED_INPUT_AND_MODEL":
        return _stop(race_id, q["state"])
    cutoff = _moment(race["closed_at"])
    if cutoff != _moment(race["cutoff_at"]):
        return _stop(race_id, "CUTOFF_IDENTITY_MISMATCH")
    if cutoff.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d") != race_id[:8]:
        return _stop(race_id, "CUTOFF_DATE_MISMATCH")
    try:
        saved = readback(race)
    except (ValueError, TypeError, OSError):
        return _stop(race_id, "PR64_READBACK_UNAVAILABLE")
    if saved is not None:
        try:
            existing = _rank(saved, race, clock(), validate_receipt)
        except (KeyError, ValueError, TypeError):
            return _stop(race_id, "PR64_PREEXISTING_RECEIPT_INVALID")
        return {**existing, "reused_existing_receipt": True}
    if _moment(clock()) + margin >= cutoff:
        return _stop(race_id, "TOO_LATE_FOR_PR64_PUBLICATION")
    try:
        ready = exhibition_ready(race)
    except (ValueError, TypeError, OSError):
        return _stop(race_id, "PR64_EXHIBITION_CHECK_FAILED")
    if ready is not True:
        return _stop(race_id, "EXHIBITION_NOT_COMPLETE")
    if _moment(clock()) + margin >= cutoff:
        return _stop(race_id, "TOO_LATE_FOR_PR64_PUBLICATION")
    # An independent durable CAS claim is mandatory, not supplied by PR64's
    # overwriteable "latest" manifest. Without a claim, NEVER POST.
    try:
        reservation = claim(race)
    except (ValueError, TypeError, OSError):
        return _stop(race_id, "PR64_CLAIM_FAILED")
    if not isinstance(reservation, dict) or reservation.get("state") != "CREATED" or not isinstance(reservation.get("request_id"), str) or not REQUEST_ID.fullmatch(reservation["request_id"]):
        return _stop(race_id, "PR64_CLAIM_NOT_CREATED")
    if _moment(clock()) + margin >= cutoff:
        return _stop(race_id, "PR64_CLAIMED_TOO_LATE_NO_POST")
    rid = reservation["request_id"]
    # Once a POST might have been sent, do NOT retry on timeout, HTTP503 or
    # transient readback absence. Reconcile that exact request_id read-only.
    try:
        metadata = publish(race, rid)
    except (ValueError, TypeError, OSError):
        return _stop(race_id, "PR64_POST_UNCERTAIN_NO_RETRY")
    if (not isinstance(metadata, dict) or metadata.get("status") != "verified"
            or metadata.get("request_id") != rid
            or metadata.get("race_id") != race_id):
        return _stop(race_id, "PR64_POST_UNCERTAIN_NO_RETRY")
    try:
        stored = readback(race, rid)
        projection = _rank(stored, race, clock(), validate_receipt)
    except (KeyError, ValueError, TypeError, OSError):
        return _stop(race_id, "PR64_POST_UNCERTAIN_NO_RETRY")
    if (metadata.get("sha256") != projection["receipt_sha256"]
            or metadata.get("snapshot_id") != projection["prediction_snapshot_id"]
            or metadata.get("cloud_saved_at") != projection["cloud_saved_at"]):
        return _stop(race_id, "PR64_POST_RECEIPT_MISMATCH")
    return {**projection, "reused_existing_receipt": False}


def score_after_finish(race, forecast, race_bundle, *, now, validate_result):
    """Never recompute forecast: compare its original immutable eight tickets."""
    if not callable(validate_result):
        raise ValueError("PR64 result verifier required")
    at = _moment(now)
    cutoff = _moment(race["closed_at"])
    rid = race["race_id"]
    if at < cutoff:
        return _stop(rid, "RACE_NOT_CLOSED")
    if race_bundle is None:
        return _stop(rid, "RESULT_NOT_OBTAINED")
    # PR64 validate_cloud_bundle validates venue/date/6 identities/receipts.
    observations = validate_result(race_bundle, race, now)
    if not isinstance(observations, dict):
        raise ValueError("verified PR64 race bundle expected")
    result = observations.get("raceresult")
    if result is None:
        return _stop(rid, "RESULT_NOT_OBTAINED")
    row = result["record"]
    data = row.get("data")
    if row.get("status") == "PENDING" or data is None:
        return _stop(rid, "OFFICIAL_RESULT_PENDING")
    if (not isinstance(data, dict) or data.get("status") != "settled"
            or data.get("finish_confirmed") is not True):
        return _stop(rid, "OFFICIAL_RESULT_UNSUPPORTED")
    if data.get("refund_boats") or data.get("refunds") not in ([], None):
        return _stop(rid, "REFUND_OUTCOME_REQUIRES_SEPARATE_POLICY")
    winner = tuple(data.get("top3") or ())
    if winner not in TICKETS:
        return _stop(rid, "RESULT_TOP3_INVALID")
    if _moment(row["captured_at"]) < cutoff or _moment(result["cloud_saved_at"]) < cutoff:
        raise ValueError("post-close result evidence cannot predate close")
    # Missing forecast counts as 0 after result, not missing denominator.
    is_frozen = isinstance(forecast, dict) and forecast.get("frozen") is True and forecast.get("race_id") == rid
    ordered = forecast["ordered_top8"] if is_frozen else []
    ranked = forecast["all_triples"] if is_frozen else []
    if is_frozen:
        if (len(ordered) != 8 or len(ranked) != 120 or
                [x["combination"] for x in ranked[:8]] != ordered
                or [tuple(x["combination"]) for x in ranked] !=
                    sorted(TICKETS, key=lambda t: (-next(x["score"] for x in ranked if tuple(x["combination"]) == t), t))):
            raise ValueError("frozen ranking evidence malformed")
        if (_moment(forecast["cloud_saved_at"]) >= cutoff
                or forecast.get("scores_calibrated") is not False):
            raise ValueError("unsafe historical forecast evidence")
    win = list(winner)
    p = next((x["score"] for x in ranked if x["combination"] == win), None)
    brier = (math.fsum((x["score"] - (x["combination"] == win)) ** 2 for x in ranked)
             if p is not None else None)
    return {
        "race_id": rid, "state": "RESULT_SCORED", "cutoff_at": race["closed_at"],
        "official_result": win, "result_source_sha256": row["source_sha256"],
        "result_captured_at": row["captured_at"],
        "frozen": is_frozen, "eligible_in_denominator": True,
        "hit_at_1": int(bool(is_frozen and ordered[0] == win)),
        "hit_at_8": int(bool(is_frozen and win in ordered)),
        "winner_model_score": p, "multiclass_brier": brier,
        "log_loss": -math.log(p) if p is not None else None,
        "model_calibrated": False,
        "next_race_policy": "REGENERATE_FROM_NEW_PRE_CUTOFF_FACTS_ONLY",
        "model_upgrade_approved": False,
    }


def daily_rollup(races):
    """No result/forecast cherry-picking. Pending / void excluded with reason."""
    if not isinstance(races, list):
        raise ValueError("race ledger required")
    seen = set()
    outcomes = []
    for item in races:
        if not isinstance(item, dict) or not isinstance(item.get("race_id"), str):
            raise ValueError("race identity missing")
        if item["race_id"] in seen:
            raise ValueError("duplicate race result")
        seen.add(item["race_id"])
        outcomes.append(item)
    scored = [x for x in outcomes if x.get("state") == "RESULT_SCORED"
              and x.get("eligible_in_denominator") is True]
    return {
        "discovered_races": len(outcomes),
        "officially_scored_races": len(scored),
        "frozen_forecasts": sum(bool(x.get("frozen")) for x in scored),
        "hits_at_1": sum(x["hit_at_1"] for x in scored),
        "hits_at_8": sum(x["hit_at_8"] for x in scored),
        "hit_at_1_all": sum(x["hit_at_1"] for x in scored) / len(scored) if scored else None,
        "hit_at_8_all": sum(x["hit_at_8"] for x in scored) / len(scored) if scored else None,
        "unscored_states": [
            {"race_id": x["race_id"], "reason": x.get("state", "UNKNOWN")}
            for x in outcomes if x not in scored
        ],
        "results_are_model_training_admissions": False,
        "model_auto_promotion": False,
    }
