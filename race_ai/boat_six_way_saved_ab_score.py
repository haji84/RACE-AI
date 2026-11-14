"""Score genuinely saved P1 A/B BOAT shadows, without generating either one.

Uses the existing independent AES-view caller and retained official RESULT
revision eligibility; refuses to score a B reconstructed after race cutoff.
A and B are the same physical race, eight tickets x ¥100, not wagers.
No provider GET, training, original forecast mutation, or model promotion.
"""
from collections import Counter
from math import fsum, isfinite, log
import re

from . import saved_view_feed as F
from .actions_contract import digest
from .retained_model_pdca_audit import (
    _result_context, _saved_clock, _score_using_existing_bulk_engine,
)

SCHEMA = "RACE_AI_BOAT_SIXWAY_SAVED_AB_SCORE_V1"
B_VARIANT = "B_SIX_COURSE_TACTICS"
B_RESEARCH_SCHEMA = "RACE_AI_BOAT_SIXWAY_OVERLAY_V1"
SHA = re.compile(r"[a-f0-9]{64}\Z")
TICKET = re.compile(r"([1-6])-([1-6])-([1-6])\Z")


def _need(condition, reason):
    if not condition:
        raise ValueError("SIX_WAY_SAVED_AB_" + reason)


def _tickets(rows):
    _need(type(rows) is list and len(rows) == 8, "EQUAL_TOP8_REQUIRED")
    value = []
    for part in rows:
        _need(type(part) is list and len(part) == 3 and
              all(type(n) is int and n in range(1, 7) for n in part)
              and len(set(part)) == 3, "TICKET_INVALID")
        value.append(tuple(part))
    _need(len(set(value)) == 8, "TICKET_DUPLICATED")
    return value


def _distribution(rows):
    """All 120 ordered *boat numbers*, not observed courses."""
    if type(rows) is not list or len(rows) != 120:
        raise ValueError("SIX_WAY_SAVED_AB_FULL120_REQUIRED")
    dist = {}
    for row in rows:
        _need(type(row) is dict and set(row) >= {"ticket", "score"},
              "DISTRIBUTION_ROW_INVALID")
        m = TICKET.fullmatch(row["ticket"]) if type(row["ticket"]) is str else None
        score = row["score"]
        _need(m is not None and len(set(m.groups())) == 3 and
              type(score) in (float, int) and isfinite(score) and score > 0 and
              row["ticket"] not in dist, "DISTRIBUTION_CONTENT_INVALID")
        dist[row["ticket"]] = score
    _need(len(dist) == 120 and abs(fsum(dist.values()) - 1.0) <= 1e-7,
          "DISTRIBUTION_SUM_INVALID")
    return dist


def _saved(row, prediction):
    _need(type(prediction) is dict and prediction.get("stage") == "P1",
          "P1_ORIGINAL_REQUIRED")
    _saved_clock(prediction, row)
    _need(prediction.get("race_id", row["race_id"]) == row["race_id"] and
          prediction.get("cutoff_at", row["cutoff_at"]) == row["cutoff_at"],
          "P1_RACE_CUTOFF_MISMATCH")
    tickets = _tickets(prediction.get("ordered_top8"))
    distribution = _distribution(prediction.get("full_120"))
    expected = ["-".join(map(str, t)) for t in tickets]
    ranked = sorted(distribution, key=lambda k: (-distribution[k], k))
    _need(expected == ranked[:8], "TOP8_NOT_SAME_AS_DISTRIBUTION")
    return tickets, distribution


