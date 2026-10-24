"""One-shot official Isesaki11 runner respects publication and cutoff gates."""
from datetime import datetime
import unittest
from scripts.p0_isesaki11_real_trial_probe_20261024 import probe,URL,BRANCH,TOKEN

ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":BRANCH,
     "RACE_AI_ISESAKI11_ONCE":TOKEN,"GITHUB_SHA":"a"*40}
NOW=datetime.fromisoformat("2026-10-24T19:39:00+09:00")

def fixture(complete):
    header="2026/10/24 伊勢崎 11R 3100m 該当レースの開催は中止となりました"
    if not complete:return ("<html>"+header+" 試走T 表の見方</html>").encode()
    rows="".join(f"<tr><td><span>{i}</span><span>3.{30+i:02d}</span></td>"
                f"<td><span>{i+4}</span><span>3.{34+i:02d}</span></td></tr>"
                for i in range(1,5))
    return ("<html>"+header+"<table><tr><th>試走タイム</th><th>試走タイム</th></tr>"
           +rows+"</table></html>").encode()

class Response:
    status=200
    def __init__(self,data):self.data=data
    def geturl(self):return URL
    def read(self,n):return self.data
    def __enter__(self):return self
    def __exit__(self,*_):return False
class Client:
    def __init__(self,data):self.data=data;self.count=0
    def open(self,request,timeout):
        assert request.full_url==URL and timeout==9
        self.count+=1
        return Response(self.data)
class SourceRunnerTests(unittest.TestCase):
    def test_generic_cancel_without_race_table_is_not_successful_trial(self):
        op=Client(fixture(False))
        r=probe(env=ENV,opener=op,clock=lambda:NOW)
        self.assertEqual(r["status"],"NO_RACE_BOUND_NUMERIC_TRIAL_OBSERVED")
        self.assertEqual(op.count,1)
        self.assertEqual(r["numeric_trial_car_count"],0)
        self.assertFalse(r["official_race_cancellation_verified"])
        self.assertFalse(r["official_prediction"])
    def test_synthetic_complete_eight_trials_still_not_admitted_for_model(self):
        op=Client(fixture(True))
        r=probe(env=ENV,opener=op,clock=lambda:NOW)
        self.assertEqual(r["status"],"RACE_BOUND_NUMERIC_TRIAL_OBSERVED_RESEARCH_ONLY")
        self.assertEqual(r["numeric_trial_car_count"],8)
        self.assertFalse(r["source_analysis_rights_admitted"])
        self.assertFalse(r["model_executed"])
    def test_postcutoff_blocks_network_before_first_get(self):
        op=Client(fixture(True))
        r=probe(env=ENV,opener=op,
                clock=lambda:datetime.fromisoformat("2026-10-24T19:49:00+09:00"))
        self.assertEqual(r["status"],"CUTOFF_PASSED_DONT_FETCH")
        self.assertEqual(op.count,0)
    def test_wrong_ref_blocks_network(self):
        op=Client(fixture(True))
        with self.assertRaises(RuntimeError):
            probe(env=dict(ENV,GITHUB_REF="refs/heads/main"),opener=op,clock=lambda:NOW)
        self.assertEqual(op.count,0)
if __name__=="__main__":unittest.main()
