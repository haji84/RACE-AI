"""All records invented. No provider access or real forecast data published."""
import copy
import unittest
from race_ai.keirin_candidate_audit import research_audit_one, CandidateAuditError

RID = "202611033601"
CUTOFF = "2026-11-03T08:45:00+09:00"


def fixture():
    source = {
      "schema":"RACE_AI_KEIRIN_MOBILE_SINGLE_PAGE_RESEARCH_PROBE_V1",
      "source_kind":"THIRD_PARTY_NOT_KEIRIN_JP",
      "source_url":"https://www.keirin-mobile.jp/top/result.php?date=20261103&jcode=36&race=01",
      "source_sha256":"a"*64,
      "captured_at_unattested":"2026-11-03T10:17:00+09:00",
      "page_date_marker":True,
      "page_race_marker":True,
      "candidate_result":{"state":"ONE_UNVERIFIED_PROVIDER_CANDIDATE",
                          "triple":[6,1,5],"payout_100yen":11480},
      "result_officially_authenticated":False,
      "forecast_generated":False,
      "perpetual_polling_enabled":False,
    }
    reference = {
      "officially_frozen":False,"calibrated":False,
      "stamp_jst":"2026-11-03T08:10:15+09:00",
      "version":"SYNTHETIC_REFERENCE_ONLY",
      "races":[{
        "id":RID,
        "ranked":[{"pick":s,"p":0.01} for s in (
            "5-1-4","5-1-7","1-5-7","1-5-4",
            "1-4-7","4-1-5","4-1-7","1-4-5")]
      }]
    }
    return source,reference


class AuditTests(unittest.TestCase):
    def test_one_result_compares_to_unchanged_top8(self):
        src,ref=fixture()
        before=copy.deepcopy(ref)
        result=research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)
        self.assertFalse(result["research_hit8"])
        self.assertIsNone(result["formal_hit_at_8_all"])
        self.assertFalse(result["result_authoritative"])
        self.assertFalse(result["model_changed"])
        self.assertFalse(result["next_forecast_saved"])
        self.assertEqual(ref,before)

    def test_one_true_hit_only_research(self):
        src,ref=fixture()
        src["candidate_result"]["triple"]=[5,1,4]
        result=research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)
        self.assertTrue(result["research_hit8"])
        self.assertIsNone(result["formal_hit_at_8_all"])

    def test_pending_no_result_rejected(self):
        src,ref=fixture()
        src["candidate_result"]={"state":"NO_UNAMBIGUOUS_TRIFECTA",
                                  "triple":None,"payout_100yen":None}
        with self.assertRaises(CandidateAuditError):
            research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)

    def test_wrong_race_id_rejected(self):
        src,ref=fixture()
        with self.assertRaisesRegex(CandidateAuditError,"RACE_ID_MISMATCH"):
            research_audit_one(src,ref,race_id="202611033602",cutoff_at=CUTOFF)

    def test_changed_forecast_after_cutoff_refused(self):
        src,ref=fixture()
        ref["stamp_jst"]="2026-11-03T09:00:00+09:00"
        with self.assertRaisesRegex(CandidateAuditError,"NON_PROSPECTIVE"):
            research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)

    def test_unauthenticated_probe_cannot_become_authenticated(self):
        src,ref=fixture()
        src["result_officially_authenticated"]=True
        with self.assertRaisesRegex(CandidateAuditError,"UNTRUSTED_PROBE"):
            research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)

    def test_forecast_generated_flag_rejected(self):
        src,ref=fixture()
        src["forecast_generated"]=True
        with self.assertRaises(CandidateAuditError):
            research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)

    def test_wrong_source_rejected(self):
        src,ref=fixture()
        src["source_url"]="https://keirin-mobile.jp/top/result.php?date=20261103&jcode=36&race=01"
        with self.assertRaises(CandidateAuditError):
            research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)

    def test_unverified_date_marker_rejected(self):
        src,ref=fixture()
        src["page_date_marker"]=False
        with self.assertRaises(CandidateAuditError):
            research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)

    def test_duplicate_tickets_rejected(self):
        src,ref=fixture()
        ref["races"][0]["ranked"][1]["pick"]=ref["races"][0]["ranked"][0]["pick"]
        with self.assertRaises(CandidateAuditError):
            research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)

    def test_ambiguous_refund_status_not_guessed(self):
        src,ref=fixture()
        src["candidate_result"]["payout_100yen"]=None
        with self.assertRaises(CandidateAuditError):
            research_audit_one(src,ref,race_id=RID,cutoff_at=CUTOFF)


if __name__=="__main__":
    unittest.main()
