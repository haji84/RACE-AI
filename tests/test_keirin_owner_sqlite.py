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


    def test_all_76_discovered_races_survive_restart(self):
        venue_counts={12:12,36:7,38:7,45:12,53:7,63:12,83:12,84:7}
        rows=[]
        for venue,count in venue_counts.items():
            for number in range(1,count+1):
                rows.append({"race_id":f"20261103{venue:02d}{number:02d}",
                    "event_date_jst":"2026-11-03",
                    "venue_code":venue,"race_no":number,
                    "official_cutoff_at":None})
        self.assertEqual(len(rows),76)
        doc={"schema":"RACE_AI_KEIRIN_ALL_DISCOVERED_RACES_LEDGER_V1",
             "event_date_jst":"2026-11-03",
             "discovered_count":len(rows),
             "national_coverage_verified":False,
             "records":rows}
        first=self.store.register_discovered_cohort(doc)
        self.assertEqual(first["total"],76)
        self.assertEqual(first["new"],76)
        self.assertEqual(first["forecast_generated"],0)
        self.assertEqual(self.store.register_discovered_cohort(doc)["new"],0)
        with PrivateKeirinStore(self.path,clock=self.clock) as reopened:
            status=reopened.inspect_cohort("2026-11-03")
            self.assertEqual(status["known_race_count"],76)
            self.assertEqual(status["forecast_count"],0)
            self.assertEqual(len(status["records"]),76)
            self.assertTrue(all(r["result_status"]=="UNOBSERVED"
                                for r in status["records"]))
            self.assertFalse(status["official_coverage_verified"])

    def test_discovered_race_duplicates_are_rejected_without_partial_write(self):
        key={"race_id":"202611033601","venue_code":36,
             "race_no":1,"official_cutoff_at":None}
        doc={"schema":"RACE_AI_KEIRIN_ALL_DISCOVERED_RACES_LEDGER_V1",
             "event_date_jst":"2026-11-03",
             "discovered_count":2,
             "national_coverage_verified":False,
             "records":[key,key]}
        with self.assertRaisesRegex(OwnerStoreError,"UNVERIFIED_COHORT_IDENTITY"):
            self.store.register_discovered_cohort(doc)
        self.assertEqual(self.store.inspect_cohort("2026-11-03")["known_race_count"],0)

    def test_result_payout_inconsistent_is_never_a_hit(self):
        result={"race_id":RID,
                "observed_at":"2026-11-03T10:51:00+09:00",
                "source_sha256":"a"*64,
                "status":"FINAL_NORMAL","refund_status":"NONE",
                "winning_triples":[[1,2,3]],
                "payouts_100yen":[{"triple":[2,1,3],"yen":1000}]}
        with self.assertRaisesRegex(OwnerStoreError,"INCONSISTENT_SETTLED_RESULT"):
            self.store.add_result_observation(result)
        self.assertIsNone(self.store.research_audit(RID)["research_hit8"])

    def test_outcome_time_regression_is_rejected(self):
        doc={"race_id":RID,"observed_at":"2026-11-03T10:50:30+09:00",
             "source_sha256":"a"*64,"status":"FINAL_NORMAL",
             "refund_status":"NONE","winning_triples":[[1,2,3]],
             "payouts_100yen":[{"triple":[1,2,3],"yen":1000}]}
        self.store.add_result_observation(doc)
        changed=deepcopy(doc)
        changed["observed_at"]="2026-11-03T10:49:30+09:00"
        changed["source_sha256"]="b"*64
        with self.assertRaisesRegex(OwnerStoreError,"RESULT_REVISION_TIME_REGRESSION"):
            self.store.add_result_observation(changed)
        self.assertEqual(self.store.db.execute(
            "SELECT count(*) FROM result_revisions").fetchone()[0],1)

    def test_pending_result_with_winner_is_refused(self):
        doc={"race_id":RID,"observed_at":"2026-11-03T10:50:30+09:00",
             "source_sha256":"a"*64,"status":"PENDING",
             "refund_status":"UNKNOWN","winning_triples":[[1,2,3]],
             "payouts_100yen":[]}
        with self.assertRaisesRegex(OwnerStoreError,"NON_FINAL_RESULT_CANNOT_HAVE_WINNERS"):
            self.store.add_result_observation(doc)


if __name__ == "__main__":
    unittest.main()
