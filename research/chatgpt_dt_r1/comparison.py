"""Independent DT-R1 research comparison; never a production scorer or PDCA authority.

``compare_models(forecasts, outcomes, registry, expected_model_ids=[...],
bootstrap_samples=1000, seed=20261128, expected_model_sha256=None)`` uses the
explicit THREE entrant IDs, not IDs inferred from available forecasts. Registry
is the full scheduled-race list of {race_id, day}; optional input_sha256,
cutoff_at, cohort and condition fields bind admission more tightly. Outcomes
contain race_id/day/status and unique top3 when settled. Cancelled, dead_heat,
pending, full refund and missing outcomes have predeclared exclusion counts.
Settled races with valid top3 remain eligible even when tails had incidents.

All-target Hit@K retains missing/held/invalid forecasts as misses. Proper scores
and raw-probability calibration report their own forecast denominator; absent
forecasts are NEVER replaced with invented probability distributions. A separate
common cohort requires all three models with identical input hash, cohort,
prediction clock and cutoff clock. SHA/model drift and duplicate identities are
hard failures; invalid individual forecasts are recorded as HOLD, not dropped
from the scheduled denominator. Retrospective null clocks are not manufactured.

The report includes fixed trifecta K=1/2/4/9/12, exacta K=1/2, joint NLL/Brier,
calibration bin counts, conditions, actual attached selection coverage/returns,
and deterministic paired bootstrap resampling entire days. Retrospective and
prospective bootstrap samples are never pooled. No automatic winner/promotion
rule is invented. Optional ``selection`` must be the lineage-bound policy output.
Payouts require ``outcome.payout_verification`` with verified=True, authority
official/approved_consensus, race_id/day/market/cars/payout_per_100, source_sha256
and verification_receipt_sha256. Approved consensus also needs approval_id.
The receipt may instead be a mapping keyed by market. These are caller-supplied
admission receipts; this pure function cannot authenticate their issuer. No
receipt means no realised-return score, even for a numeric payout. Forecast odds
never settle returns. Prospective declared clocks alone are SHADOW_UNATTESTED;
formal verification remains the responsibility of the existing external verifier.

Existing forward/PDCA modules require their own admitted-original contracts and
normal-result filters. This new all-target research contract is deliberately
kept separate; it does not duplicate their source authentication or flow grading.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
import math
import random

try:
    from .policy import (PolicyError, checked_cars, checked_day, checked_sha, clock,
                         digest, finite_number, probability, require, validate_forecast)
except ImportError:
    from policy import (PolicyError, checked_cars, checked_day, checked_sha, clock,
                        digest, finite_number, probability, require, validate_forecast)


POINTS = {"trifecta": (1, 2, 4, 9, 12), "exacta": (1, 2)}
PROBABILITY_FLOOR = 1e-300


def _index(rows, name):
    require(isinstance(rows, list), name + "_MUST_BE_LIST")
    out = {}
    for row in rows:
        require(isinstance(row, dict), "INVALID_" + name + "_ROW")
        rid = row.get("race_id")
        require(isinstance(rid, str) and bool(rid.strip()), name + "_RACE_ID_REQUIRED")
        require(rid not in out, "DUPLICATE_" + name + "_RACE")
        checked_day(row.get("day"))
        out[rid] = row
    return out


def _clock_equal(a, b):
    return a is None and b is None or a is not None and b is not None and clock(a) == clock(b)


def _market_score(forecast, outcome, market):
    ranked = forecast[market + "s"]
    target = tuple(outcome["top3"][:3 if market == "trifecta" else 2])
    values = {tuple(t["cars"]): t["probability"] for t in ranked}
    actual = values[target]
    return {
        "nll": -math.log(max(PROBABILITY_FLOOR, actual)),
        "brier": math.fsum(p * p for p in values.values()) - 2 * actual + 1,
        "zero_probability_outcome": int(actual == 0),
        "points": {str(k): {"hit": int(any(tuple(t["cars"]) == target for t in ranked[:k])),
                             "raw_probability": min(1.0, math.fsum(t["probability"] for t in ranked[:k])),
                             "actual_ticket_count": min(k, len(ranked))}
                   for k in POINTS[market]},
    }


def _payout(outcome, market, target):
    """Validate the admitted amount against its market/ticket/source receipt."""
    paid = outcome.get("payout_per_100")
    if isinstance(paid, dict):
        paid = paid.get(market)
    elif market != "trifecta":
        paid = None
    if paid is None:
        return None, "MISSING", "PAYOUT_MISSING"
    try:
        paid = finite_number(paid, "INVALID_PAYOUT")
        require(paid >= 0, "INVALID_PAYOUT")
        receipt = outcome.get("payout_verification")
        if isinstance(receipt, dict) and market in receipt:
            receipt = receipt[market]
        require(isinstance(receipt, dict) and receipt.get("verified") is True, "PAYOUT_VERIFICATION_REQUIRED")
        authority = receipt.get("authority")
        require(authority in ("official", "approved_consensus"), "PAYOUT_AUTHORITY_NOT_ADMITTED")
        if authority == "approved_consensus":
            require(isinstance(receipt.get("approval_id"), str) and bool(receipt["approval_id"].strip()), "PAYOUT_CONSENSUS_APPROVAL_REQUIRED")
        for key in ("race_id", "day"):
            require(receipt.get(key) == outcome[key], "PAYOUT_RECEIPT_" + key.upper() + "_MISMATCH")
        require(receipt.get("market") == market, "PAYOUT_RECEIPT_MARKET_MISMATCH")
        require(checked_cars(receipt.get("cars"), len(target)) == target, "PAYOUT_RECEIPT_TICKET_MISMATCH")
        require(finite_number(receipt.get("payout_per_100")) == paid, "PAYOUT_RECEIPT_AMOUNT_MISMATCH")
        checked_sha(receipt.get("source_sha256"), "PAYOUT_SOURCE_SHA_REQUIRED")
        checked_sha(receipt.get("verification_receipt_sha256"), "PAYOUT_RECEIPT_SHA_REQUIRED")
        return paid, "RECEIPT_BOUND", None
    except (ValueError, TypeError, KeyError) as error:
        return None, "UNVERIFIED", str(error) if isinstance(error, PolicyError) else "PAYOUT_RECEIPT_INVALID"


def _attestation(forecast):
    """Check declared external-receipt bindings without claiming issuer verification."""
    receipt = forecast.get("source_attestation")
    if receipt is None:
        return "UNATTESTED"
    try:
        require(isinstance(receipt, dict) and receipt.get("verified") is True and receipt.get("external_verifier") is True, "NO_EXTERNAL_VERIFIER")
        require(isinstance(receipt.get("verifier"), str) and bool(receipt["verifier"].strip()), "VERIFIER_REQUIRED")
        checked_sha(receipt.get("receipt_sha256"))
        for key in ("race_id", "model_sha256", "input_sha256"):
            require(receipt.get(key) == forecast.get(key), "ATTESTATION_LINEAGE_MISMATCH")
        for key in ("prediction_at", "cutoff_at"):
            require(_clock_equal(receipt.get(key), forecast.get(key)), "ATTESTATION_CLOCK_MISMATCH")
        payload = {k: v for k, v in forecast.items() if k not in ("source_attestation", "selection")}
        require(receipt.get("forecast_sha256") == digest(payload), "ATTESTATION_FORECAST_HASH_MISMATCH")
        return "DECLARED_BOUND_EXTERNAL_RECEIPT"
    except (ValueError, TypeError, KeyError):
        return "INVALID_ATTESTATION_BINDING"


def _selection_score(forecast, outcome):
    selection = forecast.get("selection")
    if selection is None:
        return {"status": "HOLD", "reason": "NO_ACTUAL_SELECTION"}
    try:
        require(isinstance(selection, dict), "INVALID_SELECTION")
        for key in ("race_id", "day", "model_id", "model_sha256", "input_sha256", "cohort"):
            require(selection.get(key) == forecast.get(key), "SELECTION_LINEAGE_MISMATCH_" + key.upper())
        for key in ("prediction_at", "cutoff_at"):
            require(_clock_equal(selection.get(key), forecast.get(key)), "SELECTION_CLOCK_MISMATCH")
        checked_sha(selection.get("policy_sha256"), "SELECTION_POLICY_SHA_REQUIRED")
        if selection.get("policy") is not None:
            require(digest(selection["policy"]) == selection["policy_sha256"], "SELECTION_POLICY_HASH_MISMATCH")
        if selection.get("selection_sha256") is not None:
            require(digest({k: v for k, v in selection.items() if k != "selection_sha256"}) == selection["selection_sha256"], "SELECTION_HASH_MISMATCH")
        require(selection.get("status") == "SELECTED", "SELECTION_HOLD")
        market = selection.get("market")
        require(market in POINTS, "INVALID_SELECTION_MARKET")
        selected = selection.get("selected_tickets")
        require(isinstance(selected, list) and selected, "EMPTY_SELECTION")
        require(selection.get("ticket_count") == len(selected), "SELECTION_COUNT_MISMATCH")
        require(len(selected) <= (12 if market == "trifecta" else 2), "SELECTION_CAP_EXCEEDED")
        support = {tuple(t["cars"]): t["probability"] for t in forecast[market + "s"]}
        tickets, stakes = [], {}
        for item in selected:
            ticket = checked_cars(item.get("cars"), 3 if market == "trifecta" else 2)
            require(ticket in support and ticket not in stakes, "INVALID_OR_DUPLICATE_SELECTION_TICKET")
            if "probability" in item:
                require(abs(probability(item["probability"]) - support[ticket]) <= 1e-7, "SELECTION_PROBABILITY_MISMATCH")
            stake = finite_number(item.get("stake", selection.get("stake_per_ticket", 100)))
            require(stake > 0, "INVALID_SELECTION_STAKE")
            tickets.append(ticket)
            stakes[ticket] = stake
        raw = math.fsum(support[t] for t in tickets)
        require(abs(probability(selection.get("raw_coverage")) - raw) <= 1e-7, "SELECTION_COVERAGE_MISMATCH")
        target = tuple(outcome["top3"][:3 if market == "trifecta" else 2])
        hit = int(target in stakes)
        paid, payout_status, payout_reason = _payout(outcome, market, target)
        total_stake = math.fsum(stakes.values())
        gross = (paid * stakes[target] / 100 if hit else 0.0) if paid is not None else None
        return {"status": "SELECTED", "market": market, "hit": hit, "ticket_count": len(tickets),
                "raw_probability": min(1.0, raw), "policy_sha256": selection["policy_sha256"],
                "odds_band": selection.get("odds_band"), "stake": total_stake,
                "payout_status": payout_status, "payout_reason": payout_reason,
                "gross": gross, "net": None if gross is None else gross - total_stake,
                "hit_but_net_loss": hit == 1 and gross is not None and gross < total_stake}
    except (ValueError, TypeError, KeyError) as error:
        return {"status": "HOLD", "reason": str(error) if isinstance(error, PolicyError) else "INVALID_SELECTION"}


def _calibration_bins(records, market, k):
    bins = [{"lower": i / 10, "upper": (i + 1) / 10, "n": 0, "hits": 0,
             "mean_raw_probability": None, "empirical_rate": None} for i in range(10)]
    sums = [0.0] * 10
    for row in records:
        point = row["markets"][market]["points"][str(k)]
        index = min(9, int(point["raw_probability"] * 10))
        bins[index]["n"] += 1
        bins[index]["hits"] += point["hit"]
        sums[index] += point["raw_probability"]
    for index, item in enumerate(bins):
        if item["n"]:
            item["mean_raw_probability"] = sums[index] / item["n"]
            item["empirical_rate"] = item["hits"] / item["n"]
    return bins


def _selection_summary(records, eligible_n):
    active = [r["selection"] for r in records if r["selection"]["status"] == "SELECTED"]
    scored = [s for s in active if s["gross"] is not None]
    hits = sum(s["hit"] for s in active)
    out = {"eligible_n": eligible_n, "presented_n": len(active), "hits": hits,
           "presentation_rate": len(active) / eligible_n if eligible_n else None,
           "hit_rate_all_target": hits / eligible_n if eligible_n else None,
           "hit_rate_presented": hits / len(active) if active else None,
           "mean_ticket_count": math.fsum(s["ticket_count"] for s in active) / len(active) if active else None,
           "payout_scored_n": len(scored),
           "payout_missing_n": sum(s["payout_status"] == "MISSING" for s in active),
           "payout_unverified_n": sum(s["payout_status"] == "UNVERIFIED" for s in active),
           "payout_hold_reasons": dict(Counter(s["payout_reason"] for s in active if s["payout_reason"] is not None)),
           "payout_evidence": "Receipt bindings checked; issuer authentication is an external admission responsibility.",
           "stake_on_payout_scored": math.fsum(s["stake"] for s in scored) if scored else None,
           "gross_on_payout_scored": math.fsum(s["gross"] for s in scored) if scored else None,
           "net_on_payout_scored": math.fsum(s["net"] for s in scored) if scored else None,
           "hit_but_net_loss_n": sum(s["hit_but_net_loss"] for s in scored),
           "hold_reasons": dict(Counter(r["selection"].get("reason") for r in records if r["selection"]["status"] != "SELECTED"))}
    for name in ("ticket_count", "odds_band", "policy_sha256", "market"):
        groups = defaultdict(list)
        for row in active:
            groups[str(row[name])].append(row)
        out["by_" + name] = {key: {"n": len(rows), "hits": sum(r["hit"] for r in rows),
                                        "hit_rate": sum(r["hit"] for r in rows) / len(rows)}
                                  for key, rows in sorted(groups.items())}
    return out


def _aggregate(race_ids, model_id, admitted, reasons, *, conditions=None):
    records = [admitted[(rid, model_id)] for rid in race_ids if (rid, model_id) in admitted]
    n = len(race_ids)
    out = {"eligible_n": n, "forecast_n": len(records), "missing_or_held_n": n - len(records),
           "coverage": len(records) / n if n else None,
           "hold_reasons": dict(Counter(reasons.get((rid, model_id), "MISSING_FORECAST") for rid in race_ids if (rid, model_id) not in admitted)),
           "cohort_counts": dict(Counter(r["cohort"] for r in records)),
           "model_sha256": sorted({r["model_sha256"] for r in records})}
    for market, ks in POINTS.items():
        out[market] = {
            "score_n": len(records), "probability_floor": PROBABILITY_FLOOR,
            "nll": math.fsum(r["markets"][market]["nll"] for r in records) / len(records) if records else None,
            "brier": math.fsum(r["markets"][market]["brier"] for r in records) / len(records) if records else None,
            "zero_probability_outcomes": sum(r["markets"][market]["zero_probability_outcome"] for r in records),
            "hit_at": {str(k): {"hits": sum(r["markets"][market]["points"][str(k)]["hit"] for r in records),
                                 "n": n,
                                 "rate": sum(r["markets"][market]["points"][str(k)]["hit"] for r in records) / n if n else None,
                                 "forecast_n": len(records)} for k in ks},
            "calibration": {str(k): _calibration_bins(records, market, k) for k in ks},
        }
    out["actual_selection"] = _selection_summary(records, n)
    if conditions is not None:
        out["by_condition"] = {}
        for field in ("field_size", "class", "venue"):
            groups = defaultdict(list)
            for rid in race_ids:
                groups[str(conditions[rid].get(field, "unknown"))].append(rid)
            out["by_condition"][field] = {
                key: {"eligible_n": len(ids), "forecast_n": sum((rid, model_id) in admitted for rid in ids),
                      "hit_at": {market: {str(k): sum(admitted[(rid, model_id)]["markets"][market]["points"][str(k)]["hit"]
                                                      for rid in ids if (rid, model_id) in admitted) / len(ids)
                                                   for k in ks} for market, ks in POINTS.items()}}
                for key, ids in sorted(groups.items())}
    return out


def _metric_values(record):
    values = {}
    for market, ks in POINTS.items():
        data = record["markets"][market]
        values.update({f"{market}_hit_at_{k}": data["points"][str(k)]["hit"] for k in ks})
        values.update({f"{market}_nll": data["nll"], f"{market}_brier": data["brier"]})
    return values


def _quantile(sorted_values, q):
    position = (len(sorted_values) - 1) * q
    lo = int(position)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (position - lo)


def _paired_bootstrap(common_ids, admitted, model_ids, samples, seed):
    out = []
    for cohort in ("retrospective", "prospective"):
        ids = [rid for rid in common_ids if admitted[(rid, model_ids[0])]["cohort"] == cohort]
        if not ids:
            continue
        for left, right in combinations(model_ids, 2):
            days = defaultdict(list)
            for rid in ids:
                a, b = _metric_values(admitted[(rid, left)]), _metric_values(admitted[(rid, right)])
                days[admitted[(rid, left)]["day"]].append({key: a[key] - b[key] for key in a})
            names = list(next(iter(next(iter(days.values())))).keys())
            day_names = sorted(days)
            totals = {day: {name: math.fsum(row[name] for row in rows) for name in names} for day, rows in days.items()}
            estimate = {name: math.fsum(totals[day][name] for day in day_names) / len(ids) for name in names}
            item = {"models": [left, right], "difference": "first_minus_second", "cohort": cohort,
                    "race_n": len(ids), "day_n": len(days), "seed": seed, "samples": samples,
                    "method": "paired percentile bootstrap; whole days with all their races", "metrics": {}}
            draws = defaultdict(list)
            if len(days) >= 2:
                rng = random.Random(seed)
                for _ in range(samples):
                    chosen = rng.choices(day_names, k=len(day_names))
                    denominator = sum(len(days[day]) for day in chosen)
                    for name in names:
                        draws[name].append(math.fsum(totals[day][name] for day in chosen) / denominator)
            for name in names:
                values = sorted(draws[name])
                item["metrics"][name] = {"difference": estimate[name],
                                         "ci": [_quantile(values, .025), _quantile(values, .975)] if values else None,
                                         "higher_is_better": "hit_at" in name,
                                         "reason": None if values else "INSUFFICIENT_DAYS"}
            out.append(item)
    return out


def compare_models(forecasts, outcomes, registry, *, expected_model_ids, bootstrap_samples=1000,
                   seed=20261128, expected_model_sha256=None):
    """Compare declared entrants on the full registry and on an exact common cohort."""
    require(isinstance(expected_model_ids, (list, tuple)) and len(expected_model_ids) == 3 and
            all(isinstance(m, str) and bool(m.strip()) for m in expected_model_ids) and
            len(set(expected_model_ids)) == 3, "EXACTLY_THREE_DECLARED_MODEL_IDS_REQUIRED")
    require(isinstance(bootstrap_samples, int) and not isinstance(bootstrap_samples, bool) and 1 <= bootstrap_samples <= 100000, "INVALID_BOOTSTRAP_SAMPLES")
    require(isinstance(seed, int) and not isinstance(seed, bool), "INVALID_BOOTSTRAP_SEED")
    ids = list(expected_model_ids)
    scheduled, result_index = _index(registry, "REGISTRY"), _index(outcomes, "OUTCOME")
    require(set(result_index) <= set(scheduled), "UNREGISTERED_OUTCOME")
    excluded, eligible, conditions = Counter(), [], {}
    for rid, registered in scheduled.items():
        if registered.get("cohort") is not None:
            require(registered["cohort"] in ("retrospective", "prospective"), "INVALID_REGISTRY_COHORT")
        if registered.get("input_sha256") is not None:
            checked_sha(registered["input_sha256"])
        if registered.get("cutoff_at") is not None:
            clock(registered["cutoff_at"])
        outcome = result_index.get(rid)
        if outcome is None:
            excluded["missing_outcome"] += 1
            continue
        require(outcome["day"] == registered["day"], "OUTCOME_DAY_MISMATCH")
        status = outcome.get("status")
        require(status in ("settled", "cancelled", "dead_heat", "pending"), "INVALID_OUTCOME_STATUS")
        if status != "settled" or outcome.get("refunded") is True:
            excluded["refunded" if outcome.get("refunded") is True else status] += 1
            continue
        checked_cars(outcome.get("top3"), 3)
        size = outcome.get("field_size", registered.get("field_size"))
        if size is not None:
            require(isinstance(size, int) and not isinstance(size, bool) and 3 <= size <= 9, "INVALID_OUTCOME_FIELD_SIZE")
        eligible.append(rid)
        conditions[rid] = {**registered, **outcome}
    require(isinstance(forecasts, list), "FORECASTS_MUST_BE_LIST")
    supplied, declared_versions = {}, defaultdict(set)
    if expected_model_sha256 is not None:
        require(isinstance(expected_model_sha256, dict) and set(expected_model_sha256) <= set(ids), "INVALID_MODEL_MANIFEST")
        for value in expected_model_sha256.values():
            checked_sha(value)
    for forecast in forecasts:
        require(isinstance(forecast, dict), "INVALID_FORECAST_ROW")
        rid, model_id = forecast.get("race_id"), forecast.get("model_id")
        require(rid in scheduled, "UNREGISTERED_FORECAST")
        require(model_id in ids, "UNEXPECTED_MODEL_ID")
        key = rid, model_id
        require(key not in supplied, "DUPLICATE_FORECAST_IDENTITY")
        supplied[key] = forecast
        value = forecast.get("model_sha256")
        if value is not None:
            checked_sha(value, "INVALID_MODEL_SHA256")
            declared_versions[model_id].add(value)
            if expected_model_sha256 and model_id in expected_model_sha256:
                require(value == expected_model_sha256[model_id], "MODEL_MANIFEST_MISMATCH")
    require(all(len(versions) <= 1 for versions in declared_versions.values()), "MODEL_VERSION_DRIFT_WITHIN_COMPARISON")
    admitted, reasons = {}, {}
    for rid in eligible:
        registered, outcome = scheduled[rid], result_index[rid]
        for model_id in ids:
            key = rid, model_id
            if key not in supplied:
                reasons[key] = "MISSING_FORECAST"
                continue
            try:
                f = validate_forecast(supplied[key])
                require(f["day"] == registered["day"], "FORECAST_DAY_MISMATCH")
                if registered.get("input_sha256") is not None:
                    require(f["input_sha256"] == registered["input_sha256"], "REGISTRY_INPUT_MISMATCH")
                if registered.get("cutoff_at") is not None:
                    require(_clock_equal(f["cutoff_at"], registered["cutoff_at"]), "REGISTRY_CUTOFF_MISMATCH")
                if registered.get("cohort") is not None:
                    require(f["cohort"] == registered["cohort"], "REGISTRY_COHORT_MISMATCH")
                if outcome.get("field_size") is not None:
                    require(outcome["field_size"] == f["field_size"], "RESULT_FIELD_SIZE_MISMATCH")
                require(set(outcome["top3"]) <= set(f["starters"]), "RESULT_CARS_NOT_IN_FORECAST")
                admitted[key] = {"race_id": rid, "day": registered["day"], "cohort": f["cohort"],
                                 "model_sha256": f["model_sha256"], "input_sha256": f["input_sha256"],
                                 "prediction_at": f["prediction_at"], "cutoff_at": f["cutoff_at"],
                                 "source_attestation_status": _attestation(supplied[key]),
                                 "markets": {market: _market_score(f, outcome, market) for market in POINTS},
                                 "selection": _selection_score(f, outcome)}
            except (ValueError, TypeError, KeyError) as error:
                reasons[key] = str(error) if isinstance(error, PolicyError) else "INVALID_FORECAST"
    common_ids, common_reasons, common_exclusions = [], Counter(), []
    for rid in eligible:
        rows = [admitted.get((rid, model_id)) for model_id in ids]
        why = []
        if any(row is None for row in rows):
            why.append("MISSING_OR_INVALID_MODEL_FORECAST")
        else:
            if len({r["input_sha256"] for r in rows}) != 1:
                why.append("INPUT_MISMATCH")
            if len({r["cohort"] for r in rows}) != 1:
                why.append("COHORT_MISMATCH")
            for key in ("prediction_at", "cutoff_at"):
                if not all(_clock_equal(rows[0][key], r[key]) for r in rows[1:]):
                    why.append(key.upper() + "_MISMATCH")
        if why:
            common_reasons.update(why)
            common_exclusions.append({"race_id": rid, "reasons": why,
                                      "model_reasons": {m: reasons[(rid, m)] for m in ids if (rid, m) in reasons}})
        else:
            common_ids.append(rid)
    observed_models = {model_id for _, model_id in supplied}
    verdict_reasons = ["NO_AUTOMATIC_WINNER_RULE_OR_PRODUCTION_PROMOTION"]
    if observed_models != set(ids):
        verdict_reasons.append("MISSING_MODEL_ROWS")
    if not common_ids:
        verdict_reasons.append("NO_COMMON_COHORT")
    if not any(admitted[(rid, ids[0])]["cohort"] == "prospective" for rid in common_ids):
        verdict_reasons.append("NO_COMMON_PROSPECTIVE_EVIDENCE")
    report = {
        "scope": "INDEPENDENT_RESEARCH_COMPARISON_NOT_SOURCE_ATTESTED", "expected_model_ids": ids,
        "registry": {"scheduled_n": len(scheduled), "eligible_n": len(eligible),
                     "excluded_status_counts": dict(excluded), "registry_sha256": digest(registry)},
        "predeclared_scoring": {"cancelled": "excluded", "refunded": "excluded", "dead_heat": "unscored_unsupported",
                                 "pending": "unscored", "missing_forecast": "all_target_hit_miss",
                                 "settled_with_valid_top3_and_tail_incidents": "included",
                                 "missing_probability_distribution": "proper_scores_unavailable_not_imputed"},
        "all_target": {"eligible_n": len(eligible), "models": {m: _aggregate(eligible, m, admitted, reasons, conditions=conditions) for m in ids}},
        "common_cohort": {"eligible_n": len(common_ids), "race_ids_sha256": digest(sorted(common_ids)),
                          "models": {m: _aggregate(common_ids, m, admitted, reasons, conditions=conditions) for m in ids},
                          "cohort_counts": dict(Counter(admitted[(rid, ids[0])]["cohort"] for rid in common_ids)),
                          "exclusion_reasons": dict(common_reasons), "exclusions": common_exclusions},
        "paired_bootstrap": _paired_bootstrap(common_ids, admitted, ids, bootstrap_samples, seed),
        "verdict": {"winner": None, "reasons": verdict_reasons},
        "conditional_distribution_caveat": "Forecast distributions exclude dead heats/abnormal completion; settled incident races with valid top3 remain in all-target scoring.",
        "source_attested": False,
    }
    prospective = [row for row in admitted.values() if row["cohort"] == "prospective"]
    receipt_n = sum(row["source_attestation_status"] == "DECLARED_BOUND_EXTERNAL_RECEIPT" for row in prospective)
    report["prospective_evidence"] = {
        "forecast_n": len(prospective), "declared_bound_receipt_n": receipt_n,
        "attestation_status_counts": dict(Counter(row["source_attestation_status"] for row in prospective)),
        "status": ("NO_PROSPECTIVE_FORECASTS" if not prospective else
                   "EXTERNAL_RECEIPTS_DECLARED_NOT_INDEPENDENTLY_REVERIFIED" if receipt_n == len(prospective) else "SHADOW_UNATTESTED"),
        "formal_comparison_verified": False,
        "requirement": "Existing external verifier must independently authenticate original forecast receipts and official outcomes; declared clocks or local hashes are insufficient.",
    }
    report["common_cohort"]["by_cohort"] = {
        cohort: {"eligible_n": len(group), "models": {m: _aggregate(group, m, admitted, reasons) for m in ids}}
        for cohort in ("retrospective", "prospective")
        for group in [[rid for rid in common_ids if admitted[(rid, ids[0])]["cohort"] == cohort]]
    }
    # All-target cohort denominators come only from registry declarations, never
    # from which models happened to submit a forecast.
    report["all_target"]["by_registry_cohort"] = {
        cohort: {"eligible_n": len(group), "models": {m: _aggregate(group, m, admitted, reasons) for m in ids}}
        for cohort in ("retrospective", "prospective", "undeclared")
        for group in [[rid for rid in eligible if scheduled[rid].get("cohort", "undeclared") == cohort]]
    }
    return report
