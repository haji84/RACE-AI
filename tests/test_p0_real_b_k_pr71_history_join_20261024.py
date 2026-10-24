"""Synthetic transport/results for real K/B join contract. No provider fetch."""
import unittest
from datetime import datetime,timezone
from scripts.p0_real_b_k_pr71_history_join_20261024 import (
    audit,BRANCH,TOKEN,TARGET,K_DAYS,B_DAY
)
ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":BRANCH,"GITHUB_SHA":"a"*40,
     "RACE_AI_BK_JOIN_ONE_SHOT":TOKEN}
NOW=datetime(2026,10,24,3,tzinfo=timezone.utc)
class FakeResp:
    status=200
    headers={}
    def __init__(self,url):self.url=url
    def geturl(self):return self.url
    def read(self,n):return b"\x16\x00-lh5-"+b"Q"*100
    def __enter__(self):return self
    def __exit__(self,*_):return False
class FakeTransport:
    def __init__(self):self.calls=[]
    def open(self,request,timeout):
        assert timeout==10
        self.calls.append(request.full_url)
        return FakeResp(request.full_url)
def extraction(raw,name):return name.encode()
def pk(_,day):
    rid=day.replace("-","")+"-18-01"
    return [{"race_id":rid,"lane":i,"racer_id":str(4000+i),
             "st":.10+i*.01,"st_status":"OK",
             "finish":i} for i in range(1,7)]
def pb(_,day):
    return [{"race_id":TARGET,"lane":i,"racer_id":str(4000+i)} for i in range(1,7)]
def detail(_,day):
    return ({(TARGET,i):{"racer_registration_id":str(4000+i),
              "motor_no":30+i,"national_win_rate":5.0,
              "local_win_rate":4.2,"motor_top2_rate":20.0}
             for i in range(1,7)}, {TARGET:"2026-10-24T15:09:00+09:00"})
def model(history,day,cutoff):
    assert len(history)==6 and day==B_DAY
    return (44.0,55.0)
class RealJoinOneShotTests(unittest.TestCase):
    def test_two_existing_sources_join_and_no_formal_prediction(self):
        trans=FakeTransport()
        r=audit(env=ENV,opener=trans,extract=extraction,parse_k_fn=pk,
              parse_b_fn=pb,parse_details_fn=detail,history_model=model,clock=lambda:NOW)
        self.assertEqual(r["provider_get_attempts"],7)
        self.assertEqual(len(trans.calls),7)
        self.assertEqual(r["target_race_lanes_with_at_least_5_valid_prior_K"],6)
        self.assertEqual(r["real_prior_K_values_reached_existing_PR71_history_formula_count"],12)
        self.assertFalse(r["source_terms_or_published_time_promotion"])
        self.assertFalse(r["forecast_executed"])
        self.assertEqual(r["formal_model_predicted_top8_count"],0)
        self.assertNotIn("4001",str(r))
    def test_invalid_gate_refuses_before_fetch(self):
        trans=FakeTransport()
        with self.assertRaisesRegex(RuntimeError,"not admitted"):
            audit(env=dict(ENV,GITHUB_REF="refs/heads/main"),
                  opener=trans,clock=lambda:NOW)
        self.assertEqual(len(trans.calls),0)
    def test_valid_F_not_faked_as_0(self):
        def k_with_missing(raw,day):
            rows=pk(raw,day)
            rows[0]["st_status"]="F"
            rows[0]["st"]=None
            rows[0]["finish"]=None
            return rows
        trans=FakeTransport()
        r=audit(env=ENV,opener=trans,extract=extraction,parse_k_fn=k_with_missing,
                parse_b_fn=pb,parse_details_fn=detail,history_model=model,clock=lambda:NOW)
        self.assertEqual(r["target_race_lanes_with_at_least_5_valid_prior_K"],5)
        self.assertEqual(r["target_race_prior_K_nonnumeric_or_unsettled_rows"],6)
    def test_existing_PR64_partial_historical_K_race_never_invents_missing_boat(self):
        from pathlib import Path
        import race_ai
        from scripts.p0_real_b_k_pr71_history_join_20261024 import ROOT, parse_prior_K_preserving_complete_races
        pr64=ROOT/"pr64-parser-reference"/"race_ai"
        if not pr64.is_dir():
            self.skipTest("pinned PR64 checkout not yet available")
        if str(pr64) not in race_ai.__path__:
            race_ai.__path__.append(str(pr64))
        from race_ai.core import parse_k
        good=[]
        for i in range(1,7):
            good.append(f"{i:02d} {i} {4000+i} Name 52 45 6.82 {i} 0.15 1.50.3")
        bad=good[:5]
        raw=("STARTK\n18KBGN\n2026/10/21\n"
             "1R 予選 H1800m\n"+"\n".join(good)+"\n"
             "2R 予選 H1800m\n"+"\n".join(bad)+"\n18KEND\n").encode("cp932")
        with self.assertRaises(Exception):
            parse_k(raw,"2026-10-21")
        rows, excluded=parse_prior_K_preserving_complete_races(raw,"2026-10-21",parse_k)
        self.assertEqual(len(rows),6)
        self.assertEqual(excluded,1)
        self.assertEqual({row["race_id"] for row in rows},{"20261021-18-01"})
        self.assertEqual({row["lane"] for row in rows},set(range(1,7)))

    def test_K_same_day_not_ingested_in_prior_collection(self):
        trans=FakeTransport()
        r=audit(env=ENV,opener=trans,extract=extraction,parse_k_fn=pk,
                parse_b_fn=pb,parse_details_fn=detail,history_model=model,clock=lambda:NOW)
        self.assertEqual(r["prior_K_days_requested"],list(K_DAYS))
        self.assertNotIn(B_DAY,r["prior_K_days_requested"])
if __name__=="__main__":unittest.main()
