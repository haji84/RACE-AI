"""Exact error-state transitions for real bounded result refreshes."""
import unittest
from scripts.boat_result_fresh_postflight import decision


class ResultPostflightTests(unittest.TestCase):
    def decide(self, **kw):
        return decision(before_final=130, after_final=130, changed_races=0,
                        provider_gets=12, get_cap=12, **kw)

    def test_no_new_official_final_is_a_hold_even_when_observations_saved(self):
        self.assertEqual(self.decide(), "BOAT_NO_NEW_FORMAL_FINAL_HOLD")
        self.assertEqual(decision(before_final=130, after_final=130, changed_races=5,
                                  provider_gets=12, get_cap=12),
                         "BOAT_NO_NEW_FORMAL_FINAL_HOLD")

    def test_new_final_must_be_attributed_to_this_writer(self):
        self.assertEqual(decision(before_final=130, after_final=131, changed_races=1,
                                  provider_gets=12, get_cap=12),
                         "FRESH_OFFICIAL_FINAL_INCREASE_VERIFIED")
        with self.assertRaisesRegex(ValueError, "UNATTRIBUTED_FINAL_ADVANCE"):
            decision(before_final=130, after_final=131, changed_races=0,
                     provider_gets=12, get_cap=12)

    def test_final_count_cannot_go_backwards(self):
        with self.assertRaisesRegex(ValueError, "FINAL_REGRESSION"):
            decision(before_final=131, after_final=130, changed_races=5,
                     provider_gets=12, get_cap=12)

    def test_bounded_provider_budget_remains_enforced(self):
        for gets, cap in [(0,12),(37,37),(14,12),(1,0),(1,37),(-1,12)]:
            with self.subTest(gets=gets,cap=cap),self.assertRaisesRegex(ValueError,"UNVERIFIED_COUNTS"):
                decision(before_final=130, after_final=130, changed_races=0,
                         provider_gets=gets, get_cap=cap)

    def test_boolean_counts_are_not_integers(self):
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_COUNTS"):
            decision(before_final=130, after_final=130, changed_races=False,
                     provider_gets=12, get_cap=12)


if __name__=="__main__":
    unittest.main()
