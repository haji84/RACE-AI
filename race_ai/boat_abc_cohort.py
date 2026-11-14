"""Existing frozen BOAT A/B/C-lite same-race scoreboard, never new predictions.

Consumes result packets already authenticated by the existing nationwide
result workflow. Never trusts this module alone as proof of source authenticity.
A selected-results cohort is not the complete nationwide eligible population.
"""
from __future__ import annotations

from datetime import datetime
import math
import re

from .boat_shadow_result_audit import AB_IDS, C_ID

ABC = (*AB_IDS, C_ID)
NORMAL = "ABC_SAME_FROZEN_INPUT_SCORED"
RID = re.compile(r"^\d{8}-(?:0[1-9]|1\d|2[0-4])-(?:0[1-9]|1[0-2])$")
HEX64 = re.compile(r"^[a-f0-9]{64}$")


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _time(value):
    try:
        v = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(v.tzinfo is not None and v.utcoffset() is not None,
                 "timezone absent")
        return v
    except (AttributeError, ValueError) as exc:
        raise ValueError("invalid time in original/result") from exc


def summarize_abc_results(packets, *, min_races=100, min_days=5,
                          min_venue_day_blocks=10):
    """Aggregate exact three-model comparisons without creating any forecast.

    Input: list of previously verified boat-national result.json packets.
    The caller MUST independently verify GitHub artifact ZIP/JSON hash, earliest
    external pre-cutoff receipt, and official source before invoking this.
    """
    _require(type(packets) is list and 1 <= len(packets) <= 1000,
             "bounded result packet list required")
    _require(all(type(n) is int and n >= 1 for n in
                 (min_races, min_days, min_venue_day_blocks)),
             "positive fixed evidence gates")
    scored, exceptions, seen, seen_artifacts = [], [], set(), set()
    for packet in packets:
        _require(isinstance(packet, dict) and
                 packet.get("schema") ==
                 "RACE_AI_BOAT_NATIONAL_3R_RESULT_AUDIT_V1" and
                 packet.get("first_receipt_per_race_only") is True and
                 packet.get("past_predictions_untouched") is True and
                 packet.get("model_coefficients_unchanged") is True and
                 packet.get("research_only") is True and
                 packet.get("actual_purchases") is False,
                 "upstream official frozen-result audit flags invalid")
        artifact = packet.get("frozen_artifact_id")
        _require(type(artifact) is int and artifact > 0 and
                 artifact not in seen_artifacts, "duplicate original artifact")
        seen_artifacts.add(artifact)
        _require(isinstance(packet.get("frozen_forecast_json_sha256"), str) and
                 HEX64.fullmatch(packet["frozen_forecast_json_sha256"]),
                 "missing original forecast hash")
        source = packet.get("official_results")
        abc = packet.get("frozen_current_feature_comparison")
        _require(type(source) is list and isinstance(abc, dict) and
                 abc.get("schema") == "RACE_AI_BOAT_FROZEN_ABC_COMPARISON_V1" and
                 type(abc.get("comparisons")) is list and
                 abc.get("auto_promoted") is False and
                 abc.get("past_forecasts_changed") is False,
                 "invalid A/B/C frozen comparison")
        by_race = {row["race_id"]: row for row in source}
        _require(len(by_race) == len(source) ==
                 len(abc["comparisons"]), "result audit coverage mismatch")
        for comparison in abc["comparisons"]:
            race = comparison.get("race_id")
            _require(isinstance(race, str) and RID.fullmatch(race) and
                     race in by_race and race not in seen,
                     "duplicate/malformed/foreign race")
            seen.add(race)
            official = by_race[race]
            if comparison.get("state") != NORMAL:
                exceptions.append({"race_id": race,
                                   "reason": comparison.get("state")})
                continue
            _require(official.get("state") == "INDEPENDENT_AB_RESULT_VERIFIED",
                     "abnormal result must not enter normal 3T score")
            _require(comparison.get("official_top3") == official.get("official_top3")
                     and comparison.get("payout_per_100_yen") ==
                     official.get("payout_per_100_yen") and
                     comparison.get("pair_bundle_sha256") ==
                     official["paired_comparison"].get("pair_bundle_sha256"),
                     "result and frozen A/B hash mismatch")
            _require(isinstance(official.get("official_source_sha256"), str)
                     and HEX64.fullmatch(official["official_source_sha256"]),
                     "official result source SHA absent")
            saved = _time(comparison["server_saved_at"])
            cutoff = _time(official["paired_comparison"]["cutoff_at"])
            observed = _time(official["result_captured_at"])
            _require(saved < cutoff < observed and
                     official["paired_comparison"]["forecast_server_saved_at"]
                     == comparison["server_saved_at"],
                     "original receipt does not precede result")
            payout = comparison["payout_per_100_yen"]
            _require(type(payout) is int and payout > 0,
                     "missing 100-yen official payout")
            models = comparison.get("models")
            _require(type(models) is list and len(models) == 3 and
                     tuple(m.get("model_id") for m in models) == ABC,
                     "expected frozen A/B/C-lite identities")
            verified = {}
            for m in models:
                rank = m.get("winning_combination_rank")
                _require(type(rank) is int and 1 <= rank <= 120 and
                         m.get("hit_at_1") == int(rank == 1) and
                         m.get("hit_at_8") == int(rank <= 8) and
                         m.get("virtual_stake_yen") == 800 and
                         m.get("virtual_payout_yen") ==
                         (payout if rank <= 8 else 0) and
                         m.get("actual_man_shu") == (payout >= 10000) and
                         m.get("man_shu_missed") ==
                         (payout >= 10000 and rank > 8) and
                         m.get("calibrated") is False,
                         "score/rank/return contract mismatch")
                for name in ("multiclass_brier", "log_loss"):
                    _require(type(m.get(name)) in (int, float) and
                             math.isfinite(m[name]), "invalid proper score")
                verified[m["model_id"]] = {
                    "winning_rank": rank, "hit1": int(rank == 1),
                    "hit8": int(rank <= 8),
                    "hit12_research_only": int(rank <= 12),
                    "return8_yen": payout if rank <= 8 else 0,
                    "return12_research_yen": payout if rank <= 12 else 0}
            for mid in AB_IDS:
                prev = next((m for m in
                             official["paired_comparison"]["models"]
                             if m.get("model_id") == mid), None)
                _require(prev is not None and
                         prev.get("winning_combination_rank") ==
                         verified[mid]["winning_rank"],
                         "independent A/B audit rank changed")
            scored.append({
                "race_id": race, "original_artifact_id": artifact,
                "result_source_sha256": official["official_source_sha256"],
                "official_top3": comparison["official_top3"],
                "official_payout_per_100_yen": payout,
                "models": verified})
    count = len(scored)
    day_count = len({r["race_id"][:8] for r in scored})
    blocks = len({r["race_id"][:11] for r in scored})
    summary = {}
    man_shu_count = sum(r["official_payout_per_100_yen"] >= 10000
                       for r in scored)
    for name in ABC:
        h8 = sum(r["models"][name]["hit8"] for r in scored)
        h12 = sum(r["models"][name]["hit12_research_only"] for r in scored)
        recv8 = sum(r["models"][name]["return8_yen"] for r in scored)
        recv12 = sum(r["models"][name]["return12_research_yen"]
                     for r in scored)
        manshu_hit = sum(r["models"][name]["hit8"] for r in scored
                         if r["official_payout_per_100_yen"] >= 10000)
        summary[name] = {
            "races": count, "hit_at_8": h8,
            "hit_at_8_rate": h8/count if count else None,
            "stake8_yen": count * 800, "return8_yen": recv8,
            "net8_yen": recv8-count*800,
            "roi8": recv8/(count*800) if count else None,
            "hit_at_12_retrospective": h12,
            "return12_retrospective_yen": recv12,
            "roi12_retrospective": recv12/(count*1200) if count else None,
            "actual_manshu_events": man_shu_count,
            "manshu_hit8": manshu_hit,
            "manshu_capture8": manshu_hit/man_shu_count
                               if man_shu_count else None}
    return {
        "schema": "RACE_AI_BOAT_ABC_FROZEN_SELECTED_RESULTS_V1",
        "normal_scored": count, "exceptions": exceptions,
        "unique_dates": day_count, "unique_venue_day_blocks": blocks,
        "meets_minimum_sample_gate": (count >= min_races and
                                      day_count >= min_days and
                                      blocks >= min_venue_day_blocks),
        "complete_national_denominator_verified": False,
        "original_zip_and_external_receipt_reverification_here": False,
        "requires_upstream_verified_receipts": True,
        "research_only": True,
        "production_model_promotion": False,
        "winner_selected": None, "model_metrics": summary,
        "race_rows": scored}
