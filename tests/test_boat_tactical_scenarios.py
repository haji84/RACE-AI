"""Synthetic actual-course and method scenario tests. Not a real prediction."""
from copy import deepcopy
from datetime import datetime, timedelta
import itertools
import math
import unittest

from race_ai.boat_racer_tendencies import profile_before
from race_ai.boat_tactical_scenarios import predict_tactical_shadow, SCHEMA
from race_ai.boat_ab_shadow import build_pair


FORECAST_AT="2030-11-03T13:10:00+09:00"
CUTOFF="2030-11-03T13:30:00+09:00"


def history():
    records=[]
    for i, method in enumerate(("nige","sashi","makuri","makurizashi","nige","sashi")):
        courses=[1,2,3,4,5,6]
        if i==1:courses=[2,1,3,4,5,6]
        if i==2:courses=[1,2,4,3,5,6]
        winner=(i%6)+1
        finishes=list(range(1,7))
        finishes[0],finishes[winner-1]=finishes[winner-1],finishes[0]
        records.append({
            "race_id":f"20301102-04-{i+1:02d}",
            "cutoff_at":f"2030-11-02T12:{10+i:02d}:00+09:00",
            "result_captured_at":f"2030-11-02T12:{20+i:02d}:00+09:00",
            "winner_method":method,
            "entries":[{"frame":lane,"course":courses[lane-1],
                        "racer_id":str(4100+lane),"finish":finishes[lane-1]}
                       for lane in range(1,7)],
            "source_sha256":f"{i+1:x}"*64,
        })
    return records


def inputs():
    records=history()
    source={
        "race_id":"20301103-04-06",
        "cutoff_at":CUTOFF,
        "captured_at":"2030-11-03T13:08:00+09:00",
        "program_source_sha256":"a"*64,
        "beforeinfo_source_sha256":"b"*64,
        "boats":[{"lane":lane,"racer_id":str(4100+lane),
                  "national_win_rate":6.5 if lane==1 else 5.0+lane*.1,
                  "exhibition_time_seconds":6.7+lane*.01,
                  "motor_two_place_rate_percent":20+5*lane}
                 for lane in range(1,7)]
    }
    profiles=[]
    for lane in range(1,7):
        p=profile_before(records,as_of=FORECAST_AT,racer_id=str(4100+lane))
        prof={key:p[key] for key in (
            "racer_id","as_of","sample_races","actual_entry_course_history",
            "by_frame_actual_course_counts","wins_by_actual_course_and_kimarite",
            "recent_form","tendencies")}
        prof["source_receipt"]={
            "official_source_sha256":"c"*64,
            "captured_at":"2030-11-03T13:05:00+09:00",
            "upstream_identity_verified":True}
        profiles.append(prof)
    venue={
        "venue_code":"04",
        "captured_at":"2030-11-03T13:00:00+09:00",
        "official_source_sha256":"d"*64,
        "source_identity_verified":True,
        "frame_course_counts":[[80 if c==i else 4 for c in range(6)] for i in range(6)],
        "course_win_rate":[.55,.14,.13,.10,.06,.02],
        "course_top3_rate":[.80,.60,.50,.40,.30,.20],
        "winner_method_rates":{
            "nige":.55, "sashi":.13, "makuri":.14,
            "makurizashi":.10,"other":.08},
    }
    return source,profiles,venue


def priced_odds():
    return {
        "captured_at":"2030-11-03T13:09:00+09:00",
        "official_source_sha256":"e"*64,
        "source_identity_verified":True,
        "decimal_odds":{
            "-".join(map(str,t)): 101. if t[0]!=1 else 70.
            for t in itertools.permutations(range(1,7),3)}}


