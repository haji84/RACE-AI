"""Cross-branch contract tests for actual existing PR64/PR71 logic.

All source figures, origins and right-grant callbacks in this fixture are
synthetic. They prove adapter wiring, never evidence of real-source approval.
"""
import copy
import math
import unittest
from pathlib import Path

import race_ai

ROOT=Path(__file__).resolve().parents[1]
PR64=ROOT/"pr64-existing-reference"/"race_ai"
PR71=ROOT/"pr71-existing-reference"/"race_ai"
for directory in (PR64,PR71):
    if directory.is_dir() and str(directory) not in race_ai.__path__:
        race_ai.__path__.append(str(directory))

from race_ai.boat_existing_asset_integration import (
    SCHEMA, ReuseGateError, pr64_history_candidates, from_pr64_imported_K,
    build_readiness, run_pr71_existing_multi_models,
    pr64_B_to_PR71_racelist,
)

DAY="2030-04-01"
ASOF="2030-04-01T10:42:00+09:00"
LAST_PUBLISHED="2030-03-25T08:00:00+09:00"
LAST_CAPTURED="2030-03-25T08:15:00+09:00"
COMMON={"source_ref":"https://example.org/synthetic-source",
        "published_at":"2030-04-01T09:00:00+09:00",
        "captured_at":"2030-04-01T09:11:00+09:00"}


def sample_rows(pid="4001",count=5):
    return [
        {"race_id":f"203003{11+i:02d}-18-01","lane":1,"racer_id":pid,
         "course":1,"finish":1+(i%6),"st":round(.13+.01*i,2),
         "st_status":"OK","sha":"a"*64,"published_at":LAST_PUBLISHED,
         "captured_at":LAST_CAPTURED}
        for i in range(count)
    ]


def full_fixture():
    racelist={
        "race_id":"20300401-18-01","venue":"18","date_jst":DAY,
        "closed_at":"2030-04-01T10:59:00+09:00",
        "source_url":"https://example.org/fictional-B",
        "first_observed_at":"2030-04-01T09:00:00+09:00",
        "original_publication_verification":True,
        "boats":[{"lane":i,"racer_registration_id":str(4000+i),
                  "motor_no":20+i,"national_win_rate":float(3+i),
                  "local_win_rate":float(2+i/2)} for i in range(1,7)]
    }
    history={
        str(4000+i):pr64_history_candidates(sample_rows(str(4000+i)),
                               racer_id=str(4000+i),day=DAY,as_of=ASOF)
        for i in range(1,7)
    }
    motor={str(20+i):dict(COMMON,motor_two_place_rate_percent=20.+8*i)
           for i in range(1,7)}
    exhibition={
        str(i):dict(COMMON,exhibition_time_seconds=6.8-.03*i,
                    exhibition_start_seconds=.11+.02*i)
        for i in range(1,7)
    }
    weather=dict(COMMON,wind_speed_mps=5,wave_height_cm=12,
                 wind_relative_to_course=.65,wet_surface_factor=.15)
    aux={"as_of":ASOF,"history_by_racer":history,
         "motor_by_number":motor,"exhibition_by_lane":exhibition,"weather":weather}
    return racelist,aux


