"""PR72 -> PR71 compatibility contract with fictional fixtures only."""
import copy
import itertools
import unittest

from race_ai.pr71_delivery_binding import BindingError,bind_audit_to_delivery,_digest

DAY="2030-01-15"
RID="boat:2030-01-15:boatrace-jcd-16:2"
CUTOFF="2030-01-15T10:00:00+09:00"

def fixture():
    audit={
        "schema":"RACE_AI_FORECAST_AUDIT_V1","dataset_status":"AUDIT_ONLY",
        "event_date_jst":DAY,
        "records":[{"race_id":RID,"venue":"boatrace-jcd-16","sport":"boat","race_no":2,
                    "sales_cutoff_at":CUTOFF,"cutoff_verified":False,
                    "prediction":None,"result":None,
                    "no_forecast_reason":"UNVERIFIED"}]}
    participants=[{"number":i,"identity":"fictional "+str(i)} for i in range(1,7)]
    snapshot={"race":{"race_id":RID,"venue":"boatrace-jcd-16","sport":"boat",
                      "event_date_jst":DAY,"as_of":"2030-01-15T09:00:00+09:00",
                      "sales_cutoff_at":CUTOFF},"participants":participants}
    fd=_digest(snapshot)
    ranked=list(itertools.permutations(range(1,7),3))
    model={"model_id":"fictional-model","race_id":RID,"sport":"boat",
           "scope":"OPERATOR_SUPPLIED_RESEARCH","cutoff_at":CUTOFF,
           "snapshot_sha256":fd,"candidate_count":len(ranked),
           "candidates":[{"combination":list(x),"score":1/120} for x in ranked],
           "ordered_top8":[list(x) for x in ranked[:8]],
           "odds_independent":True,"official_prediction":False,
           "external_pre_cutoff_receipt":None,"official_result":None}
    model["prediction_sha256"]=_digest(model)
    suite={"schema":"RACE_AI_FOUR_SPORT_RESEARCH_SUITE_V1",
           "scope":"OPERATOR_SUPPLIED_RESEARCH","sport":"boat","race_id":RID,
           "sales_cutoff_at":CUTOFF,"as_of":snapshot["race"]["as_of"],
           "input_sha256":fd,"official_prediction":False,
           "external_timestamp_receipts":None,"official_result":None,
           "models":{"fictional-model":model},"ranked_model_ids":["fictional-model"],
           "model_count":1}
    suite["suite_sha256"]=_digest(suite)
    delivery={"schema":"RACE_AI_PRIVATE_DELIVERY_V1","race_id":RID,"sport":"boat",
              "source_payload_sha256":"a"*64,"policy_record_sha256":"b"*64,
              "feature_snapshot_sha256":fd,"snapshot":snapshot,
              "research_suite":suite,"ingested_at":"2030-01-15T09:01:00+09:00",
              "status":"PRIVATE_RESEARCH_ONLY_NOT_EXTERNAL_FROZEN",
              "official_prediction":False,"external_receipt":None,
              "can_count_in_hit_at_8":False,
              "source_terms_independently_verified_by_code":False}
    delivery["delivery_sha256"]=_digest(delivery)
    return audit,delivery

def rehash(delivery):
    model=delivery["research_suite"]["models"]["fictional-model"]
    model["prediction_sha256"]=_digest({k:v for k,v in model.items() if k!="prediction_sha256"})
    suite=delivery["research_suite"]
    suite["suite_sha256"]=_digest({k:v for k,v in suite.items() if k!="suite_sha256"})
    delivery["feature_snapshot_sha256"]=_digest(delivery["snapshot"])
    delivery["delivery_sha256"]=_digest({k:v for k,v in delivery.items() if k!="delivery_sha256"})

class BindingTests(unittest.TestCase):
    def test_same_race_bound_but_still_not_frozen_or_scored(self):
        a,d=fixture()
        result=bind_audit_to_delivery(a,d,race_id=RID)
        self.assertEqual(result["models"][0]["ordered_top8"],[[1,2,3],[1,2,4],
                         [1,2,5],[1,2,6],[1,3,2],[1,3,4],[1,3,5],[1,3,6]])
        for flag in ("external_freeze_verified","official_sales_cutoff_verified",
                     "eligible_for_scoring","eligible_for_website_publication"):
            self.assertFalse(result[flag])
        self.assertNotIn("participants",result)
        self.assertNotIn("source_rights_ref",result)

    def test_missing_or_mismatched_race_id_rejected(self):
        a,d=fixture()
        a["records"][0]["race_id"]=RID.replace(":2",":3")
        with self.assertRaisesRegex(BindingError,"missing"):
            bind_audit_to_delivery(a,d,race_id=RID)
        a,d=fixture()
        d["snapshot"]["race"]["venue"]="unrelated"
        rehash(d)
        with self.assertRaisesRegex(BindingError,"identity"):
            bind_audit_to_delivery(a,d,race_id=RID)

    def test_no_assumed_cutoff_from_schedule_disagreement(self):
        a,d=fixture()
        a["records"][0]["sales_cutoff_at"]="2030-01-15T09:59:00+09:00"
        with self.assertRaisesRegex(BindingError,"cutoff disagreement"):
            bind_audit_to_delivery(a,d,race_id=RID)
        a,d=fixture()
        a["records"][0]["sales_cutoff_at"]=None
        result=bind_audit_to_delivery(a,d,race_id=RID)
        self.assertIsNone(result["announced_cutoff_at"])
        self.assertFalse(result["official_sales_cutoff_verified"])

    def test_delivery_integrity_and_false_approval_rejected(self):
        a,d=fixture()
        d["research_suite"]["models"]["fictional-model"]["ordered_top8"][0]=[6,5,4]
        with self.assertRaisesRegex(BindingError,"checksum"):
            bind_audit_to_delivery(a,d,race_id=RID)
        a,d=fixture()
        d["external_receipt"]={"issuer":"FICTIONAL"}
        d["delivery_sha256"]=_digest({k:v for k,v in d.items() if k!="delivery_sha256"})
        with self.assertRaisesRegex(BindingError,"promotion flags"):
            bind_audit_to_delivery(a,d,race_id=RID)

    def test_model_hash_and_top8_guard(self):
        a,d=fixture()
        model=d["research_suite"]["models"]["fictional-model"]
        model["ordered_top8"][0]=[6,5,4]
        rehash(d)
        with self.assertRaisesRegex(BindingError,"top-eight"):
            bind_audit_to_delivery(a,d,race_id=RID)
        a,d=fixture()
        model=d["research_suite"]["models"]["fictional-model"]
        model["candidates"][0]["score"]=100
        rehash(d)
        with self.assertRaisesRegex(BindingError,"mass"):
            bind_audit_to_delivery(a,d,race_id=RID)

    def test_missing_predicted_races_cannot_disappear_from_audit(self):
        a,d=fixture()
        a["records"].append({"race_id":"boat:2030-01-15:boatrace-jcd-16:3","race_no":3,
                             "sport":"boat","venue":"boatrace-jcd-16",
                             "sales_cutoff_at":None,"prediction":None,
                             "cutoff_verified":False,"result":None})
        result=bind_audit_to_delivery(a,d,race_id=RID)
        self.assertEqual(result["race_no"],2)
        self.assertEqual(len(a["records"]),2)
        self.assertFalse(result["eligible_for_scoring"])

if __name__=="__main__":
    unittest.main()
