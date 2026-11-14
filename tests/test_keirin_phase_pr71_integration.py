"""Offline adapter: actual pinned PR71 FourModelRankLedger -> phase sidecar.

The original four-model suite is generated using entirely fictional riders
and is read back from a temporary owner SQLite. No actual source, true
pre-cutoff external witness, video recording, or trained classifier involved.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import importlib.util
import os
import unittest

from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from test_keirin_pr71_model_adapter import make_sources, RID

JST = timezone(timedelta(hours=9))
AT = datetime(2030, 1, 15, 9, 21, tzinfo=JST)
LATER = AT + timedelta(minutes=1)


def main_overlay():
    location = os.environ.get("RACE_AI_PHASE_MAIN_ROOT")
    if not location:
        raise RuntimeError("MAIN_PHASE_OVERLAY_PATH_REQUIRED")
    p = Path(location) / "race_ai" / "keirin_phase_overlay.py"
    if not p.is_file():
        raise RuntimeError("MAIN_PHASE_OVERLAY_MISSING")
    spec = importlib.util.spec_from_file_location("_main_keirin_phase_overlay", p)
    if spec is None or spec.loader is None:
        raise RuntimeError("MAIN_PHASE_OVERLAY_UNLOADABLE")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ExistingPR71PrivateOriginalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = main_overlay()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "private.sqlite3"
        source, _, _ = make_sources()
        with PrivateKeirinStore(self.db, clock=lambda: AT) as store:
            ledger = FourModelRankLedger(store)
            self.assertEqual(ledger.freeze_once(deepcopy(source)),
                             "FOUR_MODELS_FROZEN_ONCE")
            self.saved = deepcopy(ledger.read_suite(RID))
        self.assertEqual(self.saved["source"]["race_id"], RID)

    def predictions(self):
        return {
            name: {
                part: self.overlay.UNKNOWN for part in (
                    "leader", "top3", "line_groups",
                    "second_wheel", "attack")
            } for name, _ in self.overlay.STAGES
        }

    def make(self, saved=None, *, verifier=True, clock=lambda: LATER):
        return self.overlay.build_from_existing_pr71_saved(
            self.saved if saved is None else saved,
            model_id="multisport-race-trajectory-v1",
            stage_predictions=self.predictions(),
            clock=clock,
            verified_ledger_reader=lambda value: verifier,
        )

    def test_existing_four_model_readback_binds_exact_parent_and_input_sha(self):
        row = self.make()
        m = self.saved["suite"]["models"]["multisport-race-trajectory-v1"]
        self.assertEqual(row["race_id"], RID)
        self.assertEqual(row["model_id"], m["model_id"])
        self.assertEqual(row["parent_prediction_sha256"],
                         m["prediction_sha256"])
        self.assertEqual(row["pre_race_input_sha256"],
                         m["snapshot_sha256"])
        self.assertEqual(row["parent_saved_at"],
                         self.saved["persisted_at"])
        self.assertTrue(self.overlay.checked_forecast(row))
        # No phase tactic is invented from the model's 210-way top-eight.
        self.assertTrue(all(
            part == self.overlay.UNKNOWN
            for phase in row["stage_predictions"].values()
            for part in phase.values()
        ))

    def test_refuse_absent_independent_existing_ledger_attestation(self):
        with self.assertRaisesRegex(
            self.overlay.PhaseError, "EXISTING_PR71_LEDGER_NOT_INDEPENDENTLY_VERIFIED"):
            self.make(verifier=False)

    def test_mismatch_source_or_model_cannot_be_bound_as_parent(self):
        corrupted = deepcopy(self.saved)
        corrupted["suite"]["models"][
            "multisport-race-trajectory-v1"]["snapshot_sha256"] = "a" * 64
        with self.assertRaisesRegex(
            self.overlay.PhaseError, "PR71_LEDGER_OR_SOURCE_IDENTITY_MISMATCH"):
            self.make(saved=corrupted)
        corrupted = deepcopy(self.saved)
        corrupted["source"]["race_id"] = "keirin:2030-01-15:invented:2"
        with self.assertRaisesRegex(
            self.overlay.PhaseError, "PR71_LEDGER_OR_SOURCE_IDENTITY_MISMATCH"):
            self.make(saved=corrupted)

    def test_stale_parent_cannot_be_rewritten_to_after_cutoff_phase(self):
        with self.assertRaisesRegex(
            self.overlay.PhaseError, "MISSING_PRE_CUTOFF_PHASE_FREEZE"):
            self.make(clock=lambda: datetime(2030, 1, 15, 10, 1, tzinfo=JST))


if __name__ == "__main__":
    unittest.main()
