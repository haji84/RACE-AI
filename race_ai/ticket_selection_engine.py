"""Four-sport *research* ticket-count selection attached to ranked prediction engines.

Exactly 1..12 *proposed* tickets, never a zero-ticket prediction.
An actual NO_BET/NO_FORECAST event is separate from the generated proposal.
The current scores and thresholds are NOT calibrated or approved for wagering.
Never edits the ranking, original Top8, or prediction hash.
"""
from __future__ import annotations

from datetime import datetime
import math

from .comprehensive_four_sport_models import digest

SCHEMA = "RACE_AI_RESEARCH_TICKET_TRIALS_V1"
MIN_TICKETS = 1
MAX_TICKETS = 12
POLICY_VERSION = "research-fixed-thresholds-v1-20261104"
PLAN_NAMES = (
    "fixed_8",
    "fixed_12",
    "spread_adaptive_8_or_12",
    "confidence_shortlist_1_to_8",
)


class TicketSelectionError(ValueError):
    pass


def _require(ok, reason):
    if not ok:
        raise TicketSelectionError(reason)


def _instant(value):
    _require(type(value) is str, "aware timestamp required")
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TicketSelectionError("invalid timestamp") from exc
    _require(when.tzinfo is not None and when.utcoffset() is not None,
             "offset-aware timestamp required")
    return when


def _ranking(prediction):
    _require(type(prediction) is dict, "prediction required")
    _require(prediction.get("prediction_sha256") ==
             digest({k: v for k, v in prediction.items()
                     if k != "prediction_sha256"}), "forecast hash mismatch")
    _require(prediction.get("official_prediction") is False and
             prediction.get("purchase_decision") == "NO_BET" and
             prediction.get("external_pre_cutoff_receipt") is None,
             "only unauthorised research predictions supported")
    _require(_instant(prediction["as_of"]) < _instant(prediction["cutoff_at"]),
             "forecast is not before scheduled cutoff")
    ranked = prediction.get("candidates")
    _require(type(ranked) is list and
             type(prediction.get("candidate_count")) is int and
             prediction["candidate_count"] == len(ranked) and len(ranked) >= 6,
             "complete ranked candidate universe required")
    choices = set()
    numbers = set()
    previous = None
    mass = []
    for row in ranked:
        _require(type(row) is dict and set(row) == {"combination", "score"},
                 "candidate schema mismatch")
        combo, score = row["combination"], row["score"]
        _require(type(combo) is list and len(combo) == 3 and
                 all(type(n) is int and 1 <= n <= 99 for n in combo)
                 and len(set(combo)) == 3, "invalid trifecta")
        key = tuple(combo)
        _require(key not in choices, "duplicate candidate")
        choices.add(key)
        numbers.update(combo)
        _require(type(score) in (int, float) and math.isfinite(score) and
                 score >= 0, "invalid uncalibrated score")
        order = (-score, key)
        _require(previous is None or previous <= order,
                 "candidate ranking must be score ordered")
        previous = order
        mass.append(float(score))
    n = len(numbers)
    _require(n >= 3 and len(ranked) == n * (n - 1) * (n - 2),
             "incomplete result universe")
    _require(math.isclose(math.fsum(mass), 1.0, abs_tol=1e-8),
             "candidate scores do not normalize")
    _require(prediction.get("ordered_top8") ==
             [row["combination"] for row in ranked[:8]],
             "existing top8 changed")
    return ranked, n


def _short_count(ranked):
    """Pre-registered *uncalibrated* concentration proxy, not P(hit)."""
    first = ranked[0]["score"]
    last = ranked[min(7, len(ranked) - 1)]["score"]
    ratio = first / max(last, 1e-15)
    if ratio >= 8:
        count = 1
    elif ratio >= 5:
        count = 2
    elif ratio >= 4:
        count = 3
    elif ratio >= 3.2:
        count = 4
    elif ratio >= 2.6:
        count = 5
    elif ratio >= 2.1:
        count = 6
    else:
        count = 8
    return min(count, len(ranked)), ratio


def _spread_count(ranked, n):
    """Use the distribution of candidate FIRST positions, not future payouts."""
    first_mass = {number: 0.0 for number in {
        x for row in ranked for x in row["combination"]}}
    for row in ranked:
        first_mass[row["combination"][0]] += row["score"]
    leading = max(first_mass.values())
    wide = leading < 1.5 / n
    return (12 if wide else 8), leading


