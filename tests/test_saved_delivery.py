"""Private saved timestamps never certify independent user-visible delivery."""
import unittest

from race_ai.saved_delivery import assess_delivery


CUTOFF = "2030-01-15T10:00:00+09:00"
ASSESSED = "2030-01-15T09:55:00+09:00"


class SavedDeliveryTests(unittest.TestCase):
    def saved(self, saved_at, **overrides):
        evidence = dict(source_captured_at="2030-01-15T09:40:00+09:00",
                        generated_at="2030-01-15T09:44:00+09:00",
                        saved_at=saved_at, assessed_at=ASSESSED)
        evidence.update(overrides)
        return assess_delivery(CUTOFF, **evidence)

    def test_measured_save_uses_inclusive_15_to_10_minute_window(self):
        for saved_at, expected in (
            ("2030-01-15T09:44:59+09:00", "EARLY"),
            ("2030-01-15T09:45:00+09:00", "ON_TIME"),
            ("2030-01-15T09:50:00+09:00", "ON_TIME"),
            ("2030-01-15T09:50:01+09:00", "LATE"),
        ):
            with self.subTest(saved_at=saved_at):
                result = self.saved(saved_at)
                self.assertEqual(result["state"], "SAVED")
                self.assertEqual(result["window_status"], expected)
                self.assertEqual(result["next_cutoff_at"], CUTOFF)
                self.assertEqual(result["target_open_at"], "2030-01-15T09:45:00+09:00")
                self.assertEqual(result["target_due_at"], "2030-01-15T09:50:00+09:00")
                self.assertIsNone(result["visible_at"])
                self.assertFalse(result["independent_user_visibility_time_verified"])

    def test_save_after_official_close_is_late_never_on_time(self):
        out = self.saved("2030-01-15T10:00:01+09:00",
                         assessed_at="2030-01-15T10:01:00+09:00")
        self.assertEqual(out["window_status"], "LATE")
        self.assertEqual(out["reason"], "SAVED_AFTER_CUTOFF")

    def test_missing_saved_or_missing_chain_never_proves_success(self):
        out = assess_delivery(CUTOFF, assessed_at=ASSESSED)
        self.assertEqual((out["state"], out["window_status"]), ("NOT_SAVED", "UNKNOWN"))
        for field in ("source_captured_at", "generated_at", "assessed_at"):
            with self.subTest(field=field):
                out = self.saved("2030-01-15T09:46:00+09:00", **{field: None})
                self.assertEqual((out["state"], out["window_status"]), ("UNKNOWN", "UNKNOWN"))

    def test_inverted_or_future_evidence_is_unknown(self):
        for changed in (
            {"source_captured_at": "2030-01-15T09:47:00+09:00"},
            {"generated_at": "2030-01-15T09:47:00+09:00"},
            {"assessed_at": "2030-01-15T09:45:59+09:00"},
        ):
            with self.subTest(changed=changed):
                out = self.saved("2030-01-15T09:46:00+09:00", **changed)
                self.assertEqual((out["state"], out["window_status"]), ("UNKNOWN", "UNKNOWN"))
                self.assertEqual(out["reason"], "INCONSISTENT_TIMESTAMP_ORDER")

    def test_missing_cutoff_and_malformed_evidence_do_not_invent_times(self):
        out = assess_delivery(None)
        for name in ("next_cutoff_at", "target_open_at", "target_due_at", "assessed_at"):
            self.assertIsNone(out[name])
        self.assertEqual(out["window_status"], "UNKNOWN")
        for cutoff, changes in (
            ("2030-01-15T10:00:00", {}),
            (CUTOFF, {"saved_at": "2030-01-15T09:46:00"}),
            (CUTOFF, {"generated_at": "invalid"}),
        ):
            with self.subTest(cutoff=cutoff, changes=changes):
                out = assess_delivery(cutoff, **changes)
                self.assertEqual((out["state"], out["window_status"]), ("UNKNOWN", "UNKNOWN"))
                self.assertIsNone(out["visible_at"])

    def test_timezones_compare_instants_without_substituting_saved_time(self):
        out = assess_delivery(CUTOFF, source_captured_at="2030-01-15T00:40:00Z",
                              generated_at="2030-01-15T00:44:00Z",
                              saved_at="2030-01-15T00:46:00Z", assessed_at=ASSESSED)
        self.assertEqual(out["window_status"], "ON_TIME")
        self.assertEqual(out["source_captured_at"], "2030-01-15T00:40:00+00:00")
        self.assertEqual(out["generated_at"], "2030-01-15T00:44:00+00:00")
        self.assertEqual(out["saved_at"], "2030-01-15T00:46:00+00:00")


if __name__ == "__main__":
    unittest.main()