def _baseline_and_b(row):
    predictions = ([row["prediction"]] if row.get("prediction") else []) + list(
        row.get("comparison_predictions") or []
    )
    bases = [p for p in predictions if type(p) is dict and
             p.get("stage") == "P1" and (
                 p is row.get("prediction") or
                 p.get("research_variant") == "A_FROZEN_BASELINE"
             )]
    shadows = [p for p in predictions if type(p) is dict and
               p.get("research_variant") == B_VARIANT and
               p.get("research_schema") == B_RESEARCH_SCHEMA]
    _need(len(bases) == 1, "EXACTLY_ONE_SAVED_A_REQUIRED")
    _need(len(shadows) == 1, "EXACTLY_ONE_SAVED_B_REQUIRED")
    a, b = bases[0], shadows[0]
    _need(b is not a and b.get("stage") == "P1", "B_STORED_AS_SEPARATE_P1")
    _need(type(b.get("baseline_prediction_sha256")) is str and
          SHA.fullmatch(b["baseline_prediction_sha256"]) and
          b["baseline_prediction_sha256"] == digest(a),
          "B_FROZEN_A_DIGEST_MISMATCH")
    _need(type(b.get("research_feature_sha256")) is str and
          SHA.fullmatch(b["research_feature_sha256"]) and
          type(b.get("six_way_context")) is dict and
          b["research_feature_sha256"] == digest(b["six_way_context"]),
          "B_FEATURE_CONTEXT_DIGEST_MISMATCH")
    _need(b["six_way_context"].get("race_id") == row["race_id"],
          "B_CONTEXT_RACE_MISMATCH")
    return a, b


def score_ab_view(view, *, authenticated):
    """Only numbers and HOLD reason counts leave the authenticated caller."""
    _need(authenticated is True and type(view) is dict and
          view.get("dataset_status") == "REAL_REPORTED",
          "AUTHENTICATED_REAL_SAVED_VIEW_REQUIRED")
    F.forecast_anchor(view)
    reasons = Counter()
    counts = Counter()
    summary = {
        k: dict(hit=0, eligible=0, high_payout_captured=0,
                invested_yen=0, received_yen=0, refunded_yen=0,
                probability_races=0, log_loss_sum=0.0, brier120_sum=0.0)
        for k in ("A_FROZEN_BASELINE", B_VARIANT)
    }
    for row in view.get("records", []):
        if row.get("sport") != "boat":
            continue
        counts["saved_boat_races"] += 1
        try:
            a, b = _baseline_and_b(row)
        except (ValueError, KeyError, TypeError):
            reasons["HOLD_SAME_RACE_P1_A_B_NOT_FROZEN"] += 1
            continue
        try:
            ta, pa = _saved(row, a)
            tb, pb = _saved(row, b)
        except (ValueError, KeyError, TypeError):
            reasons["HOLD_PRE_CUTOFF_SAVED_FULL120_OR_TOP8_INVALID"] += 1
            continue
        try:
            result_state, winners, refunds = _result_context(row)
        except (ValueError, TypeError, KeyError):
            reasons["HOLD_OFFICIAL_RESULT_PROOF_INVALID"] += 1
            continue
        if result_state != "FINAL":
            reasons["HOLD_OFFICIAL_RESULT_NOT_FINAL"] += 1
            continue
        _need(type(winners) is dict and bool(winners) and type(refunds) is set,
              "OFFICIAL_WINNERS_INVALID")
        # The existing bulk scorer alone handles monetary refunds and ties.
        try:
            sa = _score_using_existing_bulk_engine(
                row, a, ta, winners, refunds, "FINAL", "SIXWAY_A_REFERENCE")
            sb = _score_using_existing_bulk_engine(
                row, b, tb, winners, refunds, "FINAL", "SIXWAY_B_REFERENCE")
        except (ValueError, TypeError, KeyError):
            reasons["HOLD_ORIGINAL_BULK_SETTLEMENT_REJECTED"] += 1
            continue
        # A completely refunded ticket set is not a losing race. Exclude
        # the entire matched pair so both variants retain the same denominator.
        if sa["status"] == "FULL_REFUND" or sb["status"] == "FULL_REFUND":
            reasons["HOLD_FULL_REFUND_NOT_A_MISS"] += 1
            continue
        high = any(payout >= 10000 for payout in winners.values())
        for key, score, tickets, distribution in (
            ("A_FROZEN_BASELINE", sa, ta, pa),
            (B_VARIANT, sb, tb, pb),
        ):
            g = summary[key]
            g["eligible"] += 1
            g["hit"] += int(score["status"] in ("HIT", "HIT_PLUS_REFUND"))
            g["high_payout_captured"] += int(
                any(winners.get(t, 0) >= 10000 for t in tickets)
            )
            g["invested_yen"] += score["gross_yen"]
            g["received_yen"] += score["received_yen"]
            g["refunded_yen"] += score["refund_yen"]
            if len(winners) == 1 and not refunds:
                winner = "-".join(map(str, next(iter(winners))))
                g["probability_races"] += 1
                g["log_loss_sum"] -= log(distribution[winner])
                g["brier120_sum"] += fsum(
                    (p - int(ticket == winner))**2
                    for ticket, p in distribution.items()
                )
        counts["same_race_formally_settled_ab_pairs"] += 1
        counts["high_payout_races"] += int(high)
    data = {}
    for key, g in summary.items():
        count = g["eligible"]
        data[key] = dict(
            races=count, hit_count=g["hit"],
            hit_at8_rate=g["hit"] / count if count else None,
            high_payout_captured=g["high_payout_captured"],
            invested_yen=g["invested_yen"], received_yen=g["received_yen"],
            refunded_yen=g["refunded_yen"],
            hypothetical_net_yen=g["received_yen"] - g["invested_yen"],
            probability_scored_races=g["probability_races"],
            mean_log_loss=g["log_loss_sum"] / g["probability_races"]
            if g["probability_races"] else None,
            mean_brier120=g["brier120_sum"] / g["probability_races"]
            if g["probability_races"] else None,
            hypothetical_roi=g["received_yen"] / g["invested_yen"]
            if g["invested_yen"] else None,
            actual_purchases=False,
        )
    return dict(schema=SCHEMA, saved_boat_races=counts["saved_boat_races"],
                compared_ab_races=counts["same_race_formally_settled_ab_pairs"],
                high_payout_events=counts["high_payout_races"],
                by_variant=data, hold_reasons=dict(sorted(reasons.items())),
                no_new_predictions_generated=True, existing_bulk_scorer_reused=True,
                input_view_authentication_asserted_by_caller=True,
                pre_cutoff_source_feature_proven_independently_here=False,
                real_purchase_result_available=False, provider_gets=0,
                production_model_promoted=False, original_p0_p1_unchanged=True)



