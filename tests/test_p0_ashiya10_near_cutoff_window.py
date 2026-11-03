"""Near-cutoff selection must reject far/too-late races BEFORE network."""
import unittest
from datetime import datetime
from scripts.p0_ashiya10_near_cutoff_join_20261024 import audit, EVENT_REF, EVENT_ADMISSION

ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":EVENT_REF,
     "GITHUB_SHA":"a"*40,"RACE_AI_FULL_ONE_RACE_ALLOWED":EVENT_ADMISSION}

class NoNetwork:
    def __init__(self):self.n=0
    def open(self,*_args,**_kwargs):
        self.n+=1
        raise AssertionError("no source GET may occur out of range")

class NearCutoffWindowTests(unittest.TestCase):
    def test_far_ahead_zero_requests(self):
        net=NoNetwork()
        r=audit(env=ENV,opener=net,clock=lambda:datetime.fromisoformat("2026-10-24T12:30:00+09:00"))
        self.assertEqual(r["status"],"NO_FORECAST_CUTOFF_TOO_FAR")
        self.assertEqual(net.n,0)
    def test_too_close_zero_requests(self):
        net=NoNetwork()
        r=audit(env=ENV,opener=net,clock=lambda:datetime.fromisoformat("2026-10-24T13:09:00+09:00"))
        self.assertEqual(r["status"],"NO_FORECAST_INSUFFICIENT_SAFE_CUTOFF_MARGIN")
        self.assertEqual(net.n,0)
    def test_past_cutoff_zero_requests(self):
        net=NoNetwork()
        r=audit(env=ENV,opener=net,clock=lambda:datetime.fromisoformat("2026-10-24T13:10:00+09:00"))
        self.assertEqual(r["status"],"NO_FORECAST_CUTOFF_PASSED")
        self.assertEqual(net.n,0)
    def test_wrong_branch_zero_requests(self):
        net=NoNetwork()
        with self.assertRaisesRegex(RuntimeError,"admission"):
            audit(env=dict(ENV,GITHUB_REF="refs/heads/main"),
                  opener=net,clock=lambda:datetime.fromisoformat("2026-10-24T13:04:00+09:00"))
        self.assertEqual(net.n,0)

if __name__=="__main__":
    unittest.main()
