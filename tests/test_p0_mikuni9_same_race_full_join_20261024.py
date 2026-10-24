"""No external access. Test a single race_id across K, B and beforeinfo."""
import unittest
from datetime import datetime, timezone

import race_ai
from scripts.p0_mikuni9_same_race_full_join_20261024 import (
    audit, EVENT_REF, EVENT_ADMISSION, RACE, DAY,
)
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for path in ("pr64-parser-reference/race_ai", "pr71-existing-reference/race_ai"):
    folder=ROOT/path
    if folder.is_dir() and str(folder) not in race_ai.__path__:
        race_ai.__path__.append(str(folder))

ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":EVENT_REF,
     "RACE_AI_FULL_ONE_RACE_ALLOWED":EVENT_ADMISSION,"GITHUB_SHA":"b"*40}
NOW=datetime.fromisoformat("2026-10-24T12:25:50+09:00")


class FakeResponse:
    status=200
    headers={"Date":"Sat, 24 Oct 2026 03:25:50 GMT"}
    def __init__(self, url):self.url=url
    def geturl(self):return self.url
    def read(self, n):
        if "beforeinfo" in self.url:
            return b"<html>test fixture</html>"
        return b"\x10\x00-lh5-"+b"synthetic"*12
    def __enter__(self):return self
    def __exit__(self,*args):return False

class Client:
    def __init__(self):self.urls=[]
    def open(self,request,timeout):
        assert timeout==10
        self.urls.append(request.full_url)
        return FakeResponse(request.full_url)


def historical(_body, day):
    rid=day.replace("-","")+"-10-01"
    return [{"race_id":rid,"racer_id":str(4000+i),"lane":i,
             "st_status":"OK","st":.12+i*.01,"finish":i,
             "course":i} for i in range(1,7)]

def entries(_body, day):
    return [{"race_id":RACE,"lane":i,"racer_id":str(4000+i)}
            for i in range(1,7)]

def details(_body, day):
    return ({(RACE,i):{"racer_registration_id":str(4000+i),
                       "motor_no":i+20,"national_win_rate":4.1,
                       "local_win_rate":4.0,"motor_top2_rate":30.0}
             for i in range(1,7)}, {RACE:"2026-10-24T12:42:00+09:00"})

def beforeinfo(_body):
    return {"race_id":RACE,"closed_at":"2026-10-24T12:42:00+09:00",
            "status":"AVAILABLE","eligible_pre_race":True,
            "data":{"boats":[{"lane":i,"racer_registration_id":str(4000+i),
                             "display_time":6.4,
                             "preview_st_status":"OK" if i!=6 else "F",
                             "preview_st":.13 if i!=6 else None}
                             for i in range(1,7)],
                    "weather":{"wind_speed_mps":1.0,"wave_height_cm":2.0}}}

def calculated(rows,day,asof):
    assert len(rows)>=5 and day==DAY
    return 50.0,90.0


def run(client, **kwargs):
    args=dict(env=ENV,opener=client,clock=lambda:NOW,
              extractor=lambda *_:b"test extracted",
              parser_k=historical,parser_b=entries,
              parser_details=details,parser_preview=beforeinfo,
              form_model=calculated)
    args.update(kwargs)
    return audit(**args)


class FullSameRaceJoinTests(unittest.TestCase):
    def setUp(self):
        if not (ROOT/"pr64-parser-reference/race_ai").is_dir():
            self.skipTest("PR64 checkout not present")
        if not (ROOT/"pr71-existing-reference/race_ai").is_dir():
            self.skipTest("PR71 checkout not present")

    def test_genuine_join_shape_all_four_sources_without_unauthorized_prediction(self):
        client=Client()
        result=run(client)
        self.assertEqual(client.urls.__len__(),8)
        self.assertEqual(result["status"],"REAL_SAME_RACE_DATA_JOINED_MODEL_BLOCKED_BY_EVIDENCE")
        self.assertEqual(result["joined_same_race_id"],RACE)
        self.assertEqual(result["six_lanes_with_at_least_5_K"],6)
        self.assertEqual(result["PR71_original_form_and_ST_candidate_count"],12)
        self.assertEqual(result["display_time_count"],6)
        self.assertEqual(result["numeric_preview_ST_count"],5)
        self.assertTrue(result["weather_wave_cm_available"])
        self.assertIn("MISSING_EXHIBITION_START_ST",result["PR71_existing_FULL_blockers"])
        self.assertIn("SOURCE_PURPOSE_RIGHTS_NOT_VERIFIED",result["PR71_existing_FULL_blockers"])
        self.assertFalse(result["model_run"])
        self.assertIsNone(result["ordered_top8"])
        self.assertNotIn("4001",str(result))

    def test_preview_racer_not_equal_to_B_must_fail_closed(self):
        client=Client()
        def bad(html):
            out=beforeinfo(html)
            out["data"]["boats"][0]["racer_registration_id"]="9999"
            return out
        report=run(client,parser_preview=bad)
        self.assertEqual(report["status"],"NO_FORECAST_SOURCE_OR_JOIN_UNVERIFIED")
        self.assertEqual(report["error_type"],"ValueError")
        self.assertFalse(report["model_run"])

    def test_false_branch_blocks_all_source_requests(self):
        client=Client()
        with self.assertRaisesRegex(RuntimeError,"admission"):
            run(client,env=dict(ENV,GITHUB_REF="refs/heads/main"))
        self.assertEqual(client.urls,[])

    def test_started_after_cutoff_makes_zero_requests(self):
        client=Client()
        state=run(client,clock=lambda:datetime.fromisoformat("2026-10-24T12:43:00+09:00"))
        self.assertEqual(state["status"],"NO_FORECAST_CUTOFF_PASSED")
        self.assertEqual(state["upstream_get_attempts"],0)
        self.assertEqual(client.urls,[])

    def test_missing_historical_st_causes_explicit_form_gap(self):
        client=Client()
        def k(_body,day):
            rows=historical(_body,day)
            rows[0]["st_status"]="F";rows[0]["st"]=None
            return rows
        state=run(client,parser_k=k)
        self.assertEqual(state["six_lanes_with_at_least_5_K"],5)
        self.assertIn("MISSING_FIVE_PRIOR_K_SOME_LANES",state["PR71_existing_FULL_blockers"])
        self.assertFalse(state["official_prediction"])


if __name__=="__main__":
    unittest.main()
