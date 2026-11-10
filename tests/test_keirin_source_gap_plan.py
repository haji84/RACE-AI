"""Existing PR71 mapping, count-only provenance and rights fail-closed tests."""
from collections import Counter
from pathlib import Path
import copy
import unittest

from race_ai.comprehensive_four_sport_models import feature_inventory
from race_ai.keirin_allowed_delivery import RIDER_MAP, ENV_MAP
from scripts.keirin_source_gap_plan import (
    SourceGapPlanError, summarize_source_gaps, SCHEMA, PROBE_SCHEMA,
)

# Snapshot of count-only missing-field groups observed on 2026-11-10.
# No rider names, scores, odds, licensed material or real predictions.
MISSING_79 = {
    "last_lap_acceleration": 14,
    "venue_and_distance_compatibility": 14,
    "lead_attempt_and_success": 7,
    "position_flexibility_and_solo_behavior": 7,
    "recent_strength_or_form_change": 7,
    "stamina_and_pace_resilience": 7,
    "start_or_line_reliability": 7,
    "teammate_pair_history": 7,
    "race/air_temperature": 1,
    "race/bank_cant_and_corner_shape": 1,
    "race/humidity": 1,
    "race/line_competition_and_lead_candidates": 1,
    "race/rainfall": 1,
    "race/surface_wetness": 1,
    "race/track_surface_and_condition": 1,
    "race/track_weather_effect_history": 1,
    "race/wind_speed": 1,
}


def observation(groups=None, *, riders=7, slots=93, missing=79,
                observed=14, odds=True):
    return {
        "schema": PROBE_SCHEMA,
        "status": "LIVE_TRIFECTA_PRICE_UNIVERSE_VERIFIED",
        "race_id": "202611101203",
        "rider_identity_count": riders,
        "required_source_slots_total": slots,
        "required_source_slots_A_observed": observed,
        "required_source_slots_A_missing": missing,
        "required_source_gap_groups_A": dict(MISSING_79 if groups is None else groups),
        "real_full_odds_verified": odds,
        "actual_model_prediction_saved": False,
    }


class SafeSourceGapPlanTests(unittest.TestCase):
    def test_79_model_features_require_65_unique_missing_source_instances(self):
        self.assertEqual(sum(MISSING_79.values()), 79)
        result = summarize_source_gaps(observation())
        self.assertEqual(result["required_model_feature_slots"], 93)
        self.assertEqual(result["observed_model_feature_slots"], 14)
        self.assertEqual(result["missing_model_feature_slots"], 79)
        self.assertEqual(result["distinct_required_origin_instances"], 79)
        self.assertEqual(result["distinct_observed_origin_instances"], 14)
        self.assertEqual(result["distinct_missing_origin_instances"], 65)
        self.assertEqual(result["missing_source_field_families"], 17)
        rows = {r["source_field"]: r for r in result["deficits_by_source_field"]}
        self.assertEqual(rows["last_lap_acceleration"]["required_for_number_of_model_features"], 2)
        self.assertEqual(rows["last_lap_acceleration"]["missing_origin_instances"], 7)
        self.assertEqual(rows["venue_and_distance_compatibility"]["missing_origin_instances"], 7)
        self.assertEqual(rows["race/line_competition_and_lead_candidates"]["source_kind"],
                         "forecast_hypothesis_not_raw_data")
        self.assertTrue(result["full_trifecta_price_structure_verified"])
        self.assertFalse(result["license_rights_verified"])
        self.assertFalse(result["formal_model_predictions_verified"])
        self.assertEqual(result["state"], "SOURCE_ORIGIN_COVERAGE_AUDITED_NOT_ADMITTED")
        self.assertEqual(sum(x["missing_origin_instances"]
                             for x in result["deficits_by_source_kind"].values()), 65)

    def test_all_93_absent_is_79_distinct_unobserved_no_imputation(self):
        required = tuple(feature_inventory("keirin")["common_required"]) + tuple(
            feature_inventory("keirin")["sport_required"])
        env_required = tuple(feature_inventory("keirin")["environment_required"])
        rider = Counter(RIDER_MAP[f][0] for f in required)
        env = Counter("race/" + ENV_MAP[f][0] for f in env_required)
        gaps = {**{k: v * 7 for k, v in rider.items()}, **env}
        result = summarize_source_gaps(observation(gaps, missing=93, observed=0))
        self.assertEqual(result["distinct_missing_origin_instances"], 79)
        self.assertEqual(result["distinct_observed_origin_instances"], 0)
        self.assertFalse(result["full_pr71_model_input_verified"])
        self.assertTrue(result["missing_derived_values_are_not_zero"])

    def test_complete_structural_inputs_do_not_grant_license_or_prediction(self):
        report = summarize_source_gaps(observation({}, missing=0, observed=93))
        self.assertTrue(report["full_pr71_model_input_verified"])
        self.assertFalse(report["license_rights_verified"])
        self.assertFalse(report["formal_model_predictions_verified"])
        self.assertEqual(report["distinct_missing_origin_instances"], 0)

    def test_refuse_mismatched_slots_unknown_field_and_duplicate_alias_counts(self):
        bad = observation()
        bad["required_source_slots_A_missing"] = 78
        with self.assertRaises(SourceGapPlanError):
            summarize_source_gaps(bad)
        bad = observation()
        bad["required_source_gap_groups_A"]["last_lap_acceleration"] = 13
        with self.assertRaises(SourceGapPlanError):
            summarize_source_gaps(bad)
        bad = observation()
        bad["required_source_gap_groups_A"]["unknown_rider_data"] = 1
        with self.assertRaises(SourceGapPlanError):
            summarize_source_gaps(bad)

    def test_no_future_source_is_hold_not_false_success(self):
        report = summarize_source_gaps({
            "schema": PROBE_SCHEMA,
            "status": "NO_UPCOMING_SOURCE_ELIGIBLE_EVENT",
            "actual_model_prediction_saved": False,
        })
        self.assertEqual(report["state"], "HOLD_SOURCE_ORIGIN_COUNTS_NOT_OBSERVED")
        self.assertIsNone(report["distinct_missing_origin_instances"])
        self.assertFalse(report["license_rights_verified"])

    def test_no_rider_names_prices_or_source_values_ever_leave_count_plan(self):
        sample = observation()
        sample["private_rider_secret"] = "not_an_approved_output"
        report = summarize_source_gaps(sample)
        full = repr(report)
        self.assertNotIn("private_rider_secret", full)
        self.assertNotIn("not_an_approved_output", full)
        self.assertNotIn("decimal_odds", full)
        self.assertTrue(report["no_source_values_or_rider_identifiers_output"])


if __name__ == "__main__":
    unittest.main()
