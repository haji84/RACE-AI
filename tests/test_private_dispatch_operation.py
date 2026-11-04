"""Private operation contracts; all races, grants and observations are fictional."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import existing_model_dispatch as native
from race_ai.four_sport_model_suite import ALL_MODELS, run_suite
from tests.test_comprehensive_four_sport_models import sample
from tests.test_permissioned_source_delivery import snapshot as reviewed_snapshot, gate, AT


try:
    operation = importlib.import_module("race_ai.private_dispatch_operation")
except ModuleNotFoundError:
    operation = None


def fixture(sport="boat", *, real=False):
    snap = reviewed_snapshot(sport) if real else sample(
        sport, size=10 if sport == "horse" else None)
    race = snap["race"]
    row = dict(race_id=race["race_id"], sport=sport,
               cutoff_at=race["sales_cutoff_at"], stage="P0")
    return [row], {row["race_id"]: {"P0": {"shared": {"snapshot": snap}}}}


def generated(report):
    return [s for s in report.get("dispatch", report)["slots"] if s["prediction"] is not None]


class PrivateDispatchOperationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(operation, "private saved-input operation is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "private.sqlite"
        self.journal = operation.PrivateDispatchJournal(self.path)

    def test_four_sports_run_native_models_and_read_every_slot_losslessly(self):
        for sport in ("boat", "keirin", "autorace", "horse"):
            with self.subTest(sport=sport):
                rows, inputs = fixture(sport)
                expected = run_suite(inputs[rows[0]["race_id"]]["P0"]["shared"]["snapshot"])
                report = operation.run_saved_inputs(self.journal, rows, inputs, at=AT)
                self.assertEqual(len(report["dispatch"]["slots"]), 16)
                self.assertEqual(report["dispatch"]["schedule"], rows)
                self.assertEqual(len(generated(report)), 4)
                for slot in generated(report):
                    self.assertEqual(slot["prediction"], expected["models"][slot["model_id"]])
                    self.assertEqual(slot["status"], "GENERATED_UNATTESTED")
                    self.assertFalse(slot["official_prediction"])
                self.assertEqual(self.journal.read_operation(report["operation_id"]), report)
                self.assertEqual(report["source_requests"], 0)
                self.assertFalse(report["dispatch"]["external_receipts_created"])
                self.assertFalse(report["production_operation"])
                self.assertFalse(report["all_models_operational"])
                self.assertFalse(report["independent_freeze_verified"])
        originals = self.journal.originals()
        self.assertEqual(len(originals), 16)
        horse = next(s for s in originals if s["sport"] == "horse")
        self.assertTrue(all(type(k) is int for k in horse["prediction"]["missing_optional_by_participant"]))
        self.assertEqual(horse["output_sha256"], digest(horse["prediction"]))
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_restart_reuses_all_versions_after_deadline_without_native_calls(self):
        rows, inputs = fixture("horse")
        first = operation.run_saved_inputs(self.journal, rows, inputs, at=AT)
        before = self.journal.originals()
        reopened = operation.PrivateDispatchJournal(self.path)
        with patch.object(native, "run_suite", side_effect=AssertionError("saved forecast recalculated")):
            second = operation.run_saved_inputs(reopened, rows, {}, at="2030-01-15T12:00:00+09:00")
        self.assertEqual(len(generated(second)), 4)
        self.assertTrue(all(s["status"] == "ORIGINAL_REUSED" for s in generated(second)))
        self.assertEqual([s["prediction"] for s in generated(first)],
                         [s["prediction"] for s in generated(second)])
        self.assertEqual(reopened.originals(), before)
        self.assertEqual(reopened.read_operation(first["operation_id"]), first)

    def test_real_sources_need_analysis_and_both_private_uses_before_inference(self):
        rows, inputs = fixture(real=True)
        for granted in ((), ("analysis",), ("analysis", "private_storage")):
            with self.subTest(granted=granted):
                authorize = lambda ref, rights, purpose: purpose in granted
                with patch.object(native, "run_suite", side_effect=AssertionError("unapproved inference")):
                    report = operation.run_saved_inputs(self.journal, rows, inputs, at=AT,
                                                        allow_source=authorize)
                self.assertTrue(all(s["status"] == "SOURCE_NOT_AUTHORIZED" for s in report["dispatch"]["slots"]
                                    if s["model_id"] in ALL_MODELS))
        self.assertEqual(self.journal.originals(), [])

    def test_signed_fictional_policy_reaches_native_models_and_is_not_reissued(self):
        rows, inputs = fixture("keirin", real=True)
        first = operation.run_saved_inputs(self.journal, rows, inputs, at=AT,
                                           allow_source=gate().authorize)
        self.assertEqual(len(generated(first)), 4)
        with patch.object(native, "run_suite", side_effect=AssertionError("saved real output recalculated")):
            later = operation.run_saved_inputs(self.journal, rows, {}, at="2030-01-15T12:00:00+09:00")
        self.assertTrue(all(s["status"] == "ORIGINAL_REUSED" for s in generated(later)))
        self.assertFalse(later["independent_freeze_verified"])

    def test_real_first_import_requires_matching_saved_input_and_never_reexecutes(self):
        for sport in ("boat", "keirin", "autorace", "horse"):
            with self.subTest(sport=sport):
                rows, inputs = fixture(sport, real=True)
                originals = generated(native.dispatch(rows, inputs, now=AT,
                                                      allow_source=gate().authorize))
                before = deepcopy(originals)
                with patch.object(native, "run_suite", side_effect=AssertionError("saved original inferred again")):
                    report = operation.run_saved_inputs(self.journal, rows, inputs,
                                at="2030-01-15T12:00:00+09:00", allow_source=gate().authorize,
                                originals=originals)
                self.assertEqual(len(generated(report)), 4)
                self.assertTrue(all(s["status"] == "ORIGINAL_REUSED" for s in generated(report)))
                self.assertEqual(originals, before)
                self.assertEqual([s["prediction"] for s in generated(report)],
                                 [s["prediction"] for s in originals])
        self.assertEqual(len(self.journal.originals()), 16)

    def test_unbound_or_storage_denied_real_original_import_is_rejected_atomically(self):
        rows, inputs = fixture(real=True)
        originals = generated(native.dispatch(rows, inputs, now=AT, allow_source=gate().authorize))
        changed = deepcopy(inputs)
        snap = changed[rows[0]["race_id"]]["P0"]["shared"]["snapshot"]
        snap["participants"][0]["features"]["ability"]["value"] = 0.17
        for supplied, authorize in (({}, gate().authorize), (changed, gate().authorize),
                                     (inputs, lambda ref, rights, use: use == "analysis")):
            with self.subTest(supplied=bool(supplied)):
                with patch.object(native, "run_suite", side_effect=AssertionError("invalid import inferred")):
                    with self.assertRaisesRegex(ValueError, "UNVERIFIED_ORIGINAL_STORAGE_EVIDENCE"):
                        operation.run_saved_inputs(self.journal, rows, supplied,
                            at="2030-01-15T12:00:00+09:00", allow_source=authorize, originals=originals)
                self.assertEqual(self.journal.originals(), [])

    def test_relabeling_real_native_original_as_synthetic_cannot_bypass_source_gates(self):
        rows, inputs = fixture(real=True)
        original = generated(native.dispatch(rows, inputs, now=AT, allow_source=gate().authorize))[0]
        original["scope"] = "SYNTHETIC_ONLY"
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_ORIGINAL_STORAGE_EVIDENCE"):
            operation.run_saved_inputs(self.journal, rows, {}, at="2030-01-15T12:00:00+09:00",
                                       originals=[original])
        self.assertEqual(self.journal.originals(), [])

    def test_saved_inventory_rejects_conflicting_outer_and_native_scope(self):
        rows, inputs = fixture(real=True)
        original = generated(native.dispatch(rows, inputs, now=AT, allow_source=gate().authorize))[0]
        original["scope"] = "SYNTHETIC_ONLY"
        key = (original["sport"], original["race_id"], original["stage"], original["model_id"],
               '"' + original["model_version"] + '"')
        with self.journal.connect() as db:
            db.execute("INSERT INTO dispatch_originals VALUES(?,?,?,?,?,?)", (*key, operation._wire(original)))
        with self.assertRaises(ValueError):
            self.journal.originals()

    def test_late_missing_models_stay_missing_and_stage_is_never_inferred(self):
        rows, inputs = fixture()
        late = operation.run_saved_inputs(self.journal, rows, inputs,
                                          at="2030-01-15T12:00:00+09:00")
        self.assertEqual(generated(late), [])
        self.assertIn("DEADLINE_PASSED", {s["status"] for s in late["dispatch"]["slots"]})
        rows[0].pop("stage")
        with self.assertRaises(ValueError):
            operation.run_saved_inputs(self.journal, rows, inputs, at=AT)

    def test_imported_original_versions_coexist_without_replacement(self):
        rows, inputs = fixture()
        original = generated(native.dispatch(rows, inputs, now=AT))[0]
        second_version = deepcopy(original)
        second_version["prediction"]["model_version"] = "FICTIONAL_PRIOR_VERSION"
        second_version["model_version"] = "FICTIONAL_PRIOR_VERSION"
        p = second_version["prediction"]
        p["prediction_sha256"] = digest({k:v for k,v in p.items() if k != "prediction_sha256"})
        second_version["prediction_sha256"] = p["prediction_sha256"]
        second_version["output_sha256"] = digest(p)
        report = operation.run_saved_inputs(self.journal, rows, {},
                    at="2030-01-15T12:00:00+09:00", originals=[original, second_version])
        self.assertEqual(len(generated(report)), 2)
        self.assertEqual(len(self.journal.originals()), 2)
        changed = deepcopy(original)
        changed["prediction"]["confidence_level"] = "FICTIONAL_MUTATION"
        p = changed["prediction"]
        p["prediction_sha256"] = digest({k:v for k,v in p.items() if k != "prediction_sha256"})
        changed["prediction_sha256"] = p["prediction_sha256"]
        changed["output_sha256"] = digest(p)
        with self.assertRaises(ValueError):
            operation.run_saved_inputs(self.journal, rows, {}, at=AT, originals=[changed])
        self.assertEqual(len(self.journal.originals()), 2)

    def test_concurrent_operations_infer_once_and_keep_one_original_per_version(self):
        rows, inputs = fixture()
        barrier = threading.Barrier(2)
        journals = [self.journal, operation.PrivateDispatchJournal(self.path)]
        def execute(index):
            barrier.wait(timeout=5)
            return operation.run_saved_inputs(journals[index], rows, inputs, at=AT)
        with patch.object(native, "run_suite", wraps=native.run_suite) as called:
            with ThreadPoolExecutor(max_workers=2) as pool:
                reports = list(pool.map(execute, range(2)))
        self.assertEqual(called.call_count, 1)
        self.assertEqual(len(self.journal.originals()), 4)
        self.assertEqual(sorted(s["status"] for report in reports for s in generated(report)),
                         ["GENERATED_UNATTESTED"]*4 + ["ORIGINAL_REUSED"]*4)

    def test_failure_rolls_back_claims_and_all_operation_rows(self):
        rows, inputs = fixture()
        with patch.object(native, "dispatch", side_effect=RuntimeError("fictional interruption")):
            with self.assertRaises(RuntimeError):
                operation.run_saved_inputs(self.journal, rows, inputs, at=AT)
        self.assertEqual(self.journal.originals(), [])
        report = operation.run_saved_inputs(self.journal, rows, inputs, at=AT)
        self.assertEqual(report["operation_id"], 1)

    def test_existing_autorace_tables_and_api_are_preserved(self):
        rows, inputs = fixture()
        operation.run_saved_inputs(self.journal, rows, inputs, at=AT)
        self.assertEqual(self.journal.readback("fixture-race", "A_PRE_TRIAL", "fixture-model"),
                         {"state": "ABSENT"})
        with self.journal.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0], 0)
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE dispatch_originals SET wire=wire")

    def test_db_and_ancestor_path_privacy_guards_fail_closed(self):
        git = self.root / "checkout"
        git.mkdir(mode=0o700)
        (git / ".git").mkdir()
        private = git / "private"
        private.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            operation.PrivateDispatchJournal(private / "journal.sqlite")
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            operation.PrivateDispatchJournal(alias / "nested.sqlite")
        hardlink = self.root / "hardlink.sqlite"
        os.link(self.path, hardlink)
        with self.assertRaises(ValueError):
            operation.PrivateDispatchJournal(hardlink)
        hardlink.unlink()
        os.chmod(self.path, 0o644)
        with self.assertRaises(ValueError):
            operation.PrivateDispatchJournal(self.path)
        os.chmod(self.path, 0o600)
        os.chmod(self.root, 0o755)
        with self.assertRaises(ValueError):
            operation.PrivateDispatchJournal(self.path)
        os.chmod(self.root, 0o700)

    def test_later_database_replacement_or_mutation_is_not_silently_recovered(self):
        rows, inputs = fixture()
        operation.run_saved_inputs(self.journal, rows, inputs, at=AT)
        prior = self.root / "prior.sqlite"
        self.path.rename(prior)
        with self.assertRaises(ValueError):
            operation.run_saved_inputs(self.journal, rows, inputs, at=AT)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
