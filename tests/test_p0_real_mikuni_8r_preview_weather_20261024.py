"""Strict one-GET synthetic fixture for existing PR64 official beforeinfo intake."""
from datetime import datetime,timezone
import unittest
from scripts.p0_real_mikuni_8r_preview_weather_20261024 import audit,URL,BRANCH,TOKEN,RACE,CUTOFF

CTX={"GITHUB_EVENT_NAME":"push","GITHUB_REF":BRANCH,
     "RACE_AI_EXHIBIT_ONE_SHOT":TOKEN,"GITHUB_SHA":"a"*40}
NOW=datetime(2026,10,24,3,5,50,tzinfo=timezone.utc)
class Reply:
    status=200
    headers={"Date":"Sat, 24 Oct 2026 03:05:49 GMT"}
    def geturl(self):return URL
    def read(self,_):return b"<html>synthetic</html>"
    def __enter__(self):return self
    def __exit__(self,*_):return False
class Net:
    def __init__(self):self.n=0
    def open(self,req,timeout):
        assert req.full_url==URL and timeout==10
        self.n+=1
        return Reply()
def preview(_):
    return {"race_id":RACE,"closed_at":CUTOFF,
            "status":"AVAILABLE","body_identity_verified":True,
            "eligible_pre_race":True,
            "data":{"boats":[{"lane":i,"display_time":6.5,
                   "preview_st_status":"OK" if i!=6 else "PENDING",
                   "preview_st":.10 if i!=6 else None}
                            for i in range(1,7)],
                    "weather":{"wind_speed_mps":1.0,"wave_height_cm":1.0,
                               "air_temperature_c":19.0,
                               "source_reported_local_time":None}}}
class TestOfficialPreviewOneShot(unittest.TestCase):
    def test_real_shape_metrics_not_model(self):
        net=Net()
        r=audit(env=CTX,opener=net,parser=preview,clock=lambda:NOW)
        self.assertEqual(net.n,1)
        self.assertEqual(r["numeric_display_times_available"],6)
        self.assertEqual(r["numeric_start_exhibition_ST_available"],5)
        self.assertEqual(r["weather_wave_cm"],1.0)
        self.assertEqual(r["weather_wind_mps"],1.0)
        self.assertFalse(r["full_model_run"])
        self.assertFalse(r["source_asof_weather_admitted_to_full_model"])
    def test_preview_pending_does_not_get_fake_data(self):
        net=Net()
        def pending(_):
            return {"race_id":RACE,"closed_at":CUTOFF,"status":"PENDING",
                    "body_identity_verified":True,"eligible_pre_race":True,
                    "missing_reason":"OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID"}
        r=audit(env=CTX,opener=net,parser=pending,clock=lambda:NOW)
        self.assertEqual(r["status"],"OFFICIAL_PREVIEW_NOT_YET_PUBLISHED_OR_PENDING")
        self.assertNotIn("numeric_display_times_available",r)
        self.assertFalse(r["full_model_run"])
    def test_wrong_race_cutoff_fails_closed(self):
        net=Net()
        def wrong(_):
            s=preview(_);s["closed_at"]="2026-10-24T12:10:00+09:00";return s
        r=audit(env=CTX,opener=net,parser=wrong,clock=lambda:NOW)
        self.assertEqual(r["status"],"REAL_PREVIEW_SOURCE_OR_PARSER_UNVERIFIED")
        self.assertFalse(r["official_prediction"])
    def test_wrong_workflow_branch_stops_before_network(self):
        net=Net()
        with self.assertRaises(RuntimeError):
            audit(env=dict(CTX,GITHUB_REF="refs/heads/main"),opener=net,clock=lambda:NOW)
        self.assertEqual(net.n,0)
if __name__=="__main__":unittest.main()
