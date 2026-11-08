"""Fixed pre-event historical signal rules for the *existing* PR71 model.

No new predictor, factor weights or training. Computes only bounded research
CANDIDATES from older race outcomes whose published time precedes the target
snapshot. Every historical event is source-stamped. Never re-label retrospective
calculation as original pre-cutoff forecast. No odds or target-result input.

Close-speed percentile is NOT acceleration; acceleration requires two adjacent
measured distance/time segments from past events. "Line coordination" is a
joint top-three *association*, not a causal measure of teamwork. "Bank fit" is
a matched-class/length venue-versus-other-place top-three differential, not a
calibrated win probability. None may enter PR71 without separate evidence,
rights and 347-factor checks.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import math

from .keirin_result_delivery import canonical, utc

SCHEMA = "RACE_AI_KEIRIN_HISTORICAL_PRIOR_SIGNAL_INPUT_V1"
OUTPUT_SCHEMA = "RACE_AI_KEIRIN_HISTORICAL_PRIOR_SIGNAL_CANDIDATES_V1"
FORMULA_VERSION = "keirin-prior-signals-research-v1-fixed-20261109"
LOOKBACK_DAYS = 365
MIN_FINISH_SAMPLES = 3
MIN_SPLIT_SAMPLES = 3
MIN_LINE_SAMPLES = 5
MIN_VENUE_SAMPLES = 5
MIN_COMPARISON_SAMPLES = 5
MIN_FIELD_TIMES = 5


class PriorSignalError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise PriorSignalError(code)


def _timestamp(value):
    need(type(value) is str, "SOURCE_TIME_STRING_REQUIRED")
    try:
        return utc(value)
    except (ValueError, TypeError, KeyError) as exc:
        raise PriorSignalError("SOURCE_TIME_INVALID") from exc


def _number(value, *, low=0, high=1_000_000):
    need(type(value) in (float, int) and
         math.isfinite(value) and low <= value <= high,
         "NONFINITE_OR_BAD_PRIOR_NUMBER")
    return float(value)


def _url(value):
    need(type(value) is str and
         value.startswith("https://") and
         len(value) <= 512,
         "HISTORICAL_SOURCE_REF_REQUIRED")


def _sha(value):
    need(type(value) is str and len(value) == 64 and
         all(c in "0123456789abcdef" for c in value),
         "HISTORICAL_SOURCE_SHA_REQUIRED")


def _percentile_better_when_lower(values, needle):
    """Average tied positions, with best=1 and worst=0."""
    need(len(values) >= MIN_FIELD_TIMES, "NOT_ENOUGH_TIMED_PEERS")
    sorted_values = sorted(values)
    lower = sum(v < needle for v in sorted_values)
    equal = sum(v == needle for v in sorted_values)
    need(equal > 0, "CLOSING_SAMPLE_NOT_IN_RACE")
    mid_index = lower + (equal - 1) / 2
    return 1 - mid_index / (len(values) - 1)


def _percentile_better_when_higher(values, needle):
    need(len(values) >= MIN_FIELD_TIMES, "NOT_ENOUGH_SPLIT_PEERS")
    neg = [-v for v in values]
    return _percentile_better_when_lower(neg, -needle)


def _acceleration(segments):
    """Two observed adjacent segments; finite-difference speed derivative.

    Relative times alone don't establish instantaneous acceleration. Units
    m/s², preliminary interval-average proxy, not athlete telemetry.
    """
    if segments is None:
        return None
    need(type(segments) is list and len(segments) == 2,
         "TWO_ADJACENT_SPLITS_REQUIRED")
    for item in segments:
        need(type(item) is dict and set(item) == {
            "distance_m", "elapsed_s"}, "SPLIT_FIELDS_INVALID")
        _number(item["distance_m"], low=30, high=250)
        _number(item["elapsed_s"], low=1, high=60)
    d1,t1 = segments[0]["distance_m"],segments[0]["elapsed_s"]
    d2,t2 = segments[1]["distance_m"],segments[1]["elapsed_s"]
    need(abs(d1-d2) < 1e-9, "SPLIT_SEGMENTS_NOT_EQUAL_LENGTH")
    v1,v2=d1/t1,d2/t2
    need(4 <= v1 <= 26 and 4 <= v2 <= 26,
         "SPLIT_AVERAGE_SPEED_OUTSIDE_VALIDATED_RANGE")
    return (v2-v1)/((t1+t2)/2)


def _field(record, own_id):
    starters=record["starters"]
    need(type(starters) is list and len(starters) in (7,9),
         "PRIOR_RACE_SEVEN_OR_NINE_REQUIRED")
    members={}
    for p in starters:
        need(type(p) is dict and set(p)=={
            "rider_id", "finish_rank", "line_id", "agari_s",
            "final_two_splits"}, "PRIOR_RACE_STARTER_SHAPE")
        rid=p["rider_id"]
        need(type(rid) is str and rid and
             len(rid)<=100 and rid not in members,
             "PRIOR_RACE_RIDER_ID_BAD")
        fin=p["finish_rank"]
        need(fin is None or type(fin) is int and 1 <= fin <= len(starters),
             "PRIOR_RACE_FINISH_RANK_INVALID")
        need(p["line_id"] is None or
             type(p["line_id"]) is str and p["line_id"] and
             len(p["line_id"])<=50, "PRIOR_LINE_ID_INVALID")
        if p["agari_s"] is not None:
            _number(p["agari_s"],low=8,high=30)
        if p["final_two_splits"] is not None:
            need(fin is not None and p["agari_s"] is not None,
                 "SPLIT_WITHOUT_FINISH_OR_AGARI")
            _acceleration(p["final_two_splits"])
        members[rid]=p
    need(own_id in members, "OWNER_RIDER_NOT_IN_PRIOR_EVENT")
    present=[p["finish_rank"] for p in starters if p["finish_rank"] is not None]
    need(len(present)==len(set(present)),
         "DUPLICATE_FINISH_RANK_IN_PRIOR_EVENT")
    # An absence of line membership is unknown, never a solo race.
    me=members[own_id]
    peers=[p for p in starters if p["rider_id"]!=own_id and
           me["line_id"] is not None and
           p["line_id"]==me["line_id"]]
    agari=[p["agari_s"] for p in starters
           if p["finish_rank"] is not None and p["agari_s"] is not None]
    closing = (_percentile_better_when_lower(agari, me["agari_s"])
               if me["agari_s"] is not None and
               me["finish_rank"] is not None and
               len(agari) >= MIN_FIELD_TIMES else None)
    split_values=[_acceleration(p["final_two_splits"])
                  for p in starters if p["final_two_splits"] is not None]
    actual_split = (_acceleration(me["final_two_splits"])
                    if me["final_two_splits"] is not None else None)
    accel = (_percentile_better_when_higher(split_values, actual_split)
             if actual_split is not None and
             len(split_values) >= MIN_FIELD_TIMES else None)
    joint_top3=(me["finish_rank"] in (1,2,3) and
                any(p["finish_rank"] in (1,2,3) for p in peers))
    return {"closing_percentile":closing,
            "split_acceleration_percentile":accel,
            "had_known_prior_line":bool(peers),
            "joint_top3":joint_top3,
            "own_top3":me["finish_rank"] in (1,2,3),
            "starter_count":len(starters)}


def compute_prior_signal_candidates(packet):
    """All event rows must be explicitly as-of-safe; fails on a future row.

    "published_at" is a source claim, not an independent witness. The output
    remains CANDIDATE_ONLY even for structurally complete packs.
    """
    need(type(packet) is dict and set(packet)=={
        "schema", "target", "prior_events"}, "PRIOR_SIGNAL_PACKET_SHAPE")
    need(packet["schema"]==SCHEMA, "PRIOR_SIGNAL_SCHEMA_MISMATCH")
    target=packet["target"]
    need(type(target) is dict and set(target)=={
        "race_id", "as_of", "cutoff", "rider_id",
        "venue", "race_class", "distance_m", "race_category",
    }, "PRIOR_TARGET_SHAPE")
    need(all(type(target[k]) is str and target[k] for k in (
        "race_id", "rider_id", "venue", "race_class", "race_category")),
        "PRIOR_TARGET_IDENTITY_REQUIRED")
    cutoff=_timestamp(target["cutoff"])
    asof=_timestamp(target["as_of"])
    need(asof<cutoff, "TARGET_SOURCE_NOT_BEFORE_CUTOFF")
    distance=_number(target["distance_m"],low=100,high=10000)
    events=packet["prior_events"]
    need(type(events) is list and len(events)<=100,
         "UNBOUNDED_PRIOR_RACE_EVENTS")
    seen=set()
    results=[]
    older_than=asof-timedelta(days=LOOKBACK_DAYS)
    count_outside_window=0
    for r in events:
        need(type(r) is dict and set(r)=={
            "race_id", "started_at", "ended_at",
            "lineup_published_at", "result_published_at",
            "lineup_source_url", "result_source_url",
            "lineup_source_sha256", "result_source_sha256",
            "venue", "race_class", "distance_m",
            "race_category", "starters",
        }, "HISTORICAL_EVENT_SHAPE")
        rid=r["race_id"]
        need(type(rid) is str and rid and rid not in seen
             and rid!=target["race_id"], "PRIOR_EVENT_DUPLICATE_OR_TARGET")
        seen.add(rid)
        for url in ("lineup_source_url", "result_source_url"):
            _url(r[url])
        for sha in ("lineup_source_sha256", "result_source_sha256"):
            _sha(r[sha])
        start=_timestamp(r["started_at"])
        end=_timestamp(r["ended_at"])
        pub_lineup=_timestamp(r["lineup_published_at"])
        pub_result=_timestamp(r["result_published_at"])
        need(pub_lineup<=start<end<=pub_result<=asof,
             "PRIOR_EVENT_RESULT_OR_LINEUP_NOT_PUBLIC_ASOF")
        need(type(r["venue"]) is str and r["venue"] and
             type(r["race_class"]) is str and r["race_class"] and
             type(r["race_category"]) is str and r["race_category"],
             "PRIOR_EVENT_CLASS_OR_VENUE_MISSING")
        _number(r["distance_m"],low=100,high=10000)
        if end < older_than:
            count_outside_window+=1
            continue
        if (r["race_class"]!=target["race_class"] or
            r["race_category"]!=target["race_category"] or
            r["distance_m"]!=distance):
            continue
        outcome=_field(r,target["rider_id"])
        results.append({**outcome,"venue":r["venue"],
                        "source_digest":sha256(canonical(r)).hexdigest(),
                        "ended_at":r["ended_at"]})
    # Fixed prior-race window + minimum evidence; abstain instead of zero
    # when the sample is too small, has no actual splits, or lacks venue peers.
    finish=[p["closing_percentile"] for p in results
            if p["closing_percentile"] is not None]
    accel=[p["split_acceleration_percentile"] for p in results
           if p["split_acceleration_percentile"] is not None]
    lines=[p for p in results if p["had_known_prior_line"]]
    same=[p for p in results if p["venue"]==target["venue"]]
    other=[p for p in results if p["venue"]!=target["venue"]]
    features={}
    def candidate(name,value,n,minimum,definition):
        features[name]={"candidate_value":value if n>=minimum else None,
                        "sample_count":n,"minimum_required":minimum,
                        "status":"RESEARCH_CANDIDATE_UNVERIFIED_ASOF"
                                 if n>=minimum else "INSUFFICIENT_PAST_SAMPLES",
                        "definition":definition,
                        "approved_for_pr71_input":False}
    candidate("finishing_power",math.fsum(finish)/len(finish)
              if finish else None,len(finish),MIN_FINISH_SAMPLES,
              "mean within-prior-race last-half-lap-time percentile, NOT acceleration")
    candidate("sprint_acceleration",math.fsum(accel)/len(accel)
              if accel else None,len(accel),MIN_SPLIT_SAMPLES,
              "mean rank of measured 2-adjacent-equal-distance split acceleration m/s2")
    candidate("line_coordination",
              sum(p["joint_top3"] for p in lines)/len(lines)
              if lines else None,len(lines),MIN_LINE_SAMPLES,
              "joint top3 association in previous races with confirmed line mates, not causal")
    venue_hits=sum(p["own_top3"] for p in same)
    other_hits=sum(p["own_top3"] for p in other)
    venue_level=((venue_hits+1)/(len(same)+2) if same else None)
    other_level=((other_hits+1)/(len(other)+2) if other else None)
    matched_bank=(0.5+(venue_level-other_level)/2
                  if venue_level is not None and other_level is not None
                  else None)
    candidate("bank_fit",matched_bank,
              min(len(same),len(other)),
              max(MIN_VENUE_SAMPLES,MIN_COMPARISON_SAMPLES),
              "0.5+0.5*(beta11_same_venue_top3_rate - beta11_other_venue_top3_rate), same class/category/distance")
    features["bank_fit"].update({
        "same_venue_count":len(same),"other_venue_count":len(other),
        "required_each_group":MIN_VENUE_SAMPLES,
    })
    # Do NOT duplicate old half-lap percentile into the PR71
    # last_lap_acceleration key without measured acceleration.
    return {
        "schema":OUTPUT_SCHEMA,
        "formula_version":FORMULA_VERSION,
        "source_packet_sha256":sha256(canonical(packet)).hexdigest(),
        "event_count_provided":len(events),
        "past_events_older_than_window":count_outside_window,
        "comparison_eligible_past_events":len(results),
        "features":features,
        "needs_separate_replay_input_adapter":True,
        "source_published_at_independently_authenticated":False,
        "source_use_rights_verified":False,
        "external_pre_cutoff_prediction_witness":False,
        "original_pr71_forecast_exists":False,
        "no_training_or_new_model":True,
        "no_hindsight_target_results":True,
        "real_world_accuracy":None,
        "status":"CANDIDATE_ONLY_NOT_ADMITTED_FOR_PR71",
    }
