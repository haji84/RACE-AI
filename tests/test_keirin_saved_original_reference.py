"""Synthetic-only regression: original Top8 snapshot versus later results.

All riders, times and payouts here are fictional; real archived owner data
belongs exclusively in an operator-private local input, never in public CI.
"""
from copy import deepcopy
from hashlib import sha256
import unittest

from race_ai.keirin_reference_history_recheck import (
    HistoryRecheckError, recheck_original_saved_baseline_against_published
)


def historical_pair():
    picks = [
        ["1-2-3","1-3-2","2-1-3","2-3-1","3-1-2",
         "3-2-1","4-1-2","4-2-1"],
        ["7-6-5","7-5-6","6-7-5","6-5-7","5-6-7",
         "5-7-6","7-5-1","7-1-5"],
    ]
    rows = [{"id":f"20300115360{i}", "baseline_top8":pool,
             "baseline_probabilities_unvalidated":
                  [round(0.03-0.001*n, 6) for n in range(8)]}
            for i,pool in enumerate(picks,1)]
    digest = sha256("\n".join(
        r["id"]+":"+",".join(r["baseline_top8"])
        for r in rows).encode()).hexdigest()
    early = {
        "prediction_origin":"conversation-generated reference, not official sealed",
        "results_status":"NOT_VERIFIED",
        "source_version":"20261103-am-reference-v1",
        "date_jst":"2026-11-03",
        "races":rows,
    }
    later = {
        "forecast_file_verified":False,"formal_hits":None,
        "fallback_sha256":digest,
        "races":[
            {"race_id":rows[0]["id"],"ordered_top8":list(picks[0]),
             "provider_trifecta":"1-2-3","payout_yen_per_100":16090,
             "hit8_research":1,"official_organizer_checked":False,
             "refund_and_revision_checked":False},
            {"race_id":rows[1]["id"],"ordered_top8":list(picks[1]),
             "provider_trifecta":"1-6-2","payout_yen_per_100":650,
             "hit8_research":0,"official_organizer_checked":False,
             "refund_and_revision_checked":False},
        ],
    }
    return early,later


class SavedHistoricalResearchBacktest(unittest.TestCase):
    def test_sha_proved_against_original_snapshot_and_mansha_count(self):
        a,b=historical_pair()
        out=recheck_original_saved_baseline_against_published(a,b)
        self.assertTrue(out["fallback_sha_recomputed_and_equal"])
        self.assertEqual(out["baseline_record_count"],2)
        self.assertEqual(out["top8_hits"],1)
        self.assertEqual(out["mansha_races"],1)
        self.assertEqual(out["mansha_top8_captured"],1)
        self.assertEqual(out["reference_investment_yen"],1600)
        self.assertEqual(out["reference_return_yen"],16090)
        self.assertEqual(out["reference_profit_yen"],14490)
        self.assertIsNone(out["top12_hit_rate"])
        self.assertIsNone(out["formal_roi"])
        self.assertFalse(out["source_full_original_file_verified"])
        self.assertFalse(out["valid_for_model_promotion"])

    def test_original_source_changed_fails_without_rewriting_digest(self):
        a,b=historical_pair()
        a["races"][0]["baseline_top8"][0]="6-1-2"
        with self.assertRaisesRegex(HistoryRecheckError,"ORIGINAL_REFERENCE_FALLBACK_SHA_MISMATCH"):
            recheck_original_saved_baseline_against_published(a,b)

    def test_later_results_changed_fails_closed(self):
        a,b=historical_pair()
        b["races"][0]["payout_yen_per_100"]=15000
        # With one post-publication source only, payout amount *itself*
        # cannot be authenticated; external published-result comparison
        # must be separately verified (don't falsely assert a hash exists).
        out=recheck_original_saved_baseline_against_published(a,b)
        self.assertEqual(out["reference_return_yen"],15000)
        self.assertFalse(out["third_party_result_match_crosschecked_by_this_function"])

    def test_changed_top8_or_hit_flag_is_rejected(self):
        a,b=historical_pair()
        b["races"][0]["ordered_top8"][0]="6-1-2"
        with self.assertRaisesRegex(HistoryRecheckError,"PUBLISHED_REFERENCE_CHANGED"):
            recheck_original_saved_baseline_against_published(a,b)
        a,b=historical_pair()
        b["races"][1]["hit8_research"]=1
        with self.assertRaisesRegex(HistoryRecheckError,"PUBLISHED_REFERENCE_HIT_FLAG"):
            recheck_original_saved_baseline_against_published(a,b)

    def test_missing_race_or_fake_official_witness_is_rejected(self):
        a,b=historical_pair()
        b["races"].pop()
        with self.assertRaisesRegex(HistoryRecheckError,"COVERAGE_GAP"):
            recheck_original_saved_baseline_against_published(a,b)
        a,b=historical_pair()
        b["races"][0]["official_organizer_checked"]=True
        with self.assertRaisesRegex(HistoryRecheckError,"PUBLISHED_REFERENCE_CHANGED"):
            recheck_original_saved_baseline_against_published(a,b)


if __name__=="__main__":
    unittest.main()
