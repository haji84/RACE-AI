"""Synthetic AES-view shape only; never proof of official research accuracy."""
from copy import deepcopy
import unittest

from race_ai.boat_six_way_real_readiness import scan_views
from tests.test_racer_result_bridge import saved_view


class SixWayRealReadinessTests(unittest.TestCase):
    def test_existing_saved_view_has_no_six_way_120_or_grade(self):
        view = saved_view()
        original = deepcopy(view)
        result = scan_views([view], aes_saved_view_authenticated=True)
        self.assertEqual(view, original)
        self.assertEqual(result["counted_races"], 1)
        self.assertEqual(result["races_with_saved_p1"], 0)
        self.assertEqual(result["actual_three_way_120_results_scored"], 0)
        self.assertEqual(result["reason_counts"], {"NO_SAVED_P1": 1})
        self.assertEqual(result["new_provider_requests"], 0)

    def test_p1_receipt_without_120_is_hold_not_false_result(self):
        view = saved_view()
        row = view["records"][0]
        row["prediction"]["stage"] = "P1"
        result = scan_views([view], aes_saved_view_authenticated=True)
        self.assertEqual(result["races_with_saved_p1"], 1)
        self.assertEqual(result["races_with_receipt_timed_p1"], 1)
        self.assertEqual(result["races_with_saved_120_vector"], 0)
        self.assertEqual(result["reason_counts"],
                         {"NO_COMPLETE_SAVED_120_PROBABILITY_VECTOR": 1})

    def test_p1_with_120_does_not_invent_official_result_or_grades(self):
        view = saved_view()
        p = view["records"][0]["prediction"]
        p["stage"] = "P1"
        p["full_120"] = [
            {"ticket": f"{a}-{b}-{c}", "score": 1 / 120}
            for a in range(1, 7) for b in range(1, 7)
            for c in range(1, 7) if len({a, b, c}) == 3
        ]
        result = scan_views([view], aes_saved_view_authenticated=True)
        self.assertEqual(result["races_with_saved_120_vector"], 1)
        self.assertEqual(result["races_with_declared_tactical_context"], 0)
        self.assertEqual(result["reason_counts"], {"OFFICIAL_RESULT_NOT_FORMALLY_SETTLED": 1})

    def test_after_cutoff_original_is_not_accepted(self):
        view = saved_view()
        p = view["records"][0]["prediction"]
        p["stage"] = "P1"
        p["persisted_at"] = "2026-11-07T11:00:00+09:00"
        result = scan_views([view], aes_saved_view_authenticated=True)
        self.assertEqual(result["reason_counts"], {"NO_VERIFIABLE_PRE_CUTOFF_P1_CLOCK": 1})

    def test_invented_or_duplicate_view_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "AUTHENTICATED_VIEW_REQUIRED"):
            scan_views([saved_view()], aes_saved_view_authenticated=False)
        bad = saved_view()
        bad["dataset_status"] = "SYNTHETIC"
        with self.assertRaisesRegex(ValueError, "REAL_SAVED_VIEW_REQUIRED"):
            scan_views([bad], aes_saved_view_authenticated=True)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_RACE_OR_ID"):
            scan_views([saved_view(), saved_view()], aes_saved_view_authenticated=True)


if __name__ == "__main__":
    unittest.main()
