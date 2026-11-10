"""Fail-closed clock and evidence gates for a real prospective 15-to-10 minute race.

No provider GETs, source-rights self-approval, model inference, or repository
writes occur here. A successful synthetic test does not establish a live proof.
Only a new, independently read-back, authorized original can be graded.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import re

SPORTS = frozenset(("boat", "keirin", "autorace"))
HEX = re.compile(r"^[0-9a-f]{64}$")
MODEL_LIMIT = 40
MIN_SECONDS = 600
MAX_SECONDS = 900
CUTOFF_MARGIN_SECONDS = 65


class LiveProofError(ValueError):
    pass


def _require(ok, code):
    if not ok:
        raise LiveProofError(code)


def _instant(value):
    _require(type(value) is str and len(value) <= 40, "TIME_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise LiveProofError("TIME_INVALID") from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
             "TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _sha(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def _triple(value):
    return (type(value) is list and len(value) == 3
            and all(type(v) is int and 1 <= v <= 99 for v in value)
            and len(set(value)) == 3)


def select_window(schedule, at):
    """Return a bounded, non-secret status from an independently sourced grid.

    No unverified clock or self-declared permission may authorize a forecast.
    No start time: HOLD, never substitute official cutoff as a start.
    """
    _require(type(schedule) is dict, "SCHEDULE_REQUIRED")
    if not schedule.get("scheduled_start_at"):
        return "HOLD_NO_VERIFIED_START_TIME"
    if not schedule.get("official_cutoff_at"):
        return "HOLD_NO_VERIFIED_CUTOFF_TIME"
    if not schedule.get("schedule_published_at"):
        return "HOLD_NO_SCHEDULE_PUBLICATION_TIME"
    _require(schedule.get("sport") in SPORTS, "SPORT_INVALID")
    start = _instant(schedule["scheduled_start_at"])
    cutoff = _instant(schedule["official_cutoff_at"])
    published = _instant(schedule["schedule_published_at"])
    observed = _instant(at)
    _require(cutoff <= start, "CUTOFF_AFTER_START_INVALID")
    if published > observed:
        return "HOLD_SCHEDULE_PUBLISHED_AFTER_FREEZE"
    delta = (start - observed).total_seconds()
    if delta > MAX_SECONDS:
        return "WAIT_BEFORE_15_MINUTE_WINDOW"
    if delta < MIN_SECONDS:
        return "HOLD_MISSED_10_MINUTE_DEADLINE"
    if (cutoff - observed).total_seconds() <= CUTOFF_MARGIN_SECONDS:
        return "HOLD_OFFICIAL_CUTOFF_MARGIN"
    return "IN_15_TO_10_MINUTE_PRE_RACE_WINDOW"


def audit_frozen_race(saved, *, start_evidence=None, result=None,
                      expected_models=(), independent_model_readback=False,
                      independently_authenticated_result=False):
    """Check one *already frozen* race; never create or rewrite predictions.

    saved: existing source/SHA-validated immutable ledger.read_suite() record.
    start_evidence: independently sourced start/cutoff as-of the freeze,
      bound to its source SHA. Omission means HOLD.
    result: existing separately verified revision, never an inferred outcome.
    The caller must establish receipt authority and external readback itself.
    Output contains no race ID, ticket combinations, or private source details.
    """
    _require(type(saved) is dict, "SAVED_ORIGINAL_REQUIRED")
    _require(type(expected_models) in (tuple, list) and
             1 <= len(expected_models) <= MODEL_LIMIT and
             all(type(m) is str and 1 <= len(m) <= 128
                 for m in expected_models) and
             len(set(expected_models)) == len(expected_models),
             "EXPECTED_MODEL_ROSTER_INVALID")
    source, suite = saved.get("source"), saved.get("suite")
    _require(type(source) is dict and type(suite) is dict,
             "SOURCE_AND_SUITE_REQUIRED")
    _require(_sha(saved.get("source_sha256")) and
             type(saved.get("persisted_at")) is str,
             "IMMUTABLE_ORIGINAL_PROOF_MISSING")
    models = suite.get("models")
    _require(type(models) is dict, "MODELS_REQUIRED")
    if set(models) != set(expected_models):
        return {"status": "HOLD_MODEL_ROSTER_INCOMPLETE", "models": len(models)}
    if not independent_model_readback:
        return {"status": "HOLD_SEPARATE_RUNNER_READBACK_MISSING",
                "models": len(models)}
    if not isinstance(start_evidence, dict):
        return {"status": "HOLD_NO_VERIFIED_START_TIME",
                "models": len(models)}
    if (start_evidence.get("race_id") != source.get("race_id") or
            start_evidence.get("source_sha256") != saved["source_sha256"] or
            start_evidence.get("official_cutoff_at") !=
            source.get("official_cutoff_at")):
        return {"status": "HOLD_SCHEDULE_OR_SOURCE_SHA_MISMATCH",
                "models": len(models)}
    # A timestamp-only packet cannot prove authorization. The trusted runner
    # must supply an independently checked receipt, never a guessed flag.
    if start_evidence.get("authority") != "INDEPENDENTLY_VERIFIED_SOURCE":
        return {"status": "HOLD_SCHEDULE_AUTHORITY_UNVERIFIED",
                "models": len(models)}
    try:
        window = select_window(start_evidence, saved["persisted_at"])
    except LiveProofError:
        return {"status": "HOLD_SCHEDULE_TIME_INVALID", "models": len(models)}
    if window != "IN_15_TO_10_MINUTE_PRE_RACE_WINDOW":
        return {"status": window, "models": len(models)}
    if any(type(model) is not dict
           or model.get("model_id") != mid
           or not _sha(model.get("prediction_sha256"))
           or type(model.get("ordered_top8")) is not list
           or not 1 <= len(model["ordered_top8"]) <= 8
           or not all(_triple(pick) for pick in model["ordered_top8"])
           or len({tuple(t) for t in model["ordered_top8"]}) !=
                  len(model["ordered_top8"])
           for mid, model in models.items()):
        return {"status": "HOLD_INVALID_MODEL_TICKETS_OR_SHA",
                "models": len(models)}
    if result is None or result.get("status") not in ("FINAL", "CANCELLED"):
        return {"status": "HOLD_RESULT_PENDING", "models": len(models)}
    if not independently_authenticated_result:
        return {"status": "HOLD_OFFICIAL_RESULT_AUTHENTICATION_MISSING",
                "models": len(models)}
    if result.get("race_id") != source.get("race_id") or not _sha(
            result.get("source_sha256")):
        return {"status": "HOLD_RESULT_ID_OR_SHA_MISMATCH", "models": len(models)}
    try:
        published = _instant(result["source_published_at"])
        start = _instant(start_evidence["scheduled_start_at"])
        frozen = _instant(saved["persisted_at"])
    except (KeyError, LiveProofError):
        return {"status": "HOLD_RESULT_TIMESTAMP_INVALID", "models": len(models)}
    if not frozen < start <= published:
        return {"status": "HOLD_RESULT_NOT_AFTER_START", "models": len(models)}
    if result["status"] == "CANCELLED":
        return {"status": "VOID_OFFICIAL_CANCELLATION", "models": len(models),
                "hits": 0, "misses": 0}
    winners = result.get("winning_triples")
    if (type(winners) is not list or not 1 <= len(winners) <= 8
            or not all(_triple(w) for w in winners)):
        return {"status": "HOLD_INVALID_OFFICIAL_FINISH", "models": len(models)}
    winning = {tuple(w) for w in winners}
    count = sum(any(tuple(p) in winning for p in m["ordered_top8"])
                for m in models.values())
    return {"status": "PROVEN_TIME_WINDOW_MODEL_RESULT_MATCH",
            "models": len(models), "hits": count,
            "misses": len(models) - count}


def summarize(records):
    """Count statuses without printing private race IDs or forecast tickets."""
    _require(type(records) is list and len(records) <= 10000,
             "REPORT_BOUNDS_INVALID")
    counts = Counter()
    proven_pairs = proven_hits = proven_misses = 0
    for record in records:
        _require(type(record) is dict and
                 type(record.get("status")) is str and
                 len(record["status"]) <= 90, "BAD_PROOF_RECORD")
        counts[record["status"]] += 1
        if record["status"] == "PROVEN_TIME_WINDOW_MODEL_RESULT_MATCH":
            proven_pairs += record["models"]
            proven_hits += record["hits"]
            proven_misses += record["misses"]
    return {"schema": "RACE_AI_LIVE_15MIN_PROOF_COUNTS_V1",
            "races_checked": len(records),
            "proven_races": counts["PROVEN_TIME_WINDOW_MODEL_RESULT_MATCH"],
            "model_result_pairs_proven": proven_pairs,
            "hits": proven_hits, "misses": proven_misses,
            "holds": dict(sorted((s, n) for s, n in counts.items()
                                 if s != "PROVEN_TIME_WINDOW_MODEL_RESULT_MATCH")),
            "predictor_run_by_audit": False,
            "official_source_fetched_by_audit": False}
