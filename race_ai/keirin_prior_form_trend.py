"""Replayable, as-of-safe B-only finish-rank form trend from real past races.

This does NOT infer tactics, sprint acceleration, rider health, or race outcomes.
Source packet validation, SHA and historical evidence replay are performed by
private_research_packet before this function is used by the B research adapter.
At least six comparable, already-observed events are needed. No model weights,
source grants, official forecast, nor live result data are created.
"""
from __future__ import annotations

from datetime import timedelta
import math

from .keirin_result_delivery import utc
from .keirin_winticket_prior_events import PriorSourceError

SCHEMA = "RACE_AI_KEIRIN_B_PRIOR_FORM_TREND_V1"
FORMULA = "keirin-b-matched-finish-percentile-last3-vs-previous3-20261111"
MIN_RECENT = 3
MIN_BASELINE = 3
LOOKBACK_DAYS = 365


def need(yes, reason):
    if not yes:
        raise PriorSourceError(reason)


def compute_prior_form_trend(reference, events, *, as_of):
    """Recent matched-event finish position improvement, scaled to [0,1].

    Event score is (starters - finish_rank)/(starters - 1) and not a calibrated
    win probability. Trend = 0.5 + 0.5 * (mean(newest 3) - mean(previous 3)).
    Equal performance yields neutral 0.5. Every event must have been captured
    before the target cutoff and computation, never after it.
    """
    need(type(reference) is dict and type(events) is list and
         0 <= len(events) <= 100 and type(as_of) is str,
         "FORM_REPLAY_INPUT_INVALID")
    target = reference.get("target") or {}
    riders = reference.get("rider_ids")
    need(type(target) is dict and type(target.get("race_id")) is str and
         type(riders) is list and len(riders) in (7, 9) and
         len(set(riders)) == len(riders) and all(type(v) is str for v in riders),
         "FORM_TARGET_ROSTER_INVALID")
    current = utc(as_of)
    cutoff = utc(target["cutoff"])
    need(current < cutoff and utc(target["as_of"]) <= current,
         "FORM_TARGET_ASOF_INVALID")
    oldest = current - timedelta(days=LOOKBACK_DAYS)
    refs = reference.get("references")
    need(type(refs) is list and len(refs) <= 2000 and
         all(type(r) is dict and type(r.get("race_id")) is str and
             type(r.get("url")) is str for r in refs),
         "FORM_REFERENCE_LIST_INVALID")
    source_links = {r["race_id"]:r["url"] for r in refs}
    need(len(source_links) == len(refs), "FORM_DUPLICATE_SOURCE_LINK")
    all_by_rider = {name: [] for name in riders}
    seen = set()
    for event in events:
        need(type(event) is dict and type(event.get("race_id")) is str and
             event["race_id"] not in seen and
             event["race_id"][:8] < target["race_id"][:8],
             "FORM_FUTURE_OR_DUPLICATE_EVENT")
        seen.add(event["race_id"])
        need(event["race_id"] in source_links and
             event.get("result_source_url") == source_links[event["race_id"]] and
             type(event.get("result_source_sha256")) is str and
             len(event["result_source_sha256"]) == 64 and
             all(c in "0123456789abcdef" for c in event["result_source_sha256"]),
             "FORM_CAPTURED_RESULT_SOURCE_NOT_BOUND")
        start = utc(event["started_at"])
        capture = utc(event["result_captured_at"])
        need(start < capture <= current and capture < cutoff,
             "FORM_EVENT_CAPTURE_INVALID")
        published = event.get("result_published_at")
        if published is not None:
            need(start < utc(published) <= capture,
                 "FORM_RESULT_PUBLICATION_INVALID")
        if (start < oldest or event.get("race_class") != target["race_class"]
                or event.get("race_category") != target["race_category"]
                or event.get("distance_m") != target["distance_m"]):
            continue
        starters = event.get("starters")
        need(type(starters) is list and len(starters) in (7, 9) and
             len({z.get("rider_id") for z in starters if type(z) is dict}) == len(starters),
             "FORM_HISTORICAL_FIELD_INVALID")
        field_size = len(starters)
        positions = [row.get("finish_rank") for row in starters]
        ranked = [p for p in positions if p is not None]
        need(all(type(v) is int and 1 <= v <= field_size for v in ranked)
             and len(set(ranked)) == len(ranked),
             "FORM_DUPLICATE_OR_INVALID_RANK")
        for row in starters:
            name = row["rider_id"]
            if name not in all_by_rider:
                continue
            rank = row.get("finish_rank")
            if rank is None:
                continue
            need(type(rank) is int and 1 <= rank <= field_size,
                 "FORM_RESULT_RANK_INVALID")
            value = (field_size - rank) / (field_size - 1)
            need(math.isfinite(value) and 0 <= value <= 1,
                 "FORM_RESULT_PERCENTILE_INVALID")
            all_by_rider[name].append((start, event["race_id"], value))
    result = {}
    for name, values in all_by_rider.items():
        values.sort(reverse=True)
        count = len(values)
        active = values[:MIN_RECENT]
        baseline = values[MIN_RECENT:MIN_RECENT + MIN_BASELINE]
        enough = len(active) == MIN_RECENT and len(baseline) == MIN_BASELINE
        trend = None
        if enough:
            new_mean = math.fsum(v[2] for v in active) / MIN_RECENT
            old_mean = math.fsum(v[2] for v in baseline) / MIN_BASELINE
            trend = 0.5 + 0.5 * (new_mean - old_mean)
            need(math.isfinite(trend) and 0 <= trend <= 1,
                 "FORM_TREND_RANGE_INVALID")
        result[name] = {
            "candidate_value": trend,
            "sample_count": MIN_RECENT + MIN_BASELINE if enough else count,
            "recent_samples": len(active),
            "baseline_samples": len(baseline),
            "minimum_required": MIN_RECENT + MIN_BASELINE,
            "formula_version": FORMULA,
            "status": "OBSERVED_PRIOR_TREND_CANDIDATE" if enough
                      else "INSUFFICIENT_COMPARABLE_PRIOR_RESULTS",
            "approved_for_pr71_input": False,
        }
    return {"schema": SCHEMA, "as_of": as_of, "riders": result,
            "candidate_count": sum(r["candidate_value"] is not None for r in result.values()),
            "model_training_or_prediction_executed": False,
            "provider_requests": 0}
