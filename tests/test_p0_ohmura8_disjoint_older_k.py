"""Disjoint older K dates are audited without a repeated Oct09..23 fetch."""
import unittest
from datetime import datetime, timezone
from scripts.p0_ohmura8_disjoint_older_k_20261024 import (
    audit, DAYS, REF, TOKEN, RACERS
)
ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":REF,
     "GITHUB_SHA":"a"*40,"RACE_AI_K8_OLDER_ONE_SHOT":TOKEN}
NOW=datetime.fromisoformat("2026-10-24T12:55:00+09:00")

class Response:
    status=200
    def __init__(self,url):self.url=url
    def geturl(self):return self.url
    def read(self,n):return b"\x16\x00-lh5-"+b"x"*100
    def __enter__(self):return self
    def __exit__(self,*_):return False

class Open:
    def __init__(self):self.urls=[]
    def open(self,request,timeout):
        assert timeout==10
        self.urls.append(request.full_url)
        return Response(request.full_url)

def K(_raw,day):
    out=[]
    for i,pid in enumerate(RACERS,1):
        rid=f"{day.replace('-','')}-24-{i:02d}"
        out.append({"race_id":rid,"lane":i,"racer_id":pid,
                    "st_status":"OK","st":.13,"finish":i,"course":i})
    return out

class DistinctKTests(unittest.TestCase):
    def test_eight_unvisited_days_and_proven_lower_bound(self):
        client=Open()
        result=audit(env=ENV,opener=client,clock=lambda:NOW,
            extractor=lambda *_:b"synthetic K",parser=K)
        self.assertEqual(result["status"],"OLDER_DISTINCT_K_ROWS_OBSERVED_NOT_MODEL_ADMITTED")
        self.assertEqual(result["GET_attempts"],8)
        self.assertEqual(len(client.urls),8)
        self.assertEqual(len(set(client.urls)),8)
        self.assertEqual(result["source_dates_prior_15day_overlap_count"],0)
        self.assertEqual(result["minimal_new_K_count_across_six"],8)
        self.assertTrue(result["combined_at_least_five_can_be_deduced_without_RACER_CROSS_RUN_STATE"])
        self.assertFalse(result["cross_run_racer_specific_join_performed"])
        self.assertFalse(result["eligible_for_formal_hit8"])
        self.assertNotIn("4263",str(result))
    def test_insufficient_new_K_does_not_approve_all_six(self):
        client=Open()
        def sparse(raw,day):
            return [r for r in K(raw,day) if r["racer_id"]!=RACERS[5]]
        result=audit(env=ENV,opener=client,clock=lambda:NOW,
            extractor=lambda *_:b"synthetic K",parser=sparse)
        self.assertFalse(result["combined_at_least_five_can_be_deduced_without_RACER_CROSS_RUN_STATE"])
        self.assertEqual(result["minimal_new_K_count_across_six"],0)
    def test_bad_branch_refuses_get(self):
        client=Open()
        with self.assertRaises(RuntimeError):
            audit(env=dict(ENV,GITHUB_REF="refs/heads/main"),opener=client,
                clock=lambda:NOW)
        self.assertEqual(client.urls,[])
    def test_after_cutoff_refuses_get(self):
        client=Open()
        with self.assertRaises(RuntimeError):
            audit(env=ENV,opener=client,
                  clock=lambda:datetime.fromisoformat("2026-10-24T18:45:00+09:00"))
        self.assertEqual(client.urls,[])
    def test_f_is_not_numeric_history(self):
        client=Open()
        def bad(raw,day):
            rows=K(raw,day)
            rows[0]["st_status"]="F";rows[0]["st"]=None
            return rows
        result=audit(env=ENV,opener=client,
            extractor=lambda *_:b"synthetic",parser=bad,clock=lambda:NOW)
        self.assertEqual(result["selected_6_racers_additional_K_counts_by_lane"][0],0)
        self.assertFalse(result["eligible_for_formal_hit8"])

if __name__=="__main__":
    unittest.main()