def score_ab_views(views, *, authenticated):
    """Aggregate same-variant scores over distinct AES-restored day partitions."""
    _need(authenticated is True and type(views) is list and
          len(views) <= 64, "AUTHENTICATED_VIEWS_REQUIRED")
    seen = set()
    summaries = []
    for view in views:
        for row in view.get("records", []):
            if row.get("sport") != "boat":
                continue
            race_id = row.get("race_id")
            _need(type(race_id) is str and race_id not in seen,
                  "DUPLICATE_SAVED_RACE_ACROSS_VIEWS")
            seen.add(race_id)
        summaries.append(score_ab_view(view, authenticated=True))
    totals = {}
    for variant in ("A_FROZEN_BASELINE", B_VARIANT):
        counts = {key: sum(s["by_variant"][variant][key] for s in summaries)
                  for key in ("races", "hit_count", "high_payout_captured",
                              "invested_yen", "received_yen", "refunded_yen")}
        p_count = sum(s["by_variant"][variant]["probability_scored_races"]
                      for s in summaries)
        loss = sum(
            (s["by_variant"][variant]["mean_log_loss"] or 0) *
            s["by_variant"][variant]["probability_scored_races"]
            for s in summaries
        )
        brier = sum(
            (s["by_variant"][variant]["mean_brier120"] or 0) *
            s["by_variant"][variant]["probability_scored_races"]
            for s in summaries
        )
        totals[variant] = dict(
            **counts,
            probability_scored_races=p_count,
            mean_log_loss=loss/p_count if p_count else None,
            mean_brier120=brier/p_count if p_count else None,
            hit_at8_rate=counts["hit_count"] / counts["races"]
            if counts["races"] else None,
            hypothetical_net_yen=counts["received_yen"] - counts["invested_yen"],
            hypothetical_roi=counts["received_yen"] / counts["invested_yen"]
            if counts["invested_yen"] else None,
            actual_purchases=False,
        )
    reasons = Counter()
    for item in summaries:
        reasons.update(item["hold_reasons"])
    return dict(schema=SCHEMA, saved_boat_races=len(seen),
                compared_ab_races=sum(item["compared_ab_races"] for item in summaries),
                high_payout_events=sum(item["high_payout_events"] for item in summaries),
                by_variant=totals, hold_reasons=dict(sorted(reasons.items())),
                source_provider_requests=0, actual_purchase_data_available=False,
                real_source_feature_readback_independently_reverified=False,
                original_saved_forecasts_unchanged=True,
                production_model_promoted=False)
