"""Real SQLite + existing PR71 spool + PR103 sidecar, synthetic riders only.

No live odds, rightsholder source, official claim, or real-money purchase.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.four_sport_model_suite import run_suite, verify_suite
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_private_spool import KeirinPrivateSpool
from race_ai.keirin_variable_selection import ODDS_SCHEMA
from race_ai.keirin_variable_integration import (
    PrivateVariableLedger, PrivateVariableBridgeError
)
from tests.test_keirin_pr71_model_adapter import make_sources, RID


class VariableOwnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.inbox=self.root/"incoming"
        for name in ("pre","odds","results","daily"):
            (self.inbox/name).mkdir(parents=True)
        self.dbpath=self.root/"owner.sqlite3"
        self.now=[datetime.fromisoformat("2030-01-15T09:21:00+09:00")]
        self.clock=lambda:self.now[0]
        self.snapshot,_,_=make_sources()
        self.suite=run_suite(self.snapshot["facts"]["pr71_evidenced_snapshot"])
        self.model=self.suite["models"]["multisport-scenario-ensemble-v1"]

    def agent(self, store):
        return KeirinPrivateSpool(
            store,clock=self.clock,
            model_suite=run_suite,model_verifier=verify_suite,
            source_attestor=None,source_observation_gate=None,
            source_odds_gate=None,witness=None)

    def save(self,kind,name,obj):
        path=self.inbox/kind/name
        path.write_text(json.dumps(obj,ensure_ascii=False,
                                   sort_keys=True),encoding="utf-8")

    def odds(self, *, positive=2):
        prices=[]
        for i,row in enumerate(self.model["candidates"]):
            prices.append({
                "triple":row["combination"],
                "decimal_odds":(1.5 if i<positive else 0.6)/row["score"],
            })
        return {"schema":ODDS_SCHEMA,"race_id":RID,
                "captured_at":"2030-01-15T09:21:00+09:00",
                "source_ref":"synthetic://fictional-private",
                "source_rights_ref":"SYNTHETIC_ONLY",
                "prices":prices}

    def begin(self, *, positive=2):
        self.save("pre","first.json",self.snapshot)
        if positive is not None:
            self.save("odds","first.json",self.odds(positive=positive))
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            tick=self.agent(store).tick(self.inbox)
            original=store.get_persisted_forecast(RID)
            selection=PrivateVariableLedger(store).selection(
                RID,"multisport-scenario-ensemble-v1")
        return tick,original,selection

    def result(self,winning,payout=690,*,source="a",at="2030-01-15T10:10:00+09:00",
               status="FINAL_NORMAL",refund="NONE"):
        return {"schema":"RACE_AI_PRIVATE_KEIRIN_RESULT_OBSERVATION_V1",
                "observation":{
                    "race_id":RID,"observed_at":at,
                    "source_sha256":source*64,
                    "status":status,"refund_status":refund,
                    "winning_triples":[winning] if winning else [],
                    "payouts_100yen":[{"triple":winning,"yen":payout}]
                       if winning else [],
                }}

    def test_same_tick_eight_forecast_and_two_pick_sidecar_cross_process(self):
        tick,original,selection=self.begin(positive=2)
        self.assertEqual(tick["private_forecasts_saved_this_tick"],1)
        self.assertEqual(tick["variable_selections_saved_this_tick"],1)
        self.assertEqual(selection["selection"]["pick_count"],2)
        self.assertEqual(selection["selection"]["reference_investment_yen"],200)
        self.assertEqual(selection["original_forecast_sha256"],original["sha256"])
        self.assertEqual(len(original["forecast"]["top8"]),8)
        self.assertFalse(original["external_receipt_verified"])
        self.assertFalse(selection["selection"]["official_pre_cutoff_witness_verified"])
        self.assertEqual(tick["provider_network_requests"],0)

        # Restarted independent private SQLite connection reads identical SHA.
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as reopened:
            ledger=PrivateVariableLedger(reopened)
            self.assertEqual(reopened.get_persisted_forecast(RID)["sha256"],
                             original["sha256"])
            self.assertEqual(ledger.selection(RID,original["forecast"]["model_id"]),
                             selection)
            self.assertEqual(ledger.odds_snapshot(
                selection["selection"]["odds_snapshot_sha256"]),self.odds())
            self.assertEqual(reopened.db.execute(
                "SELECT COUNT(*) FROM forecasts").fetchone()[0],1)
            self.assertEqual(reopened.db.execute(
                "SELECT COUNT(*) FROM variable_selections").fetchone()[0],1)

    def test_pre_cutoff_hit_revision_and_roi_saved_without_original_rewrite(self):
        _,original,selection=self.begin(positive=2)
        winner=selection["selection"]["tickets"][0]["triple"]
        self.save("results","01.json",self.result(winner,payout=690))
        self.now[0]=datetime.fromisoformat("2030-01-15T10:20:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            tick=self.agent(store).tick(self.inbox)
            self.assertEqual(tick["variable_selections_saved_this_tick"],0)
            ledger=PrivateVariableLedger(store)
            audit=ledger.audit_latest(RID,original["forecast"]["model_id"])
            self.assertTrue(audit["research_hit"])
            self.assertEqual(audit["reference_investment_yen"],200)
            self.assertEqual(audit["reference_payout_yen"],690)
            self.assertEqual(audit["reference_profit_yen"],490)
            self.assertEqual(audit["reference_roi"],3.45)
            self.assertFalse(audit["result_auth_independently_verified"])
            self.assertEqual(ledger.aggregate()["reference_profit_yen"],490)
            self.assertTrue(ledger.aggregate()["latest_revision_reconciled"])
            compared=ledger.compare_latest(RID,original["forecast"]["model_id"])
            self.assertEqual(compared["state"],"SETTLED_UNVERIFIED_RESEARCH")
            self.assertEqual(compared["fixed8_investment_yen"],800)
            self.assertEqual(compared["variable_investment_yen"],200)
            self.assertEqual(compared["variable_payout_yen"],690)
            self.assertEqual(compared["variable_profit_yen"],490)
            self.assertEqual(compared["original_forecast_sha256"],original["sha256"])
            self.assertEqual(store.get_persisted_forecast(RID)["sha256"],
                             original["sha256"])
        # Reopening for repeat audit does not duplicate results or selections.
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            ledger=PrivateVariableLedger(store)
            self.assertEqual(ledger.audit_latest(
                RID,original["forecast"]["model_id"])["result_revision"],1)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM variable_selection_audits").fetchone()[0],1)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM result_revisions").fetchone()[0],1)

    def test_new_result_revision_corrects_reference_roi_not_original_ticket(self):
        _,original,selection=self.begin(positive=2)
        winner=selection["selection"]["tickets"][0]["triple"]
        self.now[0]=datetime.fromisoformat("2030-01-15T10:20:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            store.add_result_observation(self.result(winner)["observation"])
            ledger=PrivateVariableLedger(store)
            first=ledger.audit_latest(RID,original["forecast"]["model_id"])
            self.assertTrue(first["research_hit"])
            missed=[7,6,5]
            if missed == winner:
                missed=[6,7,5]
            store.add_result_observation(
                self.result(missed,payout=9990,source="b",
                            at="2030-01-15T10:11:00+09:00")["observation"])
            # Older revision is counted neither twice nor after correction.
            self.assertFalse(ledger.aggregate()["latest_revision_reconciled"])
            self.assertEqual(ledger.aggregate()["settled_prediction_count"],0)
            second=ledger.audit_latest(RID,original["forecast"]["model_id"])
            self.assertFalse(second["research_hit"])
            self.assertEqual(second["result_revision"],2)
            self.assertEqual(second["reference_profit_yen"],-200)
            summary=ledger.aggregate()
            self.assertEqual(summary["settled_prediction_count"],1)
            self.assertEqual(summary["wins"],0)
            self.assertEqual(summary["reference_investment_yen"],200)
            self.assertEqual(summary["reference_profit_yen"],-200)
            self.assertEqual(summary["reference_roi"],0.0)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM variable_selection_audits").fetchone()[0],2)
            self.assertEqual(store.get_persisted_forecast(RID)["sha256"],
                             original["sha256"])

    def test_zero_pick_skip_and_pending_not_forced_loss(self):
        _,original,selection=self.begin(positive=0)
        self.assertEqual(selection["selection"]["pick_count"],0)
        self.now[0]=datetime.fromisoformat("2030-01-15T10:20:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            store.add_result_observation(
                self.result(None,at="2030-01-15T10:05:00+09:00",
                            status="PENDING",refund="UNKNOWN")["observation"])
            ledger=PrivateVariableLedger(store)
            pending=ledger.audit_latest(RID,original["forecast"]["model_id"])
            self.assertIsNone(pending["research_hit"])
            self.assertIsNone(pending["reference_payout_yen"])
            self.assertEqual(ledger.aggregate()["unresolved_or_refunded"],1)
            store.add_result_observation(
                self.result([1,2,3],at="2030-01-15T10:12:00+09:00",
                            source="b")["observation"])
            skipped=ledger.audit_latest(RID,original["forecast"]["model_id"])
            self.assertEqual(skipped["status"],"SETTLED_SKIPPED_RESEARCH")
            summary=ledger.aggregate()
            self.assertEqual(summary["skipped"],1)
            self.assertIsNone(summary["hit_rate"])
            self.assertIsNone(summary["reference_roi"])
            self.assertEqual(summary["reference_investment_yen"],0)

    def test_reconcile_all_owner_history_revisions_without_overwriting(self):
        _,original,selection=self.begin(positive=2)
        picked=selection["selection"]["tickets"][0]["triple"]
        missed=[7,6,5] if picked!=[7,6,5] else [6,7,5]
        self.now[0]=datetime.fromisoformat("2030-01-15T10:20:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            store.add_result_observation(self.result(
                picked,payout=690,source="a",
                at="2030-01-15T10:10:00+09:00")["observation"])
            store.add_result_observation(self.result(
                missed,payout=2200,source="b",
                at="2030-01-15T10:11:00+09:00")["observation"])
            ledger=PrivateVariableLedger(store)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM variable_selection_audits").fetchone()[0],0)
            first=ledger.reconcile_saved_history()
            self.assertEqual(first["replayed_result_revisions"],2)
            self.assertEqual(first["newly_reconciled_audit_rows"],2)
            self.assertTrue(first["saved_history_research_reconciled"])
            self.assertFalse(first["complete_official_race_coverage"])
            self.assertFalse(first["official_result_authenticity_verified"])
            self.assertIsNone(first["formal_return_rate"])
            self.assertEqual(first["reference_profit_yen"],-200)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM variable_selection_audits").fetchone()[0],2)
            again=ledger.reconcile_saved_history()
            self.assertEqual(again["newly_reconciled_audit_rows"],0)
            self.assertEqual(again["reference_profit_yen"],-200)
            self.assertEqual(store.get_persisted_forecast(RID)["sha256"],
                             original["sha256"])
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as reopened:
            report=PrivateVariableLedger(reopened).reconcile_saved_history()
            self.assertEqual(report["reference_profit_yen"],-200)
            self.assertEqual(report["newly_reconciled_audit_rows"],0)

    def test_reconcile_missing_original_odds_stays_reported(self):
        _,original,selection=self.begin(positive=None)
        self.assertIsNone(selection)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            report=PrivateVariableLedger(store).reconcile_saved_history()
            self.assertEqual(report["saved_variable_race_model_pairs"],0)
            self.assertEqual(report["originals_without_variable_sidecar"],1)
            self.assertFalse(report["saved_history_research_reconciled"])
            self.assertIsNone(report["formal_hit_rate"])

    def test_missing_odds_never_blocks_original_private_forecast(self):
        tick,original,selection=self.begin(positive=None)
        self.assertIsNotNone(original)
        self.assertIsNone(selection)
        self.assertEqual(tick["private_forecasts_saved_this_tick"],1)
        self.assertEqual(tick["variable_selections_saved_this_tick"],0)

    def test_mismatched_original_sha_and_altered_selection_rejected(self):
        _,original,selection=self.begin(positive=2)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            ledger=PrivateVariableLedger(store)
            with self.assertRaisesRegex(PrivateVariableBridgeError,"ORIGINAL"):
                ledger.freeze_once(selection["selection"],
                                   original_forecast_sha256="a"*64,
                                   odds_snapshot=self.odds())
            modified=deepcopy(selection["selection"])
            modified["tickets"][0]["reference_stake_yen"]=200
            # Tampered digest is not accepted even for matching race.
            with self.assertRaisesRegex(PrivateVariableBridgeError,"HASH"):
                ledger.freeze_once(modified,
                                   original_forecast_sha256=original["sha256"],
                                   odds_snapshot=self.odds())
            self.assertEqual(ledger.selection(
                RID,original["forecast"]["model_id"]),selection)

    def test_post_freeze_changed_odds_are_not_silently_accepted(self):
        _,original,selection=self.begin(positive=2)
        self.now[0]=datetime.fromisoformat("2030-01-15T09:25:00+09:00")
        changed=self.odds(positive=3)
        self.save("odds","second.json",changed)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            tick=self.agent(store).tick(self.inbox)
            self.assertEqual(
                tick["states"].get("VARIABLE_POST_FREEZE_ODDS_CONFLICT"),1)
            ledger=PrivateVariableLedger(store)
            saved=ledger.selection(RID,original["forecast"]["model_id"])
            self.assertEqual(saved,selection)
            self.assertEqual(ledger.odds_snapshot(
                selection["selection"]["odds_snapshot_sha256"]),self.odds(positive=2))
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM variable_odds_snapshots").fetchone()[0],1)

    def test_after_cutoff_new_odds_cannot_recreate_selection(self):
        tick,original,selection=self.begin(positive=None)
        self.assertIsNone(selection)
        self.save("odds","new.json",self.odds(positive=2))
        self.now[0]=datetime.fromisoformat("2030-01-15T10:20:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            x=self.agent(store).tick(self.inbox)
            self.assertEqual(x["states"]["VARIABLE_ODDS_TOO_LATE"],1)
            self.assertIsNone(PrivateVariableLedger(store).selection(
                RID,original["forecast"]["model_id"]))
            self.assertEqual(store.get_persisted_forecast(RID)["sha256"],
                             original["sha256"])

    def test_missing_odds_rows_reject_incomplete_market(self):
        self.save("pre","one.json",self.snapshot)
        odds=self.odds(positive=2)
        odds["prices"].pop()
        self.save("odds","bad.json",odds)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            x=self.agent(store).tick(self.inbox)
            self.assertEqual(x["states"]["VARIABLE_INCOMPLETE_ODDS"],1)
            self.assertIsNone(PrivateVariableLedger(store).selection(
                RID,"multisport-scenario-ensemble-v1"))
            self.assertIsNotNone(store.get_persisted_forecast(RID))


if __name__=="__main__":
    unittest.main()
