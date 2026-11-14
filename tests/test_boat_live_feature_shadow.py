"""No-age-bonus same-race official local/ST research model, synthetic only."""
from copy import deepcopy
import unittest
import math

from race_ai.boat_live_feature_shadow import build_live_feature_shadow,MODEL_ID


def fixture():
    race={
        "race_id":"20301103-04-05",
        "cutoff_at":"2030-11-03T13:30:00+09:00",
        "captured_at":"2030-11-03T13:07:00+09:00",
        "program_source_sha256":"a"*64,
        "beforeinfo_source_sha256":"b"*64,
        "boats":[
            {"lane":n,"racer_id":str(4100+n),
             "national_win_rate":4.+n*.3,
             "exhibition_time_seconds":6.8+n*.01,
             "motor_two_place_rate_percent":20.+n*3}
            for n in range(1,7)]}
    extra={"race_id":race["race_id"],
           "observed_at":"2030-11-03T13:08:00+09:00",
           "source_sha256":"c"*64,
           "participants":[{"lane":n,"racer_id":str(4100+n),
                            "local_win_rate":5.8+n*.1,
                            "average_st":.14+n*.01,
                            "exhibition_st":.10+n*.01,
                            "exhibition_st_status":"OK"} for n in range(1,7)]}
    return race,extra,"2030-11-03T13:09:00+09:00"


class LiveFeatureShadowTests(unittest.TestCase):
    def test_normalizes_120_and_uses_only_available_same_source_racer_features(self):
        source,extra,at=fixture()
        forecast=build_live_feature_shadow(source,extra,at)
        self.assertEqual(forecast["model_id"],MODEL_ID)
        self.assertEqual(len(forecast["full_120"]),120)
        self.assertEqual(len(forecast["top8"]),8)
        self.assertEqual(forecast["top8"],forecast["full_120"][:8])
        self.assertAlmostEqual(math.fsum(x["score"] for x in forecast["full_120"]),1,places=10)
        self.assertFalse(forecast["calibrated"])
        self.assertFalse(forecast["odds_used"])
        self.assertFalse(forecast["auto_promoted"])
        self.assertEqual(len(forecast["features"][0]["features_used"]),3)
        self.assertEqual(forecast,build_live_feature_shadow(source,extra,at))

    def test_missing_history_and_missing_st_are_not_imputed_zero(self):
        source,extra,at=fixture()
        source["boats"][0]["national_win_rate"]=None
        extra["participants"][0]["local_win_rate"]=None
        extra["participants"][0]["average_st"]=None
        extra["participants"][0]["exhibition_st"]=None
        extra["participants"][0]["exhibition_st_status"]="PENDING"
        x=build_live_feature_shadow(source,extra,at)
        self.assertEqual(x["features"][0]["features_used"],[])
        self.assertFalse(x["features"][0]["historic_course_tactics_available"])
        self.assertEqual(len(x["full_120"]),120)

    def test_race_change_future_source_and_fake_result_are_rejected(self):
        source,extra,at=fixture()
        changes=[
            lambda s,e:e.update(race_id="20301103-04-06"),
            lambda s,e:e.update(observed_at="2030-11-03T13:15:00+09:00"),
            lambda s,e:e["participants"][0].update(racer_id="4999"),
            lambda s,e:e["participants"][0].update(exhibition_st=None),
            lambda s,e:e["participants"][0].update(exhibition_st_status="PENDING"),
            lambda s,e:e["participants"][0].update(average_st=1.5),
            lambda s,e:s.update(result_top3=[1,2,3]),
            lambda s,e:e.update(odds={"1-2-3":500}),
        ]
        for func in changes:
            s,e=deepcopy((source,extra));func(s,e)
            with self.subTest(change=func),self.assertRaises(ValueError):
                build_live_feature_shadow(s,e,at)


if __name__=="__main__":
    unittest.main()
