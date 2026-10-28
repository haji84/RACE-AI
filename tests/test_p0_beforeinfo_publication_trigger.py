"""Offline proof that observed official preview, NOT ten minutes, is the trigger.

Fictional source content only. Existing PR64 official parser is separately
verified by the pinned integration tests; no real network in this module.
"""
import unittest
from datetime import datetime
from scripts.p0_cutoff_ordered_preview_20261024 import audit,BRANCH,TOKEN

DAY="2026-10-24"
A="20261024-05-07"
B="20261024-09-07"
CUT_A="2026-10-24T15:05:00+09:00"
CUT_B="2026-10-24T15:12:00+09:00"
NOW="2026-10-24T14:36:00+09:00"
ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":BRANCH,
     "RACE_AI_CUTOFF_ORDERED_ONCE":TOKEN,"GITHUB_SHA":"a"*40}

class FakeResponse:
    status=200
    def __init__(self,url):
        self.url=url
    def geturl(self):
        return self.url
    def read(self,n):
        if "beforeinfo" in self.url:
            return b"<html>fictional-beforeinfo</html>"
        return b"\x16\x00-lh5-"+b"Q"*100
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False

class FakeOpener:
    def __init__(self):
        self.calls=[]
    def open(self,req,timeout):
        assert timeout==8
        self.calls.append(req.full_url)
        return FakeResponse(req.full_url)

def parsed_B(_raw,day):
    assert day==DAY
    return [{"race_id":rid,"lane":i,"racer_id":str(4000+i)}
            for rid in (A,B) for i in range(1,7)]

def details_B(_raw,day):
    return ({(rid,i):{} for rid in (A,B) for i in range(1,7)},
            {A:CUT_A,B:CUT_B})

def beforeinfo_available(*, race, cutoff, st_count=6):
    num=race.split("-")[-1]
    return {
        "race_id":race,"closed_at":cutoff,
        "body_identity_verified":True,"status":"AVAILABLE",
        "data":{"boats":[
            {"lane":i,"racer_registration_id":str(4000+i),
             "display_time":6.8,
             "preview_st_status":"OK" if i<=st_count else "F",
             "preview_st":0.13 if i<=st_count else None}
            for i in range(1,7)],
            "weather":{"wind_speed_mps":2.0,"wave_height_cm":1.0}}
    }

def run(preview,now=NOW):
    net=FakeOpener()
    result=audit(env=ENV,opener=net,clock=lambda:datetime.fromisoformat(now),
                 extractor=lambda _bytes,_filename:b"fictional extracted source",
                 parser_b=parsed_B,parser_details=details_B,
                 parser_preview=preview)
    return result,net

class PreviewPublishedTriggerTests(unittest.TestCase):
    def test_future_published_preview_at_29_minutes_is_selected(self):
        def parse(_raw,*,venue,**other):
            return beforeinfo_available(race=A if venue=="05" else B,
                                        cutoff=CUT_A if venue=="05" else CUT_B)
        report,net=run(parse)
        self.assertEqual(report["status"],"OFFICIAL_PREVIEW_OBSERVED_RUN_INPUT_GATES_NOT_FORECAST")
        self.assertEqual(report["selected_race"],A)
        self.assertEqual(report["numeric_ready_race"],A)
        self.assertEqual(report["published_preview_count"],2)
        self.assertTrue(report["no_arbitrary_upper_cutoff_minutes"])
        self.assertGreater(report["candidates_sorted"][0]["cutoff"],NOW)
        self.assertEqual(report["provider_GET_attempts"],3)
        self.assertEqual(len(net.calls),3)
        self.assertFalse(report["formal_model_executed"])
        self.assertIsNone(report["full_PR71_model_top8"])
        self.assertFalse(report["model_source_rights_independently_verified"])

    def test_unpublished_earlier_race_does_not_block_later_published_one(self):
        def parse(_raw,*,venue,**kwargs):
            if venue=="05":
                return {"race_id":A,"closed_at":CUT_A,
                        "body_identity_verified":True,"status":"PENDING",
                        "missing_reason":"OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID"}
            return beforeinfo_available(race=B,cutoff=CUT_B)
        report,net=run(parse)
        self.assertEqual(report["selected_race"],B)
        self.assertEqual(report["numeric_ready_race"],B)
        self.assertEqual(report["published_preview_count"],1)
        self.assertEqual(report["checked"][0]["source_parser_status"],"PENDING")
        self.assertEqual(len(net.calls),3)

    def test_st_F_does_not_prevent_publication_trigger_but_blocks_numeric_readiness(self):
        def parse(_raw,*,venue,**kwargs):
            if venue=="05":
                return beforeinfo_available(race=A,cutoff=CUT_A,st_count=5)
            return beforeinfo_available(race=B,cutoff=CUT_B)
        report,_=run(parse)
        self.assertEqual(report["selected_race"],A)
        self.assertEqual(report["numeric_ready_race"],B)
        self.assertEqual(report["checked"][0]["exhibition_ST_numeric_count"],5)
        self.assertEqual(report["checked"][1]["exhibition_ST_numeric_count"],6)
        self.assertIsNone(report["full_PR71_model_top8"])

    def test_pending_both_yields_no_selected_race(self):
        def parse(_raw,*,venue,**kwargs):
            return {"race_id":A if venue=="05" else B,
                    "closed_at":CUT_A if venue=="05" else CUT_B,
                    "body_identity_verified":True,"status":"PENDING",
                    "missing_reason":"OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID"}
        report,_=run(parse)
        self.assertEqual(report["status"],"NO_OBSERVED_OFFICIAL_PREVIEW_AVAILABLE")
        self.assertIsNone(report["selected_race"])
        self.assertEqual(report["published_preview_count"],0)

    def test_all_expired_cannot_become_forecasts_or_get_previews(self):
        def never_called(*args,**kwargs):
            raise AssertionError("past race beforeinfo must never be fetched")
        report,net=run(never_called,now="2026-10-24T15:13:00+09:00")
        self.assertEqual(report["status"],"NO_UNEXPIRED_RACES_LEFT_IN_DAILY_B")
        self.assertIsNone(report["selected_race"])
        self.assertEqual(len(net.calls),1)
        self.assertFalse(report["formal_model_executed"])

    def test_bad_ref_refuses_all_get(self):
        net=FakeOpener()
        with self.assertRaises(RuntimeError):
            audit(env=dict(ENV,GITHUB_REF="refs/heads/main"),opener=net,
                  clock=lambda:datetime.fromisoformat(NOW))
        self.assertEqual(net.calls,[])

if __name__=="__main__":
    unittest.main()
