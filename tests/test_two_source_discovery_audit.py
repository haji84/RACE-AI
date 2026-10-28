"""Offline-only regressions: no upstream fetching or real race records."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.discovery_audit_cli import audit, main

DATE = "2030-01-01"
SPORTS = ("boat", "keirin", "autorace", "horse_local", "horse_jra")


def reference(race_numbers=None, omitted=()):
    return {
        "scope": "MANUAL_REFERENCE_ONLY",
        "event_date_jst": DATE,
        "venues": [{"sport": s, "venue": "fictional-" + s,
                    "race_numbers": [1] if race_numbers is None else race_numbers}
                   for s in SPORTS if s not in omitted],
    }


def ledger():
    return {
        "schema": "RACE_AI_FORECAST_AUDIT_V1", "dataset_status": "AUDIT_ONLY",
        "event_date_jst": DATE,
        "records": [
            {"sport": s, "venue": "fictional-" + s, "race_no": 1,
             "race_id": f"{s}:{DATE}:fictional-{s}:1",
             "cutoff_verified": False, "prediction": None,
             "no_forecast_reason": "PERMISSION_NOT_VERIFIED"}
            for s in SPORTS],
    }


class TwoSourceAuditTests(unittest.TestCase):
    def test_cross_source_race_disagreement_is_explicit_and_no_write(self):
        first, second = reference(), reference()
        second["venues"][0]["race_numbers"] = [1, 2]
        report = audit(first, ledger(), second)
        self.assertEqual(report["status"], "SOURCE_DISAGREEMENT")
        self.assertEqual(report["cross_reference"]["differing_races"],
                         [["boat", "fictional-boat", 2, "SECONDARY_ONLY"]])
        self.assertEqual(report["secondary_reconciliation"]["missing_races"],
                         [["boat", "fictional-boat", 2]])
        self.assertFalse(report["automatic_source_collection_admitted"])
        self.assertFalse(report["real_pre_cutoff_forecast_verified"])
        self.assertFalse(report["prediction_write_allowed"])

    def test_source_only_venue_is_not_silently_dropped(self):
        report = audit(reference(), ledger(), reference(omitted=("autorace",)))
        self.assertEqual(report["status"], "SOURCE_DISAGREEMENT")
        self.assertEqual(report["cross_reference"]["only_primary_venues"],
                         [["autorace", "fictional-autorace"]])

    def test_unknown_race_counts_are_uncertainty_not_completeness(self):
        report = audit(reference(), ledger(), reference(race_numbers=None))
        # Both known; replacing one venue with unknown must still block certainty.
        other = reference()
        other["venues"][0]["race_numbers"] = None
        report = audit(reference(), ledger(), other)
        self.assertEqual(report["status"], "UNRESOLVED_COVERAGE_OR_PROOF")
        self.assertEqual(report["cross_reference"]["unknown_either_race_count"],
                         [["boat", "fictional-boat"]])
        self.assertFalse(report["official_completeness_verified"])

    def test_equal_sources_are_still_manual_and_untrusted(self):
        report = audit(reference(), ledger(), reference())
        self.assertEqual(report["status"], "UNRESOLVED_COVERAGE_OR_PROOF")
        self.assertEqual(report["reference_count"], 2)
        self.assertFalse(report["cross_reference"]["sources_complete_and_authorized"])

    def test_wrong_date_secondary_reference_is_rejected(self):
        second = reference()
        second["event_date_jst"] = "2030-01-02"
        with self.assertRaises(ValueError):
            audit(reference(), ledger(), second)

    def test_cli_dual_sources_nonzero_and_report_exclusive(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            a, b, c, out = [folder / n for n in ("primary.json", "second.json", "ledger.json", "report.json")]
            a.write_text(json.dumps(reference()), encoding="utf-8")
            secondary = reference()
            secondary["venues"][0]["race_numbers"] = [1, 2]
            b.write_text(json.dumps(secondary), encoding="utf-8")
            c.write_text(json.dumps(ledger()), encoding="utf-8")
            args = ["--reference", str(a), "--secondary-reference", str(b),
                    "--ledger", str(c), "--output", str(out)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 2)
            before = out.read_bytes()
            self.assertEqual(json.loads(before)["status"], "SOURCE_DISAGREEMENT")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 3)
            self.assertEqual(out.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
