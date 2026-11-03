"""Prospective same-race A/B BOAT evaluation, Vercel-free and no auto-promotion.

Receives independently verified official outcome and the audit produced from
an externally timestamped PRE-cutoff pair. This module deliberately does no
source fetching, learning, price-based prediction, or remote writes.

Caller must authenticate GitHub artifact readback and official source receipts
before building each row. A SHA-256 string by itself is NOT source authenticity.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
import random
import re

from .boat_ab_shadow import MODEL_IDS, _time

JST = timezone(timedelta(hours=9))
RACE_ID = re.compile(r"^(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$")
SHA = re.compile(r"^[0-9a-f]{64}$")
TICKET = re.compile(r"^[1-6]-[1-6]-[1-6]$")
STATES = frozenset({"SETTLED", "PENDING", "UNAVAILABLE", "REFUNDED",
                    "CANCELLED", "NO_TRIFECTA"})
PAIRED_MIN = 100
DAYS_MIN = 5


def _need(ok, msg):
    if not ok:
        raise ValueError(msg)


def _sha(s):
    return isinstance(s, str) and SHA.fullmatch(s) is not None


def _race_row(row):
    _need(isinstance(row, dict), "race ledger item must be dict")
    keys = {"race_id", "cutoff_at", "trifecta_offered", "result_state",
            "official_top3", "official_source_sha256",
            "official_result_captured_at", "payout_per_100_yen",
            "paired_audit", "artifact_receipt"}
    _need(set(row) == keys, "exact race ledger columns required")
    rid = row["race_id"]
    m = RACE_ID.fullmatch(rid) if isinstance(rid, str) else None
    _need(m is not None, "invalid race identity")
    cutoff = _time(row["cutoff_at"])
    _need(cutoff.astimezone(JST).strftime("%Y%m%d") == m.group(1),
          "race date does not match JST closing")
    _need(type(row["trifecta_offered"]) is bool, "official trifecta offering required")
    state = row["result_state"]
    _need(state in STATES, "invalid official result state")
    if state == "SETTLED":
        _need(row["trifecta_offered"], "settled 3t cannot be unoffered")
        top3 = row["official_top3"]
        _need(isinstance(top3, str) and TICKET.fullmatch(top3) is not None
              and len(set(top3.split("-"))) == 3, "unique official 3t result required")
        _need(_sha(row["official_source_sha256"]), "official result source hash required")
        captured = _time(row["official_result_captured_at"])
        _need(captured >= cutoff, "result cannot predate closing")
        payout = row["payout_per_100_yen"]
        _need(payout is None or (type(payout) is int and 1 <= payout <= 10_000_000),
              "validated official 100 yen payout required")
    else:
        _need(row["official_top3"] is None and row["payout_per_100_yen"] is None,
              "nonsettled race cannot contain confirmed payout or winner")
        _need(row["paired_audit"] is None, "nonsettled race not scored")
    return rid, cutoff


def _verified_pair(row, cutoff):
    audit = row["paired_audit"]
    receipt = row["artifact_receipt"]
    if audit is None:
        _need(receipt is None, "artifact receipt without scored pair")
        return None
    _need(isinstance(audit, dict) and isinstance(receipt, dict),
          "paired evidence requires server receipt")
    _need(receipt.get("verified_download_and_sha256") is True,
          "archive readback and digest not independently verified")
    _need(_sha(receipt.get("artifact_sha256"))
          and _sha(receipt.get("original_pair_json_sha256")),
          "artifact and original JSON SHA mandatory")
    created = _time(receipt["server_created_at"])
    _need(created < cutoff and created == _time(audit["forecast_server_saved_at"]),
          "independent preclosing artifact time missing")
    _need(audit.get("schema") == "RACE_AI_BOAT_AB_INDEPENDENT_RESULT_AUDIT_V1"
          and audit.get("race_id") == row["race_id"]
          and _time(audit["cutoff_at"]) == cutoff
          and audit.get("official_top3") == row["official_top3"]
          and _time(audit["result_observed_at"]) ==
                   _time(row["official_result_captured_at"])
          and audit.get("next_model_auto_promoted") is False
          and audit.get("model_calibrated") is False
          and _sha(audit.get("pair_bundle_sha256")),
          "paired score identity/phase not independently verified")
    _need(receipt.get("pair_bundle_sha256") == audit["pair_bundle_sha256"],
          "saved pair bundle hash mismatch")
    models = audit.get("models")
    _need(isinstance(models, list) and len(models) == 2 and
          [x.get("model_id") for x in models] == list(MODEL_IDS),
          "A and B must be compared on the identical preclosing forecast")
    for model in models:
        _need(type(model.get("hit_at_1")) is int and model["hit_at_1"] in (0,1)
              and type(model.get("hit_at_8")) is int and model["hit_at_8"] in (0,1)
              and type(model.get("winning_combination_rank")) is int
              and 1 <= model["winning_combination_rank"] <= 120,
              "full ranked result score required")
        _need(model["hit_at_1"] == int(model["winning_combination_rank"] == 1)
              and model["hit_at_8"] == int(model["winning_combination_rank"] <= 8),
              "rank and hit metrics disagree")
        _need(_sha(model.get("model_sha256"))
              and isinstance(model.get("top8"), list)
              and len(model["top8"]) == 8
              and len(set(model["top8"])) == 8
              and all(TICKET.fullmatch(t) and len(set(t.split("-"))) == 3
                      for t in model["top8"]),
              "saved model identity or top8 invalid")
        _need(model["hit_at_1"] == int(model["top8"][0] == row["official_top3"])
              and model["hit_at_8"] == int(row["official_top3"] in model["top8"]),
              "readback prediction tickets do not match result")
        for key in ("multiclass_brier", "log_loss"):
            val = model.get(key)
            _need(type(val) in (float,int) and math.isfinite(val) and val >= 0,
                  "proper scoring rule is not finite")
        mass = model.get("model_top8_mass_uncalibrated")
        _need(type(mass) in (float, int) and math.isfinite(mass) and 0 < mass < 1,
              "model top8 probability mass required for calibration audit")
        points = model.get("top8_model_scores_uncalibrated")
        _need(isinstance(points, list) and len(points) == 8
              and [x.get("ticket") for x in points if isinstance(x,dict)] == model["top8"],
              "exact frozen top8 score identities required")
        _need(all(type(x.get("score")) in (float,int) and
                   math.isfinite(x["score"]) and 0 < x["score"] < 1 for x in points),
              "frozen forecast scores must be finite")
        _need(math.isclose(math.fsum(x["score"] for x in points), mass, abs_tol=1e-10),
              "forecast mass differs from frozen top8")
        _need(math.isclose(points[0]["score"],
                           model["model_top1_mass_uncalibrated"], abs_tol=1e-10),
              "frozen top1 score differs from claimed model score")
    return models


def wilson(successes, attempts):
    """95% marginal Wilson interval, not a claim of independent races."""
    if attempts == 0:
        return None
    p = successes / attempts
    z = 1.959963984540054
    zz = z * z
    denominator = 1 + zz / attempts
    centre = (p + zz / (2*attempts)) / denominator
    half = z * math.sqrt((p * (1-p) + zz/(4*attempts)) / attempts) / denominator
    return [max(0., centre-half), min(1., centre+half)]


def _paired_bootstrap(values, samples=2000):
    """Deterministic percentile bootstrap of B-A within the SAME races."""
    n = len(values)
    if n < 30:
        return None
    rnd = random.Random(20261103)
    means = []
    for _ in range(samples):
        means.append(math.fsum(values[rnd.randrange(n)] for _ in range(n))/n)
    means.sort()
    return [means[int(samples * .025)], means[int(samples * .975)-1]]


def _sign_test(b_only, a_only):
    """Exact two-sided equal-win conditional test for discordant race pairs."""
    n = b_only+a_only
    if n == 0:
        return None
    k = min(b_only, a_only)
    # Recurrence avoids computing enormous exact combinations.
    term = math.ldexp(1., -n) if n <= 1022 else 0.
    terms = [term]
    for i in range(k):
        if term == 0:
            return None
        term *= (n-i)/(i+1)
        terms.append(term)
    return min(1., 2*math.fsum(terms))


def analyze(rows, *, minimum_paired=PAIRED_MIN, minimum_days=DAYS_MIN):
    """Score every eligible confirmed race; missing predictions stay misses.

    All discovered races must be supplied by a complete external day/venue
    registry; this function never pretends selected rows are a complete day.
    """
    _need(isinstance(rows,list) and len(rows) <= 12000, "bounded day ledger list required")
    _need(type(minimum_paired) is int and minimum_paired >= 30
          and type(minimum_days) is int and minimum_days >= 2, "predeclared gate required")
    ids=set()
    states=Counter()
    compared=[]
    all_eligible=[]
    covered=[]
    for row in sorted(rows, key=lambda x:x["race_id"] if isinstance(x,dict) else ""):
        rid,cutoff=_race_row(row)
        _need(rid not in ids, "duplicate official race in cohort")
        ids.add(rid)
        states[row["result_state"]]+=1
        if row["result_state"]!="SETTLED":
            continue
        all_eligible.append(row)
        pair=_verified_pair(row,cutoff)
        if pair is None:
            continue
        covered.append(row)
        compared.append(pair)
    n=len(all_eligible)
    matched=len(covered)
    a=list(x[0] for x in compared)
    b=list(x[1] for x in compared)
    missing=n-matched
    out={
        "schema":"RACE_AI_BOAT_AB_PROSPECTIVE_COHORT_V1",
        "total_discovered":len(rows),
        "state_counts":dict(sorted(states.items())),
        "officially_settled_eligible":n,
        "paired_forecast_count":matched,
        "unforecast_or_unverified":missing,
        "distinct_days":len({row["race_id"][:8] for row in all_eligible}),
        "paired_days":len({row["race_id"][:8] for row in covered}),
        "coverage_all_eligible":matched/n if n else None,
        "models":[],
        "paired_comparison":None,
        "model_auto_promoted":False,
        "statement":"INCONCLUSIVE_NOT_ENOUGH_PROSPECTIVE_EVIDENCE",
        "scope_note":"Only supplied discovered race ledger; external complete schedule proof needed before all-race claims",
        "scores_calibrated":False,
        "money_staked":False,
    }
    for k, name in enumerate(MODEL_IDS):
        mx=[a,b][k]
        hit1=sum(x["hit_at_1"] for x in mx)
        hit8=sum(x["hit_at_8"] for x in mx)
        valid_payout=all(row["payout_per_100_yen"] is not None for row in covered)
        gross=sum(row["payout_per_100_yen"] * m["hit_at_8"]
                  for row,m in zip(covered,mx)) if valid_payout else None
        o={
            "model_id":name,
            "hit_at_1_all":hit1/n if n else None,
            "hit_at_8_all":hit8/n if n else None,
            "hit_at_1_matched":hit1/matched if matched else None,
            "hit_at_8_matched":hit8/matched if matched else None,
            "hit_at_8_all_wilson95":wilson(hit8,n),
            "hit_at_1_all_wilson95":wilson(hit1,n),
            "hits_at_1":hit1, "hits_at_8":hit8,
            "avg_multiclass_brier":math.fsum(m["multiclass_brier"] for m in mx)/matched if matched else None,
            "avg_log_loss":math.fsum(m["log_loss"] for m in mx)/matched if matched else None,
            "mean_top8_model_mass":math.fsum(m["model_top8_mass_uncalibrated"] for m in mx)/matched if matched else None,
            "empirical_top8_matched_rate":hit8/matched if matched else None,
            "calibration_bins": [
                {"bin_lo": i/10, "bin_hi": (i+1)/10,
                 "count": len([m for m in mx if min(9,int(10*m["model_top8_mass_uncalibrated"]))==i]),
                 "mean_predicted_mass": (
                    math.fsum(m["model_top8_mass_uncalibrated"] for m in mx
                        if min(9,int(10*m["model_top8_mass_uncalibrated"]))==i) /
                    len([m for m in mx if min(9,int(10*m["model_top8_mass_uncalibrated"]))==i]))
                    if any(min(9,int(10*m["model_top8_mass_uncalibrated"]))==i for m in mx) else None,
                 "empirical_hit_rate": (
                    math.fsum(m["hit_at_8"] for m in mx
                        if min(9,int(10*m["model_top8_mass_uncalibrated"]))==i) /
                    len([m for m in mx if min(9,int(10*m["model_top8_mass_uncalibrated"]))==i]))
                    if any(min(9,int(10*m["model_top8_mass_uncalibrated"]))==i for m in mx) else None,
                 "low_sample_flag":sum(min(9,int(10*m["model_top8_mass_uncalibrated"]))==i for m in mx)<30}
                for i in range(10)
            ],
            "hypothetical_8x100_yen_spend":800*matched,
            "hypothetical_return_yen":gross,
            "hypothetical_roi_on_covered":gross/(800*matched) if gross is not None and matched else None,
            "hypothetical_only":True,
        }
        out["models"].append(o)
    if matched:
        b_only=sum(x["hit_at_8"]==0 and y["hit_at_8"]==1 for x,y in zip(a,b))
        a_only=sum(x["hit_at_8"]==1 and y["hit_at_8"]==0 for x,y in zip(a,b))
        diffs_hit8=[y["hit_at_8"]-x["hit_at_8"] for x,y in zip(a,b)]
        diffs_brier=[y["multiclass_brier"]-x["multiclass_brier"] for x,y in zip(a,b)]
        diffs_log=[y["log_loss"]-x["log_loss"] for x,y in zip(a,b)]
        diff_mass=[y["model_top8_mass_uncalibrated"]-x["model_top8_mass_uncalibrated"]
                   for x,y in zip(a,b)]
        comp={
            "paired_n":matched,
            "a_only_hits_at8":a_only,"b_only_hits_at8":b_only,
            "both_hit_at8":sum(x["hit_at_8"] and y["hit_at_8"] for x,y in zip(a,b)),
            "both_miss_at8":sum(not x["hit_at_8"] and not y["hit_at_8"] for x,y in zip(a,b)),
            "b_minus_a_hit_at8_paired":math.fsum(diffs_hit8)/matched,
            "b_minus_a_hit_at8_bootstrap95":_paired_bootstrap(diffs_hit8),
            "b_minus_a_multiclass_brier":math.fsum(diffs_brier)/matched,
            "b_minus_a_brier_bootstrap95":_paired_bootstrap(diffs_brier),
            "b_minus_a_log_loss":math.fsum(diffs_log)/matched,
            "b_minus_a_logloss_bootstrap95":_paired_bootstrap(diffs_log),
            "b_minus_a_top8_model_mass":math.fsum(diff_mass)/matched,
            "hit_at8_discordant_exact_p":_sign_test(b_only,a_only),
        }
        out["paired_comparison"]=comp
        # Decision rule is predeclared, NOT tuned to earlier result data.
        if matched>=minimum_paired and out["paired_days"]>=minimum_days:
            if (comp["b_minus_a_hit_at8_bootstrap95"][0]>0 and
                    comp["b_minus_a_brier_bootstrap95"][1]<0 and
                    comp["b_minus_a_logloss_bootstrap95"][1]<0 and
                    b_only>a_only):
                out["statement"]="PROSPECTIVE_EVIDENCE_FAVORS_B_NOT_AUTO_PROMOTED"
            else:
                out["statement"]="PROSPECTIVE_EVIDENCE_INCONCLUSIVE_OR_NOT_FAVORABLE"
    return out