class ExistingAssetIntegrationTests(unittest.TestCase):
    def test_prior_K_candidates_keep_real_race_id_source_time_and_sample(self):
        report=pr64_history_candidates(sample_rows(),racer_id="4001",day=DAY,as_of=ASOF)
        self.assertEqual(report["sample_n"],5)
        self.assertEqual(report["status"],"CANDIDATE_PENDING_INDEPENDENT_SOURCE_AND_RIGHTS")
        self.assertEqual(len(report["history_source_hashes"]),1)
        self.assertEqual(report["last_races"][0]["race_day"],"2030-03-15")
        self.assertEqual(report["last_races"][0]["start_seconds"],.17)
        self.assertIs(report["approved_for_model"],False)

    def test_K_future_and_F_and_unknown_ST_are_never_backfilled(self):
        rows=sample_rows()
        rows[0]["st_status"]="F"
        rows[0]["st"]=None
        rows[1]["published_at"]="2030-04-01T10:50:00+09:00"
        rows[2]["race_id"]="20300401-18-04"
        report=pr64_history_candidates(rows,racer_id="4001",day=DAY,as_of=ASOF)
        self.assertEqual(report["sample_n"],2)
        self.assertEqual(report["excluded_counts"]["invalid_finish_or_ST"],1)
        self.assertEqual(report["excluded_counts"]["after_as_of"],1)
        self.assertEqual(report["excluded_counts"]["target_day_or_future"],1)
        self.assertEqual(report["status"],"INSUFFICIENT_VERIFIED_K_HISTORY")
        self.assertTrue(all(x["start_seconds"]>0 for x in report["last_races"]))

    def test_K_duplicate_and_source_lies_are_rejected(self):
        with self.assertRaisesRegex(ReuseGateError,"deduplicate"):
            pr64_history_candidates(sample_rows()+sample_rows()[:1],
                     racer_id="4001",day=DAY,as_of=ASOF)
        x=sample_rows()
        x[0]["sha"]="not-a-hash"
        with self.assertRaisesRegex(ReuseGateError,"digest"):
            pr64_history_candidates(x,racer_id="4001",day=DAY,as_of=ASOF)

    def test_real_PR64_parsed_B_shape_binds_six_lanes_without_pubtime_fiction(self):
        rid="20300401-18-01"
        entries=[{"race_id":rid,"lane":i,"racer_id":str(4000+i)} for i in range(1,7)]
        details={
            (rid,i):{"racer_registration_id":str(4000+i),"motor_no":30+i,
                     "national_win_rate":4.+.25*i,
                     "local_win_rate":3.+.25*i,
                     "motor_top2_rate":25.+i}
            for i in range(1,7)}
        closings={rid:"2030-04-01T10:59:00+09:00"}
        result=pr64_B_to_PR71_racelist(
            entries,details,closings,race_id=rid,
            source_url="https://example.org/synthetic-B",
            archive_sha256="a"*64,captured_at="2030-04-01T09:01:00+09:00")
        self.assertEqual(len(result["boats"]),6)
        self.assertEqual(result["boats"][0]["racer_registration_id"],"4001")
        self.assertEqual(result["boats"][0]["motor_top2_rate"],26.)
        self.assertIsNone(result["source_original_published_at"])
        self.assertFalse(result["original_publication_verification"])
        racelist,aux=full_fixture()
        for field in ("first_observed_at","closed_at"):
            self.assertIn(field,result)
        with self.assertRaisesRegex(ReuseGateError,"publication"):
            run_pr71_existing_multi_models(
                result,aux,original_published_verified=True,
                source_admission=lambda *_:True)

    def test_b_join_rejects_postcutoff_and_wrong_motor(self):
        rid="20300401-18-01"
        rows=[{"race_id":rid,"lane":i,"racer_id":str(4000+i)} for i in range(1,7)]
        details={(rid,i):{"racer_registration_id":str(4000+i),"motor_no":20+i,
                "national_win_rate":5.0,"local_win_rate":4.0,
                "motor_top2_rate":40.0} for i in range(1,7)}
        kwargs=dict(race_id=rid,source_url="https://example.org/example",
                    archive_sha256="b"*64,
                    captured_at="2030-04-01T10:01:00+09:00")
        cutoff={rid:"2030-04-01T10:59:00+09:00"}
        with self.assertRaisesRegex(ReuseGateError,"elapsed"):
            pr64_B_to_PR71_racelist(rows,details,cutoff,
                **dict(kwargs,captured_at="2030-04-01T11:01:00+09:00"))
        modified=copy.deepcopy(details)
        modified[(rid,1)]["motor_no"]=None
        with self.assertRaisesRegex(ReuseGateError,"motor"):
            pr64_B_to_PR71_racelist(rows,modified,cutoff,**kwargs)

    def test_ready_report_advertises_source_gates_not_model_success(self):
        racelist,aux=full_fixture()
        report=build_readiness(racelist,aux["history_by_racer"],
                   motor_by_number=aux["motor_by_number"],
                   exhibition_by_lane=aux["exhibition_by_lane"],
                   weather=aux["weather"],as_of=ASOF)
        self.assertEqual(report["schema"],SCHEMA)
        self.assertEqual(report["history_ready_lane_count"],6)
        self.assertEqual(report["motor_candidate_lane_count"],6)
        self.assertEqual(report["exhibition_candidate_lane_count"],6)
        self.assertEqual(report["missing_weather_keys"],[])
        self.assertFalse(report["forecast_executed"])
        self.assertFalse(report["official_source_publication_independently_verified"])
        aux["exhibition_by_lane"].pop("1")
        report2=build_readiness(racelist,aux["history_by_racer"],
                   motor_by_number=aux["motor_by_number"],
                   exhibition_by_lane=aux["exhibition_by_lane"],
                   weather=aux["weather"],as_of=ASOF)
        self.assertEqual(report2["exhibition_candidate_lane_count"],5)

    def test_existing_PR71_runner_refuses_unverified_source(self):
        racelist,aux=full_fixture()
        with self.assertRaisesRegex(ReuseGateError,"publication"):
            run_pr71_existing_multi_models(racelist,aux)
        with self.assertRaisesRegex(ReuseGateError,"rights"):
            run_pr71_existing_multi_models(racelist,aux,
                                            original_published_verified=True)
    
    def test_PR64_revision_aware_sqlite_reuse_when_pinned(self):
        if not PR64.is_dir():
            self.skipTest("PR64 pinned checkout unavailable")
        from race_ai.core import connect, source, utc
        db=connect(":memory:")
        sha=source(db,"K",b"SYNTHETIC-PR64-K","fictional-K.txt",
                   LAST_PUBLISHED,LAST_CAPTURED,False)
        for row in sample_rows():
            db.execute("INSERT INTO starts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (row["race_id"],row["lane"],row["racer_id"],row["course"],
                 row["st"],row["st_status"],row["finish"],
                 row["race_day"]+"T00:00:00+00:00" if "race_day" in row else
                 row["race_id"][:4]+"-"+row["race_id"][4:6]+"-"+row["race_id"][6:8]+"T00:00:00+00:00",
                 utc(LAST_PUBLISHED),utc(LAST_CAPTURED),sha))
        db.commit()
        report=from_pr64_imported_K(db,racer_id="4001",day=DAY,as_of=ASOF)
        self.assertEqual(report["sample_n"],5)
        self.assertTrue(report["source_provenance_metadata_checked"])
        self.assertFalse(report["independent_official_publisher_attestation"])
        db.close()

    def test_both_PR71_real_existing_models_with_synthetic_auxiliary(self):
        if not PR71.is_dir():
            self.skipTest("PR71 pinned checkout unavailable")
        racelist,aux=full_fixture()
        result=run_pr71_existing_multi_models(
            racelist,aux,original_published_verified=True,
            source_admission=lambda _record,_purpose: True)
        self.assertEqual(set(result["models"]),{
            "boat-comprehensive-v1","boat-scenario-mixture-v1"})
        self.assertEqual(len(result["models"]),2)
        for model in result["models"].values():
            self.assertEqual(len(model["candidates"]),120)
            self.assertEqual(len(model["ordered_top8"]),8)
            self.assertFalse(model["official_prediction"])
            self.assertEqual(model["model_status"],"RESEARCH_UNTRAINED_NOT_CALIBRATED")
        # Same synthetic input, distinct existing algorithms, no new weights.
        a,b=list(result["models"].values())
        self.assertNotEqual(a["prediction_sha256"],b["prediction_sha256"])
        self.assertFalse(result["formal_hit_at_8_eligible"])


    def test_read_actual_existing_score_components_not_recalculated_new_weights(self):
        if not PR71.is_dir():
            self.skipTest("PR71 pinned checkout unavailable")
        from race_ai.boat_existing_asset_integration import explain_existing_PR71_boat_score
        racelist,aux=full_fixture()
        outcome=run_pr71_existing_multi_models(racelist,aux,
                    original_published_verified=True,
                    source_admission=lambda *_: True)
        rationale=explain_existing_PR71_boat_score(outcome["snapshot"])
        self.assertEqual(len(rationale["score_components_by_lane"]),6)
        self.assertEqual({x["lane"] for x in rationale["score_components_by_lane"]},
                         set(range(1,7)))
        self.assertAlmostEqual(sum(rationale["scenario_mixture_weights"].values()),1)
        self.assertIn("start_consistency_rating",rationale["observed_feature_names"])
        self.assertIn("wave_height_cm",rationale["observed_weather_names"])
        self.assertFalse(rationale["weights_learned"])
        self.assertFalse(rationale["rationale_is_postrace_causation"])

    def test_reuse_four_existing_PR71_models_no_new_75_slot_filler(self):
        if not PR71.is_dir():
            self.skipTest("PR71 pinned checkout unavailable")
        from race_ai.boat_existing_asset_integration import run_PR71_existing_all_four_model_families
        from race_ai.comprehensive_four_sport_models import feature_inventory, SCHEMA
        inv=feature_inventory("boat")
        runner=inv["common_required"]+inv["sport_required"]
        weather=inv["environment_required"]
        def obs(value):
            return {"value":value,"published_at":"2030-04-01T09:00:00+09:00",
                    "captured_at":"2030-04-01T10:00:00+09:00",
                    "source_ref":"synthetic://fixture","source_rights_ref":"synthetic-test",
                    "sample_n":5,"transform_id":"synthetic-only-v1"}
        participants=[{
            "number":i,"identity":str(4000+i),"draw":i,"style":"unknown",
            "group_id":None,
            "features":{key:obs(round(.35+.06*i+.01*n,4))
                        for n,key in enumerate(runner)}
        } for i in range(1,7)]
        env_values={"wind_mps":3.5,"rain_mm_h":0.1,"humidity_pct":70,
                    "air_temp_c":22,"surface_wetness":.1,"wave_cm":9}
        environment={key:obs(env_values.get(key,.25)) for key in weather}
        snapshot={"schema":SCHEMA,"scope":"SYNTHETIC_ONLY",
                  "race":{"race_id":"boat:2030-04-01:fictional-venue:1",
                          "sport":"boat","venue":"fictional-venue",
                          "event_date_jst":DAY,
                          "sales_cutoff_at":"2030-04-01T10:59:00+09:00",
                          "as_of":ASOF,"distance_m":1800,"surface":"water",
                          "race_kind":"synthetic-test","race_revision":1},
                  "participants":participants,"environment":environment}
        suite=run_PR71_existing_all_four_model_families(snapshot)
        self.assertEqual(len(suite["models"]),4)
        for model in suite["models"].values():
            self.assertEqual(len(model["ordered_top8"]),8)
            self.assertEqual(len(model["candidates"]),120)
            self.assertFalse(model["official_prediction"])
        self.assertIsNone(suite["external_timestamp_receipts"])
        broken=copy.deepcopy(snapshot)
        del broken["participants"][0]["features"]["start_reliability"]
        with self.assertRaisesRegex(ValueError,"required features missing"):
            run_PR71_existing_all_four_model_families(broken)

    def test_out_of_time_but_complete_exhibition_still_rejected(self):
        if not PR71.is_dir():
            self.skipTest("PR71 pinned checkout unavailable")
        racelist,aux=full_fixture()
        aux["exhibition_by_lane"]["1"]["captured_at"]="2030-04-01T10:50:00+09:00"
        with self.assertRaisesRegex(ValueError,"not prior"):
            run_pr71_existing_multi_models(
                racelist,aux,original_published_verified=True,
                source_admission=lambda *_: True)


if __name__=="__main__":
    unittest.main()
