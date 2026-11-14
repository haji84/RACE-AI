"""Synthetic regressions for research-only historical pattern signals."""
import copy
import math
import unittest

from test_comprehensive_four_sport_models import sample, obs, OBS, CAP, ASOF
from race_ai.horse_historical_patterns import build_historical_win_signal
from race_ai.comprehensive_four_sport_models import (
    ModelInputError, HISTORY_TRANSFORM, SYNTHETIC, RESEARCH,
    HISTORICAL_HORSE_FEATURES, MODEL_IDS, predict,
)
from race_ai.four_sport_matchup_models import predict as matchup_predict


class HorseHistoricalPatterns(unittest.TestCase):
    def signal(self, **overrides):
        data = {
            "feature_name": "route_jockey_joint_win_signal",
            "case_wins": 8,
            "case_total": 8,
            "comparison_wins": 2,
            "comparison_total": 10,
            "condition_description": "fictional prev G1 and same jockey",
            "comparison_description": "fictional other prev G1 / jockey changed",
            "published_at": OBS,
            "captured_at": CAP,
            "as_of": ASOF,
            "source_ref": "synthetic://pre-race-cohort-counts",
            "source_rights_ref": "synthetic-fixture",
            "scope": SYNTHETIC,
        }
        data.update(overrides)
        return build_historical_win_signal(**data)

    def test_eight_of_eight_is_not_certain_and_has_auditable_denominators(self):
        answer = self.signal()
        observation = answer["observation"]
        audit = answer["audit"]
        self.assertLess(observation["value"], 1.0)
        self.assertGreater(observation["value"], 0.5)
        self.assertLess(observation["value"], 0.65)
        self.assertEqual(observation["sample_n"], 8)
        self.assertEqual(observation["transform_id"], HISTORY_TRANSFORM)
        self.assertEqual(audit["case_wins"], 8)
        self.assertEqual(audit["comparison_total"], 10)
        self.assertEqual(audit["outcome"], "win")
        self.assertFalse(audit["source_counts_externally_audited"])
        self.assertEqual(audit["status"], "RESEARCH_ONLY_UNCALIBRATED")

    def test_all_four_supported_pattern_categories_are_explicit(self):
        self.assertEqual(len(HISTORICAL_HORSE_FEATURES), 4)
        for name in HISTORICAL_HORSE_FEATURES:
            with self.subTest(name=name):
                self.assertIn("observation", self.signal(feature_name=name))

    def test_missing_hypothesis_is_neutral_and_new_feature_changes_forecast(self):
        original = sample("horse", size=6)
        baseline = predict(original)
        raw = copy.deepcopy(original)
        raw["participants"][0]["features"]["route_jockey_joint_win_signal"] = self.signal()["observation"]
        changed = predict(raw)
        for model in MODEL_IDS:
            self.assertNotEqual(
                baseline[model]["prediction_sha256"],
                changed[model]["prediction_sha256"])
            self.assertNotEqual(
                baseline[model]["candidates"],
                changed[model]["candidates"])
            self.assertFalse(changed[model]["official_prediction"])
            self.assertEqual(changed[model]["purchase_decision"], "NO_BET")
            self.assertEqual(changed[model]["candidate_count"], 6*5*4)
        before_matchup = matchup_predict(original)
        after_matchup = matchup_predict(raw)
        for model in before_matchup:
            self.assertNotEqual(
                before_matchup[model]["candidates"],
                after_matchup[model]["candidates"])
        neutral = self.signal(case_wins=3, case_total=8,
                              comparison_wins=3, comparison_total=8)
        self.assertEqual(neutral["observation"]["value"], .5)
        neutral_raw = copy.deepcopy(original)
        neutral_raw["participants"][0]["features"]["route_jockey_joint_win_signal"] = neutral["observation"]
        for model in MODEL_IDS:
            self.assertEqual(predict(neutral_raw)[model]["candidates"],
                             baseline[model]["candidates"])

    def test_future_counts_rejected(self):
        with self.assertRaisesRegex(ModelInputError, "as_of"):
            self.signal(captured_at="2030-01-16T09:00:00+09:00")
        raw = sample("horse", size=6)
        direct = self.signal()["observation"]
        direct["published_at"] = "2030-01-15T09:15:00+09:00"
        raw["participants"][0]["features"]["route_jockey_joint_win_signal"] = direct
        with self.assertRaisesRegex(ModelInputError, "after as_of"):
            predict(raw)

    def test_raw_unsmoothed_or_unknown_pattern_is_rejected(self):
        raw = sample("horse", size=6)
        raw["participants"][0]["features"]["route_jockey_joint_win_signal"] = obs(1.0)
        with self.assertRaisesRegex(ModelInputError, "historical count transform"):
            predict(raw)
        with self.assertRaisesRegex(ModelInputError, "unsupported horse history"):
            self.signal(feature_name="last_night_tv_8_of_8_certainty")
        other = sample("boat")
        other["participants"][0]["features"]["route_jockey_joint_win_signal"] = self.signal()["observation"]
        with self.assertRaisesRegex(ModelInputError, "prohibited participant"):
            predict(other)

    def test_invalid_counts_and_group_definition_fail_closed(self):
        bads = (
            {"case_wins": 9},
            {"case_wins": True},
            {"case_total": 0},
            {"comparison_total": 0},
            {"comparison_wins": -1},
            {"comparison_wins": 11},
            {"condition_description": "identical", "comparison_description": "identical"},
        )
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises(ModelInputError):
                self.signal(**bad)

    def test_real_scope_requires_independent_rights_callback(self):
        with self.assertRaisesRegex(ModelInputError, "permission"):
            self.signal(scope=RESEARCH)
        with self.assertRaisesRegex(ModelInputError, "permission"):
            self.signal(scope=RESEARCH, allow_source=lambda *_: False)
        admitted = self.signal(scope=RESEARCH, allow_source=lambda *_: True)
        self.assertTrue(admitted["audit"]["source_rights_externally_admitted"])
        self.assertFalse(admitted["audit"]["source_counts_externally_audited"])


if __name__ == "__main__":
    unittest.main()
