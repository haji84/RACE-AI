"""Fictional-only regression for 15 older K archives + one official-day B."""
import unittest
from datetime import datetime,timezone
from scripts.p0_ohmura8_extended_pr71_historical_k_audit import (
    audit, K_DAYS, B_DAY, TARGET, BRANCH, TOKEN, MAX_GETS,
)

ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":BRANCH,
     "RACE_AI_BK_JOIN_ONE_SHOT":TOKEN,"GITHUB_SHA":"a"*40}

class Response:
    status=200
    headers={"Content-Type":"application/octet-stream"}
    def __init__(self,url):self.url=url
    def geturl(self):return self.url
    def read(self,n):return b"\x16\x00-lh5-"+b"Z"*70
    def __enter__(self):return self
    def __exit__(self,*args):return False

class Transport:
    def __init__(self):self.urls=[]
    def open(self,request,timeout):
        assert timeout==10
        self.urls.append(request.full_url)
        return Response(request.full_url)

def k_rows(body,day):
    rid=day.replace("-","")+"-24-01"
    return [{"race_id":rid,"lane":lane,"racer_id":str(4000+lane),
             "st_status":"OK","st":.12+lane*.01,
             "finish":lane,"course":lane} for lane in range(1,7)]
def b_rows(body,day):
    return [{"race_id":TARGET,"lane":lane,"racer_id":str(4000+lane)}
             for lane in range(1,7)]
def b_details(body,day):
    return ({(TARGET,lane):{"racer_registration_id":str(4000+lane)}
             for lane in range(1,7)}, {TARGET:"2026-10-24T18:45:00+09:00"})
def formula(rows,day,asof):
    assert len(rows)==15 and day==B_DAY
    return 80.,60.
class ExtendHistoryTests(unittest.TestCase):
    def test_exact_fifteen_days_no_duplicate_provider_get_and_six_racers(self):
        transport=Transport()
        result=audit(env=ENV,opener=transport,
              extract=lambda *_:b"synthetic",parse_k_fn=k_rows,
              parse_b_fn=b_rows,parse_details_fn=b_details,history_model=formula,
              clock=lambda:datetime(2026,10,24,4,tzinfo=timezone.utc))
        self.assertEqual(len(K_DAYS),15)
        self.assertEqual(MAX_GETS,16)
        self.assertEqual(result["provider_get_attempts"],16)
        self.assertEqual(len(set(transport.urls)),16)
        self.assertEqual(result["target_race_lanes_with_at_least_5_valid_prior_K"],6)
        self.assertEqual(result["real_prior_K_values_reached_existing_PR71_history_formula_count"],12)
        self.assertFalse(result["forecast_executed"])
        self.assertFalse(result["source_model_use_rights_independently_approved"])
        self.assertNotIn("4001",str(result))
    def test_no_unapproved_branch_can_fetch_history(self):
        client=Transport()
        with self.assertRaisesRegex(RuntimeError,"not admitted"):
            audit(env=dict(ENV,GITHUB_REF="refs/heads/main"),opener=client,
                 clock=lambda:datetime(2026,10,24,4,tzinfo=timezone.utc))
        self.assertEqual(client.urls,[])
    def test_K_future_ST_excluded_not_imputed(self):
        client=Transport()
        def bad_k(raw,day):
            rows=k_rows(raw,day)
            rows[0]["st_status"]="F";rows[0]["st"]=None
            return rows
        r=audit(env=ENV,opener=client,extract=lambda *_:b"synthetic",
                parse_k_fn=bad_k,parse_b_fn=b_rows,parse_details_fn=b_details,
                history_model=formula,clock=lambda:datetime(2026,10,24,4,tzinfo=timezone.utc))
        self.assertEqual(r["target_race_lanes_with_at_least_5_valid_prior_K"],5)
        self.assertEqual(r["target_race_prior_K_nonnumeric_or_unsettled_rows"],15)

if __name__=="__main__":
    unittest.main()