class TacticalShadowTest(unittest.TestCase):
    def test_full_120_normalizes_and_scenario_weighting_is_reproducible(self):
        source,history,venue=inputs()
        out=predict_tactical_shadow(source,history,venue,FORECAST_AT)
        self.assertEqual(out["schema"],SCHEMA)
        self.assertEqual(len(out["full_120"]),120)
        self.assertEqual(len(out["main_top8"]),8)
        self.assertEqual(out["main_top8"],out["full_120"][:8])
        self.assertEqual(out["entry_scenario_count"],720)
        self.assertAlmostEqual(math.fsum(x["score"] for x in out["full_120"]),1,places=9)
        self.assertFalse(out["validated_accuracy"])
        self.assertFalse(out["automatically_promoted"])
        self.assertTrue(out["prospective_entry_course_is_inferred_not_observed"])
        self.assertFalse(out["man_shu_priced"])
        self.assertEqual(out["man_shu_watch"],[])
        self.assertEqual(out,predict_tactical_shadow(source,history,venue,FORECAST_AT))

    def test_sparse_skill_is_not_erased_by_age_or_lifetime_bonus(self):
        source,profiles,venue=inputs()
        source["boats"][1]["national_win_rate"]=None
        out=predict_tactical_shadow(source,profiles,venue,FORECAST_AT)
        self.assertEqual(out["racer_history_sample_sizes"][1]["sample_races"],6)
        self.assertTrue(any("2-" in x["ticket"] for x in out["full_120"]))
        self.assertTrue(out["main_top8_mass_uncalibrated"]>0)

    def test_official_100x_odds_only_known_preclose(self):
        source,profiles,venue=inputs()
        out=predict_tactical_shadow(source,profiles,venue,FORECAST_AT,preclose_odds=priced_odds())
        self.assertTrue(out["man_shu_priced"])
        self.assertTrue(len(out["man_shu_watch"])<=4)
        self.assertTrue(all(x["decimal_odds"]>=100 for x in out["man_shu_watch"]))
        self.assertTrue(all(x["ticket"].split("-")[0]!="1" for x in out["man_shu_watch"]))
        old=predict_tactical_shadow(source,profiles,venue,FORECAST_AT)
        self.assertEqual(out["main_top8"],old["main_top8"])

    def test_future_or_mismatched_historical_inputs_fail_closed(self):
        source,profiles,venue=inputs()
        changes=[
            lambda s,p,v:p[0].update(racer_id="4999"),
            lambda s,p,v:p[0].update(as_of="2030-11-04T00:00:00+09:00"),
            lambda s,p,v:p[0]["source_receipt"].update(upstream_identity_verified=False),
            lambda s,p,v:p[0]["actual_entry_course_history"]["1"].update(starts=999),
            lambda s,p,v:p[0]["by_frame_actual_course_counts"]["1"].update({"1":999}),
            lambda s,p,v:v.update(venue_code="17"),
            lambda s,p,v:v.update(captured_at="2030-11-04T00:00:00+09:00"),
            lambda s,p,v:v.update(winner_method_rates={"nige":1.}),
            lambda s,p,v:s.update(result_top3=[1,2,3]),
            lambda s,p,v:s.update(cutoff_at="2030-11-03T13:11:00+09:00")
        ]
        for change in changes:
            s,p,v=deepcopy((source,profiles,venue))
            change(s,p,v)
            with self.subTest(change=change),self.assertRaises(ValueError):
                predict_tactical_shadow(s,p,v,FORECAST_AT)

    def test_unverified_odds_and_missing_odds_are_not_manshu_claims(self):
        source,profiles,venue=inputs()
        for change in (lambda d:d.update(captured_at="2030-11-03T13:11:00+09:00"),
                       lambda d:d.update(source_identity_verified=False),
                       lambda d:d["decimal_odds"].pop("1-2-3")):
            _,p,v=deepcopy((source,profiles,venue))
            odds=priced_odds();change(odds)
            with self.assertRaises(ValueError):
                predict_tactical_shadow(source,p,v,FORECAST_AT,preclose_odds=odds)


if __name__=="__main__":
    unittest.main()
