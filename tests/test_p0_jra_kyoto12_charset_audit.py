"""Regression: strict JRA character decoding with synthetic CP932/UTF-8 HTML."""
from datetime import datetime,timezone
import unittest
from scripts.p0_jra_kyoto12_charset_audit_20261024 import (
 decode_first_party,inspect_jra_kyoto12,audit,REF,TOKEN,URL)
ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":REF,
     "RACE_AI_JRA_CHARSET_ONE_SHOT":TOKEN,"GITHUB_SHA":"a"*40}
CP="<html><meta charset=Shift_JIS><body>2026年10月24日 京都 12R 出馬表 馬体重</body></html>"
class Response:
 status=200
 headers={"Content-Type":"text/html; charset=Shift_JIS"}
 def geturl(self):return URL
 def read(self,n):return CP.encode("cp932")
 def __enter__(self):return self
 def __exit__(self,*_):return False
class Connection:
 def __init__(self):self.count=0
 def open(self,request,timeout):
  assert timeout==8 and request.full_url==URL
  self.count+=1
  return Response()
class JraCharsetTests(unittest.TestCase):
 def test_shift_jis_meta_decodes_without_fake_weight_claim(self):
  text,meta=decode_first_party(CP.encode("cp932"),"shift_jis")
  self.assertEqual(meta["decoder"],"cp932")
  self.assertEqual(meta["decoder_source"],"HTTP_CONTENT_TYPE")
  p=inspect_jra_kyoto12(text)
  self.assertTrue(p["race_identity_from_body_verified"])
  self.assertTrue(p["bodyweight_field_present"])
  self.assertFalse(p["horse_bound_current_weight_verified"])
  self.assertFalse(p["event_trigger_eligible_for_formal_model"])
 def test_fallback_cp932_if_unspecified_and_meta_missing(self):
  raw="<html>2026年10月24日 京都 12R 出馬表 馬体重</html>".encode("cp932")
  text,meta=decode_first_party(raw,None)
  self.assertIn("馬体重",text)
  self.assertEqual(meta["decoder_source"],"STRICT_CP932_FALLBACK")
 def test_one_get_success_with_competitor_identity_pending(self):
  conn=Connection()
  x=audit(env=ENV,opener=conn,
          clock=lambda:datetime(2026,10,24,6,tzinfo=timezone.utc))
  self.assertEqual(x["GET_attempts"],1)
  self.assertEqual(conn.count,1)
  self.assertEqual(x["status"],"RACECARD_IDENTITY_CONFIRMED_WEIGHT_RELEASE_UNVERIFIED")
  self.assertFalse(x["source_rights_verified"])
  self.assertFalse(x["official_prediction"])
  self.assertNotIn("馬体重",str(x))
 def test_published_word_in_unrelated_page_does_not_verify_horse(self):
  p=inspect_jra_kyoto12("出馬表 馬体重 発表済")
  self.assertFalse(p["race_identity_from_body_verified"])
  self.assertFalse(p["horse_bound_current_weight_verified"])
 def test_wrong_ref_blocks_all_http(self):
  conn=Connection()
  with self.assertRaises(RuntimeError):
   audit(env=dict(ENV,GITHUB_REF="refs/heads/main"),opener=conn)
  self.assertEqual(conn.count,0)
if __name__=="__main__":unittest.main()
