"""No network; fake tiny archive and synthetic K rows."""
from datetime import datetime,timezone
import unittest
from scripts.p0_one_shot_real_k_readiness_20261024 import audit, URL, BRANCH, TOKEN, DAY

ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":BRANCH,
     "RACE_AI_K_ONE_SHOT":TOKEN,"GITHUB_SHA":"a"*40}
UTC=datetime(2026,10,24,3,0,tzinfo=timezone.utc)

class Resp:
    status=200
    headers={"Content-Type":"application/x-lzh-compressed"}
    def geturl(self):return URL
    def read(self,n):return b"\x16\x00-lh5-"+b"x"*100
    def __enter__(self):return self
    def __exit__(self,*_):return False

class Open:
    def __init__(self):self.n=0
    def open(self,request,timeout):
        self.n+=1
        assert request.full_url==URL and timeout==10
        return Resp()

def parser(_):
    rows=[]
    for k in range(2):
        rid=f"20261023-18-{k+1:02d}"
        for lane in range(1,7):
            rows.append({"race_id":rid,"lane":lane,"racer_id":f"{4000+lane}",
                         "st_status":"OK","st":.1+lane*.01,"finish":lane,
                         "course":lane})
    return rows

class TestPriorK(unittest.TestCase):
    def test_one_get_and_aggregate_only(self):
        o=Open()
        result=audit(env=ENV,opener=o,extractor=lambda *_:b"synthetic txt",
                     parser=parser,clock=lambda:UTC)
        self.assertEqual(o.n,1)
        self.assertEqual(result["status"],"REAL_K_FORMAT_ACCEPTED_NOT_MODEL_ADMITTED")
        self.assertEqual(result["parsed_entries"],12)
        self.assertEqual(result["parsed_races"],2)
        self.assertEqual(result["parsed_venues"],1)
        self.assertEqual(result["valid_start_time_count"],12)
        self.assertFalse(result["source_purpose_rights_independently_verified"])
        self.assertFalse(result["all_required_five_prior_races_verified"])
        self.assertNotIn("4001",str(result))
    def test_current_day_rejected_before_fetch(self):
        o=Open()
        with self.assertRaisesRegex(RuntimeError,"current/future"):
            audit(env=ENV,opener=o,clock=lambda:datetime(2026,10,23,15,tzinfo=timezone.utc))
        self.assertEqual(o.n,0)
    def test_invalid_branch_rejected_before_fetch(self):
        o=Open()
        with self.assertRaisesRegex(RuntimeError,"admission"):
            audit(env=dict(ENV,GITHUB_REF="refs/heads/main"),opener=o,clock=lambda:UTC)
        self.assertEqual(o.n,0)
    def test_duplicate_result_rejected(self):
        o=Open()
        result=audit(env=ENV,opener=o,extractor=lambda *_:b"txt",
                     parser=lambda raw:parser(raw)+parser(raw)[:1],clock=lambda:UTC)
        self.assertEqual(o.n,1)
        self.assertEqual(result["status"],"REAL_K_TRANSPORT_OR_PARSE_UNVERIFIED")
        self.assertNotIn("racer_id",result)
    def test_f_l_not_zero_and_not_fake_st(self):
        def f_l(_):
            rows=parser(_)
            rows[0]["st_status"]="F";rows[0]["st"]=None;rows[0]["finish"]=None
            rows[1]["st_status"]="L";rows[1]["st"]=None
            return rows
        result=audit(env=ENV,opener=Open(),extractor=lambda *_:b"txt",parser=f_l,clock=lambda:UTC)
        self.assertEqual(result["status"],"REAL_K_FORMAT_ACCEPTED_NOT_MODEL_ADMITTED")
        self.assertEqual(result["F_count"],1)
        self.assertEqual(result["L_count"],1)
        self.assertEqual(result["valid_start_time_count"],10)

if __name__=="__main__":unittest.main()
