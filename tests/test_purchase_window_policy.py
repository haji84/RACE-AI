"""Purchase buffer SLA tests: synthetic timestamps are NOT external proof."""
import unittest
from race_ai.purchase_window_policy import (
    policy, reported_delivery, PurchaseWindowError
)

END="2030-01-15T10:00:00+09:00"


class PurchaseReviewTests(unittest.TestCase):
    def test_clear_early_preview_and_final_deadline(self):
        p=policy(END)
        self.assertEqual(p["first_preview_target_at"],"2030-01-15T09:30:00+09:00")
        self.assertEqual(p["final_forecast_visible_by"],"2030-01-15T09:50:00+09:00")
        self.assertFalse(p["readiness_evidence_independently_verified"])

    def test_review_time_requires_actual_user_visible_delivery_not_just_frozen(self):
        result=reported_delivery(
            END, "2030-01-15T09:40:00+09:00",
            "2030-01-15T09:50:00+09:00"
        )
        self.assertEqual(result["reported_publication_status"],
                         "BUFFER_TARGET_REPORTED_NOT_ATTESTED")
        self.assertEqual(result["reported_minutes_before_cutoff"],10)
        self.assertFalse(result["official_forecast_eligible_from_this_check"])

    def test_frozen_early_but_published_late_is_not_consumer_ready(self):
        result=reported_delivery(END, "2030-01-15T09:35:00+09:00",
                                 "2030-01-15T09:57:00+09:00")
        self.assertEqual(result["reported_publication_status"],
                         "LATE_FOR_PURCHASE_REVIEW")
        self.assertEqual(result["reported_minutes_before_cutoff"],3)

    def test_publication_after_cutoff_and_bad_order_rejected_as_not_actionable(self):
        out=reported_delivery(END, "2030-01-15T09:30:00+09:00",
                              "2030-01-15T10:00:00+09:00")
        self.assertEqual(out["reported_publication_status"],
                         "POST_CUTOFF_NOT_ACTIONABLE")
        bad=reported_delivery(END, "2030-01-15T09:55:00+09:00",
                              "2030-01-15T09:49:00+09:00")
        self.assertEqual(bad["reported_publication_status"],
                         "INCONSISTENT_PUBLICATION_EVIDENCE")

    def test_missing_freeze_or_publication_does_not_count(self):
        p=reported_delivery(END,None,"2030-01-15T09:40:00+09:00")
        self.assertEqual(p["reported_publication_status"],
                         "NOT_PUBLISHED_FOR_REVIEW")
        self.assertFalse(p["independent_freeze_receipt_verified"])

    def test_configurable_buffer_not_claimed_as_official_threshold(self):
        p=policy(END,initial_lead_minutes=40,final_buffer_minutes=15)
        self.assertEqual(p["final_forecast_visible_by"],"2030-01-15T09:45:00+09:00")
        with self.assertRaises(PurchaseWindowError):
            policy(END,initial_lead_minutes=10,final_buffer_minutes=10)
        with self.assertRaises(PurchaseWindowError):
            policy(END,initial_lead_minutes=30,final_buffer_minutes=2)


if __name__ == "__main__":
    unittest.main()
