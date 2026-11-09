"""Strict 78-race and real PR71 four-algorithm reconciliation regressions.

Fictional competitors ONLY; tests never score real 2026 races as hits.
"""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import unittest

from scripts.keirin_day_four_model_audit import (
    MODELS, DayAuditError, audit_day, load_cohort, public_summary
)
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from test_keirin_pr71_model_adapter import RID, make_sources

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"docs/evidence/2026-11-10/keirin_78r_source_only_cohort.json"


def minimal_test_day():
    return {
        "schema":"RACE_AI_KEIRIN_20261110_78R_SOURCE_ONLY_COHORT_V1",
        "event_day_jst":"2030-01-15","scheduled_venues":2,
        "scheduled_races":2,"expected_model_race_pairs":8,
        "model_ids":list(MODELS),
        "venue_counts":{"fictional":1,"other":1},
        "races":[
            {"race_id":RID,"venue":"fictional","race_no":1,
             "venue_code":"00","prediction_expected_models":4},
            {"race_id":"unseen","venue":"other","race_no":1,
             "venue_code":"01","prediction_expected_models":4},
        ],
    }


class All78FourModelsAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=self.root/"private.sqlite3"
        self.clock=[datetime.fromisoformat("2030-01-15T09:21:00+09:00")]

    def freeze(self):
        with PrivateKeirinStore(self.db,clock=lambda:self.clock[0]) as store:
            ledger=FourModelRankLedger(store)
            self.assertEqual(ledger.freeze_once(copy.deepcopy(make_sources()[0])),
                             "FOUR_MODELS_FROZEN_ONCE")
            return ledger.read_suite(RID)

    def test_entire_20261110_78_race_manifest_no_fabricated_outcomes(self):
        cohort=load_cohort(MANIFEST)
        self.assertEqual(cohort["scheduled_races"],78)
        self.assertEqual(cohort["scheduled_venues"],8)
        self.assertEqual(cohort["expected_model_race_pairs"],312)
        self.assertEqual(len(set(r["race_id"] for r in cohort["races"])),78)
        self.assertEqual(tuple(cohort["model_ids"]),MODELS)
        r=audit_day(cohort)
        self.assertEqual(r["frozen_four_model_races"],0)
        self.assertEqual(r["missing_four_model_original_races"],78)
        self.assertEqual(r["model_race_pairs_missing"],312)
        self.assertEqual(r["formally_authenticated_model_race_scores"],0)
        self.assertEqual(len(r["races"]),78)
        self.assertTrue(all(
            all(entry["models"][mid]["top8"] is None and
                entry["models"][mid]["top12"] is None and
                entry["models"][mid]["variable_0_to_12"] is None
                for mid in MODELS) for entry in r["races"]))
        self.assertIsNone(r["models"][MODELS[0]]["modes"]["top8"]["hit_rate"])
        self.assertIsNone(r["models"][MODELS[0]]["modes"]["top8"]["reference_roi"])
        safe=public_summary(r)
        self.assertNotIn("races",safe)
        self.assertNotIn("original_source_sha256",json.dumps(safe))
        self.assertNotIn('"top8": [',json.dumps(safe))

    def test_actual_four_distinct_model_algorithms_top8_top12_and_readback(self):
        old=self.freeze()
        result=audit_day(minimal_test_day(),self.db,include_private=True)
        self.assertEqual(result["frozen_four_model_races"],1)
        self.assertEqual(result["missing_four_model_original_races"],1)
        self.assertEqual(result["frozen_model_race_pairs"],4)
        self.assertEqual(result["model_race_pairs_missing"],4)
        first=result["races"][0]
        self.assertEqual(tuple(first["models"]),MODELS)
        ids=set()
        for mid,model in first["models"].items():
            self.assertEqual(model["state"],"MODEL_ORIGINAL_FROZEN")
            self.assertEqual(len(model["top8"]),8)
            self.assertEqual(len(model["top12"]),12)
            self.assertEqual(model["top8"],model["top12"][:8])
            self.assertIsNone(model["variable_0_to_12"])
            self.assertFalse(model["variable_frozen"])
            self.assertEqual(model["result_state"],"PENDING")
            ids.add(model["model_prediction_sha256"])
        self.assertEqual(len(ids),4)
        self.assertEqual(first["suite_sha256"],old["suite"]["suite_sha256"])
        self.assertEqual(first["result_state"],"NO_RESULT_REVISION")
        self.assertEqual(result["models"][MODELS[0]]["result_pending_races"],1)
        self.assertEqual(result["models"][MODELS[0]]["variable_unselected_races"],1)

    def test_existing_result_engine_scores_only_saved_pre_cutoff_race(self):
        original=self.freeze()
        winning=original["suite"]["models"][MODELS[0]]["ordered_top8"][0]
        self.clock[0]=datetime.fromisoformat("2030-01-15T10:40:00+09:00")
        with PrivateKeirinStore(self.db,clock=lambda:self.clock[0]) as store:
            store.add_result_observation({
                "race_id":RID,"observed_at":"2030-01-15T10:15:00+09:00",
                "source_sha256":"e"*64,"status":"FINAL_NORMAL",
                "refund_status":"NONE","winning_triples":[winning],
                "payouts_100yen":[{"triple":winning,"yen":18700}],
            })
        result=audit_day(minimal_test_day(),self.db)
        self.assertEqual(result["settled_research_races"],1)
        self.assertEqual(result["formally_authenticated_model_race_scores"],0)
        a=result["models"][MODELS[0]]["modes"]
        self.assertEqual(a["top8"]["active_races"],1)
        self.assertEqual(a["top8"]["hit_races"],1)
        self.assertEqual(a["top8"]["reference_stake_yen"],800)
        self.assertEqual(a["top8"]["reference_paid_yen"],18700)
        self.assertAlmostEqual(a["top8"]["reference_roi"],18700/800)
        self.assertEqual(a["top8"]["mansha_races_evaluable"],1)
        self.assertEqual(a["top8"]["mansha_races_captured"],1)
        self.assertEqual(a["top12"]["reference_stake_yen"],1200)
        self.assertEqual(a["variable"]["active_races"],0)
        self.assertIsNone(a["variable"]["reference_roi"])
        self.assertEqual(result["models"][MODELS[0]]["variable_unselected_races"],1)
        self.assertEqual(result["races"][1]["result_state"],
                         "NOT_EVALUABLE_NO_ORIGINAL")

    def test_bad_cohort_duplicate_fails_before_scoring(self):
        orig=load_cohort(MANIFEST)
        bad=copy.deepcopy(orig)
        bad["races"][1]["race_id"]=bad["races"][0]["race_id"]
        p=self.root/"tampered.json"
        p.write_text(json.dumps(bad),encoding="utf-8")
        with self.assertRaisesRegex(DayAuditError,
                                     "COHORT_DUPLICATED_OR_UNGROUNDED_RACE_ID"):
            load_cohort(p)

    def test_nonexistent_db_cannot_be_created_as_fake_production(self):
        with self.assertRaisesRegex(DayAuditError,
                                     "PREEXISTING_PRIVATE_SQLITE_REQUIRED"):
            audit_day(minimal_test_day(),self.db)
        self.assertFalse(self.db.exists())


if __name__=="__main__":
    unittest.main()
