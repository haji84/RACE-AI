"""As-of-safe horse historical win-rate contrasts: research only, no IO.

This does NOT authenticate the supplied counts or sources. A trusted data
pipeline must separately verify all historical results, eligibility rules,
publication time and source rights. An unverified TV '8/8' is not evidence.
Only use the generated observation after independent audit.
"""
from __future__ import annotations

from .comprehensive_four_sport_models import (
    HISTORY_TRANSFORM, HISTORICAL_HORSE_FEATURES, ModelInputError,
    RESEARCH, SYNTHETIC, moment,
)

def build_historical_win_signal(
    *,
    feature_name,
    case_wins,
    case_total,
    comparison_wins,
    comparison_total,
    condition_description,
    comparison_description,
    published_at,
    captured_at,
    as_of,
    source_ref,
    source_rights_ref,
    scope=SYNTHETIC,
    allow_source=None,
):
    """Construct a smoothed, sample-shrunk signal with a separate audit record.

    Inputs are *pre-race counts*, not post-race predictions or bookmaker odds.
    The comparison group should be independent (e.g., same race type with
    a jockey switch), defined before looking at the target race result.
    This score is NOT a calibrated win probability, even if case_wins == n.
    The function checks claims for internal consistency, not source truth.
    """
    if feature_name not in HISTORICAL_HORSE_FEATURES:
        raise ModelInputError("unsupported horse history signal")
    if scope not in (SYNTHETIC, RESEARCH):
        raise ModelInputError("history source scope invalid")
    for name, wins, total in (
        ("case", case_wins, case_total),
        ("comparison", comparison_wins, comparison_total),
    ):
        if (type(total) is not int or type(wins) is not int or
                not 1 <= total <= 10000000 or not 0 <= wins <= total):
            raise ModelInputError(name+" wins/total invalid")
    for name, value in (
        ("condition_description", condition_description),
        ("comparison_description", comparison_description),
        ("source_ref", source_ref),
        ("source_rights_ref", source_rights_ref),
    ):
        if not isinstance(value, str) or not 1 <= len(value) <= 256:
            raise ModelInputError(name+" missing")
    if condition_description == comparison_description:
        raise ModelInputError("case/comparison cohorts must be distinct")
    pub, cap, cutoff = moment(published_at), moment(captured_at), moment(as_of)
    if not pub <= cap <= cutoff:
        raise ModelInputError("historical counts not available by forecast as_of")
    if (scope == RESEARCH and
        (allow_source is None or
         allow_source(source_ref, source_rights_ref, "analysis") is not True)):
        raise ModelInputError("historical source analysis permission not admitted")

    # Beta(1,1) posterior means, then shrink toward a neutral 0.5
    # as case_total approaches zero; 8/8 does not become 100%.
    case_rate = (case_wins+1)/(case_total+2)
    comparison_rate = (comparison_wins+1)/(comparison_total+2)
    shrinkage = case_total/(case_total+20)
    score = 0.5 + 0.5*(case_rate-comparison_rate)*shrinkage
    observation = {
        "value": score,
        "published_at": published_at,
        "captured_at": captured_at,
        "source_ref": source_ref,
        "source_rights_ref": source_rights_ref,
        "sample_n": case_total,
        "transform_id": HISTORY_TRANSFORM,
    }
    audit = {
        "feature_name": feature_name,
        "outcome": "win",
        "condition_description": condition_description,
        "comparison_description": comparison_description,
        "case_wins": case_wins,
        "case_total": case_total,
        "comparison_wins": comparison_wins,
        "comparison_total": comparison_total,
        "case_beta11_rate": case_rate,
        "comparison_beta11_rate": comparison_rate,
        "sample_shrinkage": shrinkage,
        "forecast_input_signal": score,
        "published_at": published_at,
        "captured_at": captured_at,
        "as_of": as_of,
        "source_ref": source_ref,
        "source_rights_ref": source_rights_ref,
        "source_counts_externally_audited": False,
        "source_rights_externally_admitted": scope == RESEARCH and allow_source is not None,
        "status": "RESEARCH_ONLY_UNCALIBRATED",
    }
    return {"observation": observation, "audit": audit}
