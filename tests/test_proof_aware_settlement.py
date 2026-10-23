"""Artificial authority callbacks used ONLY with 2030 fictional fixtures."""
import copy,unittest
from race_ai.proof_aware_settlement import audit_settlement,SettlementError
DAY="2030-01-15"
def fixture():
    records=[]
    for n in range(1,4):
        records.append({"race_id":f"boat:{DAY}:fictional:{n}","sport":"boat",
                        "venue":"fictional","race_no":n,"prediction":None,"result":None,
                        "sales_cutoff_at":f"{DAY}T10:00:00+09:00","cutoff_verified":False})
    ledger={"schema":"RACE_AI_FORECAST_AUDIT_V1","dataset_status":"AUDIT_ONLY",
            "event_date_jst":DAY,"records":records}
    results=[]
    for n in range(1,4):
        results.append({"race_id":records[n-1]["race_id"],"status":"FINAL",
             "trifecta_offered":True,"payouts":[{"combination":[1,2,n+2],
             "yen_per_100":600+n*100}],"refund_status":"NONE","revision_no":1,
             "confirmed_at":f"{DAY}T11:00:00+09:00",
             "source_ref":"https://example.org/fictional-result"})
    forecast={"race_id":records[0]["race_id"],"model_race_id":records[0]["race_id"],
         "model_id":"TEST-NOT-REAL","ordered_top8":[[1,2,3],[1,3,2]],
         "prediction_sha256":"a"*64,"generated_at":f"{DAY}T09:00:00+09:00",
         "persisted_at":f"{DAY}T09:01:00+09:00","cutoff_at":f"{DAY}T10:00:00+09:00",
         "receipt":{"run_id":42,"path":"fictional"}}
    return ledger,results,[forecast]
def calls():
    return {"verify_result":lambda r:True,"verify_cutoff":lambda r:True,
            "verify_freeze":lambda f,i:True,"verify_coverage":lambda x:True}
class SettlementTests(unittest.TestCase):
 def test_defaults_do_not_claim_measured_scores(self):
    a,b,c=fixture();x=audit_settlement(a,b,c)
    self.assertIsNone(x["formal_hit_at_8_all"])
    self.assertEqual(x["eligible_verified_subset"],0)
    self.assertIsNone(x["paper_roi_on_frozen_picks"])
 def test_missing_forecasts_count_in_denominator(self):
    a,b,c=fixture();x=audit_settlement(a,b,c,**calls())
    self.assertEqual(x["eligible_verified_subset"],3)
    self.assertEqual(x["freeze_verified_subset"],1)
    self.assertAlmostEqual(x["formal_hit_at_8_all"],1/3)
    self.assertAlmostEqual(x["formal_hit_at_1_all"],1/3)
    self.assertAlmostEqual(x["formal_capture_rate"],1/3)
    self.assertEqual(x["paper_roi_on_frozen_picks"],700/200)
    self.assertIsNone(x["actual_purchase_roi"])
 def test_not_frozen_or_bad_receipt_never_counts(self):
    a,b,c=fixture();c[0]["persisted_at"]=f"{DAY}T10:00:00+09:00"
    x=audit_settlement(a,b,c,**calls())
    self.assertEqual(x["formal_hit_at_8_all"],0)
    self.assertEqual(x["freeze_verified_subset"],0)
 def test_uncertified_coverage_and_result_are_not_formal(self):
    a,b,c=fixture()
    args=calls();args["verify_coverage"]=lambda x:False
    x=audit_settlement(a,b,c,**args)
    self.assertIsNone(x["formal_hit_at_8_all"])
    args=calls();args["verify_result"]=lambda x: x["race_id"].endswith(":1")
    x=audit_settlement(a,b,c,**args)
    self.assertIsNone(x["formal_hit_at_8_all"])
 def test_return_unknown_blocks_roi_but_not_graded_hits(self):
    a,b,c=fixture();b[0]["refund_status"]="UNKNOWN"
    x=audit_settlement(a,b,c,**calls())
    self.assertIsNone(x["paper_roi_on_frozen_picks"])
    self.assertEqual(x["formal_hit_at_8_all"],1/3)
 def test_modified_invalid_and_unsourced_data_rejected(self):
    a,b,c=fixture();b[0]["payouts"][0]["combination"]=[1,1,2]
    with self.assertRaisesRegex(SettlementError,"payout"):
        audit_settlement(a,b,c)
    a,b,c=fixture();b[0]["payouts"]=[]
    with self.assertRaisesRegex(SettlementError,"requires"):
        audit_settlement(a,b,c)
    a,b,c=fixture();c[0]["ordered_top8"].append(c[0]["ordered_top8"][0])
    with self.assertRaisesRegex(SettlementError,"duplicate"):
        audit_settlement(a,b,c)
if __name__=="__main__":unittest.main()
