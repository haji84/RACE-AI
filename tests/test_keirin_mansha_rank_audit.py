"""Synthetic-only immutable full-ranking/万車券 research audit tests."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_real_rider_shadow import forecast_from_real_observations
from race_ai.keirin_shadow_variable_pair import (
    ShadowVariablePairLedger, choose_shadow_variable, ShadowPairError)
from race_ai.keirin_mansha_rank_audit import KeirinManshaRankLedger
from race_ai.keirin_variable_selection import ODDS_SCHEMA
from race_ai.keirin_owner_manual import PERSONAL_MARKER
from test_keirin_real_rider_shadow import fixture, grants, RID, ISSUED

NOW = "2030-01-15T09:23:00+09:00"


def pair_fixture(positive=2):
    raw = fixture()
    shadow = forecast_from_real_observations(
        raw, grant_check=grants().allowed, issued_at=ISSUED)
    odds = {"schema": ODDS_SCHEMA, "race_id": RID,
            "captured_at": "2030-01-15T09:22:00+09:00",
            "source_ref": "https://example.invalid/fictional-odds",
            "source_rights_ref": PERSONAL_MARKER,
            "prices": [{"triple": r["triple"],
                        "decimal_odds": (1.6 if i < positive else .7) /
                                         r["relative_score"]}
                       for i, r in enumerate(
                           shadow["ranked_candidates_untrained_not_probabilities"])]}
    selected = choose_shadow_variable(
        shadow, odds, decided_at=NOW, odds_allowed=lambda *a: True)
    return raw, shadow, odds, selected


def observed(ticket=None, pay=15600, status="FINAL_NORMAL",
             refund="NONE", sha_char="a"):
    return {"race_id": RID, "observed_at": "2030-01-15T10:10:00+09:00",
            "source_sha256": sha_char*64, "status": status,
            "refund_status": refund,
            "winning_triples": [ticket] if ticket else [],
            "payouts_100yen": [{"triple": ticket, "yen": pay}]
                                 if ticket else []}


class ManshaRankResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"private.sqlite3"
        self.clock = lambda: datetime.fromisoformat(NOW)

    def freeze(self, store, positive=2):
        raw, shadow, odds, selected = pair_fixture(positive)
        ledger = ShadowVariablePairLedger(store)
        self.assertEqual(ledger.freeze_pair_once(
            shadow, selected, odds, source_packet=raw), "CREATED_PAIR_ONCE")
        result = ledger.read_pair(RID)
        self.assertTrue(result["input_snapshot_frozen"])
        self.assertEqual(result["shadow"]["candidate_count"], 210)
        return result

    def test_rank10_mansha_fixed8_miss_top12_hit(self):
        with PrivateKeirinStore(self.path, clock=self.clock) as db:
            pair = self.freeze(db)
            winner = pair["shadow"][
                "ranked_candidates_untrained_not_probabilities"][9]["triple"]
            db.add_result_observation(observed(winner))
            rank = KeirinManshaRankLedger(db)
            audit = rank.audit_revision(RID)
            self.assertEqual(audit["winners"][0]["pre_cutoff_model_rank"], 10)
            self.assertTrue(audit["winners"][0]["is_mansha"])
            self.assertFalse(audit["modes"]["top8"]["hit"])
            self.assertTrue(audit["modes"]["top12"]["hit"])
            self.assertEqual(audit["modes"]["top12"]["payout_yen"], 15600)
            self.assertEqual(audit["modes"]["top12"]["profit_yen"], 14400)
            summary = ShadowVariablePairLedger(db).replay_all()[
                "mansha_ranking_reference"]
            self.assertEqual(summary["mansha_rank_bands"], {"09-12": 1})
            self.assertEqual(summary["modes"]["top12"][
                "mansha_races_captured"], 1)
            self.assertEqual(summary["modes"]["top8"][
                "mansha_races_captured"], 0)
            self.assertEqual(rank.audit_revision(RID), audit)
            self.assertEqual(db.db.execute(
                "SELECT COUNT(*) FROM keirin_mansha_rank_audits"
            ).fetchone()[0], 1)

    def test_result_revision_keeps_original_and_latest_aggregate_only(self):
        with PrivateKeirinStore(self.path, clock=self.clock) as db:
            before = self.freeze(db)
            ranked = before["shadow"][
                "ranked_candidates_untrained_not_probabilities"]
            db.add_result_observation(observed(
                ranked[0]["triple"], pay=12000))
            rank = KeirinManshaRankLedger(db)
            first = rank.audit_revision(RID)
            self.assertEqual(first["winners"][0]["pre_cutoff_model_rank"], 1)
            db.add_result_observation(observed(
                ranked[15]["triple"], pay=21000, sha_char="b"))
            second = rank.audit_revision(RID)
            self.assertEqual(second["winners"][0]["pre_cutoff_model_rank"], 16)
            self.assertEqual(second["result_revision"], 2)
            summary = rank.replay_all()
            self.assertEqual(summary["mansha_winning_tickets"], 1)
            self.assertEqual(summary["mansha_rank_bands"], {"13-24": 1})
            self.assertEqual(summary["modes"]["top8"]["hits"], 0)
            self.assertEqual(db.db.execute(
                "SELECT COUNT(*) FROM keirin_mansha_rank_audits"
            ).fetchone()[0], 2)
            self.assertEqual(ShadowVariablePairLedger(db).read_pair(RID),
                             before)

    def test_pending_not_loss_and_pre_decided_skip_not_hit(self):
        with PrivateKeirinStore(self.path, clock=self.clock) as db:
            pair = self.freeze(db, positive=0)
            self.assertEqual(pair["variable"]["pick_count"], 0)
            db.add_result_observation(observed(
                status="PENDING", refund="UNKNOWN"))
            rank = KeirinManshaRankLedger(db)
            pending = rank.audit_revision(RID)
            self.assertEqual(pending["status"], "UNSETTLED")
            self.assertIsNone(pending["modes"]["top8"]["hit"])
            self.assertIsNone(pending["modes"]["top8"]["profit_yen"])
            winner = pair["shadow"][
                "ranked_candidates_untrained_not_probabilities"][100]["triple"]
            db.add_result_observation(observed(
                winner, pay=25000, sha_char="b"))
            summary = rank.replay_all()
            self.assertEqual(summary["mansha_races"], 1)
            self.assertEqual(summary["modes"]["variable"]["active_races"], 0)
            self.assertEqual(summary["modes"]["variable"]["skipped_races"], 1)
            self.assertIsNone(summary["modes"]["variable"]["reference_roi"])
            self.assertEqual(summary["mansha_rank_bands"], {"101+": 1})

    def test_private_original_input_tampering_fails_closed(self):
        with PrivateKeirinStore(self.path, clock=self.clock) as db:
            self.freeze(db)
            db.db.execute(
                "UPDATE keirin_shadow_source_inputs SET source_payload=? "
                "WHERE race_id=?", (b'{"changed":true}', RID))
            with self.assertRaisesRegex(
                ShadowPairError, "PRIVATE_SOURCE_HASH_MISMATCH"):
                ShadowVariablePairLedger(db).read_pair(RID)


if __name__ == "__main__":
    unittest.main()
