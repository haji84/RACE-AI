"""Synthetic offline write/readback contract; no provider, GitHub or betting."""
import base64,json,unittest
from race_ai.append_only_freeze_writer import prepare_anchor,submit_anchor,FreezeWriteError
B={"schema":"RACE_AI_P0_SOURCE_MODEL_BINDING_V1",
   "model_race_id":"boat:2030-01-15:fictional:1","event_date_jst":"2030-01-15",
   "model_claimed_cutoff_at":"2030-01-15T10:00:00+09:00",
   "external_freeze_verified":False,"eligible_for_scoring":False,
   "models":[{"model_id":"test","prediction_sha256":"a"*64}]}
def prepared():
    return prepare_anchor(B,"test","2030-01-15T09:00:00+09:00","2030-01-15T09:01:00+09:00")
class Test(unittest.TestCase):
 def test_prepare_hash_only(self):
    p=prepared();self.assertFalse(p["eligible_for_hit_at_8"])
    self.assertEqual(set(p["anchor"]),{"schema","race_id","prediction_sha256","cutoff_at"})
 def test_after_cutoff(self):
    with self.assertRaisesRegex(FreezeWriteError,"after cutoff"):
        prepare_anchor(B,"test","2030-01-15T10:00:00+09:00","2030-01-15T10:00:01+09:00")
 def test_failclosed_before_http(self):
    calls=[]
    def sender(*a):calls.append(a);return {}
    with self.assertRaisesRegex(FreezeWriteError,"approved"):
        submit_anchor(prepared(),"audit/immutable","x"*40,None,request=sender)
    with self.assertRaisesRegex(FreezeWriteError,"token"):
        submit_anchor(prepared(),"audit/immutable","",lambda x:True,request=sender)
    self.assertEqual(calls,[])
 def test_write_only_anchors_then_separate_server_time(self):
    p=prepared()
    def sender(url,method,data):
        if method=="PUT":
            self.assertNotIn("sha",json.loads(data))
            return {"commit":{"sha":"b"*40}}
        return {"type":"file","encoding":"base64",
            "content":base64.b64encode((json.dumps(p["anchor"],ensure_ascii=False,
                sort_keys=True,separators=(",",":"))+"\n").encode()).decode()}
    output=submit_anchor(p,"audit/immutable","x"*40,lambda x:True,request=sender)
    self.assertFalse(output["eligible_for_hit_at_8"])
    self.assertIsNone(output["run_id"])
 def test_mismatched_readback(self):
    def sender(url,method,data):
        return {"commit":{"sha":"b"*40}} if method=="PUT" else {
            "type":"file","encoding":"base64","content":base64.b64encode(b"changed").decode()}
    with self.assertRaisesRegex(FreezeWriteError,"mismatch"):
        submit_anchor(prepared(),"audit/immutable","x"*40,lambda x:True,request=sender)
if __name__=="__main__":unittest.main()
