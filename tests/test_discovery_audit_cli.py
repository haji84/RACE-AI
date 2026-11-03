"""All tests are synthetic, offline and contain no licensed race material."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.discovery_audit_cli import audit, main


DATE = "2030-01-01"
SPORTS = ("boat", "keirin", "autorace", "horse_local", "horse_jra")


def ref(names=SPORTS, race_numbers=None):
    return {"scope": "MANUAL_REFERENCE_ONLY", "event_date_jst": DATE,
            "venues": [{"sport": s, "venue": "fake-" + s,
                        "race_numbers": [1] if race_numbers is None else race_numbers}
                       for s in names]}


def row(sport, number=1, **updates):
    record = {"race_id": f"{sport}:{DATE}:fake-{sport}:{number}",
              "sport": sport, "venue": "fake-" + sport, "race_no": number,
              "cutoff_verified": True, "prediction": None,
              "no_forecast_reason": "SOURCE_PERMISSION_NOT_VERIFIED"}
    record.update(updates)
    return record


def ledger(names=SPORTS):
    return {"schema": "RACE_AI_FORECAST_AUDIT_V1",
            "dataset_status": "AUDIT_ONLY", "event_date_jst": DATE,
            "records": [row(s) for s in names]}


class GateTests(unittest.TestCase):
    def test_missing_race_is_not_hidden(self):
        expected = ref(["boat"], [1, 2])
        actual = ledger(["boat"])
        outcome = audit(expected, actual)
        self.assertEqual(outcome["status"], "REFERENCE_DISCREPANCY")
        self.assertEqual(outcome["reconciliation"]["missing_races"],
                         [["boat", "fake-boat", 2]])
        self.assertFalse(outcome["official_completeness_verified"])

    def test_absent_sport_is_uncertain_not_non_event(self):
        output = audit(ref(["boat"]), ledger(["boat"]))
        self.assertIn("horse_jra", output["sports_without_reference"])
        self.assertEqual(output["status"], "UNRESOLVED_COVERAGE_OR_PROOF")

    def test_unverified_cutoff_blocks_even_if_venue_names_match(self):
        data = ledger()
        data["records"][0]["cutoff_verified"] = False
        result = audit(ref(), data)
        self.assertEqual(result["status"], "UNRESOLVED_COVERAGE_OR_PROOF")
        self.assertFalse(result["prediction_write_allowed"])

    def test_untrusted_prediction_flag_never_authenticates(self):
        data = ledger()
        data["records"][0]["prediction"] = {
            "ordered_top8": [[1, 2, 3]], "external_receipt_verified": True}
        result = audit(ref(), data)
        self.assertEqual(result["status"], "UNRESOLVED_COVERAGE_OR_PROOF")
        self.assertFalse(result["real_pre_cutoff_forecast_verified"])

    def test_matching_manual_fields_still_not_official_verification(self):
        result = audit(ref(), ledger())
        self.assertEqual(result["status"], "MANUAL_REFERENCE_MATCH_ONLY")
        self.assertFalse(result["official_completeness_verified"])
        self.assertFalse(result["automatic_source_collection_admitted"])

    def test_cli_rejects_duplicate_json_keys_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            reference = p / "reference.json"
            journal = p / "audit.json"
            output = p / "report.json"
            reference.write_text(json.dumps(ref()), encoding="utf-8")
            journal.write_text(json.dumps(ledger()), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--reference", str(reference),
                                       "--ledger", str(journal), "--output", str(output)]), 0)
            old = output.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--reference", str(reference),
                                       "--ledger", str(journal), "--output", str(output)]), 3)
            self.assertEqual(output.read_bytes(), old)
            reference.write_text('{"scope":"MANUAL_REFERENCE_ONLY","scope":"MANUAL_REFERENCE_ONLY"}',
                                 encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--reference", str(reference),
                                       "--ledger", str(journal)]), 3)

    def test_cli_returns_nonzero_on_uncertainty(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            a, b = p / "reference.json", p / "ledger.json"
            a.write_text(json.dumps(ref(["boat"])), encoding="utf-8")
            b.write_text(json.dumps(ledger(["boat"])), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as capture:
                rc = main(["--reference", str(a), "--ledger", str(b)])
            self.assertEqual(rc, 2)
            self.assertEqual(json.loads(capture.getvalue())["status"],
                             "UNRESOLVED_COVERAGE_OR_PROOF")


if __name__ == "__main__":
    unittest.main()
