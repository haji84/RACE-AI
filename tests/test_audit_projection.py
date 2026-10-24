"""Check existing synthetic event journal projection to the four-sport viewer."""
import json
from pathlib import Path
import tempfile
import unittest
from race_ai.synthetic_e2e import run_e2e
from race_ai.actions_store import SyntheticJournal
from race_ai.audit_projection import export_synthetic_journal


class AuditProjectionTests(unittest.TestCase):
    def test_projection_preserves_scopes_missing_forecast_and_result_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.sqlite"
            run_e2e(path)
            store = SyntheticJournal(path)
            try:
                exported = export_synthetic_journal(store)
            finally:
                store.close()
        self.assertEqual(exported["dataset_status"], "SYNTHETIC_ONLY")
        self.assertEqual(exported["schema"], "RACE_AI_FORECAST_AUDIT_V1")
        records = exported["records"]
        self.assertEqual(len(records), 8)
        self.assertEqual(len({r["race_id"] for r in records}), 8)
        self.assertEqual({r["sport"] for r in records},
                         {"boat", "keirin", "autorace", "horse"})
        freezes = [r for r in records if r["prediction"]]
        self.assertEqual(len(freezes), 4)
        self.assertTrue(all(len(r["prediction"]["ordered_top8"]) == 8 for r in freezes))
        self.assertTrue(all(r["prediction"]["external_receipt_verified"] is False
                            for r in freezes))
        self.assertTrue(any(r["no_forecast_reason"] == "MISSING_FEATURES"
                            for r in records))
        self.assertTrue(any(r["offering_status"] == "NOT_OFFERED" for r in records))
        boat = next(r for r in freezes if r["sport"] == "boat")
        self.assertNotIn(boat["result"]["winning_combinations"][0],
                         boat["prediction"]["ordered_top8"],
                         "official correction changes result, not old forecast")
        self.assertTrue(json.loads(json.dumps(exported))["records"])

    def test_empty_journal_is_explicitly_synthetic(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SyntheticJournal(Path(folder) / "empty.sqlite")
            try:
                record = export_synthetic_journal(store)
            finally:
                store.close()
        self.assertEqual(record["records"], [])
        self.assertIsNone(record["event_date_jst"])


if __name__ == "__main__":
    unittest.main()
