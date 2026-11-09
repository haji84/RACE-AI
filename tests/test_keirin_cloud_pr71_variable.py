"""Synthetic-only four-model variable selection and score reconciliation."""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import unittest

from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.keirin_variable_selection import ODDS_SCHEMA
from scripts.keirin_cloud_pr71_variable import (
    FourModelVariableLedger, FourVariableError,
    stage_four_model_variable_selections,
)
from scripts.keirin_day_four_model_audit import audit_day, MODELS
from test_keirin_pr71_model_adapter import RID, make_sources


class FourVariableCloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root/"private.sqlite3"
        self.clock = [datetime.fromisoformat("2030-01-15T09:21:00+09:00")]
        (self.root/"odds").mkdir()

    def store(self):
        return PrivateKeirinStore(self.database, clock=lambda:self.clock[0])

    def original(self):
        with self.store() as store:
            ledger=FourModelRankLedger(store)
            self.assertEqual(ledger.freeze_once(copy.deepcopy(make_sources()[0])),
                             "FOUR_MODELS_FROZEN_ONCE")
            return ledger.read_suite(RID)

    def odds(self, original):
        candidates=original["suite"]["models"][ALL_MODELS[0]]["candidates"]
        return {"schema":ODDS_SCHEMA,"race_id":RID,
                "captured_at":self.clock[0].isoformat(),
                "source_ref":"synthetic://private-test",
                "source_rights_ref":"SYNTHETIC_ONLY",
                "prices":[{"triple":c["combination"],"decimal_odds":1000.0}
                          for c in candidates]}

    def stage(self, odds):
        name=sha256(RID.encode()).hexdigest()+".json"
        (self.root/"odds"/name).write_text(json.dumps(odds),encoding="utf-8")
        with self.store() as store:
            return stage_four_model_variable_selections(self.root,store)

    def test_four_distinct_model_selections_persist_and_are_idempotent(self):
        original=self.original()
        self.assertEqual(self.stage(self.odds(original))["four_model_variable_saved"],4)
        with self.store() as store:
            ledger=FourModelVariableLedger(store)
            ids=set()
            for mid in ALL_MODELS:
                doc=ledger.selection(RID,mid)["selection"]
                self.assertEqual(doc["suite_sha256"],original["suite"]["suite_sha256"])
                self.assertEqual(doc["model_prediction_sha256"],
                                 original["suite"]["models"][mid]["prediction_sha256"])
                self.assertEqual(doc["model_id"],mid)
                self.assertTrue(0<=doc["pick_count"]<=12)
                self.assertEqual(len(doc["tickets"]),doc["pick_count"])
                ids.add(doc["document_sha256"])
            self.assertEqual(len(ids),4)
            self.assertEqual(len(ledger.inventory()),4)
            self.assertEqual(FourModelRankLedger(store).read_suite(RID)["suite"]["suite_sha256"],
                             original["suite"]["suite_sha256"])
        self.assertEqual(self.stage(self.odds(original))["four_model_variable_saved"],0)

    def test_variable_winner_scored_by_existing_pr71_engine(self):
        original=self.original()
        self.stage(self.odds(original))
        with self.store() as store:
            doc=FourModelVariableLedger(store).selection(RID,ALL_MODELS[0])["selection"]
            self.assertGreater(doc["pick_count"],0)
            winner=doc["tickets"][0]["triple"]
        self.clock[0]=datetime.fromisoformat("2030-01-15T10:40:00+09:00")
        with self.store() as store:
            store.add_result_observation({
                "race_id":RID,"observed_at":"2030-01-15T10:15:00+09:00",
                "source_sha256":"e"*64,"status":"FINAL_NORMAL",
                "refund_status":"NONE","winning_triples":[winner],
                "payouts_100yen":[{"triple":winner,"yen":18700}]})
        cohort={"schema":"RACE_AI_KEIRIN_20261110_78R_SOURCE_ONLY_COHORT_V1",
                "event_day_jst":"2030-01-15","scheduled_venues":1,
                "scheduled_races":1,"model_ids":list(MODELS),
                "races":[{"race_id":RID,"venue":"fictional","race_no":1,
                          "venue_code":"00","prediction_expected_models":4}]}
        report=audit_day(cohort,self.database,include_private=True)
        self.assertEqual(report["frozen_model_race_pairs"],4)
        self.assertEqual(report["settled_research_races"],1)
        self.assertEqual(report["formally_authenticated_model_race_scores"],0)
        v=report["models"][ALL_MODELS[0]]["modes"]["variable"]
        self.assertEqual(v["active_races"],1)
        self.assertEqual(v["hit_races"],1)
        self.assertEqual(v["reference_paid_yen"],18700)
        self.assertEqual(v["mansha_races_captured"],1)
        self.assertGreater(v["reference_stake_yen"],0)

    def test_after_cutoff_is_not_retroactively_frozen(self):
        original=self.original()
        odds=self.odds(original)
        self.clock[0]=datetime.fromisoformat("2030-01-15T10:40:00+09:00")
        with self.store() as store:
            with self.assertRaises(FourVariableError):
                FourModelVariableLedger(store).freeze_four_once(RID,odds)
            self.assertEqual(FourModelVariableLedger(store).inventory(),[])

    def test_payload_tamper_is_rejected(self):
        original=self.original()
        self.stage(self.odds(original))
        with self.store() as store:
            store.db.execute("UPDATE keirin_pr71_four_model_variable_selections "
                             "SET payload=? WHERE race_id=? AND model_id=?",
                             (b'{"forged":true}',RID,ALL_MODELS[0]))
            with self.assertRaises(FourVariableError):
                FourModelVariableLedger(store).inventory()


if __name__=="__main__":
    unittest.main()
