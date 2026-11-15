"""Contract tests for read-only registration gate and unchanged 4-model suite."""
import copy
import unittest

from scripts.horse_weekend_input_gate import (
    inspect_registered_audit, execute_native_four, EXISTING_FOUR,
)
from test_comprehensive_four_sport_models import sample


class HorseWeekendInputGateTest(unittest.TestCase):
    def test_registration_gate_records_every_missing_feature(self):
        audit = {"races": [{
            "race_key": "keio", "race_name": "Keio 2yo",
            "runners": [
                {"horse_name": "Registered A", "eligibility": "not_final",
                 "verified_RACE_AI_model_features": {}},
                {"horse_name": "Registered B", "eligibility": "not_final",
                 "verified_RACE_AI_model_features": {}},
            ],
            "model_input_race": {"final_draw_verified": False,
                                 "sales_cutoff_at_verified": None,
                                 "required_environment_fields_unfilled": [
                                     "wind_mps", "rain_mm_h", "humidity_pct",
                                     "air_temp_c", "surface_wetness",
                                     "going_wetness", "course_cushion",
                                     "rail_position", "pace_pressure"
                                 ]}
        }]}
        report = inspect_registered_audit(audit)
        r = report["races"][0]
        self.assertFalse(r["can_execute_4_models"])
        self.assertEqual(r["missing_feature_count"], 24)
        self.assertEqual(len(r["missing_env"]), 9)
        self.assertIn("OFFICIAL_DRAW_UNCONFIRMED", r["reasons"])
        self.assertEqual(report["actual_forecasts_created"], 0)

    def test_raw_index_not_used_as_model_features(self):
        audit = {"races": [{
            "race_key": "keio", "race_name": "Keio 2yo",
            "runners": [{"horse_name": "Registered A",
                         "eligibility": "not_final",
                         "published_external_index": 82,
                         "last_3_top3_rate_reference_only": 1.0,
                         "verified_RACE_AI_model_features": {}}],
            "model_input_race": {}
        }]}
        r = inspect_registered_audit(audit)["races"][0]
        self.assertEqual(r["missing_feature_count"], 12)

    def test_missing_jockey_fit_refuses_native_call(self):
        s = sample("horse", size=3)
        del s["participants"][0]["features"]["jockey_fit"]
        out = execute_native_four(s)
        self.assertEqual(out["status"], "NO_FORECAST")
        self.assertEqual(out["model_count"], 0)
        self.assertTrue(any("jockey_fit" in m for m in out["reasons"]))

    def test_real_source_cannot_silently_authorize_itself(self):
        s = sample("horse", size=3, scope="OPERATOR_SUPPLIED_RESEARCH")
        out = execute_native_four(s)
        self.assertEqual(out["status"], "NO_FORECAST")
        self.assertIn("INDEPENDENT_SOURCE_AUTHORISER_MISSING", out["reasons"])

    def test_jumping_declined_until_model_is_validated(self):
        s = sample("horse", size=3)
        out = execute_native_four(s, discipline="jumps")
        self.assertEqual(out["status"], "NO_FORECAST")
        self.assertIn("UNVALIDATED_JUMPING_DISCIPLINE", out["reasons"])

    def test_existing_four_research_models_execute_on_fictional_fixture(self):
        s = sample("horse", size=3)
        unchanged = copy.deepcopy(s)
        out = execute_native_four(s)
        self.assertEqual(out["status"], "RESEARCH_UNCALIBRATED_NOT_PROVEN")
        self.assertEqual(out["model_count"], 4)
        self.assertEqual(tuple(out["top8_by_model"]), EXISTING_FOUR)
        self.assertEqual(len(out["top8_by_model"]), 4)
        self.assertFalse(out["official_prediction"])
        self.assertIsNone(out["calibrated_win_probabilities"])
        self.assertIsNone(out["market_expected_value"])
        self.assertEqual(s, unchanged)


if __name__ == "__main__":
    unittest.main()
