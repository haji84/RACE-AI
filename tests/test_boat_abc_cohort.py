"""Fictional, contract-only: does not reproduce or assert real performance."""
from copy import deepcopy
import unittest

from race_ai.boat_shadow_result_audit import AB_IDS, C_ID
from race_ai.boat_abc_cohort import summarize_abc_results


def sample():
    rid="20300115-17-08"
    ids=(*AB_IDS,C_ID)
    ranks=(28,7,3)
    payout=830
    models=[{
        "model_id":mid,
        "winning_combination_rank":rank,
        "hit_at_1":int(rank==1),
        "hit_at_8":int(rank<=8),
        "virtual_stake_yen":800,
        "virtual_payout_yen":payout if rank<=8 else 0,
        "actual_man_shu":False,"man_shu_missed":False,
        "calibrated":False,"multiclass_brier":.9,
        "log_loss":3.1,
    } for mid,rank in zip(ids,ranks)]
    ab={"cutoff_at":"2030-01-15T13:35:00+09:00",
        "forecast_server_saved_at":"2030-01-15T04:24:58Z",
        "pair_bundle_sha256":"b"*64,
        "models":[{"model_id":mid,"winning_combination_rank":rank}
                  for mid,rank in zip(ids[:2],ranks[:2])]}
    official={"race_id":rid,"state":"INDEPENDENT_AB_RESULT_VERIFIED",
              "official_top3":"1-2-3","payout_per_100_yen":payout,
              "official_source_sha256":"c"*64,
              "result_captured_at":"2030-01-15T16:36:32Z",
              "paired_comparison":ab}
    comparison={"race_id":rid,"state":"ABC_SAME_FROZEN_INPUT_SCORED",
                "official_top3":"1-2-3","payout_per_100_yen":payout,
                "pair_bundle_sha256":"b"*64,
                "server_saved_at":"2030-01-15T04:24:58Z",
                "models":models}
    return {"schema":"RACE_AI_BOAT_NATIONAL_3R_RESULT_AUDIT_V1",
            "first_receipt_per_race_only":True,
            "past_predictions_untouched":True,
            "model_coefficients_unchanged":True,
            "research_only":True,
            "actual_purchases":False,
            "frozen_artifact_id":1001,
            "frozen_forecast_json_sha256":"a"*64,
            "official_results":[official],
            "frozen_current_feature_comparison":{
                "schema":"RACE_AI_BOAT_FROZEN_ABC_COMPARISON_V1",
                "auto_promoted":False,"past_forecasts_changed":False,
                "comparisons":[comparison]}}


class ABCSelectedCohortTests(unittest.TestCase):
    def test_same_real_source_contract_scores_all_three_without_selection(self):
        r=summarize_abc_results([sample()])
        self.assertEqual(r["normal_scored"],1)
        self.assertEqual(r["unique_dates"],1)
        self.assertEqual(r["unique_venue_day_blocks"],1)
        self.assertFalse(r["meets_minimum_sample_gate"])
        self.assertFalse(r["complete_national_denominator_verified"])
        self.assertIsNone(r["winner_selected"])
        self.assertEqual(r["model_metrics"][AB_IDS[0]]["hit_at_8"],0)
        self.assertEqual(r["model_metrics"][AB_IDS[1]]["hit_at_8"],1)
        self.assertEqual(r["model_metrics"][C_ID]["hit_at_8"],1)
        self.assertEqual(r["model_metrics"][C_ID]["roi8"],830/800)
        self.assertEqual(r["model_metrics"][AB_IDS[1]]["stake8_yen"],800)

    def test_result_abnormal_is_not_marked_as_miss(self):
        packet=sample()
        packet["official_results"][0]["state"]="OFFICIAL_RESULT_ABNORMAL_FINISH_SEPARATE"
        row=packet["frozen_current_feature_comparison"]["comparisons"][0]
        row["state"]="OFFICIAL_RESULT_ABNORMAL_FINISH_SEPARATE"
        r=summarize_abc_results([packet])
        self.assertEqual(r["normal_scored"],0)
        self.assertEqual(len(r["exceptions"]),1)
        self.assertIsNone(r["model_metrics"][AB_IDS[0]]["hit_at_8_rate"])

    def test_duplicate_original_race_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate original artifact"):
            summarize_abc_results([sample(),sample()])
        distinct=deepcopy(sample())
        distinct["frozen_artifact_id"]=1002
        with self.assertRaisesRegex(ValueError,"duplicate/malformed/foreign race"):
            summarize_abc_results([sample(),distinct])

    def test_tampering_result_payout_or_model_rank_rejected(self):
        a=sample()
        a["frozen_current_feature_comparison"]["comparisons"][0]["payout_per_100_yen"]=900
        with self.assertRaisesRegex(ValueError,"result and frozen"):
            summarize_abc_results([a])
        b=sample()
        b["frozen_current_feature_comparison"]["comparisons"][0]["models"][1]["hit_at_8"]=0
        with self.assertRaisesRegex(ValueError,"score/rank"):
            summarize_abc_results([b])

    def test_forecast_after_cutoff_never_counted(self):
        p=sample()
        p["frozen_current_feature_comparison"]["comparisons"][0]["server_saved_at"]="2030-01-15T13:36:00+09:00"
        p["official_results"][0]["paired_comparison"]["forecast_server_saved_at"]="2030-01-15T13:36:00+09:00"
        with self.assertRaisesRegex(ValueError,"original receipt"):
            summarize_abc_results([p])

    def test_absent_c_lite_not_invented(self):
        p=sample()
        p["frozen_current_feature_comparison"]["comparisons"][0]={"race_id":"20300115-17-08","state":"C_LITE_NOT_FROZEN"}
        r=summarize_abc_results([p])
        self.assertEqual(r["normal_scored"],0)
        self.assertEqual(r["exceptions"][0]["reason"],"C_LITE_NOT_FROZEN")


if __name__=="__main__":
    unittest.main()
