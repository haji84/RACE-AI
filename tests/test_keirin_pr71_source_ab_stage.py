"""Proof-of-mechanics only. All riders, source grants and payouts fictional."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from race_ai.keirin_pr71_source_ab_stage import (
    KeirinEvidenceABError, stage_existing_four_models_a_b)
from race_ai.keirin_allowed_delivery import DISTINCT_B_ID
from tests.test_keirin_allowed_delivery import (
    fixture, granted, CHECKED, RID, CUTOFF)


class ExistingFourModelEvidenceABTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a_path=Path(self.tmp.name)/"a_original.sqlite3"
        self.b_path=Path(self.tmp.name)/"b_distinct.sqlite3"
        self.now=[datetime.fromisoformat("2030-01-15T09:21:00+09:00")]
        self.clock=lambda:self.now[0]

    def packet(self):
        obj=fixture(full=True)
        for row in obj["observations"]:
            if row["key"].endswith((
                "/late_lap_and_agari_time",
                "/bank_positioning_and_traffic",
            )):
                row["value"]=.6
            if row["key"]=="rider/1/last_lap_acceleration":
                row["value"]=.94
            if row["key"]=="rider/1/late_lap_and_agari_time":
                row["value"]=.13
            if row["key"]=="rider/1/bank_positioning_and_traffic":
                row["value"]=.17
            if row["key"]=="rider/1/venue_and_distance_compatibility":
                row["value"]=.81
        return obj

    def stage(self, packet=None, *, source_admission=granted):
        with PrivateKeirinStore(self.a_path,clock=self.clock) as a:
            with PrivateKeirinStore(self.b_path,clock=self.clock) as b:
                return stage_existing_four_models_a_b(
                    self.packet() if packet is None else packet,
                    a,b,grant_check=granted,
                    source_admission=source_admission,checked_at=CHECKED)

    def test_real_four_models_a_and_b_frozen_independently_and_restart(self):
        result=self.stage()
        self.assertEqual(result["state"],
                         "A_B_FOUR_MODELS_EACH_FROZEN_AND_READ_BACK")
        self.assertTrue(result["A_persisted"])
        self.assertTrue(result["B_persisted"])
        self.assertNotEqual(result["A_immutable_rank_suite_sha256"],
                            result["B_immutable_rank_suite_sha256"])
        self.assertNotEqual(result["A_immutable_source_sha256"],
                            result["B_immutable_source_sha256"])
        self.assertEqual(result["model_ids"],list(ALL_MODELS))
        self.assertIsNone(result["formal_improvement_claim"])
        # Same fictional race in two different SQLite volumes; do not
        # overwrite or retrofit the original A after seeing a result.
        for path in (self.a_path,self.b_path):
            with PrivateKeirinStore(path,clock=self.clock) as owner:
                record=FourModelRankLedger(owner).read_suite(RID)
                self.assertEqual(tuple(record["suite"]["models"]),ALL_MODELS)
                for model in record["suite"]["models"].values():
                    self.assertEqual(model["candidate_count"],210)
                    self.assertEqual(len(model["ordered_top8"]),8)
                self.assertEqual(owner.db.execute(
                    "SELECT COUNT(*) FROM forecasts").fetchone()[0],0)
        # Results arrive only AFTER both versions have been frozen.
        self.now[0]=datetime.fromisoformat(
            "2030-01-15T10:30:00+09:00")
        fictional_final={
            "race_id":RID,
            "observed_at":"2030-01-15T10:25:00+09:00",
            "source_sha256":"a"*64,
            "status":"FINAL_NORMAL", "refund_status":"NONE",
            "winning_triples":[[1,2,3]],
            "payouts_100yen":[{"triple":[1,2,3],"yen":18000}]
        }
        all_audits=[]
        for path in (self.a_path,self.b_path):
            with PrivateKeirinStore(path,clock=self.clock) as owner:
                owner.add_result_observation(fictional_final)
                # SAME PRE-EXISTING scorer, not another A/B settlement engine.
                audit=FourModelRankLedger(owner).audit_revision(RID)
                self.assertEqual(len(audit),4)
                for k,v in audit.items():
                    self.assertEqual(v["winning_tickets"][0][
                        "payout_yen_per_100"],18000)
                    self.assertFalse(v["model_probabilities_calibrated"])
                    self.assertIsNone(v["formal_roi"])
                    self.assertFalse(v[
                        "independent_external_cutoff_receipt_verified"])
                all_audits.append(audit)
        self.assertEqual(set(all_audits[0]),set(all_audits[1]))

    def test_B_missing_distinct_source_leaves_A_frozen_only(self):
        packet=self.packet()
        packet["observations"]=[
            x for x in packet["observations"]
            if x["key"]!="rider/2/late_lap_and_agari_time"]
        r=self.stage(packet)
        self.assertEqual(
            r["state"],"A_FROZEN_B_BLOCKED_MISSING_SEPARATE_EVIDENCE")
        self.assertTrue(r["A_persisted"])
        self.assertFalse(r["B_persisted"])
        self.assertIn("rider/2/finishing_power",r["input_B_missing"])
        with PrivateKeirinStore(self.a_path,clock=self.clock) as a:
            self.assertIsNotNone(FourModelRankLedger(a).read_suite(RID))
        with PrivateKeirinStore(self.b_path,clock=self.clock) as b:
            self.assertIsNone(FourModelRankLedger(b).read_suite(RID))

    def test_A_missing_core_data_neither_variant_frozen(self):
        packet=self.packet()
        packet["observations"]=[
            x for x in packet["observations"]
            if x["key"]!="rider/1/race_score"]
        result=self.stage(packet)
        self.assertEqual(result["state"],"BLOCKED_A_AND_B")
        self.assertFalse(result["A_persisted"])
        self.assertFalse(result["B_persisted"])
        self.assertIn("rider/1/ability",result["input_A_missing"])

    def test_source_grants_are_still_required_for_both(self):
        with self.assertRaises(ValueError):
            self.stage(source_admission=lambda *_:False)
        with PrivateKeirinStore(self.a_path,clock=self.clock) as a:
            self.assertIsNone(FourModelRankLedger(a).read_suite(RID))

    def test_same_database_refused_to_avoid_A_overwrite(self):
        with PrivateKeirinStore(self.a_path,clock=self.clock) as a:
            with PrivateKeirinStore(self.a_path,clock=self.clock) as b:
                with self.assertRaisesRegex(
                    KeirinEvidenceABError,"DISTINCT_PRIVATE_VAULTS_REQUIRED"):
                    stage_existing_four_models_a_b(
                        self.packet(),a,b,grant_check=granted,
                        source_admission=granted,checked_at=CHECKED)

    def test_after_cutoff_cannot_backfill_baseline(self):
        self.now[0]=datetime.fromisoformat(
            "2030-01-15T10:01:00+09:00")
        with self.assertRaisesRegex(
            KeirinEvidenceABError,"A_B_NOT_BEFORE_CUTOFF"):
            self.stage()
        with PrivateKeirinStore(self.a_path,clock=self.clock) as a:
            self.assertIsNone(FourModelRankLedger(a).read_suite(RID))


if __name__=="__main__":
    unittest.main()
