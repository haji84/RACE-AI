"""Explain source deficits for PR71 without manufacturing values or rights.

Reads only the existing public, counts-only preflight report. Derives the
number of distinct source measurements using the already pinned PR71 feature
adapter and source taxonomy. No new provider requests, model or score.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import json

from race_ai.comprehensive_four_sport_models import feature_inventory
from race_ai.keirin_allowed_delivery import RIDER_MAP, ENV_MAP
from race_ai.keirin_field_acquisition import kind

SCHEMA = "RACE_AI_KEIRIN_PR71_SOURCE_ORIGIN_GAP_PLAN_V1"
PROBE_SCHEMA = "RACE_AI_KEIRIN_NEXT_PUBLISHED_RACE_SOURCE_GATE_V1"
CATEGORY_NAMES = frozenset((
    "pre_race_source_fact",
    "source_available_only_if_published_at_race_time",
    "derived_only_with_prior_evidence",
    "forecast_hypothesis_not_raw_data",
))


class SourceGapPlanError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise SourceGapPlanError(reason)


def summarize_source_gaps(probe):
    """A missing feature slot need not be a distinct missing raw fact."""
    require(type(probe) is dict and probe.get("schema") == PROBE_SCHEMA,
            "SOURCE_PROBE_SCHEMA_REQUIRED")
    n = probe.get("rider_identity_count")
    supplied = probe.get("required_source_slots_A_observed")
    missing = probe.get("required_source_slots_A_missing")
    total = probe.get("required_source_slots_total")
    groups = probe.get("required_source_gap_groups_A")
    if groups is None and all(x is None for x in (n, supplied, missing, total)):
        return {
            "schema": SCHEMA,
            "state": "HOLD_SOURCE_ORIGIN_COUNTS_NOT_OBSERVED",
            "distinct_missing_origin_instances": None,
            "formal_model_predictions_verified": False,
            "license_rights_verified": False,
        }
    require(type(n) is int and n in (7, 9) and
            all(type(x) is int for x in (supplied, missing, total)) and
            type(groups) is dict, "SOURCE_PROBE_REQUIRED_COUNTS_MISSING")

    feature_inventory_keirin = feature_inventory("keirin")
    required = tuple(feature_inventory_keirin["common_required"]) + tuple(
        feature_inventory_keirin["sport_required"])
    environmental = tuple(feature_inventory_keirin["environment_required"])
    require(all(field in RIDER_MAP for field in required) and
            all(field in ENV_MAP for field in environmental),
            "PINNED_PR71_FEATURE_MAP_CHANGED")

    rider = Counter(RIDER_MAP[feature][0] for feature in required)
    race = Counter("race/" + ENV_MAP[feature][0] for feature in environmental)
    expected_slots = n * len(required) + len(environmental)
    distinct_total = n * len(rider) + len(race)
    require(total == expected_slots and
            0 <= missing <= total and supplied == total - missing and
            len(groups) <= len(rider) + len(race),
            "MODEL_SLOT_TOTAL_OR_INVENTORY_MISMATCH")

    categories = {}
    missing_origin_instances = 0
    gap_rows = []
    seen = set()
    total_group_slots = 0
    for source, slots in sorted(groups.items()):
        require(type(source) is str and source not in seen and
                type(slots) is int and slots > 0,
                "SOURCE_GAP_GROUP_INVALID")
        seen.add(source)
        if source.startswith("race/"):
            factor = race.get(source)
            field_type = kind(source) if factor else None
            is_rider = False
        else:
            factor = rider.get(source)
            field_type = kind("rider/1/" + source) if factor else None
            is_rider = True
        require(type(factor) is int and factor >= 1 and
                slots % factor == 0 and
                slots <= factor * (n if is_rider else 1) and
                field_type in CATEGORY_NAMES,
                "SOURCE_GAP_DOES_NOT_MATCH_EXISTING_MODEL_MAPPING")
        distinct = slots // factor
        missing_origin_instances += distinct
        total_group_slots += slots
        cat = categories.setdefault(field_type,
                                    {"missing_origin_instances": 0,
                                     "missing_model_feature_slots": 0})
        cat["missing_origin_instances"] += distinct
        cat["missing_model_feature_slots"] += slots
        gap_rows.append({
            "source_field": source,
            "source_kind": field_type,
            "required_for_number_of_model_features": factor,
            "missing_origin_instances": distinct,
            "missing_model_feature_slots": slots,
        })
    require(total_group_slots == missing and
            0 <= missing_origin_instances <= distinct_total,
            "SOURCE_GAP_SUM_DOES_NOT_MATCH_MODEL_INPUTS")
    require(sum(v["missing_origin_instances"] for v in categories.values())
            == missing_origin_instances,
            "SOURCE_GAP_CATEGORY_SUM_MISMATCH")

    return {
        "schema": SCHEMA,
        "state": "SOURCE_ORIGIN_COVERAGE_AUDITED_NOT_ADMITTED",
        "rider_count": n,
        "required_model_feature_slots": total,
        "observed_model_feature_slots": supplied,
        "missing_model_feature_slots": missing,
        "distinct_required_origin_instances": distinct_total,
        "distinct_observed_origin_instances": distinct_total -
             missing_origin_instances,
        "distinct_missing_origin_instances": missing_origin_instances,
        "missing_source_field_families": len(gap_rows),
        "deficits_by_source_kind": dict(sorted(categories.items())),
        "deficits_by_source_field": gap_rows,
        "full_trifecta_price_structure_verified": (
            probe.get("real_full_odds_verified") is True),
        "full_pr71_model_input_verified": missing == 0,
        # Presence in a public page is not evidence of legal automated reuse.
        "license_rights_verified": False,
        "external_provider_publication_time_verified": False,
        "formal_model_predictions_verified": False,
        "missing_derived_values_are_not_zero": True,
        "no_source_values_or_rider_identifiers_output": True,
        "no_new_network_calls": True,
    }


def _unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "DUPLICATED_JSON_KEY")
        obj[key] = value
    return obj


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", required=True)
    args = parser.parse_args(argv)
    try:
        path = Path(args.probe)
        require(path.is_file() and not path.is_symlink() and
                0 < path.stat().st_size <= 150_000,
                "SOURCE_PROBE_JSON_FILE_INVALID")
        probe = json.loads(path.read_text(encoding="utf-8"),
                           object_pairs_hook=_unique_keys)
        result = summarize_source_gaps(probe)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        print(json.dumps({
            "schema": SCHEMA,
            "state": "HOLD_SOURCE_GAP_PLAN_UNVERIFIED",
            "formal_model_predictions_verified": False,
            "license_rights_verified": False,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
