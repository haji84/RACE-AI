"""Synthetic official 100x screen tests, never actual purchase/recommendation."""
from copy import deepcopy
from datetime import timedelta
import itertools
import unittest

from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_manshu_watch import freeze_priced_tail

RUN="2030-11-03T13:12:00+09:00"
CUTOFF="2030-11-03T13:30:00+09:00"


def original():
    source={
        "race_id":"20301103-04-05",
        "cutoff_at":CUTOFF,
        "captured_at":"2030-11-03T13:10:00+09:00",
        "program_source_sha256":"a"*64,
        "beforeinfo_source_sha256":"b"*64,
        "boats":[{"lane":lane,"racer_id":str(4200+lane),
                  "national_win_rate":6.+lane*.1,
                  "exhibition_time_seconds":6.8+lane*.02,
                  "motor_two_place_rate_percent":20.+lane*.3}
                 for lane in range(1,7)]
    }
    return {
        "schema":"RACE_AI_BOAT_LIVE_AB_RESEARCH_V1",
        "status":"REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT",
        "race_id":source["race_id"],
        "cutoff_at":CUTOFF,
        "result_used":False,
        "paired_forecast":build_pair(source,RUN),
    }


def official_odds():
    tickets=list(itertools.permutations(range(1,7),3))
    return {
        "race_id":"20301103-04-05",
        "kind":"odds3t",
        "status":"AVAILABLE",
        "eligible_pre_race":True,
        "closed_at":CUTOFF,
        "captured_at":"2030-11-03T13:14:00+09:00",
        "source_url":"https://www.boatrace.jp/owpc/pc/race/odds3t?rno=5&jcd=04&hd=20301103",
        "source_sha256":"c"*64,
        "data":{"odds":[
            {"combination":list(t),"odds":"125.5" if t[0] in (4,5,6) else "20.0",
             "availability":"AVAILABLE"}
            for t in tickets]},
    }


class ManShuWatchTests(unittest.TestCase):
    def setUp(self):
        self.old=original()
        self.now="2030-11-03T13:15:00+09:00"

    def test_only_genuine_100x_preclose_odds_and_core_unchanged(self):
        prior=deepcopy(self.old)
        watch=freeze_priced_tail(self.old,official_odds(),self.now)
        self.assertEqual(self.old,prior)
        self.assertEqual(watch["state"],"OFFICIAL_PRE_CLOSE_100X_SCREEN_SNAPSHOT")
        self.assertFalse(watch["auto_bet"])
        self.assertEqual(len(watch["models"]),2)
        self.assertEqual(watch["wan_shu_threshold_100_yen_payout"],10000)
        for m,base in zip(watch["models"],self.old["paired_forecast"]["models"]):
            self.assertEqual(m["original_hit8_top8"],[x["ticket"] for x in base["top8"]])
            self.assertEqual(len(m["experimental_6core2priced_tail_top8"]),8)
            self.assertEqual(len(set(m["experimental_6core2priced_tail_top8"])),8)
            self.assertTrue(all(x["observed_decimal_odds"]=="125.5"
                            for x in m["observed_100x_outside_core_top4"]))
            self.assertEqual(m["betting_decision"],"NO_BET")

    def test_no_verified_odds_means_no_manshu_assertion(self):
        missing=freeze_priced_tail(self.old,None,self.now)
        self.assertEqual(missing["state"],"NO_PRE_CUTOFF_OFFICIAL_ODDS_NO_MANSYU_CLASSIFICATION")
        self.assertEqual(missing["observed_100x_candidates"],[])

    def test_missing_odds_late_snapshot_wrong_race_and_fabricated_winner_rejected(self):
        changes=[
            lambda x:x.update(race_id="20301103-04-06"),
            lambda x:x.update(captured_at="2030-11-03T13:16:00+09:00"),
            lambda x:x["data"]["odds"].pop(),
            lambda x:x["data"]["odds"][0].update(odds="--"),
            lambda x:x["data"]["odds"][0].update(availability="PENDING"),
            lambda x:x.update(source_url="https://example.com/published-odds"),
            lambda x:x.update(status="PENDING"),
        ]
        for change in changes:
            odds=official_odds();change(odds)
            with self.subTest(change=change),self.assertRaises(ValueError):
                freeze_priced_tail(self.old,odds,self.now)
        with self.assertRaises(ValueError):
            freeze_priced_tail(self.old,official_odds(),"2030-11-03T13:29:00+09:00")
        broken=deepcopy(self.old);broken["paired_forecast"]["models"][1]["top8"][0]["ticket"]="4-3-1"
        with self.assertRaises(ValueError):
            freeze_priced_tail(broken,official_odds(),self.now)


if __name__=="__main__":
    unittest.main()
