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

    def test_saved_result_revisions_are_separate_and_original_journal_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.sqlite"
            run_e2e(path)
            store = SyntheticJournal(path)
            try:
                before = store.events()
                before_sha = store.verify()
                exported = export_synthetic_journal(store)
                self.assertEqual(store.events(), before)
                self.assertEqual(store.verify(), before_sha)
            finally:
                store.close()
        boat = next(r for r in exported["records"] if r["sport"] == "boat" and r["prediction"])
        history = boat["result_revisions"]
        self.assertEqual([r["revision_no"] for r in history], [1, 2])
        self.assertIn(history[0]["winning_combinations"][0], boat["prediction"]["ordered_top8"])
        self.assertNotIn(history[1]["winning_combinations"][0], boat["prediction"]["ordered_top8"])
        self.assertEqual(boat["result"], {k:v for k,v in history[-1].items() if k != "revision_no"})
        original_results = [r for r in before if r["kind"] == "result" and
                            r["payload"]["race_key"] == next(r["payload"]["prediction"]["race_key"]
                                for r in before if r["kind"] == "freeze" and r["payload"]["snapshot"]["race_id"]["sport"] == "boat")]
        self.assertEqual([r["confirmed_at"] for r in history], [r["recorded_at"] for r in original_results])
        self.assertTrue(all(r["source_provenance"] == "synthetic://official-result" for r in history))
        self.assertTrue(all(r["source_sha256"] is None for r in history))

    def test_projection_retains_saved_model_identity_ranking_and_only_actual_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.sqlite"
            run_e2e(path)
            store = SyntheticJournal(path)
            try:
                originals = {r["payload"]["snapshot"]["race_id"]["sport"]:r["payload"]
                             for r in store.events("freeze")}
                exported = export_synthetic_journal(store)
            finally:
                store.close()
        for row in (r for r in exported["records"] if r["prediction"]):
            original = originals[row["sport"]]["prediction"]
            p = row["prediction"]
            self.assertEqual(p["model_id"], original["model"]["id"])
            self.assertEqual(p["model_version"], original["model"]["version"])
            self.assertEqual(p["ordered_top8"], original["ordered_top8"])
            self.assertEqual(p["candidates"], original["candidates"])
            self.assertEqual(p["prediction_sha256"], original["prediction_hash"])
            self.assertEqual(p["input_sha256"], original["snapshot_hash"])
            self.assertEqual(p["full_candidate_sha256"], original["full_candidate_hash"])
            self.assertEqual(p["as_of"], original["as_of"])
            self.assertIsNone(p["stage"], "journal has no P0/P1 metadata to invent")
            self.assertIsNone(p["source_sha256"])
            self.assertIsNone(row["source_sha256"])
            self.assertEqual(row["event_date_jst"], "2030-01-01")
            self.assertFalse(p["external_receipt_verified"])

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
