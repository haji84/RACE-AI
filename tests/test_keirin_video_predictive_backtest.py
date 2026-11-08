"""Synthetic pre-cutoff video-tactics model uplift and leakage regression tests."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import itertools
import math
import unittest

from race_ai.keirin_video_predictive_backtest import (
    VideoForecastError, PAIR_SCHEMA,TRAITS,verify_record, score_one,
    fit_earlier_historical,evaluate_chronological,digest,
)

JST=timezone(timedelta(hours=9))

def sha(x):return sha256(x.encode()).hexdigest()

def fixture(day, *, scope="SYNTHETIC_ONLY"):
    clock=datetime(2026,9,1,18,0,tzinfo=JST)+timedelta(days=day)
    players=[{
       "number":i,"rider_id":f"synthetic-rider-{i}",
       "group_id":("A" if i<=3 else "B" if i<=6 else "C"),
       "line_role":("LEADER" if i in (1,4,7) else
                    "SECOND" if i in (2,5) else "THIRD")
    } for i in range(1,8)]
    # Deliberately conservative static 210-combo baseline, no odds.
    scores={i:1.2-.05*i for i in range(1,8)}
    scores[1]=2.0
    scores[2]=1.7
    triples=list(itertools.permutations(range(1,8),3))
    unnormalized=[math.exp(scores[a]+.75*scores[b]+.40*scores[c])
                  for a,b,c in triples]
    total=math.fsum(unnormalized)
    candidates=[{"order":list(t),"probability":p/total}
                for t,p in zip(triples,unnormalized)]
    tactics=[]
    for i in range(1,8):
        tactics.append({
            "rider_id":f"synthetic-rider-{i}",
            "attack":int(i==4),
            "initiative":int(i in (4,5)),
            "position_gain":int(i in (4,5)),
            "line_survival":int(i in (5,6)),
        })
    return {
       "schema":PAIR_SCHEMA,"race_id":f"synthetic-race-{day:03d}",
       "source_scope":scope,
       "pre":{
         "as_of":clock.isoformat(),
         "cutoff":(clock+timedelta(minutes=15)).isoformat(),
         "snapshot_sha256":sha(f"pre-raw-{day}"),
         "baseline_sha256":digest(candidates),
         "participants":players,"baseline_probabilities":candidates,
       },
       "post":{
         "result_published_at":(clock+timedelta(minutes=25)).isoformat(),
         "result_ordered_top3":[4,5,6],
         "video_reviewed_at":(clock+timedelta(minutes=40)).isoformat(),
         "video_sha256":sha(f"real-independent-video-fixture-{day}"),
         "visual_audit_sha256":sha(f"visual-fake-fixture-{day}"),
         "visual_status":"FOUR_LAPS_VISUALLY_VERIFIED",
         "source_use_admitted":True,
         "tactics":tactics,
       },
    }

class VideoToForecastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history=[fixture(x) for x in range(23)]
    def test_210_triples_normalize_with_no_same_race_video(self):
        record=self.history[4]
        earlier=self.history[:4]
        result=score_one(record,earlier,[.0]*6)
        self.assertEqual(len(result["ordered_candidates"]),210)
        self.assertAlmostEqual(sum(p["candidate_probability"]
                              for p in result["ordered_candidates"]),1.,places=10)
        self.assertEqual(result["prior_video_races_used"],4)
        with self.assertRaisesRegex(VideoForecastError,"TARGET_VIDEO_LEAK"):
            score_one(record,[record],[.0]*6)
        with self.assertRaisesRegex(VideoForecastError,"FUTURE_VIDEO_LEAK"):
            score_one(record,[self.history[5]],[.0]*6)

    def test_source_scope_cannot_grant_itself_real_training_rights(self):
        r=fixture(0,scope="OPERATOR_SUPPLIED_RESEARCH")
        with self.assertRaisesRegex(VideoForecastError,"TRUSTED_SOURCE_ADMISSION_REQUIRED"):
            verify_record(r)
        with self.assertRaisesRegex(VideoForecastError,"SOURCE_RIGHTS_AND_PROVENANCE_NOT_ATTESTED"):
            verify_record(r,trusted_source_admission=lambda row:False)
        self.assertIs(verify_record(r,trusted_source_admission=lambda row:True),r)

    def test_real_baseline_is_immutable(self):
        r=fixture(0)
        r["pre"]["baseline_probabilities"][0]["probability"]+=.001
        with self.assertRaisesRegex(VideoForecastError,"BASELINE_MASS_NOT_ONE"):
            verify_record(r)
        r=fixture(0)
        r["pre"]["baseline_sha256"]=sha("fake-hash")
        with self.assertRaisesRegex(VideoForecastError,"BASELINE_PROBABILITIES_DIGEST_MISMATCH"):
            verify_record(r)

    def test_post_result_is_never_usable_pre_cutoff(self):
        r=fixture(4)
        r["post"]["video_reviewed_at"]=r["pre"]["cutoff"]
        with self.assertRaisesRegex(VideoForecastError,"RACE_TIMELINE_INVALID"):
            verify_record(r)
        r=fixture(4)
        r["post"]["visual_status"]="UNVERIFIED"
        with self.assertRaisesRegex(VideoForecastError,"UNVERIFIED_FULL_VIDEO_OR_RIGHTS"):
            verify_record(r)

    def test_chronological_ablation_isolated_and_never_promotes_synthetic(self):
        train=self.history[:20]
        test=self.history[20:]
        model=fit_earlier_historical(train,min_races=20,epochs=3)
        self.assertEqual(model["train_count"],20)
        self.assertEqual(model["source_scope"],"SYNTHETIC_ONLY")
        report=evaluate_chronological(train,test,model,minimum_test=3)
        self.assertEqual(report["test_count"],3)
        self.assertEqual(len(report["results"]),3)
        self.assertEqual(report["research_promotion_gate"],"NO_VERIFIED_IMPROVEMENT")
        self.assertFalse(report["roi_verified"])
        self.assertFalse(report["prediction_originals_modified"])
        self.assertTrue(all(math.isfinite(row["candidate_loss"])
                            for row in report["results"]))
        with self.assertRaisesRegex(VideoForecastError,"TRAIN_TEST_DUPLICATE_RACE"):
            evaluate_chronological(train,train[-3:],model,minimum_test=3)
        early=[fixture(8),fixture(9),fixture(10)]
        for i,row in enumerate(early):
            row["race_id"]+=f"-distinct-holdout-{i}"
        with self.assertRaisesRegex(VideoForecastError,"TRAINING_POSTRACE_LABELS_LEAK_INTO_TEST"):
            evaluate_chronological(train,early,model,minimum_test=3)

    def test_minimum_real_history_gate(self):
        with self.assertRaisesRegex(VideoForecastError,"NOT_ENOUGH_REAL_TRAINING_RACES"):
            fit_earlier_historical(self.history[:2])
        model=fit_earlier_historical(self.history[:20],epochs=2)
        with self.assertRaisesRegex(VideoForecastError,"NOT_ENOUGH_OUT_OF_TIME_TEST_RACES"):
            evaluate_chronological(self.history[:20],self.history[20:],model)

if __name__=="__main__":
    unittest.main()
