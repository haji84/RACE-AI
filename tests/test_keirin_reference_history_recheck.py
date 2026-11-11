"""Entirely fictional 2030 rows for derived-history cross-file research tests."""
from __future__ import annotations

from copy import deepcopy
import unittest

from race_ai.keirin_reference_history_recheck import (
    SCHEMAS, HistoryRecheckError, recheck_derived_references
)


def fictional():
    rows=[
        ("203001153601",["1-2-3","1-3-2","2-1-3","2-3-1",
                        "3-1-2","3-2-1","4-1-2","4-2-1"],"1-2-3",900),
        ("203001153602",["2-1-3","2-3-1","3-1-2","3-2-1",
                        "1-2-3","1-3-2","1-2-4","1-4-2"],"5-2-1",3000),
    ]
    a=[];b=[];c=[]
    for rid,picks,win,dividend in rows:
        hit=int(win in picks)
        a.append({
            "race_id":rid,"A_top8_unmodified":picks,
            "third_party_published_order":win,
            "three_trifecta_payout_jpy_per_100_yen":dividend,
            "A_research_hit8":hit,
            "official_final_organizer_verified":False,
            "independent_external_timestamp_receipt_verified":False,
        })
        b.append({
            "race_id":rid,"baseline_top8":picks,
            "published_trifecta":win,
            "published_payout_jpy_per_100":dividend,
            "hit8_reference_only":hit,
            "official_revisions_refunds_cancelations_checked":False,
            "independent_predeadline_receipt_verified":False,
        })
        c.append({
            "race_id":rid,"top8_reference_unchanged":picks,
            "published_result_3rentan":win,
            "payout_per_100_yen":dividend,
            "research_hit_at8":hit,
            "organizer_official_result_independently_verified":False,
            "independently_issued_pre_cutoff_freeze_proof_available":False,
        })
    return (
        {"schema":SCHEMAS[0],
         "reference_20261103":{
             "all_76_reference_A_from_prior_audit_unmodified":a}},
        {"schema":SCHEMAS[1],"nov03":{"rows":b}},
        {"schema":SCHEMAS[2],
         "nov03_reference_comparisons_readonly":c},
    )


class DerivedHistoryTests(unittest.TestCase):
    def test_two_derived_races_reference_roi_no_formal_claim(self):
        result=recheck_derived_references(*fictional())
        self.assertEqual(result["matched_derived_records"],2)
        self.assertEqual(result["reference_hits"],1)
        self.assertEqual(result["reference_investment_yen"],1600)
        self.assertEqual(result["reference_payout_yen"],900)
        self.assertEqual(result["reference_profit_yen"],-700)
        self.assertAlmostEqual(result["reference_roi"],900/1600)
        self.assertEqual(result["selection_only_miss_counts"],
                         {"hit":1,"winner_absent":1})
        self.assertIsNone(result["formal_hit_rate"])
        self.assertIsNone(result["formal_return_rate"])
        self.assertFalse(result["valid_for_model_promotion"])

    def test_changed_payout_blocks_cross_file_match(self):
        a,b,c=fictional()
        b["nov03"]["rows"][0]["published_payout_jpy_per_100"]=910
        with self.assertRaisesRegex(HistoryRecheckError,"DISAGREE"):
            recheck_derived_references(a,b,c)

    def test_changed_tickets_block_cross_file_match(self):
        a,b,c=fictional()
        c["nov03_reference_comparisons_readonly"][0][
            "top8_reference_unchanged"][0]="5-2-1"
        with self.assertRaises(HistoryRecheckError):
            recheck_derived_references(a,b,c)

    def test_duplicate_missing_and_invalid_race_rejected(self):
        a,b,c=fictional()
        a["reference_20261103"][
            "all_76_reference_A_from_prior_audit_unmodified"].append(
            deepcopy(a["reference_20261103"][
                "all_76_reference_A_from_prior_audit_unmodified"][0]))
        with self.assertRaisesRegex(HistoryRecheckError,"DUPLICATE_RACE"):
            recheck_derived_references(a,b,c)
        a,b,c=fictional()
        b["nov03"]["rows"].pop()
        with self.assertRaisesRegex(HistoryRecheckError,"COVERAGE_MISMATCH"):
            recheck_derived_references(a,b,c)
        a,b,c=fictional()
        a["reference_20261103"][
            "all_76_reference_A_from_prior_audit_unmodified"][0]["race_id"]="../x"
        with self.assertRaisesRegex(HistoryRecheckError,"INVALID"):
            recheck_derived_references(a,b,c)

    def test_unverified_flags_cannot_be_promoted_by_copy(self):
        a,b,c=fictional()
        a["reference_20261103"][
            "all_76_reference_A_from_prior_audit_unmodified"][0][
                "official_final_organizer_verified"]=True
        with self.assertRaisesRegex(HistoryRecheckError,"CANNOT_PROMOTE"):
            recheck_derived_references(a,b,c)


if __name__ == "__main__":
    unittest.main()
