"""Distinguish a checked item from a raw obtainable data field."""
import unittest

from race_ai.keirin_field_acquisition import (
    RACE_HYPOTHESIS, RACE_DERIVED, RACE_CONDITIONAL,
    RIDER_DERIVED, RIDER_CONDITIONAL,
    acquisition_summary, kind,
)
from race_ai.keirin_preflight import RACE_ITEMS, RIDER_ITEMS, expected_keys


class AcquisitionTypes(unittest.TestCase):
    def test_every_registered_field_classified_once(self):
        self.assertFalse(RACE_HYPOTHESIS & RACE_DERIVED)
        self.assertFalse(RACE_HYPOTHESIS & RACE_CONDITIONAL)
        self.assertFalse(RACE_DERIVED & RACE_CONDITIONAL)
        self.assertFalse(RIDER_DERIVED & RIDER_CONDITIONAL)
        self.assertTrue((RACE_HYPOTHESIS | RACE_DERIVED | RACE_CONDITIONAL) <= set(RACE_ITEMS))
        self.assertTrue((RIDER_DERIVED | RIDER_CONDITIONAL) <= set(RIDER_ITEMS))
        for n in ([1,2,3,4,5,6,7], [1,2,3,4,5,6,7,8,9]):
            keys = expected_keys(n)
            categories = [kind(k) for k in keys]
            report = acquisition_summary(n)
            self.assertEqual(len(keys), 32 + 45*len(n))
            self.assertEqual(len(categories), len(keys))
            self.assertEqual(sum(report["categories"].values()),len(keys))
            self.assertFalse(report["every_field_is_public"])
            self.assertFalse(report["every_field_can_be_fetched"])

    def test_scenarios_not_misrepresented_as_downloadable_facts(self):
        self.assertEqual(kind("race/early_position_scenarios"),
                         "forecast_hypothesis_not_raw_data")
        self.assertEqual(kind("rider/2/teammate_pair_history"),
                         "derived_only_with_prior_evidence")
        self.assertEqual(kind("rider/2/injury_illness_and_recovery"),
                         "source_available_only_if_published_at_race_time")

    def test_unknown_market_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_KEIRIN_FIELD"):
            kind("race/odds")


if __name__ == "__main__":
    unittest.main()
