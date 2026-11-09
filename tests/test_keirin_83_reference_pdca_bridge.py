"""Synthetic 83R distribution: no real results, rider names or wagers."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
import unittest

from race_ai.keirin_83_reference_pdca_bridge import (
    SCHEMA, REPORT, EXPECTED_VENUES, ReferencePDCAError,
    reference_scoreboard, validate_frozen_manifest,
)


CREATED="2026-11-09T10:36:13.061726+09:00"
CODES={"青森":12,"弥彦":21,"宇都宮":24,"松戸":31,
       "奈良":53,"高知":74,"松山":75,"武雄":84}


def sample():
    rows=[]
    for venue,races in EXPECTED_VENUES.items():
        for no in range(1,races+1):
            early=venue=="青森" and no<=6
            start=("2026-11-09T09:00:00+09:00" if early else
                   "2026-11-09T13:00:00+09:00")
            rid=f"20261109{CODES[venue]:02d}{no:02d}"
            rows.append({
                "race_id":rid, "venue":venue, "race_no":no,
                "status_at_batch_creation":(
                    "ALREADY_STARTED_NO_NEW_FORECAST" if early else
                    "FUTURE_START_CUTOFF_NOT_VERIFIED_RESEARCH_ONLY"),
                "scheduled_start_at_jst":start,
                "official_cutoff_at_jst_verified":None,
                "pr71_models_executed":False,
                "original_4_model_output_not_claimed":True,
                "independent_source_published_at_pre_cutoff_verified":False,
                "generated_this_batch_ticket_count":0 if early else 4,
                "new_research_reference_tickets":None if early else
                    ["1-2-3","1-3-2","2-1-3","2-3-1"],
                "preexisting_separately_frozen_reference_tickets":
                    ["2-3-1"] if early else None,
            })
    x={"schema":SCHEMA,"created_at_jst":CREATED,
       "date_jst":"2026-11-09","race_count":83,
       "venue_count":8,"new_reference_forecast_count":77,
       "already_started_count":6,
       "pr71_4_model_formal_forecasts_count_this_batch":0,
       "new_reference_has_independent_third_party_pre_cutoff_witness":False,
       "all_future_deadline_times_independently_verified":False,
       "rows":rows}
    return x


def settlement(rid,winner,pay,*,status="FINAL_NORMAL",refund="NONE",
               observed="2026-11-09T15:40:00+09:00",
               tier="THIRD_PARTY_PUBLISHED"):
    return {
        "race_id":rid,"observed_at":observed,
        "source_url":"https://example.invalid/fictional-results",
        "source_tier":tier,
        "status":status,"refund_status":refund,
        "winning_triples":[list(winner)] if status=="FINAL_NORMAL" else [],
        "payouts_100yen":[{"triple":list(winner),"yen":pay}]
                            if status=="FINAL_NORMAL" else [],
        "official_organizer_independently_authenticated":False,
    }


class EightyThreeReferenceTests(unittest.TestCase):
    def raw(self,doc):
        return (json.dumps(doc,ensure_ascii=False,
                sort_keys=True)+"\n").encode("utf-8")

    def assert_raw(self,doc):
        raw=self.raw(doc)
        validate_frozen_manifest(doc,original_bytes=raw,
                                  original_file_sha256=sha256(raw).hexdigest())
        return raw

    def test_all_83_verifiable_without_premature_loss_or_fake_models(self):
        doc=sample()
        raw=self.assert_raw(doc)
        report=reference_scoreboard(doc,[],original_bytes=raw,
                          original_sha256=sha256(raw).hexdigest())
        self.assertEqual(report["race_count"],83)
        self.assertEqual(report["new_frozen_reference_candidates"],77)
        self.assertEqual(report["early_races_separate_reference_required"],6)
        self.assertEqual(report["state_counts"][
            "SEPARATELY_PRE_FROZEN_OR_UNPROVEN_EARLY_REFERENCE"],6)
        self.assertEqual(report["state_counts"]["RESULT_NOT_CHECKED"],77)
        self.assertEqual(report["reference_evaluable_published_results"],0)
        self.assertIsNone(report["reference_hit_rate"])
        self.assertIsNone(report["reference_roi"])
        self.assertIsNone(report["formal_Hit8"])
        self.assertEqual(report["paired_original_A_B_races_verified"],0)
        self.assertEqual(report["reference_investment_yen"],0)

    def test_existing_settlement_is_reused_for_three_reference_races(self):
        doc=sample()
        ids={r["venue"]+str(r["race_no"]):r["race_id"] for r in doc["rows"]}
        observations=[
            settlement(ids["弥彦1"],(6,1,3),1150),
            settlement(ids["高知1"],(1,2,7),5020),
            settlement(ids["武雄1"],(1,2,3),18700),
        ]
        a=reference_scoreboard(doc,observations)
        self.assertEqual(a["reference_evaluable_published_results"],3)
        self.assertEqual(a["reference_hits"],1)
        self.assertEqual(a["reference_misses"],2)
        self.assertEqual(a["reference_investment_yen"],1200)
        self.assertEqual(a["reference_payout_yen"],18700)
        self.assertEqual(a["reference_profit_yen"],17500)
        self.assertAlmostEqual(a["reference_roi"],18700/1200)
        self.assertEqual(a["reference_mansha_results_count"],1)
        self.assertEqual(a["reference_mansha_captured"],1)
        self.assertEqual(a["reference_mansha_capture_rate"],1.0)
        self.assertEqual(len(a["rows"]),83)
        self.assertIsNone(a["formal_Hit8"])
        self.assertFalse(a["organizer_result_revisions_independently_verified"])

    def test_early_user_picks_cannot_be_reused_as_batch_created(self):
        doc=sample()
        rid=next(r["race_id"] for r in doc["rows"] if r["venue"]=="青森")
        a=reference_scoreboard(doc,[settlement(rid,(2,3,1),2400)])
        self.assertEqual(a["state_counts"][
            "SEPARATELY_PRE_FROZEN_OR_UNPROVEN_EARLY_REFERENCE"],6)
        self.assertEqual(a["reference_evaluable_published_results"],0)
        self.assertEqual(a["reference_investment_yen"],0)
        self.assertIsNone(a["rows"][0]["reference_hit"])

    def test_unsettled_refund_does_not_create_loss_or_mansha(self):
        doc=sample()
        rid=next(r["race_id"] for r in doc["rows"]
                 if r["venue"]=="弥彦")
        a=reference_scoreboard(doc,[
            settlement(rid,(1,2,3),18700,status="PENDING",
                       refund="UNKNOWN")
        ])
        self.assertEqual(a["state_counts"]["UNSETTLED_OR_REFUND_UNVERIFIED"],1)
        self.assertIsNone(a["reference_roi"])
        self.assertEqual(a["reference_evaluable_published_results"],0)
        self.assertIsNone(next(r for r in a["rows"]
                              if r["race_id"]==rid)["reference_payout_yen"])

    def test_original_sha_tamper_result_duplicate_and_after_start(self):
        original=sample()
        raw=self.raw(original)
        with self.assertRaisesRegex(ReferencePDCAError,
                                    "PRIVATE_ORIGINAL_MANIFEST_SHA_MISMATCH"):
            reference_scoreboard(original,[],original_bytes=raw,
                                 original_sha256="0"*64)
        rid=next(r["race_id"] for r in original["rows"]
                 if r["venue"]=="弥彦")
        observation=settlement(rid,(1,2,3),1200)
        with self.assertRaisesRegex(ReferencePDCAError,
                                    "RESULT_DUPLICATE_OR_BAD_RACE_ID"):
            reference_scoreboard(original,[observation,deepcopy(observation)])
        invalid=settlement(rid,(1,2,3),1200,
                           observed="2026-11-09T12:00:00+09:00")
        with self.assertRaisesRegex(ReferencePDCAError,
                                    "RESULT_SNAPSHOT_ISSUED_BEFORE_RACE_START"):
            reference_scoreboard(original,[invalid])

    def test_backdated_betting_cutoff_witness_forgery_is_rejected(self):
        doc=sample()
        doc["all_future_deadline_times_independently_verified"]=True
        with self.assertRaisesRegex(ReferencePDCAError,
                                    "WRONG_OR_REWRITTEN_83R_RESEARCH_MANIFEST"):
            reference_scoreboard(doc,[])
        doc=sample()
        doc["rows"][6]["official_cutoff_at_jst_verified"] = (
            "2026-11-09T12:55:00+09:00")
        with self.assertRaisesRegex(ReferencePDCAError,
                                    "REFERENCE_IMPERSONATING_PR71_OR_CUTOFF"):
            reference_scoreboard(doc,[])

    def test_changed_research_bet_after_start_rejected(self):
        doc=sample()
        row=next(r for r in doc["rows"] if r["venue"]=="弥彦")
        row["new_research_reference_tickets"]=["1-2-3","1-2-3",
                                                "2-1-3","2-3-1"]
        with self.assertRaisesRegex(ReferencePDCAError,
                                    "DUPLICATE_REFERENCE_COMBINATION"):
            reference_scoreboard(doc,[])

    def test_model_tracks_are_never_merged_into_outsider_reference(self):
        doc=sample()
        report=reference_scoreboard(doc,[
            settlement(next(r["race_id"] for r in doc["rows"]
                            if r["venue"]=="武雄"),
                       (1,2,3),18700)
        ])
        self.assertIsNone(report["existing_PR71_four_model_formal_hits"])
        self.assertIsNone(report["distinct_B_four_model_formal_hits"])
        self.assertEqual(report["paired_original_A_B_races_verified"],0)
        self.assertFalse(report["source_first_published_at_before_cutoff_independently_verified"])


if __name__=="__main__":
    unittest.main()
