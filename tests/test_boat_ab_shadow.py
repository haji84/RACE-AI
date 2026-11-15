"""Synthetic A/B test only. No real forecasts or official source calls."""
from copy import deepcopy
from datetime import datetime, timedelta
import math
import unittest

from race_ai.boat_ab_shadow import BASELINE_ID, CHALLENGER_ID, build_pair, _digest


def fixture():
    return dict(race_id="20301103-17-05",
                cutoff_at="2030-11-03T13:30:00+09:00",
                captured_at="2030-11-03T13:17:00+09:00",
                program_source_sha256="a"*64,
                beforeinfo_source_sha256="b"*64,
                boats=[
                    dict(lane=n, racer_id=str(4100+n),
                         national_win_rate=7.0-n*.2,
                         exhibition_time_seconds=6.7+n*.01,
                         motor_two_place_rate_percent=20+5*n)
                    for n in range(1,7)
                ])


class BoatABTests(unittest.TestCase):
    def setUp(self):
        self.source=fixture()
        self.now="2030-11-03T13:18:00+09:00"

    def test_two_models_same_evidence_and_full_120(self):
        out=build_pair(self.source,self.now)
        self.assertEqual(len(out["models"]),2)
        self.assertEqual([x["model_id"] for x in out["models"]],[BASELINE_ID,CHALLENGER_ID])
        self.assertEqual(out["actual_result_at_forecast_time"],None)
        self.assertEqual(out["generated_at"],self.now)
        for model in out["models"]:
            with self.subTest(model=model["model_id"]):
                self.assertFalse(model["calibrated"])
                self.assertTrue(model["odds_independent"])
                self.assertEqual(model["purchase_decision"],"NO_BET")
                self.assertEqual(len(model["full_120"]),120)
                self.assertEqual(len(model["top8"]),8)
                self.assertEqual(model["top8"],model["full_120"][:8])
                self.assertEqual(len({x["ticket"] for x in model["full_120"]}),120)
                self.assertAlmostEqual(sum(x["score"] for x in model["full_120"]),1,places=10)
                self.assertEqual(model["model_sha256"],
                    _digest({k:v for k,v in model.items() if k!="model_sha256"}))
        self.assertNotEqual(out["models"][0]["full_120"],out["models"][1]["full_120"])
        self.assertEqual(out["bundle_sha256"],_digest({k:v for k,v in out.items() if k!="bundle_sha256"}))

    def test_course_and_motor_contribution_are_independently_observable(self):
        origin=build_pair(self.source,self.now)
        changed=deepcopy(self.source)
        changed["boats"][0]["motor_two_place_rate_percent"]=99.0
        new=build_pair(changed,self.now)
        self.assertEqual(origin["models"][0]["full_120"],new["models"][0]["full_120"])
        self.assertNotEqual(origin["models"][1]["full_120"],new["models"][1]["full_120"])

    def test_forbidden_extra_fields_missing_motor_and_duplicates_rejected(self):
        changes=[
            lambda v:v.update(odds=[1.2]*120),
            lambda v:v["boats"][0].update(result_top3=[1,2,3]),
            lambda v:v["boats"][1].update(motor_two_place_rate_percent=None),
            lambda v:v["boats"][1].update(lane=1),
            lambda v:v["boats"][1].update(racer_id="4101"),
            lambda v:v.update(beforeinfo_source_sha256="not-a-hash"),
            lambda v:v.update(cutoff_at="2030-11-04T13:30:00+09:00")
        ]
        for change in changes:
            source=deepcopy(self.source);change(source)
            with self.subTest(change=change),self.assertRaises(ValueError):
                build_pair(source,self.now)

    def test_no_postcutoff_or_fabricated_earlier_time(self):
        for when in ["2030-11-03T13:30:00+09:00",
                     "2030-11-03T13:28:00+09:00",
                     "2030-11-03T13:16:59+09:00"]:
            with self.subTest(when=when),self.assertRaises(ValueError):
                build_pair(self.source,when)

    def test_same_input_replays_exact_hash(self):
        x=build_pair(self.source,self.now)
        y=build_pair(deepcopy(self.source),self.now)
        self.assertEqual(x,y)
        self.assertFalse(x["models"][1]["trained"])


if __name__=="__main__":
    unittest.main()
