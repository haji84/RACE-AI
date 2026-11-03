"""Synthetic contract tests only. No source fetch, forecast or model edits."""
import copy
import unittest
from scripts.review_boat_feature_gate import (
    structural_review, ReviewContractError, SOURCE_CATEGORIES, SCHEMA
)
from race_ai.boat_b_feature_bridge import MAPPING

INV = {
    "common_required": (
        "ability", "recent_form", "start_reliability", "finishing_power",
        "course_compatibility", "stamina", "tactical_adaptability", "consistency"
    ),
    "sport_required": ("motor_form", "start_timing", "lane_course_fit"),
    "environment_required": (
        "wind_mps", "rain_mm_h", "humidity_pct", "air_temp_c",
        "surface_wetness", "wave_cm", "water_current_strength",
        "crosswind_factor", "tide_activity"
    ),
}


class BFeatureRequirementAuditTests(unittest.TestCase):
    def test_exact_model_contract_and_slot_math(self):
        result = structural_review(INV, MAPPING)
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["distinct_required_keys"], 20)
        self.assertEqual(result["required_runner_keys_per_participant"], 11)
        self.assertEqual(result["required_environment_keys_per_race"], 9)
        self.assertEqual(result["required_slots_per_race"], 75)
        self.assertEqual(result["B_candidate_slots_per_race"], 18)
        self.assertEqual(result["B_absent_candidate_slots_per_race"], 57)
        self.assertEqual(result["distinct_uncovered_by_B_keys"], 17)
        self.assertEqual(len(result["feature_reviews"]), 20)
        self.assertTrue(all(row["current_contract"] == "HARD_REQUIRED"
                            and not row["source_evidence_admitted"]
                            and not row["required_for_predictive_accuracy_proven"]
                            for row in result["feature_reviews"]))
        self.assertFalse(result["numeric_required_model_version_changed"])
        self.assertFalse(result["model_accuracy_change_proven"])

    def test_rejects_model_inventory_adding_removing_or_repeating_fields(self):
        for group in INV:
            changed = copy.deepcopy(INV)
            changed[group] += ("unexpected_feature",)
            with self.subTest(group=group), self.assertRaises(ReviewContractError):
                structural_review(changed, MAPPING)
            changed = copy.deepcopy(INV)
            changed[group] = changed[group][1:]
            with self.subTest(group=group, removed=True), self.assertRaises(ReviewContractError):
                structural_review(changed, MAPPING)
            changed = copy.deepcopy(INV)
            changed[group] += (changed[group][0],)
            with self.subTest(group=group, duplicated=True), self.assertRaises(ReviewContractError):
                structural_review(changed, MAPPING)

    def test_rejects_bridge_contract_drift(self):
        with self.assertRaisesRegex(ReviewContractError, "converter"):
            structural_review(INV, MAPPING[:2])
        corrupted = list(MAPPING)
        corrupted.append(MAPPING[0])
        with self.assertRaisesRegex(ReviewContractError, "converter"):
            structural_review(INV, corrupted)

    def test_tide_is_unverified_venue_conditional_not_observed_zero(self):
        report = structural_review(INV, MAPPING)
        tide = next(x for x in report["feature_reviews"] if x["key"] == "tide_activity")
        self.assertEqual(tide["source_route_hypothesis"], "VENUE_CONDITIONAL_UNKNOWN")
        self.assertFalse(tide["required_for_predictive_accuracy_proven"])
        self.assertEqual(set(SOURCE_CATEGORIES),
                         {row["key"] for row in report["feature_reviews"]})


if __name__ == "__main__":
    unittest.main()