def build_ticket_trials(prediction):
    """Actual prediction-engine output for 4 parallel, same-as-of research plans."""
    ranked, n = _ranking(prediction)
    short, ratio = _short_count(ranked)
    spread, first_mass = _spread_count(ranked, n)
    counts = (8, 12, spread, short)
    rules = (
        "fixed baseline, first 8 ranked",
        "fixed comparator, first 12 ranked",
        "first-place mass < 1.5 / field size => 12; else 8; exploratory",
        "top1/top8 score-ratio thresholds => 1..8; exploratory",
    )
    plans = {}
    for name, count, rule in zip(PLAN_NAMES, counts, rules):
        count = min(count, len(ranked))
        _require(MIN_TICKETS <= count <= MAX_TICKETS,
                 "prediction must contain 1..12 tickets")
        selection = [list(row["combination"]) for row in ranked[:count]]
        plans[name] = {
            "ticket_count": count,
            "ordered_tickets": selection,
            "rule": rule,
            "rule_uses_results": False,
            "probabilities_calibrated": False,
            "estimated_ticket_mass_uncalibrated": math.fsum(
                row["score"] for row in ranked[:count]),
            "purchase_decision": "NO_BET",
        }
    bundle = {
        "schema": SCHEMA, "policy_version": POLICY_VERSION,
        "model_id": prediction["model_id"],
        "race_id": prediction["race_id"],
        "as_of": prediction["as_of"],
        "cutoff_at": prediction["cutoff_at"],
        "source_prediction_sha256": prediction["prediction_sha256"],
        "candidate_count": len(ranked),
        "model_calibrated": prediction.get("calibrated") is True,
        "selection_experiment_not_calibrated": True,
        "spread_first_place_mass_uncalibrated": first_mass,
        "shortlist_score_ratio_uncalibrated": ratio,
        "plans": plans,
        "official_prediction": False,
        "external_pre_cutoff_receipt": None,
        "auto_bet": False,
    }
    bundle["trials_sha256"] = digest(bundle)
    return bundle


def verify_ticket_trials(prediction, bundle):
    """Recompute from untouched model ranking, including ticket number and order."""
    try:
        return type(bundle) is dict and bundle == build_ticket_trials(prediction)
    except (TicketSelectionError, KeyError, TypeError, ValueError):
        return False


def evaluate_ticket_trials(prediction, trials, result):
    """Audit owner-supplied outcome, independently for each same-race plan.

    No result-provider authentication is performed. Missing/abnormal results are
    unscored, not misses. Hypothetical staking is 100 yen per selected ticket.
    """
    _require(verify_ticket_trials(prediction, trials), "ticket trials not intact")
    if result is None:
        return {"state": "RESULT_UNVERIFIED", "race_id": trials["race_id"],
                "plans": None, "independently_verified": False}
    _require(type(result) is dict and set(result) == {
        "race_id", "status", "observed_at", "winning_combinations",
        "refunded_numbers", "source_grade", "source_url", "revision"
    }, "result event contract required")
    _require(result["race_id"] == trials["race_id"], "race result ID mismatch")
    _require(_instant(result["observed_at"]) > _instant(trials["cutoff_at"]),
             "result observed before cutoff")
    _require(result["status"] in ("SETTLED", "CANCELLED", "SPECIAL", "UNVERIFIED"),
             "unrecognised result state")
    _require(result["source_grade"] in ("official_observed",
                                       "third_party_observed", "legacy_claim",
                                       "unverified") and
             type(result["source_url"]) is str and
             type(result["revision"]) is int and result["revision"] >= 1,
             "result source metadata required")
    if result["status"] in ("SPECIAL", "UNVERIFIED"):
        _require(not result["winning_combinations"] and
                 not result["refunded_numbers"], "unscored outcome has payouts")
        return {"state": result["status"], "race_id": trials["race_id"],
                "plans": None, "independently_verified": False}
    winners = result["winning_combinations"]
    refunds = result["refunded_numbers"]
    _require(type(refunds) is list and len(refunds) == len(set(refunds)) and
             all(type(x) is int and x >= 1 for x in refunds),
             "invalid refund participants")
    _require(type(winners) is list, "winner rows required")
    if result["status"] == "CANCELLED":
        _require(winners == [], "cancelled result cannot pay out")
    else:
        _require(bool(winners), "settled result must provide winner rows")
    observed_winners = {}
    for w in winners:
        _require(type(w) is dict and set(w) == {
            "combination", "payout_per_100_yen"}, "winner payout contract")
        combo, payout = w["combination"], w["payout_per_100_yen"]
        _require(type(combo) is list and len(combo) == 3 and
                 all(type(x) is int and x >= 1 for x in combo) and
                 len(set(combo)) == 3 and type(payout) is int and payout >= 0,
                 "invalid settled payout")
        key = tuple(combo)
        _require(key not in observed_winners and not(set(key) & set(refunds)),
                 "duplicate or refunded winner")
        observed_winners[key] = payout
    report = {}
    for name, plan in trials["plans"].items():
        stake = plan["ticket_count"] * 100
        refund = 0
        win = 0
        hit_positions = []
        for position, combo in enumerate(plan["ordered_tickets"], 1):
            key = tuple(combo)
            returned = (result["status"] == "CANCELLED" or
                        any(n in refunds for n in key))
            if returned:
                refund += 100
            elif key in observed_winners:
                win += observed_winners[key]
                hit_positions.append(position)
        received = win + refund
        status = ("FULL_REFUND" if refund == stake else
                  "HIT_PLUS_REFUND" if win and refund else
                  "HIT" if win else "MISS_PLUS_REFUND" if refund else "MISS")
        report[name] = {
            "ticket_count": plan["ticket_count"], "status": status,
            "hit_rank": min(hit_positions) if hit_positions else None,
            "gross_yen": stake, "win_yen": win,
            "refund_yen": refund, "received_yen": received,
            "net_yen": received - stake,
            "return_ratio": received / stake,
        }
    return {
        "state": "SCORED_OWNER_REPORTED_NOT_INDEPENDENTLY_VERIFIED",
        "race_id": trials["race_id"], "source_grade": result["source_grade"],
        "source_url": result["source_url"], "result_revision": result["revision"],
        "plans": report, "independently_verified": False,
        "not_official_prospective_score": True,
    }
