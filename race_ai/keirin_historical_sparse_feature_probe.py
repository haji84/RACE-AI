"""Reconstruct only defensible historical PR71 feature CANDIDATES.

Owner-private, network-free: the Nov 8 Matsuyama 7R pre-race sparse research
archive contains observed race score, starts, B and escape/makuri counts.
Reuse the existing PR71 source-to-feature map and transforms. Never invent
the 11 other mandatory per-rider features, the 9 environment observations,
source publication times or a past prediction freeze. This procedure does
NOT invoke PR71's four research models or promote retrospective scores.
"""
from __future__ import annotations

from hashlib import sha256
import math
import re

from .keirin_allowed_delivery import (
    RIDER_MAP, MODEL_REQUIRED, ENV_REQUIRED, _convert
)
from .keirin_result_delivery import canonical, utc

SCHEMA = "RACE_AI_KEIRIN_HISTORICAL_SPARSE_FEATURE_PROBE_V1"
ARCHIVE_SCHEMA = "RACE_AI_KEIRIN_REAL_RIDER_SHADOW_ONE_SHOT_V1"
EXPECTED = {
    "ability": ("race_score", "score_open_v2"),
    "recent_points": ("race_score", "score_open_v2"),
    "back_count_form": ("back_B_count", "count_rate"),
    "hsb_form": ("back_B_count", "count_rate"),
    "escape_style": ("style_escape", "ratio"),
    "makuri_style": ("style_makuri", "ratio"),
}
SOURCE_COLUMNS = frozenset({
    "name", "number", "observed_4mo_starts",
    "race_score", "B_count", "escape_count", "makuri_count"
})
NO_ADMISSION = "SOURCE_PUBLISHED_AT_AND_PER_PURPOSE_RIGHTS_NOT_ATTESTED"


class HistoricalSparseProbeError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise HistoricalSparseProbeError(reason)


def _numeric(value, *, integer=False):
    if integer:
        need(type(value) is int and 0 <= value <= 10000000,
             "INVALID_PRE_RACE_COUNT")
    else:
        need(type(value) in (int, float) and math.isfinite(value)
             and value >= 0, "INVALID_PRE_RACE_SCORE")
    return value


