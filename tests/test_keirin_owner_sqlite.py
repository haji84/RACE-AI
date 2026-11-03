"""Cross-process, real SQLite persistence tests. All race observations fictional."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from race_ai.keirin_owner_sqlite import PrivateKeirinStore, OwnerStoreError
from race_ai.keirin_next_forecast_worker import consume_next_intent
from tests.test_keirin_next_forecast_worker import fixture, RID, CUTOFF, NOW, AFTER


class RealSQLitePrivateStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "private.sqlite3"
        self.write_time = "2026-11-03T10:51:00+09:00"
        self.clock = lambda: datetime.fromisoformat(self.write_time)
        self.store = PrivateKeirinStore(self.path, clock=self.clock)
        self.addCleanup(self.store.close)
        self.intent, self.snapshot, self.prediction, self.cert = fixture()

    def test_snapshot_and_outbox_durable_across_second_connection(self):
        expected=self.intent["pre_race_snapshot_sha256"]
        self.assertEqual(self.store.save_source_snapshot_once(self.snapshot),expected)
        self.assertEqual(self.store.enqueue_once(self.intent),{
            "idempotency_key":self.intent["idempotency_key"],
            "state":"CREATED_OR_EXISTS"
        })
        with PrivateKeirinStore(self.path,clock=self.clock) as second:
            self.assertEqual(second.read_queued_intent(
                self.intent["idempotency_key"]),self.intent)
            self.assertEqual(second.read_snapshot(self.intent),self.snapshot)
            self.assertEqual(second.frozen_status(RID)["state"],
                             "ABSENT_VERIFIED_BY_OWNER")
            self.assertEqual(second.enqueue_once(deepcopy(self.intent)),{
                "idempotency_key":self.intent["idempotency_key"],
                "state":"CREATED_OR_EXISTS"
            })
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM outbox"
                                             ).fetchone()[0],1)

    def test_two_distinct_intents_same_key_never_overwrite(self):
        self.assertTrue(self.store.enqueue_once(self.intent))
        changed=deepcopy(self.intent)
        changed["trigger_source_event_sha256"]="f"*64
        self.assertIsNone(self.store.enqueue_once(changed))
        self.assertEqual(self.store.read_queued_intent(
            self.intent["idempotency_key"]),self.intent)

    def test_real_transactional_write_with_existing_worker(self):
        self.store.save_source_snapshot_once(self.snapshot)
        self.store.enqueue_once(self.intent)
        times=iter([NOW,AFTER])
        out=consume_next_intent(
            self.intent,clock=lambda:next(times),
            read_queued_intent=self.store.read_queued_intent,
            read_snapshot=self.store.read_snapshot,
            attest_source=lambda s,i:self.cert,
            frozen_status=self.store.frozen_status,
            model_forecast=lambda s:self.prediction,
            atomic_freeze=self.store.atomic_freeze,
            freeze_readback=self.store.freeze_readback,
            independent_receipt_check=lambda r,h:None)
        self.assertTrue(out["forecast_durably_saved"])
        self.assertFalse(out["independent_receipt_accepted_by_callback"])
        self.assertEqual(out["state"],"EXTERNAL_PRE_CUTOFF_RECEIPT_UNVERIFIED")
        with PrivateKeirinStore(self.path,clock=self.clock) as second:
            found=second.get_persisted_forecast(RID)
            self.assertIsNotNone(found)
            self.assertEqual(found["forecast"]["top8"],
                             self.prediction["top8"])
            self.assertFalse(found["external_receipt_verified"])
            self.assertEqual(second.frozen_status(RID)["state"],"EXISTS")
            self.assertIsNone(second.atomic_freeze(
                found["forecast"],found["sha256"]))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM forecasts"
                                              ).fetchone()[0],1)
        if os.name=="posix":
            self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_cutoff_is_enforced_again_at_write_time(self):
        self.write_time="2026-11-03T11:31:00+09:00"
        payload={"race_id":RID,"model_id":"fixture",
                "official_cutoff_at":CUTOFF,
                "generated_at":"2026-11-03T10:50:30+09:00"}
        fingerprint=sha256(__import__("race_ai.keirin_result_delivery",
                           fromlist=["canonical"]).canonical(payload)).hexdigest()
        self.assertIsNone(self.store.atomic_freeze(payload,fingerprint))
        self.assertEqual(self.store.frozen_status(RID)["state"],
                         "ABSENT_VERIFIED_BY_OWNER")

    def test_result_revisions_audit_follow_original_not_latest_model(self):
        self.test_real_transactional_write_with_existing_worker()
        self.write_time="2026-11-03T12:00:00+09:00"
        result={"race_id":RID,"observed_at":"2026-11-03T11:50:00+09:00",
                "source_sha256":"a"*64,
                "status":"FINAL_NORMAL","refund_status":"NONE",
                "winning_triples":[[1,2,3]],
                "payouts_100yen":[{"triple":[1,2,3],"yen":1200}]}
        first=self.store.add_result_observation(result)
        self.assertEqual(first["revision"],1)
        self.assertFalse(first["official_result_authenticated"])
        self.assertEqual(self.store.add_result_observation(result)["state"],
                         "ALREADY_PRESENT")
        audit=self.store.research_audit(RID)
        self.assertTrue(audit["research_hit8"])
        self.assertIsNone(audit["formal_hit_at_8_all"])
        corrected=deepcopy(result)
        corrected["winning_triples"]=[[7,6,5]]
        corrected["payouts_100yen"]=[{"triple":[7,6,5],"yen":9800}]
        corrected["source_sha256"]="b"*64
        revised=self.store.add_result_observation(corrected)
        self.assertEqual(revised["revision"],2)
        after=self.store.research_audit(RID)
        self.assertFalse(after["research_hit8"])
        self.assertEqual(after["result_revision"],2)
        self.assertEqual(self.store.db.execute(
            "SELECT count(*) FROM audits WHERE race_id=?",(RID,)
        ).fetchone()[0],2)
        with PrivateKeirinStore(self.path,clock=self.clock) as second:
            self.assertFalse(second.research_audit(RID)["research_hit8"])
            self.assertEqual(second.get_persisted_forecast(RID)["forecast"]["top8"],
                             self.prediction["top8"])

    def test_unknown_forecast_or_result_is_null_not_miss(self):
        out=self.store.research_audit(RID)
        self.assertIsNone(out["research_hit8"])
        self.assertEqual(out["reason"],"FORECAST_OR_RESULT_MISSING")

    def test_cross_process_freeze_is_create_only(self):
        self.write_time="2026-11-03T10:51:00+09:00"
        payload={"race_id":RID,"model_id":"fixture",
                 "official_cutoff_at":CUTOFF,
                 "generated_at":"2026-11-03T10:50:30+09:00",
                 "top8":self.prediction["top8"]}
        from race_ai.keirin_result_delivery import canonical
        h=sha256(canonical(payload)).hexdigest()
        result=self.store.atomic_freeze(payload,h)
        self.assertEqual(result["state"],"CREATED_ONCE")
        with PrivateKeirinStore(self.path,clock=self.clock) as competing:
            self.assertIsNone(competing.atomic_freeze(payload,h))
        self.assertEqual(self.store.db.execute(
            "SELECT count(*) FROM forecasts").fetchone()[0],1)

    def test_refuse_in_memory_db_and_symlink(self):
        with self.assertRaisesRegex(OwnerStoreError,"PERSISTENT_SQLITE"):
            PrivateKeirinStore(":memory:")
        if hasattr(os,"symlink"):
            link=Path(self.folder.name)/"db-link.sqlite3"
            try:os.symlink(self.path,link)
            except OSError:return
            with self.assertRaisesRegex(OwnerStoreError,"SYMLINKED"):
                PrivateKeirinStore(link,clock=self.clock)


if __name__ == "__main__":
    unittest.main()
