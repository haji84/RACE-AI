"""Count-only HOLD/pass preconditions; no owner key or source traffic."""
import unittest
from scripts.boat_saved_three_day_acceptance import classify

class ThreeDayAcceptanceContract(unittest.TestCase):
    base = dict(races=132, forecasts=1800, missing_model_slots=0,
                missing_results=0, unverified=0, review=0, model_groups=14)

    def check(self, changes, expected):
        self.assertEqual(classify(**dict(self.base, **changes)), expected)

    def test_empty_day_not_inferred_from_other_days(self):
        self.check(dict(races=0, forecasts=0, model_groups=0), "HOLD_NO_SAVED_DAY")

    def test_result_only_day_never_passes(self):
        self.check(dict(forecasts=0, model_groups=0), "HOLD_NO_SAVED_FORECAST")

    def test_partial_model_coverage_is_not_complete(self):
        self.check(dict(missing_model_slots=7), "HOLD_INCOMPLETE_MODEL_COVERAGE")

    def test_pending_results_not_reported_as_misses(self):
        self.check(dict(missing_results=9), "HOLD_RESULTS_NOT_FINAL")

    def test_missing_official_receipt_fails_closed(self):
        self.check(dict(unverified=1), "HOLD_RESULT_RECONCILIATION")

    def test_ambiguous_results_fail_closed(self):
        self.check(dict(review=1), "HOLD_RESULT_RECONCILIATION")

    def test_no_model_comparison_fails_closed(self):
        self.check(dict(model_groups=0), "HOLD_NO_MODEL_COMPARISON")

    def test_metadata_only_is_not_a_final_browser_pass(self):
        self.check({}, "READY_FOR_INDEPENDENT_BROWSER_AND_SOURCE_PROOF")

if __name__ == "__main__":
    unittest.main()
