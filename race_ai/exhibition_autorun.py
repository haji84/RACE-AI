"""Fail-closed, provider-neutral BOAT post-exhibition run coordinator.

This adapter ONLY coordinates existing odds-free boat_multi_feature_models.
It does not fetch official sites, grant source rights, sign timestamps, send
notifications, or implement an external durable claim store. The injected
claim/submit/readback callbacks must be supplied by an independently reviewed
cloud adapter before live operation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from .boat_multi_feature_models import FeatureModelError, MODEL_IDS, run_models
from .cutoff_job_queue import QueueError, plan

MARGIN = timedelta(seconds=120)
STATES = frozenset({"ABSENT", "CLAIMED", "UNRESOLVED_POST", "VERIFIED"})
TICKET = re.compile(r"^[1-6]-[1-6]-[1-6]$")


def _moment(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("offset-aware timestamp required")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("offset-aware timestamp required")
    return result.astimezone(timezone.utc)


def _safe_state(obj):
    if not isinstance(obj, dict) or obj.get("state") not in STATES:
        raise ValueError("receipt status unavailable")
    return obj["state"]


def _snapshot_is_exhibition(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("entrants"), list):
        return False
    entrants = snapshot["entrants"]
    if (len(entrants) != 6 or any(not isinstance(x, dict) or type(x.get("lane")) is not int for x in entrants)
            or {x["lane"] for x in entrants} != set(range(1, 7))):
        return False
    for item in entrants:
        features = item.get("features")
        if not isinstance(features, dict):
            return False
        # Existing validated model requires both values. Never infer ST=0
        # or fill missing exhibition fields with defaults.
        for key in ("exhibition_time_seconds", "exhibition_start_seconds"):
            if type(features.get(key)) not in (int, float):
                return False
    return True


def _record(race_id, state, **extra):
    return {"race_id": race_id, "state": state, **extra}


def tick(records, *, clock, readback, acquire, claim, submit, verify,
         max_collect=12, margin=MARGIN):
    """Advance each race at most once, earliest verified cutoff first.

    readback(race) -> {state: ABSENT|CLAIMED|UNRESOLVED_POST|VERIFIED}
    acquire(race) -> {status: AVAILABLE, snapshot: validated six-boat input}
                     or {status: PENDING|UNAVAILABLE|RIGHTS_BLOCKED}
    claim(race, forecast) -> {state: CREATED} or existing/uncertain state.
    submit(race, forecast) -> {state: SUBMITTED}, and may be ambiguous.
    verify(race, forecast) -> TRUE only on independent, pre-cutoff durable
                              readback of the exact frozen prediction hash.
    If a POST might have been sent, NEVER dispatch another from this tick.
    A subsequent tick must first check persistent claim state.
    """
    if not callable(clock) or not all(callable(f) for f in
            (readback, acquire, claim, submit, verify)):
        raise ValueError("all runtime adapters required")
    if type(max_collect) is not int or not 1 <= max_collect <= 100:
        raise ValueError("bounded fetch budget required")
    if not isinstance(margin, timedelta) or margin < timedelta(seconds=60):
        raise ValueError("unsafe cutoff margin")
    start = _moment(clock())
    ordered = plan(records, now=start.isoformat())["jobs"]
    index = {r["race_id"]: r for r in records}
    rows = []
    fetched = 0
    for item in ordered:
        race_id = item["race_id"]
        row = index[race_id]
        decision = item["state"]
        if row.get("sport") != "boat":
            rows.append(_record(race_id, "NOT_BOAT")); continue
        if decision != "READY_FOR_AUTHORIZED_INPUT_AND_MODEL":
            rows.append(_record(race_id, decision)); continue
        cutoff = _moment(row["cutoff_at"])
        try:
            state = _safe_state(readback(row))
        except (ValueError, KeyError, TypeError, OSError):
            rows.append(_record(race_id, "READBACK_UNAVAILABLE")); continue
        if state != "ABSENT":
            rows.append(_record(race_id,
                "ALREADY_FROZEN" if state == "VERIFIED" else "UNCERTAIN_OR_RESERVED_DO_NOT_REPOST"))
            continue
        if _moment(clock()) + margin >= cutoff:
            rows.append(_record(race_id, "TOO_LATE_FOR_SAFE_FORECAST")); continue
        if fetched >= max_collect:
            rows.append(_record(race_id, "FETCH_BUDGET_EXCEEDED")); continue
        fetched += 1
        try:
            source = acquire(row)
        except (ValueError, KeyError, TypeError, OSError):
            rows.append(_record(race_id, "SOURCE_FETCH_FAILED")); continue
        if (not isinstance(source, dict) or source.get("status") not in
                ("AVAILABLE", "PENDING", "UNAVAILABLE", "RIGHTS_BLOCKED")):
            rows.append(_record(race_id, "SOURCE_INVALID")); continue
        if source["status"] != "AVAILABLE":
            rows.append(_record(race_id, "EXHIBITION_" + source["status"])); continue
        snapshot = source.get("snapshot")
        if (source.get("source_rights_verified") is not True or
                source.get("exhibition_identity_verified") is not True):
            rows.append(_record(race_id, "SOURCE_EVIDENCE_NOT_VERIFIED")); continue
        if not _snapshot_is_exhibition(snapshot):
            rows.append(_record(race_id, "EXHIBITION_INCOMPLETE")); continue
        try:
            coherent = (snapshot.get("race_id") == race_id and
                _moment(snapshot.get("sales_cutoff_at")) == cutoff and
                _moment(snapshot.get("as_of")) <= _moment(clock()) and
                snapshot.get("scope") == "OPERATOR_SUPPLIED_RESEARCH")
        except (ValueError, TypeError, AttributeError, OverflowError):
            coherent = False
        if not coherent:
            rows.append(_record(race_id, "SOURCE_RACE_OR_CLOCK_MISMATCH")); continue
        try:
            forecast = run_models(snapshot)[MODEL_IDS[0]]
        except (FeatureModelError, ValueError, KeyError, TypeError):
            rows.append(_record(race_id, "MODEL_INPUT_REJECTED")); continue
        if (_moment(clock()) + margin >= cutoff or
                forecast.get("odds_independent") is not True or
                forecast.get("prediction_probabilities_calibrated") is not False or
                len(forecast.get("ordered_top8", [])) != 8):
            rows.append(_record(race_id, "CUTOFF_OR_MODEL_GATE_REJECTED")); continue
        try:
            reserved = claim(row, forecast)
        except (ValueError, OSError):
            rows.append(_record(race_id, "CLAIM_FAILED_NO_POST")); continue
        if not isinstance(reserved, dict) or reserved.get("state") != "CREATED":
            rows.append(_record(race_id, "CLAIM_NOT_CREATED_NO_POST")); continue
        if _moment(clock()) + margin >= cutoff:
            rows.append(_record(race_id, "CLAIMED_BUT_TOO_LATE_NO_POST")); continue
        # Once claim is durable, ambiguous POST failures are deliberately NOT
        # retried. External operator/readback reconciliation is required.
        try:
            posted = submit(row, forecast)
            if not isinstance(posted, dict) or posted.get("state") != "SUBMITTED":
                raise ValueError("unconfirmed POST")
            complete = verify(row, forecast) is True
        except (ValueError, KeyError, TypeError, OSError):
            complete = False
        if complete:
            rows.append(_record(race_id, "FROZEN_READBACK_VERIFIED",
                model_id=forecast["model_id"],
                ordered_top8=forecast["ordered_top8"],
                prediction_sha256=forecast["prediction_sha256"],
                prediction_probabilities_calibrated=False))
        else:
            rows.append(_record(race_id, "POST_UNCERTAIN_DO_NOT_RETRY"))
    return {"schema": "RACE_AI_BOAT_EXHIBITION_TICK_V1",
            "as_of": start.isoformat(), "total_races": len(rows),
            "source_fetch_count": fetched, "results": rows,
            "live_scheduling_enabled": False}
