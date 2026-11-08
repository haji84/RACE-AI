"""Offline retrospective PR71 four-model replay with strict as-of separation.

This is NOT an originally frozen pre-race forecast. Predictors are read from
an owner-provided archived pre-race packet; results are not accepted until
after the entire prediction suite has been computed and hashed. Source rights,
publication/capture dates and the full PR71 347-factor gate are required for
real-data research. The execution timestamp is ALWAYS the actual *later*
time. Synthetic fixtures prove only that the procedure can work.

Never backdate an actual inference, use post-result features, write a real
past event into the prospective prediction store, or count retrospective
predictions as formal Hit@8.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from itertools import permutations
import math
import re

from .comprehensive_four_sport_models import digest as model_digest
from .four_sport_model_suite import ALL_MODELS, run_suite, verify_suite
from .keirin_preflight import audit_pre_race
from .keirin_result_delivery import canonical, utc
from .keirin_pr71_four_model_rank import checked_four_model_suite

SCHEMA = "RACE_AI_KEIRIN_PR71_HISTORICAL_ASOF_REPLAY_V1"
REPORT = "RACE_AI_KEIRIN_PR71_HISTORICAL_ASOF_SETTLEMENT_V1"
SHA = re.compile(r"^[a-f0-9]{40}$")
MANSHA_THRESHOLD = 10000


class HistoricalReplayGateError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise HistoricalReplayGateError(code)


def _clock(value):
    require(type(value) is str, "AWARE_CLOCK_REQUIRED")
    try:
        return utc(value)
    except (ValueError,TypeError,KeyError) as exc:
        raise HistoricalReplayGateError("INVALID_AWARE_CLOCK") from exc


def select_out_of_time_cohorts(training_days, holdout_days, *,
                               embargo_days=1):
    """Freeze day groups BEFORE loading any holdout result labels."""
    from datetime import date, timedelta
    require(type(training_days) is list and type(holdout_days) is list
            and training_days and holdout_days and
            type(embargo_days) is int and embargo_days >= 0,
            "TEMPORAL_COHORT_REQUIRED")
    try:
        train = [date.fromisoformat(d) for d in training_days]
        test = [date.fromisoformat(d) for d in holdout_days]
    except (TypeError,ValueError):
        raise HistoricalReplayGateError("INVALID_COHORT_DATE") from None
    require(len(set(train)) == len(train)
            and len(set(test)) == len(test)
            and max(train)+timedelta(days=embargo_days) < min(test),
            "TRAIN_LABELS_OVERLAP_HOLDOUT_OR_EMBARGO")
    return {"training_dates":sorted(training_days),
            "holdout_dates":sorted(holdout_days),
            "embargo_days":embargo_days,
            "holdout_labels_allowed_as_model_inputs":False,
            "model_reselection_using_holdout_forbidden":True}


def prepare_historical_pr71(snapshot, *, performed_at,
                            model_code_commit_sha, source_admission=None):
    """Compute historical research predictions *without receiving results*.

    Fully verified historical sources may be replayed; this still cannot prove
    when a prediction originally existed. Never call the prospective freeze
    with a forged historical clock or write to its live forecast table.
    """
    require(type(snapshot) is dict
            and snapshot.get("schema") == "RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1"
            and type(snapshot.get("facts")) is dict
            and type(snapshot.get("starters")) is list
            and "pr71_evidenced_snapshot" in snapshot["facts"],
            "FULL_HISTORICAL_PR71_SNAPSHOT_MISSING")
    require(type(model_code_commit_sha) is str
            and SHA.fullmatch(model_code_commit_sha) is not None,
            "EXACT_MODEL_COMMIT_SHA_REQUIRED")
    now = _clock(performed_at)
    asof = _clock(snapshot.get("as_of"))
    cutoff = _clock(snapshot.get("official_cutoff_at"))
    require(asof < cutoff <= now,
            "THIS_IS_NOT_A_PAST_EVENT_OR_INVALID_ASOF")
    evidence = snapshot["facts"]["pr71_evidenced_snapshot"]
    require(type(evidence) is dict and
            evidence.get("scope") in ("SYNTHETIC_ONLY",
                                       "OPERATOR_SUPPLIED_RESEARCH"),
            "UNVERIFIED_SOURCE_SCOPE")
    require(snapshot["race_id"] == evidence["race"]["race_id"]
            and snapshot["as_of"] == evidence["race"]["as_of"]
            and snapshot["official_cutoff_at"] ==
                evidence["race"]["sales_cutoff_at"]
            and sorted(snapshot["starters"]) ==
                sorted(p["number"] for p in evidence["participants"]),
            "SNAPSHOT_AND_EVENT_MISMATCH")

    if evidence["scope"] == "OPERATOR_SUPPLIED_RESEARCH":
        require(callable(source_admission),
                "REAL_HISTORICAL_SOURCE_RIGHTS_NOT_VERIFIED")
        audit = snapshot["facts"].get("keirin_pre_race_audit_v1")
        require(type(audit) is dict,
                "HISTORICAL_347_FACTOR_AUDIT_MISSING")
        outcome = audit_pre_race(
            audit, race_id=snapshot["race_id"],
            starters=snapshot["starters"],
            cutoff_at=snapshot["official_cutoff_at"],
            snapshot_as_of=snapshot["as_of"],
            issued_at=snapshot["as_of"],
            evidence_sha256=sha256(canonical(evidence)).hexdigest())
        require(outcome["all_factors_checked"] and
                outcome["full_forecast_gate_passed"],
                "HISTORICAL_REQUIRED_FIELDS_UNVERIFIED")

    # run_suite reads ONLY the evidence snapshot. The results are neither
    # passed to this function nor imported into the estimator.
    suite = run_suite(evidence, allow_source=source_admission)
    checked_four_model_suite(snapshot, suite)
    require(verify_suite(suite) is True and len(ALL_MODELS) == 4,
            "PR71_FOUR_EXISTING_MODELS_REQUIRED")
    record = {
        "schema":SCHEMA,
        "race_id":snapshot["race_id"],
        "event_date_jst":evidence["race"]["event_date_jst"],
        "source_asof_claimed":snapshot["as_of"],
        "official_cutoff_claimed":snapshot["official_cutoff_at"],
        "actually_recomputed_at":performed_at,
        "model_code_commit_sha_selected":model_code_commit_sha,
        "model_commit_precedes_race_independently_proven":False,
        "historical_source_retrieval_before_cutoff_proven":False,
        "independent_original_pre_cutoff_forecast_receipt":None,
        "snapshot_sha256":sha256(canonical(snapshot)).hexdigest(),
        "suite_sha256":suite["suite_sha256"],
        "full_model_suite":suite,
        "model_version_is_not_result_time_adjusted":True,
        "forecast_generated_after_race":True,
        "predictions_are_retrospective_only":True,
        "official_or_prospective_performance":False,
    }
    record["retrospective_record_sha256"] = sha256(canonical(record)).hexdigest()
    return record


def evaluate_historical_without_repredicting(prepared, published_result):
    """A separate label step: immutable suite precomputed in previous call."""
    require(type(prepared) is dict and prepared.get("schema") == SCHEMA
            and prepared.get("predictions_are_retrospective_only") is True
            and prepared.get("retrospective_record_sha256") ==
                sha256(canonical({k:v for k,v in prepared.items()
                                  if k!="retrospective_record_sha256"})).hexdigest(),
            "HISTORICAL_FROZEN_RESEARCH_SUITE_MISSING_OR_TAMPERED")
    suite = prepared["full_model_suite"]
    require(verify_suite(suite) is True and
            suite["race_id"] == prepared["race_id"],
            "HISTORICAL_SUITE_INVALID")
    require(type(published_result) is dict
            and published_result.get("race_id") == prepared["race_id"]
            and _clock(published_result.get("observed_at")) >=
                _clock(prepared["official_cutoff_claimed"]),
            "RESULT_TIME_OR_RACE_MISMATCH")
    status = published_result.get("status")
    refund = published_result.get("refund_status")
    require(status in ("FINAL_NORMAL","PENDING","CANCELLED",
                       "NOT_OFFERED","SOURCE_UNAVAILABLE")
            and refund in ("NONE","PARTIAL","FULL","UNKNOWN"),
            "INVALID_RESULT_STATUS")
    normal = status == "FINAL_NORMAL" and refund == "NONE"
    prizes = {}
    if normal:
        winners = published_result.get("winning_triples")
        payouts = published_result.get("payouts_100yen")
        require(type(winners) is list and type(payouts) is list
                and winners and len(winners) == len(payouts),
                "SETTLED_WINNERS_REQUIRED")
        for p in payouts:
            require(type(p) is dict and set(p) == {"triple","yen"}
                    and type(p["yen"]) is int and p["yen"] > 0
                    and type(p["triple"]) is list
                    and len(p["triple"]) == 3
                    and all(type(x) is int for x in p["triple"]),
                    "INVALID_RESULT_PAYOUT")
            t = tuple(p["triple"])
            require(len(set(t)) == 3 and t not in prizes,
                    "INVALID_OR_DUPLICATE_RESULT_TRIPLE")
            prizes[t] = p["yen"]
        require(prizes.keys() == {tuple(t) for t in winners},
                "WINNING_TRIPLES_PAYOUT_MISMATCH")
    comparison = {}
    for mid in ALL_MODELS:
        model = suite["models"][mid]
        ranks = {tuple(c["combination"]):i+1
                 for i,c in enumerate(model["candidates"])}
        require(len(ranks) == model["candidate_count"] == (210 if
                len(suite["models"][mid]["candidates"]) == 210 else 504),
                "FULL_210_OR_504_UNIVERSE_REQUIRED")
        require(set(prizes).issubset(ranks),
                "WINNER_NOT_IN_MODEL_UNIVERSE")
        hit8 = any(ranks[t] <= 8 for t in prizes) if normal else None
        hit12 = any(ranks[t] <= 12 for t in prizes) if normal else None
        stake8,stake12 = 800,1200
        paid8 = sum(v for t,v in prizes.items() if ranks[t] <= 8)
        paid12 = sum(v for t,v in prizes.items() if ranks[t] <= 12)
        big = {t:v for t,v in prizes.items() if v >= MANSHA_THRESHOLD}
        comparison[mid] = {
            "model_version":model["model_version"],
            "prediction_sha256":model["prediction_sha256"],
            "ranked_candidate_count":len(ranks),
            "winning_rank_and_payout":[
                {"rank":ranks[t],"trifecta":list(t),"payout_per100":v,
                 "mansha":v >= MANSHA_THRESHOLD}
                for t,v in sorted(prizes.items())] if normal else [],
            "top8_hit":hit8, "top12_hit":hit12,
            "mansha_races_captured_by_top8":
                any(ranks[t]<=8 for t in big) if normal else None,
            "mansha_races_captured_by_top12":
                any(ranks[t]<=12 for t in big) if normal else None,
            "reference_top8_stake":stake8 if normal else None,
            "reference_top8_payout":paid8 if normal else None,
            "reference_top12_stake":stake12 if normal else None,
            "reference_top12_payout":paid12 if normal else None,
            "variable_mode":"NOT_EVALUABLE_NO_PRE_EVENT_SELECTION",
        }
    return {
        "schema":REPORT, "race_id":prepared["race_id"],
        "research_original_hash":prepared["retrospective_record_sha256"],
        "historical_retrospective_only":True,
        "result_status":"SETTLED_RESEARCH" if normal else "UNSETTLED",
        "four_existing_models":comparison,
        "count_as_formal_accuracy":False,
        "count_as_independently_frozen_original":False,
        "actual_purchase":None,
        "trained_model_improvement_demonstrated":False,
    }