def probe_saved_sparse_research(record):
    """Return a public-safe summary + PRIVATE candidates, never a PR71 forecast.

    Claimed 21:51 issue timestamp is not independent source publication proof.
    No database, GitHub, public artifacts, new HTTP, or paid odds are touched.
    """
    need(type(record) is dict and record.get("schema") == ARCHIVE_SCHEMA
         and record.get("source_type") ==
             "assistant_current_turn_web_page_manual_numeric_facts",
         "WRONG_HISTORICAL_SOURCE_TYPE")
    race = record.get("race_id")
    need(type(race) is str and re.fullmatch(r"\d{12}", race)
         and race.startswith(record.get("event_date_jst","").replace("-","")),
         "INVALID_HISTORICAL_RACE_ID")
    need(record.get("event_cutoff_independently_verified") is False
         and record.get("independent_pre_cutoff_timestamp_receipt") is None
         and record.get("all_347_checked_in_this_local_run") is False
         and record.get("full_PR71_model_was_executed") is False,
         "WRONG_OR_ALREADY_PROMOTED_SOURCE_STATUS")
    cutoff=utc(record["published_sales_cutoff_at"])
    issued=utc(record["issued_at_jst"])
    need(issued < cutoff,
         "RESEARCH_ISSUE_TIMESTAMP_NOT_PRE_CUTOFF")
    riders=record.get("riders")
    need(type(riders) is list and len(riders) in (7, 9),
         "MISSING_SEVEN_OR_NINE_RIDERS")
    require={name:tuple(mapping) for name,mapping in EXPECTED.items()}
    need(all(RIDER_MAP.get(name) == tup for name,tup in require.items()),
         "EXISTING_PR71_FEATURE_MAPPING_CHANGED")
    seen=set()
    values={}
    for rider in riders:
        need(type(rider) is dict and set(rider) == SOURCE_COLUMNS,
             "RIDER_FIELDS_UNTRUSTED_OR_MISSING")
        n=rider["number"]
        need(type(n) is int and 1 <= n <= 9 and n not in seen,
             "DUPLICATE_OR_BAD_RIDER_NUMBER")
        seen.add(n)
        need(type(rider["name"]) is str and 0 < len(rider["name"]) <= 100,
             "RIDER_NAME_MISSING")
        starts=_numeric(rider["observed_4mo_starts"],integer=True)
        need(starts>0, "RIDER_STAMINA_SAMPLE_ZERO")
        counts={
            key:_numeric(rider[key],integer=True)
            for key in ("B_count","escape_count","makuri_count")
        }
        need(all(v<=starts for v in counts.values()) and
             counts["escape_count"]+counts["makuri_count"] <= starts,
             "RIDER_COUNT_EXCEEDS_SAMPLE")
        score=_numeric(rider["race_score"])
        source={
            "race_score": score,
            "back_B_count": counts["B_count"],
            "style_escape": counts["escape_count"]/starts,
            "style_makuri": counts["makuri_count"]/starts,
        }
        derived={}
        for feature,(origin,method) in EXPECTED.items():
            sample=starts if method=="count_rate" else 1
            # Same deterministic transforms as PR101 permitted intake.
            derived[feature]=_convert(source[origin],sample,method)
        need(all(0<=v<=1 and math.isfinite(v) for v in derived.values()),
             "NONFINITE_NORMALIZED_CANDIDATE")
        values[n]=derived
    need(seen==set(range(1,len(riders)+1)),
         "ROSTER_NOT_CONTIGUOUS")
    lines=record.get("lineups_only_expected")
    need(type(lines) is list and
         all(type(group) is list and len(group)>=2 and
             all(type(n) is int for n in group) for group in lines)
         and sorted(n for group in lines for n in group)==sorted(seen),
         "UNCONFIRMED_OR_INCOMPLETE_EXPECTED_LINEUP")
    required=sorted(MODEL_REQUIRED)
    optional=sorted(set(EXPECTED)-MODEL_REQUIRED)
    required_present=[k for k in required if k in EXPECTED]
    counts={
        "source_observed_riders":len(riders),
        "source_distinct_numeric_stat_types":4,
        "model_required_features_per_rider":len(required),
        "model_required_feature_slots":len(required)*len(riders),
        "required_candidates_normalized_not_admitted":
            len(required_present)*len(riders),
        "required_slots_not_supported":
            (len(required)-len(required_present))*len(riders),
        "environment_required_slots":len(ENV_REQUIRED),
        "environment_candidates":0,
        "optional_candidate_slots":len(optional)*len(riders),
        "all_candidate_slots":len(EXPECTED)*len(riders),
    }
    summary={
        "schema":SCHEMA,
        "race_id":race,
        "source_archive_canonical_sha256":sha256(canonical(record)).hexdigest(),
        "claimed_issued_before_cutoff":True,
        "independent_pre_cutoff_receipt_verified":False,
        "source_observation_publication_time_per_field_verified":False,
        "source_capture_timestamp_per_field_verified":False,
        "source_rights_per_purpose_independently_verified":False,
        "official_cutoff_independently_verified":False,
        "complete_347_factor_audit":False,
        "candidate_feature_names":sorted(EXPECTED),
        "required_feature_names_without_source":
            sorted(set(required)-set(required_present)),
        "counts":counts,
        "normalized_feature_candidates_are_not_admitted_model_inputs":True,
        "eligible_for_pr71_four_model_replay":False,
        "official_predictive_performance":None,
        "model_inference_executed":False,
        "no_fill_or_hindsight_retraining":True,
        "state":"BLOCKED_"+NO_ADMISSION,
    }
    return {"public_summary":summary,
            "private_candidate_values_by_rider":values}
