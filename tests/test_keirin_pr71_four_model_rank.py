"""Synthetic-only end-to-end tests of the four existing PR71 ranked models.

No historical result is used to generate a prediction. No public real source
or external timestamp witness is claimed by these tests.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import tempfile
import unittest

from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import (
    FourModelRankLedger, FourModelRankError,
    stage_existing_owner_pre_races,
)
from test_keirin_pr71_model_adapter import make_sources, RID


def moment(clock):
    return datetime.fromisoformat(clock)


class FourModelFullRankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbfile = Path(self.tmp.name) / "owner.sqlite3"
        self.now = [moment("2030-01-15T09:21:00+09:00")]
        self.clock = lambda: self.now[0]
        self.snapshot = make_sources()[0]

    def store(self):
        return PrivateKeirinStore(self.dbfile, clock=self.clock)

    def frozen(self, store):
        ledger = FourModelRankLedger(store)
        self.assertEqual(
            ledger.freeze_once(deepcopy(self.snapshot)),
            "FOUR_MODELS_FROZEN_ONCE")
        return ledger

    def settle(self, store, winner, *, pay=18700, source="a",
               stamp="2030-01-15T10:15:00+09:00", status="FINAL_NORMAL",
               refund="NONE"):
        self.now[0] = moment("2030-01-15T10:40:00+09:00")
        data = {
            "race_id": RID, "observed_at": stamp,
            "source_sha256": source * 64,
            "status": status, "refund_status": refund,
            "winning_triples": [winner] if status == "FINAL_NORMAL" else [],
            "payouts_100yen": [{"triple": winner, "yen": pay}]
                             if status == "FINAL_NORMAL" else [],
        }
        return store.add_result_observation(data)

    def test_all_four_models_full_210_and_readback_after_restart(self):
        with self.store() as store:
            ledger = self.frozen(store)
            report = ledger.read_suite(RID)
            self.assertEqual(tuple(report["suite"]["models"]), ALL_MODELS)
            self.assertEqual(report["suite"]["model_count"], 4)
            for model in report["suite"]["models"].values():
                self.assertEqual(model["candidate_count"], 210)
                self.assertEqual(len(model["candidates"]), 210)
                self.assertEqual(model["ordered_top8"],
                                 [c["combination"] for c in model["candidates"][:8]])
                self.assertFalse(model["calibrated"])
            self.assertEqual(
                ledger.freeze_once(deepcopy(self.snapshot)),
                "FOUR_MODELS_ALREADY_FROZEN_IDENTICAL")
        with self.store() as reopened:
            ledger = FourModelRankLedger(reopened)
            self.assertEqual(
                tuple(ledger.read_suite(RID)["suite"]["models"]),ALL_MODELS)
            self.assertEqual(ledger.replay_all()["races_missing_result"],1)
            self.assertEqual(reopened.db.execute(
                "SELECT COUNT(*) FROM forecasts").fetchone()[0],0)

    def test_nine_rider_universe_504_for_all_four_models(self):
        snap = deepcopy(self.snapshot)
        for number in (8,9):
            extra = deepcopy(snap["facts"]["pr71_evidenced_snapshot"][
                "participants"][number-8])
            extra["number"] = number
            extra["draw"] = number
            extra["identity"] = f"fictional-rider-{number}"
            extra["group_id"] = "fictional-line3"
            snap["facts"]["pr71_evidenced_snapshot"]["participants"].append(extra)
        snap["starters"] = list(range(1,10))
        with self.store() as store:
            FourModelRankLedger(store).freeze_once(snap)
            suite = FourModelRankLedger(store).read_suite(RID)["suite"]
            self.assertEqual({m["candidate_count"] for m in suite[
                "models"].values()}, {504})

    def test_mansha_rank_10_hits_top12_but_misses_top8(self):
        with self.store() as store:
            ledger = self.frozen(store)
            model_id = ALL_MODELS[0]
            winner = ledger.read_suite(RID)["suite"]["models"][model_id][
                "candidates"][9]["combination"]
            self.settle(store,winner,pay=18700)
            reports = ledger.audit_revision(RID)
            self.assertEqual(len(reports),4)
            one = reports[model_id]
            self.assertEqual(one["winning_tickets"][0][
                "pre_cutoff_model_rank"],10)
            self.assertFalse(one["modes"]["top8"]["hit"])
            self.assertTrue(one["modes"]["top12"]["hit"])
            self.assertEqual(one["modes"]["top12"]["investment_yen"],1200)
            self.assertEqual(one["modes"]["top12"]["payout_yen"],18700)
            self.assertEqual(one["modes"]["top12"]["profit_yen"],17500)
            self.assertEqual(one["modes"]["variable"]["state"],
                             "NO_PRE_CUTOFF_VARIABLE_SELECTION")
            self.assertFalse(one["independent_external_cutoff_receipt_verified"])
            self.assertFalse(one["official_result_independently_authenticated"])
            summary = ledger.replay_all()
            self.assertEqual(summary["ranked_forecast_races"],1)
            self.assertEqual(summary["latest_model_race_audits"],4)
            self.assertEqual(summary["models"][model_id][
                "mansha_rank_bands"],{"9-12":1})
            self.assertEqual(summary["models"][model_id]["modes"][
                "top12"]["mansha_races_captured"],1)
            self.assertEqual(summary["models"][model_id]["modes"][
                "variable"]["mansha_races_evaluable"],0)
            self.assertIsNone(summary["models"][model_id]["modes"][
                "variable"]["mansha_capture_rate"])
            self.assertEqual(ledger.audit_revision(RID),reports)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM keirin_pr71_four_model_rank_audits"
            ).fetchone()[0],4)

    def test_revised_payout_uses_latest_and_retains_old_audit(self):
        with self.store() as store:
            ledger = self.frozen(store)
            model_id = ALL_MODELS[0]
            candidate = ledger.read_suite(RID)["suite"]["models"][model_id][
                "candidates"]
            self.settle(store,candidate[0]["combination"],pay=12100)
            first = ledger.audit_revision(RID)[model_id]
            self.assertEqual(first["winning_tickets"][0][
                "pre_cutoff_model_rank"],1)
            self.settle(store,candidate[99]["combination"],pay=21500,
                        source="b",stamp="2030-01-15T10:20:00+09:00")
            second = ledger.audit_revision(RID)[model_id]
            self.assertEqual(second["result_revision"],2)
            self.assertEqual(second["winning_tickets"][0][
                "pre_cutoff_model_rank"],100)
            summary = ledger.replay_all()
            self.assertEqual(summary["models"][model_id][
                "mansha_rank_bands"],{"51-100":1})
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM keirin_pr71_four_model_rank_audits"
            ).fetchone()[0],8)
            self.assertEqual(ledger.read_suite(RID)["suite"]["models"][
                model_id]["ordered_top8"][0],candidate[0]["combination"])

    def test_pending_is_not_relabelled_as_loss(self):
        with self.store() as store:
            ledger=self.frozen(store)
            self.settle(store,[1,2,3],status="PENDING",refund="UNKNOWN")
            report=ledger.audit_revision(RID)
            self.assertEqual(report[ALL_MODELS[0]]["result_status"],"UNSETTLED")
            self.assertIsNone(report[ALL_MODELS[0]]["modes"]["top8"]["hit"])
            self.assertEqual(ledger.replay_all()["models"][
                ALL_MODELS[0]]["settled_races"],0)

    def test_bad_source_or_after_cutoff_cannot_create_prediction(self):
        source=deepcopy(self.snapshot)
        source["facts"]["pr71_evidenced_snapshot"]["scope"]=(
            "OPERATOR_SUPPLIED_RESEARCH")
        with self.store() as store:
            ledger=FourModelRankLedger(store)
            with self.assertRaises(ValueError):
                ledger.freeze_once(source,source_admission=lambda *args:True)
            self.assertIsNone(ledger.read_suite(RID))
        self.now[0]=moment("2030-01-15T10:00:00+09:00")
        with self.store() as store:
            with self.assertRaisesRegex(FourModelRankError,"NOT_BEFORE_CUTOFF"):
                FourModelRankLedger(store).freeze_once(self.snapshot)
            self.assertIsNone(FourModelRankLedger(store).read_suite(RID))

    def test_private_blob_tamper_fails_closed(self):
        with self.store() as store:
            ledger=self.frozen(store)
            store.db.execute(
                "UPDATE keirin_pr71_four_model_suites "
                "SET suite_payload=? WHERE race_id=?",(b"{}",RID))
            with self.assertRaisesRegex(FourModelRankError,
                                        "PR71_PRIVATE_SOURCE_OR_MODEL_TAMPER"):
                ledger.read_suite(RID)

    def test_owner_local_pre_inbox_used_without_web_and_no_real_claim(self):
        root=Path(self.tmp.name)
        (root/"pre").mkdir()
        (root/"pre"/"future.json").write_text(
            json.dumps(self.snapshot,ensure_ascii=False),
            encoding="utf-8")
        with self.store() as store:
            report=stage_existing_owner_pre_races(root,store)
            self.assertEqual(report["private_four_model_predictions_saved"],1)
            self.assertEqual(report["provider_network_requests"],0)
            self.assertFalse(report["external_receipt_issued"])
            self.assertIsNotNone(FourModelRankLedger(store).read_suite(RID))


if __name__=="__main__":
    unittest.main()
