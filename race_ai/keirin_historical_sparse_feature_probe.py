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



SECOND_RACE_SCHEMA = "MATS2R_RESEARCH_SCENARIO_PREDICTION_V1"
SECOND_RACE_COLUMNS = frozenset({
    "n", "name", "p", "w", "nr", "p3", "b", "esc", "mak",
    "sashi", "mark", "recent", "line", "role",
})
SECOND_RACE_MAP = {
    **EXPECTED,
    "consistency": ("top_three_rate", "ratio"),
    "recent_win_form": ("win_rate", "ratio"),
    "sashi_style": ("style_sashi", "ratio"),
}


def probe_saved_second_race_reference(document):
    """Reconstruct candidate-only R2 features from a DIFFERENT research model.

    Legacy six-scenario outcomes and market odds are never read as PR71 inputs.
    The complete 210 predictions do not imply 210 original PR71 rankings.
    """
    need(type(document) is dict and
         document.get("schema") == SECOND_RACE_SCHEMA and
         document.get("status") ==
             "research_only_uncalibrated_no_official_frozen_proof",
         "WRONG_SECOND_RACE_RESEARCH_ARCHIVE")
    methodology=document.get("methodology",{})
    need(type(methodology) is dict and
         methodology.get("source_admission_verified_for_RACE_AI") is False
         and methodology.get("independent_validation") is False
         and methodology.get("calibrated") is False,
         "SECOND_RACE_UNEXPECTED_ADMISSION_OR_CALIBRATION")
    race=document.get("race",{})
    need(type(race) is dict and race.get("date_jst")=="2026-11-08"
         and race.get("venue")=="松山" and race.get("race_number")==2,
         "SECOND_RACE_UNMATCHED_TARGET")
    issued=utc(race["as_of_jst"])
    cutoff=utc(race["date_jst"]+"T"+race["sales_cutoff_jst"]+":00+09:00")
    need(issued<cutoff, "SECOND_RACE_NOT_CLAIMED_PRE_CUTOFF")
    need(all(RIDER_MAP.get(k) == v for k,v in SECOND_RACE_MAP.items()),
         "PR71_SECOND_RACE_MAPPING_CHANGED")
    riders=document.get("participants")
    need(type(riders) is list and len(riders)==7,
         "SECOND_RACE_FULL_SEVEN_RIDERS_REQUIRED")
    numbers=set()
    values={}
    for row in riders:
        need(type(row) is dict and set(row)==SECOND_RACE_COLUMNS,
             "SECOND_RACE_RIDER_SOURCE_SHAPE_MISSING")
        number=row["n"]
        need(type(number) is int and number in range(1,8)
             and number not in numbers,
             "SECOND_RACE_DUPLICATE_NUMBER")
        numbers.add(number)
        need(type(row["name"]) is str and len(row["name"])>=1,
             "SECOND_RACE_RIDER_IDENTITY_MISSING")
        starts=_numeric(row["nr"],integer=True)
        need(starts>0, "SECOND_RACE_SAMPLE_MISSING")
        counts={field:_numeric(row[field],integer=True) for field in
                ("w","p3","b","esc","mak","sashi","mark")}
        need(all(n<=starts for n in counts.values()) and
             counts["w"]<=counts["p3"] and
             counts["esc"]+counts["mak"]+
             counts["sashi"]+counts["mark"]<=starts,
             "SECOND_RACE_COUNTS_INCONSISTENT")
        recent=row["recent"]
        need(type(recent) is list and len(recent)==6 and
             all(type(v) is int and 1<=v<=9 for v in recent),
             "SECOND_RACE_UNVERIFIED_RECENT_RESULTS")
        score=_numeric(row["p"])
        raw={
            "race_score":score,
            "top_three_rate":counts["p3"]/starts,
            "win_rate":counts["w"]/starts,
            "back_B_count":counts["b"],
            "style_escape":counts["esc"]/starts,
            "style_makuri":counts["mak"]/starts,
            "style_sashi":counts["sashi"]/starts,
        }
        normalized={}
        for feature,(origin,transform) in SECOND_RACE_MAP.items():
            sample=starts if transform=="count_rate" else 1
            normalized[feature]=_convert(raw[origin],sample,transform)
        need(all(math.isfinite(v) and 0<=v<=1
                 for v in normalized.values()),
             "SECOND_RACE_NAN_NORMALIZATION")
        values[number]=normalized
    need(numbers==set(range(1,8)), "SECOND_RACE_ROSTER_INCOMPLETE")
    lines=race.get("line_assumptions")
    need(type(lines) is list and
         all(type(group) is list and len(group)>=2
             and all(type(n) is int for n in group) for group in lines)
         and sorted(n for group in lines for n in group)==list(range(1,8)),
         "SECOND_RACE_LINE_ROSTER_INCOMPLETE")
    # Expected line roles may not be promoted into line-coordination skill.
    for group in lines:
        for index,n in enumerate(group):
            row=next(r for r in riders if r["n"]==n)
            need(row["line"]==group[0] and row["role"]==index,
                 "SECOND_RACE_LINE_ROLE_CONFLICT")
    required=sorted(MODEL_REQUIRED)
    present=sorted(set(required) & set(SECOND_RACE_MAP))
    return {
        "public_summary":{
            "schema":SCHEMA,
            "source_kind":"MATS2R_DIFFERENT_UNTRAINED_RESEARCH_ARCHIVE",
            "source_archive_canonical_sha256":
                sha256(canonical(document)).hexdigest(),
            "race_id":"202611087502",
            "claimed_pre_cutoff_generation":True,
            "independent_field_publication_and_capture_proven":False,
            "independent_original_forecast_witness_proven":False,
            "rights_per_purpose_independently_confirmed":False,
            "existing_pr71_model_executed":False,
            "candidate_feature_names":sorted(SECOND_RACE_MAP),
            "missing_required_feature_names":sorted(
                set(required)-set(present)),
            "counts":{
                "source_observed_riders":7,
                "model_required_feature_slots":7*len(required),
                "required_candidates_normalized_not_admitted":7*len(present),
                "required_slots_not_supported":
                    7*(len(required)-len(present)),
                "environment_required_slots":len(ENV_REQUIRED),
                "environment_candidates":0,
                "optional_candidate_slots":
                    7*len(set(SECOND_RACE_MAP)-set(required)),
                "all_candidate_slots":7*len(SECOND_RACE_MAP),
            },
            "full_pr71_four_model_replay_eligible":False,
            "historical_210_from_other_model_not_PR71":True,
            "model_inference_executed":False,
            "formal_accuracy":None,
            "state":"BLOCKED_"+NO_ADMISSION,
        },
        "private_candidate_values_by_rider":values,
    }
