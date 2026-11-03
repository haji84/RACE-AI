"""Regression checks for offline race coverage reconciliation (no real race data)."""
import unittest
from race_ai.discovery_reconcile import compare_daily, CoverageError


def reference(venues=None):
    return {"scope": "MANUAL_REFERENCE_ONLY", "event_date_jst": "2030-01-01",
            "venues": venues if venues is not None else [
                {"sport": "boat", "venue": "test-boat", "race_numbers": [1, 2]},
                {"sport": "keirin", "venue": "test-keirin", "race_numbers": None}]}


def row(sport, venue, n, **changes):
    value = {"sport": sport, "venue": venue, "race_no": n,
             "race_id": f"{sport}:2030-01-01:{venue}:{n}",
             "cutoff_verified": False, "prediction": None,
             "no_forecast_reason": "SOURCE_PERMISSION_NOT_VERIFIED"}
    value.update(changes)
    return value


def ledger(records=None):
    return {"schema": "RACE_AI_FORECAST_AUDIT_V1", "dataset_status": "AUDIT_ONLY",
            "event_date_jst": "2030-01-01",
            "records": records if records is not None else [
                row("boat", "test-boat", 1), row("keirin", "test-keirin", 1)]}


class DiscoveryReconcileTests(unittest.TestCase):
    def test_detects_missing_race_without_guessing_unknown_counts(self):
        r = compare_daily(reference(), ledger())
        self.assertEqual(r["missing_races"], [["boat", "test-boat", 2]])
        self.assertEqual(r["unknown_expected_race_counts"], [["keirin", "test-keirin"]])
        self.assertEqual(r["comparison_status"], "REPORTED_MISMATCH")
        self.assertFalse(r["complete_official_coverage_verified"])
        self.assertFalse(r["real_pre_cutoff_freeze_verified"])
        self.assertFalse(r["auto_fetch_authorized"])

    def test_matching_manual_reference_is_not_official_proof(self):
        rows = [row("boat", "test-boat", 1), row("boat", "test-boat", 2),
                row("keirin", "test-keirin", 1)]
        r = compare_daily(reference(), ledger(rows))
        self.assertEqual(r["comparison_status"], "REFERENCE_MATCH_ONLY")
        self.assertFalse(r["complete_official_coverage_verified"])
        self.assertEqual(len(r["unverified_cutoffs"]), 3)

    def test_missing_venue_and_extra_venue(self):
        rows = [row("boat", "test-boat", 1),
                row("autorace", "unexpected", 1)]
        r = compare_daily(reference(), ledger(rows))
        self.assertEqual(r["missing_venues"], [["keirin", "test-keirin"]])
        self.assertEqual(r["unlisted_venues"], [["autorace", "unexpected"]])

    def test_bad_or_late_claims_cannot_become_verified(self):
        rows = [row("boat", "test-boat", 1, prediction={"ordered_top8": [[1,2,3]]},
                    cutoff_verified=True),
                row("keirin", "test-keirin", 1, no_forecast_reason=None)]
        r = compare_daily(reference(), ledger(rows))
        self.assertEqual(len(r["unauthenticated_prediction_claims"]), 1)
        self.assertEqual(len(r["missing_no_forecast_reasons"]), 1)
        self.assertFalse(r["real_pre_cutoff_freeze_verified"])

    def test_duplicate_and_wrong_day_rejected(self):
        rows = [row("boat", "test-boat", 1)] * 2
        with self.assertRaises(CoverageError):
            compare_daily(reference(), ledger(rows))
        with self.assertRaises(CoverageError):
            compare_daily(reference(), {**ledger(), "event_date_jst":"2030-01-02"})

    def test_claimed_license_and_real_dataset_cannot_bypass_scope(self):
        with self.assertRaises(CoverageError):
            compare_daily({**reference(), "rights_granted":True}, ledger())
        with self.assertRaises(CoverageError):
            compare_daily({**reference(), "scope":"LICENSED"}, ledger())
        with self.assertRaises(CoverageError):
            compare_daily(reference(), {**ledger(), "dataset_status":"REAL_REPORTED"})

    def test_race_numbers_not_assumed_twelve(self):
        r = compare_daily(reference([{"sport":"autorace","venue":"A",
                                      "race_numbers":[1,3]}]),
                          ledger([row("autorace","A",1),row("autorace","A",2)]))
        self.assertEqual(r["missing_races"],[["autorace","A",3]])
        self.assertEqual(r["unlisted_races"],[["autorace","A",2]])


if __name__ == "__main__":
    unittest.main()
