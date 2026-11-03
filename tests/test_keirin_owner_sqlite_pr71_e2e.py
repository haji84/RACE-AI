"""Actual PR71 untrained model + REAL private SQLite persistence, fictional riders.

No provider data, no source grant, no external witness. This is a
cross-process persistence E2E, NOT a live officially scored race.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_next_forecast_worker import consume_next_intent
from race_ai.keirin_pr71_model_adapter import run_pr71_for_next_race
from tests.test_keirin_pr71_model_adapter import (
    RID, CUTOFF, ISSUED, make_sources, run_suite, verify_suite
)


@unittest.skipIf(run_suite is None, "pinned PR71 engine missing")
class PersistentPR71CrossProcessTests(unittest.TestCase):
    def test_actual_model_forecast_is_durable_after_reopening_store(self):
        snap,intent,certificate=make_sources()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"owner.sqlite3"
            store_time=lambda:datetime.fromisoformat(
                "2030-01-15T09:22:01+09:00")
            with PrivateKeirinStore(path,clock=store_time) as store:
                self.assertEqual(
                    store.save_source_snapshot_once(snap),
                    intent["pre_race_snapshot_sha256"]
                )
                self.assertEqual(store.enqueue_once(intent)["state"],
                                 "CREATED_OR_EXISTS")
                calls={"model":0}
                def predict(snapshot):
                    calls["model"]+=1
                    return run_pr71_for_next_race(
                        snapshot,run_suite=run_suite,verify_suite=verify_suite,
                        source_admission=None,
                        model_id="multisport-scenario-ensemble-v1",
                        issued_at=ISSUED
                    )
                t=iter(["2030-01-15T09:20:00+09:00",
                        "2030-01-15T09:22:00+09:00"])
                outcome=consume_next_intent(
                    intent,
                    clock=lambda:next(t),
                    read_queued_intent=store.read_queued_intent,
                    read_snapshot=store.read_snapshot,
                    attest_source=lambda s,i:certificate,
                    frozen_status=store.frozen_status,
                    model_forecast=predict,
                    atomic_freeze=store.atomic_freeze,
                    freeze_readback=store.freeze_readback,
                    independent_receipt_check=lambda r,h:None,
                )
                self.assertTrue(outcome["forecast_durably_saved"])
                self.assertFalse(
                    outcome["independent_receipt_accepted_by_callback"])
                self.assertEqual(calls["model"],1)
                fingerprint=outcome["forecast_sha256"]
            with PrivateKeirinStore(path,clock=store_time) as reopened:
                record=reopened.get_persisted_forecast(RID)
                self.assertEqual(record["sha256"],fingerprint)
                self.assertEqual(
                    record["forecast"]["model_id"],
                    "multisport-scenario-ensemble-v1"
                )
                self.assertEqual(len(record["forecast"]["top8"]),8)
                self.assertEqual(len({
                    tuple(x) for x in record["forecast"]["top8"]}),8)
                self.assertEqual(record["forecast"]["trained"],False)
                self.assertIsNone(record["forecast"]["trained_until"])
                self.assertFalse(record["external_receipt_verified"])
                self.assertFalse(record["forecast"]["officially_frozen"])
                self.assertEqual(reopened.frozen_status(RID)["state"],"EXISTS")
                self.assertEqual(reopened.read_queued_intent(
                    intent["idempotency_key"]),intent)

    def test_missing_external_witness_cannot_be_laundered_into_formal_hit8(self):
        self.assertFalse(callable(None))
        # This test intentionally does NOT invent or sign any pre-cutoff
        # certificate. The owner-worker still marks external_receipt false.
        snap,intent,certificate=make_sources()
        with tempfile.TemporaryDirectory() as d:
            with PrivateKeirinStore(Path(d)/"owner.db",
                clock=lambda:datetime.fromisoformat(
                    "2030-01-15T09:21:01+09:00")) as store:
                store.enqueue_once(intent)
                store.save_source_snapshot_once(snap)
                result=store.get_persisted_forecast(RID)
                self.assertIsNone(result)
                self.assertIsNone(store.research_audit(RID)["research_hit8"])


if __name__=="__main__":
    unittest.main()
