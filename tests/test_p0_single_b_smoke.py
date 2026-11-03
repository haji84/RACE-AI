"""All calls synthetic; no actual public archive accessed by unit tests."""
import unittest
from scripts.p0_single_b_smoke import one_shot,TARGET
CTX={"GITHUB_EVENT_NAME":"push","GITHUB_REF":"refs/heads/p0-b-smoke-20261024",
     "GITHUB_SHA":"a"*40,"RACE_AI_B_ONE_SHOT":"20261025-B"}
class R:
 def __init__(self,data=b"\x11\x22-lh5-xxxx"):
    self.data=data;self.status=200;self.headers={
        "Content-Type":"application/octet-stream","Date":"Sat, 24 Oct 2026 00:00:00 GMT"}
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def geturl(self):return TARGET
 def read(self,n):return self.data[:n]
class O:
 def __init__(self,reply=None):self.calls=0;self.response=reply or R()
 def open(self,request,timeout):
    self.calls+=1
    assert request.full_url==TARGET and timeout==10
    return self.response
class SmokeTest(unittest.TestCase):
 def test_explicit_branch_only(self):
    o=O();bad=dict(CTX,GITHUB_REF="refs/heads/main")
    with self.assertRaises(RuntimeError):one_shot(context=bad,opener=o)
    self.assertEqual(o.calls,0)
 def test_one_archive_get_discard_payload(self):
    o=O()
    got=one_shot(context=CTX,opener=o)
    self.assertEqual(o.calls,1)
    self.assertEqual(got["status"],"OFFICIAL_B_BYTES_OBSERVED")
    self.assertFalse(got["raw_archive_stored"])
    self.assertFalse(got["model_feature_data_admitted"])
    self.assertTrue(got["sha256"])
 def test_wrong_response_does_not_claim_source(self):
    o=O(R(b"<html>bad</html>"))
    got=one_shot(context=CTX,opener=o)
    self.assertFalse(got.get("looks_like_lzh_header",False))
    self.assertNotEqual(got["status"],"OFFICIAL_B_BYTES_OBSERVED")
if __name__=="__main__":unittest.main()
