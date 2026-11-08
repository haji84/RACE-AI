"""PR101 real-shaped owner source -> PR103 same-race A/B, synthetic only.

No actual rider identity, source feed, official payout or independent timestamp.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import tempfile
import unittest

from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_private_spool import KeirinPrivateSpool
from race_ai.keirin_real_shadow_intake import stage_sourced_shadows
from race_ai.keirin_shadow_variable_pair import (
    ShadowVariablePairLedger, ShadowPairError
)
from race_ai.keirin_shadow_variable_intake import stage_shadow_variable_pairs
from race_ai.keirin_variable_selection import ODDS_SCHEMA
from race_ai.keirin_owner_manual import PERSONAL_MARKER
from test_keirin_real_rider_shadow import (
    fixture, grants, RID, ISSUED
)

NOW = "2030-01-15T09:23:00+09:00"
CUTOFF = "2030-01-15T10:00:00+09:00"


class OwnerRealShadowVariableResearchTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.dbpath=self.root/"owner.sqlite3"
        (self.root/"raw").mkdir()
        (self.root/"odds").mkdir()
        self.clocktime=[datetime.fromisoformat(NOW)]
        self.clock=lambda:self.clocktime[0]
        self.original_packet=fixture()
        self.grant=grants().allowed

    def raw(self, packet=None):
        data=self.original_packet if packet is None else packet
        (self.root/"raw"/"one.json").write_text(
            json.dumps(data,ensure_ascii=False,sort_keys=True),
            encoding="utf-8")

    def original(self):
        self.raw()
        state=stage_sourced_shadows(
            self.root,grant_check=self.grant,now=ISSUED)
        self.assertEqual(state["counts"].get(
            "private_shadow_research_saved"),1,state)
        saved=list((self.root/"shadow_pre").glob("*.json"))
        self.assertEqual(len(saved),1)
        shadow=json.loads(saved[0].read_text(encoding="utf-8"))
        self.assertEqual(shadow["candidate_count"],210)
        self.assertEqual(
            len(shadow["ranked_candidates_untrained_not_probabilities"]),210)
        self.assertFalse(shadow["probabilities_calibrated"])
        self.assertFalse(shadow["full_pr71_model_ran"])
        return shadow

    def odds(self, shadow, *, positive=2, bad=None):
        rows=[]
        for i,row in enumerate(
                shadow["ranked_candidates_untrained_not_probabilities"]):
            p=row["relative_score"]
            rows.append({
                "triple":row["triple"],
                "decimal_odds":(1.6 if i<positive else 0.7)/p,
            })
        if bad=="missing":
            rows.pop()
        if bad=="duplicate":
            rows[1]=deepcopy(rows[0])
        if bad=="nan":
            rows[0]["decimal_odds"]=float("nan")
        d={"schema":ODDS_SCHEMA,"race_id":RID,
           "captured_at":"2030-01-15T09:22:00+09:00",
           "source_ref":"https://example.invalid/fictional-odds",
           "source_rights_ref":PERSONAL_MARKER,
           "prices":rows}
        (self.root/"odds"/"one.json").write_text(
            json.dumps(d,ensure_ascii=False,sort_keys=True),
            encoding="utf-8")
        return d

    def dual(self, *, positive=2):
        shadow=self.original()
        odds=self.odds(shadow,positive=positive)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            report=stage_shadow_variable_pairs(
                self.root,store,grant_check=self.grant,now=NOW)
            pair=ShadowVariablePairLedger(store).read_pair(RID)
        return shadow,odds,report,pair

    def result(self,winning,paid=2600,stamp="a",time="2030-01-15T10:10:00+09:00",
               status="FINAL_NORMAL",refund="NONE"):
        return {"race_id":RID,
            "observed_at":time,"source_sha256":stamp*64,
            "status":status,"refund_status":refund,
            "winning_triples":[winning] if winning else [],
            "payouts_100yen":[{"triple":winning,"yen":paid}]
                if winning else []}

    def test_one_future_race_two_stored_versions_bound_to_source_and_odds(self):
        shadow,odds,report,pair=self.dual(positive=2)
        self.assertEqual(report["states"].get(
            "dual_prospective_forecasts_saved"),1)
        self.assertEqual(report["saved_dual_pairs_total"],1)
        self.assertIsNotNone(pair)
        self.assertEqual(pair["shadow"]["ordered_top8"],
                         shadow["ordered_top8"])
        self.assertEqual(pair["variable"]["pick_count"],2)
        self.assertEqual(pair["variable"]["reference_investment_yen"],200)
        self.assertEqual(pair["variable"]["limit"],12)
        self.assertEqual(pair["variable"]["source_packet_sha256"],
                         pair["shadow"]["input_sha256"])
        self.assertEqual(pair["variable"]["original_shadow_sha256"],
                         shadow["research_sha256"])
        self.assertEqual(pair["variable"]["odds_sha256"],
                         __import__("race_ai.keirin_shadow_variable_pair",
                             fromlist=["fingerprint"]).fingerprint(odds))
        self.assertFalse(pair["variable"]["actual_expected_value_calculated"])
        self.assertFalse(report["independent_pre_cutoff_timestamp_verified"])
        self.assertEqual(report["provider_network_requests"],0)
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as reopened:
            ledger=ShadowVariablePairLedger(reopened)
            self.assertEqual(ledger.read_pair(RID),pair)
            self.assertEqual(reopened.db.execute(
                "SELECT COUNT(*) FROM forecasts").fetchone()[0],0)
            self.assertEqual(reopened.db.execute(
                "SELECT COUNT(*) FROM keirin_shadow_variable_pairs"
            ).fetchone()[0],1)
            second=stage_shadow_variable_pairs(
                self.root,reopened,grant_check=self.grant,now=NOW)
            self.assertEqual(second["states"].get("already_frozen_identical"),1)
            self.assertEqual(reopened.db.execute(
                "SELECT COUNT(*) FROM keirin_shadow_variable_pairs"
            ).fetchone()[0],1)

    def test_result_revisions_replay_and_research_roi_only(self):
        _,_,_,pair=self.dual(positive=2)
        winner=pair["variable"]["tickets"][0]["triple"]
        self.clocktime[0]=datetime.fromisoformat("2030-01-15T10:20:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            first=store.add_result_observation(self.result(winner,paid=2600))
            self.assertEqual(first["revision"],1)
            ledger=ShadowVariablePairLedger(store)
            report1=ledger.replay_all()
            self.assertEqual(report1["settled_compared_races"],1)
            self.assertEqual(report1["variable_profit_yen"],2400)
            self.assertFalse(report1["model_probabilities_calibrated"])
            self.assertIsNone(report1["formal_roi"])
            miss=[7,6,5] if winner!=[7,6,5] else [6,7,5]
            second=store.add_result_observation(
                self.result(miss,paid=1300,stamp="b",
                            time="2030-01-15T10:11:00+09:00"))
            self.assertEqual(second["revision"],2)
            report2=ledger.replay_all()
            self.assertEqual(report2["replayed_result_revisions"],2)
            self.assertEqual(report2["settled_compared_races"],1)
            self.assertEqual(report2["variable_profit_yen"],-200)
            self.assertEqual(report2["variable_roi"],0.0)
            self.assertEqual(report2["fixed8_investment_yen"],800)
            self.assertEqual(report2["fixed8_profit_yen"],-800)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM keirin_shadow_variable_audits"
            ).fetchone()[0],2)
            replay=ledger.replay_all()
            self.assertEqual(replay["variable_profit_yen"],-200)
            self.assertEqual(replay["replayed_result_revisions"],2)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM keirin_shadow_variable_audits"
            ).fetchone()[0],2)
            self.assertEqual(ledger.read_pair(RID),pair)

    def test_no_odds_still_freezes_original_eight_but_no_pair(self):
        shadow=self.original()
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            report=stage_shadow_variable_pairs(
                self.root,store,grant_check=self.grant,now=NOW)
            self.assertEqual(report["saved_dual_pairs_total"],0)
            self.assertIsNone(ShadowVariablePairLedger(store).read_pair(RID))
        self.assertEqual(len(shadow["ordered_top8"]),8)

    def test_real_source_critical_missing_never_promotes_to_pair(self):
        packet=fixture()
        packet["observations"]=[
            row for row in packet["observations"]
            if row["key"]!="rider/3/race_score"]
        self.raw(packet)
        report=stage_sourced_shadows(
            self.root,grant_check=self.grant,now=ISSUED)
        self.assertEqual(report["counts"].get(
            "real_input_missing_or_after_cutoff"),1)
        self.assertEqual(list((self.root/"shadow_pre").glob("*.json")),[])
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            report=stage_shadow_variable_pairs(
                self.root,store,grant_check=self.grant,now=NOW)
            self.assertEqual(report["saved_dual_pairs_total"],0)

    def test_missing_duplicate_nan_odds_block_without_side_effects(self):
        shadow=self.original()
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            for form in ("missing","duplicate","nan"):
                self.odds(shadow,bad=form)
                report=stage_shadow_variable_pairs(
                    self.root,store,grant_check=self.grant,now=NOW)
                self.assertEqual(report["saved_dual_pairs_total"],0)
                self.assertGreater(sum(report["states"].values()),0)
            self.assertIsNone(ShadowVariablePairLedger(store).read_pair(RID))

    def test_after_cutoff_backdating_refused(self):
        shadow=self.original()
        self.odds(shadow)
        self.clocktime[0]=datetime.fromisoformat("2030-01-15T10:01:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            report=stage_shadow_variable_pairs(
                self.root,store,grant_check=self.grant,
                now="2030-01-15T10:01:00+09:00")
            self.assertEqual(report["states"]["missed_official_cutoff"],1)
            self.assertIsNone(ShadowVariablePairLedger(store).read_pair(RID))

    def test_unauthorized_odds_host_rejected(self):
        shadow=self.original()
        d=self.odds(shadow)
        d["source_ref"]="https://keirin.kdreams.jp/not-allowed"
        (self.root/"odds"/"one.json").write_text(
            json.dumps(d,ensure_ascii=False),encoding="utf-8")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            report=stage_shadow_variable_pairs(
                self.root,store,grant_check=self.grant,now=NOW)
            self.assertEqual(report["saved_dual_pairs_total"],0)
            self.assertEqual(report["states"]["source_odds_or_pair_rejected"],1)

    def test_post_freeze_odds_edit_does_not_rewrite_either_prediction(self):
        _,_,_,pair=self.dual()
        file=self.root/"odds"/"one.json"
        d=json.loads(file.read_text())
        d["prices"][0]["decimal_odds"]*=1.5
        file.write_text(json.dumps(d,ensure_ascii=False),encoding="utf-8")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            report=stage_shadow_variable_pairs(
                self.root,store,grant_check=self.grant,now=NOW)
            self.assertEqual(report["states"][
                "post_freeze_source_or_odds_conflict"],1)
            self.assertEqual(ShadowVariablePairLedger(store).read_pair(RID),pair)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM keirin_shadow_variable_pairs"
            ).fetchone()[0],1)

    def test_existing_results_inbox_creates_separate_shadow_variable_audit(self):
        _,_,_,pair=self.dual(positive=2)
        result=self.result(pair["variable"]["tickets"][0]["triple"],
                           paid=2180)
        (self.root/"results").mkdir()
        (self.root/"results"/"finish.json").write_text(
            json.dumps({
                "schema":"RACE_AI_PRIVATE_KEIRIN_RESULT_OBSERVATION_V1",
                "observation":result
            },sort_keys=True),encoding="utf-8")
        self.clocktime[0]=datetime.fromisoformat("2030-01-15T10:20:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            # The existing intake handles results once. It need not invent a
            # PR71 forecast when only a PR101 partial shadow exists.
            spool=KeirinPrivateSpool(store,clock=self.clock)
            tick=spool.tick(self.root)
            self.assertEqual(
                tick["states"].get("RESULT_SAVED_FORECAST_OR_SETTLEMENT_MISSING"),1)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM result_revisions").fetchone()[0],1)
            dual=stage_shadow_variable_pairs(
                self.root,store,grant_check=self.grant,
                now="2030-01-15T10:20:00+09:00")
            self.assertEqual(dual["reference_comparisons_settled"],1)
            ledger=ShadowVariablePairLedger(store)
            summary=ledger.replay_all()
            self.assertEqual(summary["variable_profit_yen"],1980)
            self.assertEqual(summary["variable_investment_yen"],200)
            self.assertFalse(summary["full_official_source_coverage_verified"])
            self.assertIsNone(summary["formal_roi"])
            self.assertEqual(ledger.read_pair(RID),pair)

    def test_pending_refund_not_loss_and_zero_variable_skip(self):
        _,_,_,pair=self.dual(positive=0)
        self.assertEqual(pair["variable"]["pick_count"],0)
        self.clocktime[0]=datetime.fromisoformat("2030-01-15T10:20:00+09:00")
        with PrivateKeirinStore(self.dbpath,clock=self.clock) as store:
            store.add_result_observation(
                self.result(None,status="PENDING",refund="UNKNOWN"))
            ledger=ShadowVariablePairLedger(store)
            pending=ledger.audit_revision(RID)
            self.assertEqual(pending["status"],"PENDING_OR_REFUND")
            self.assertIsNone(pending["fixed8_payout_yen"])
            self.assertIsNone(pending["variable_profit_yen"])
            store.add_result_observation(
                self.result([1,2,3],stamp="b",
                            time="2030-01-15T10:11:00+09:00"))
            settled=ledger.replay_all()
            self.assertEqual(settled["settled_compared_races"],1)
            self.assertIsNone(settled["variable_roi"])
            self.assertEqual(settled["variable_investment_yen"],0)
            self.assertEqual(settled["variable_profit_yen"],0)
            self.assertIsNone(settled["variable_reference_hit_rate"])


if __name__=="__main__":
    unittest.main()
