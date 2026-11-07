"""Fictional, reproducible four-sport comprehensive research model tests."""
import copy
import itertools
import math
import unittest

from race_ai.comprehensive_four_sport_models import (
    SCHEMA, SYNTHETIC, RESEARCH, MODEL_IDS, COMMON_REQUIRED,
    SPORT_REQUIRED, SPORT_OPTIONAL, ENV_COMMON, ENV_SPORT, ModelInputError,
    predict, validate, feature_inventory, digest
)

JST_DAY="2030-01-15"
OBS="2030-01-15T08:00:00+09:00"
CAP="2030-01-15T08:01:00+09:00"
ASOF="2030-01-15T09:10:00+09:00"
CUTOFF="2030-01-15T10:00:00+09:00"
SIZE={"boat":6,"keirin":7,"autorace":8,"horse":18}
SURFACE={"boat":"water","keirin":"velodrome","autorace":"track","horse":"turf"}
RANGE_ENV={
 "wind_mps":5,"rain_mm_h":2,"humidity_pct":70,"air_temp_c":18,
 "surface_wetness":.3,"wave_cm":20,"track_temp_c":31
}

def obs(value):
    return {"value":value,"published_at":OBS,"captured_at":CAP,
            "source_ref":"synthetic://fixture","source_rights_ref":"synthetic-fixture",
            "sample_n":12,"transform_id":"synthetic-normalized-good-higher"}

def sample(sport="boat",size=None,scope=SYNTHETIC):
    n=size or SIZE[sport]
    inv=feature_inventory(sport)
    participants=[]
    for i in range(n):
        num=i+1
        features={}
        for j,key in enumerate(inv["common_required"]+inv["sport_required"]):
            features[key]=obs(round(.22+((i*13+j*17)%62)/100,2))
        participants.append({"number":num,"identity":f"synthetic-runner-{num}",
            "draw":num,"style":("front","stalker","closer","allround")[i%4],
            "group_id":f"line-{i//3}" if sport=="keirin" else None,
            "features":features})
    environment={}
    for k in inv["environment_required"]:
        environment[k]=obs(RANGE_ENV.get(k, .3+((len(k)*7)%30)/100))
    return {"schema":SCHEMA,"scope":scope,
            "race":{"race_id":f"{sport}:2030-01-15:fictional-venue:1",
                    "sport":sport,"venue":"fictional-venue",
                    "event_date_jst":JST_DAY,"sales_cutoff_at":CUTOFF,
                    "as_of":ASOF,"distance_m":1800 if sport=="boat" else 2000,
                    "surface":SURFACE[sport],"race_kind":"fictional sample","race_revision":1},
            "participants":participants,"environment":environment}

class FourSportModels(unittest.TestCase):
    def test_each_sport_enumerates_exact_trifecta_universe(self):
        for sport,n in SIZE.items():
            with self.subTest(sport=sport):
                predictions=predict(sample(sport))
                self.assertEqual(tuple(predictions),MODEL_IDS)
                for result in predictions.values():
                    self.assertEqual(result["candidate_count"],n*(n-1)*(n-2))
                    self.assertEqual(len(result["candidates"]),result["candidate_count"])
                    self.assertEqual(len(result["ordered_top8"]),8)
                    self.assertEqual(len(set(tuple(x["combination"]) for x in result["candidates"])),
                                     result["candidate_count"])
                    self.assertAlmostEqual(sum(x["score"] for x in result["candidates"]),1,places=9)
                    self.assertTrue(result["odds_independent"])
                    self.assertFalse(result["trained"])
                    self.assertFalse(result["calibrated"])
                    self.assertFalse(result["official_prediction"])
                    self.assertIsNone(result["external_pre_cutoff_receipt"])
                    self.assertEqual(result["purchase_decision"],"NO_BET")
                    self.assertEqual(result["prediction_sha256"],
                                     digest({k:v for k,v in result.items() if k!="prediction_sha256"}))

    def test_two_models_different_and_scenario_mixture_normalized(self):
        p=predict(sample("keirin"))
        self.assertNotEqual(p[MODEL_IDS[0]]["candidates"],p[MODEL_IDS[1]]["candidates"])
        weights=p[MODEL_IDS[1]]["scenario_weights"]
        self.assertAlmostEqual(sum(weights.values()),1.0)
        self.assertEqual(set(weights),{"FRONT","CLOSING","DISRUPTION"})

    def test_weather_rain_and_wetness_change_scenarios(self):
        raw=sample("horse")
        before=predict(raw)[MODEL_IDS[1]]
        raw["environment"]["rain_mm_h"]["value"]=34
        raw["environment"]["going_wetness"]["value"]=.9
        after=predict(raw)[MODEL_IDS[1]]
        self.assertNotEqual(before["scenario_weights"],after["scenario_weights"])
        self.assertNotEqual(before["prediction_sha256"],after["prediction_sha256"])

    def test_keirin_line_synergy_requires_declared_group(self):
        a=sample("keirin")
        b=copy.deepcopy(a)
        for p in b["participants"]:p["group_id"]=None
        first=predict(a)[MODEL_IDS[0]]
        second=predict(b)[MODEL_IDS[0]]
        self.assertNotEqual(first["candidates"],second["candidates"])

    def test_missing_mandatory_prevents_inventing_data(self):
        raw=sample("auto") if False else sample("autorace")
        del raw["participants"][0]["features"]["machine_reliability"]
        with self.assertRaisesRegex(ModelInputError,"required features missing"):
            predict(raw)

    def test_missing_optional_is_explicitly_reported(self):
        raw=sample("horse")
        result=predict(raw)[MODEL_IDS[0]]
        self.assertIn("workout_form",result["missing_optional_by_participant"][1])
        self.assertIn("paddock_observation",result["missing_optional_by_participant"][1])
        self.assertNotIn("speed_figure",result["missing_optional_by_participant"][1])
        self.assertTrue(result["missing_optional_by_participant"])

    def test_optional_new_evidence_does_not_retroactively_change_other_snapshot(self):
        original=sample("boat")
        before=predict(original)
        later=copy.deepcopy(original)
        later["participants"][0]["features"]["wind_response"]=obs(.93)
        new=predict(later)
        self.assertNotEqual(before[MODEL_IDS[0]]["snapshot_sha256"],
                            new[MODEL_IDS[0]]["snapshot_sha256"])
        self.assertIn("wind_response",before[MODEL_IDS[0]]["missing_optional_by_participant"][1])
        self.assertNotIn("wind_response",new[MODEL_IDS[0]]["missing_optional_by_participant"][1])

    def test_reject_future_publication_capture_and_cutoff(self):
        for field in ("published_at","captured_at"):
            s=sample("boat")
            s["participants"][0]["features"]["ability"][field]="2030-01-15T09:45:00+09:00"
            with self.assertRaisesRegex(ModelInputError,"after as_of"):
                predict(s)
        s=sample("horse")
        s["environment"]["air_temp_c"]["captured_at"]="2030-01-15T10:01:00+09:00"
        with self.assertRaisesRegex(ModelInputError,"after as_of"):
            predict(s)
        s=sample("boat")
        s["race"]["as_of"]=CUTOFF
        with self.assertRaisesRegex(ModelInputError,"precede official sales cutoff"):
            predict(s)

    def test_reject_odds_popularity_payout_and_result_intrusion(self):
        for forbidden in ("odds","popularity_rank","actual_finish","market_implied",
                          "payout_yen","winning_ticket"):
            s=sample("horse")
            s["participants"][0]["features"][forbidden]=obs(.5)
            with self.subTest(field=forbidden):
                with self.assertRaisesRegex(ModelInputError,"market/result leak"):
                    predict(s)

    def test_untrusted_source_is_blocked_for_operator_supplied_data(self):
        s=sample("boat",scope=RESEARCH)
        with self.assertRaisesRegex(ModelInputError,"not externally admitted"):
            predict(s)
        passes=predict(s,allow_source=lambda ref,license_id,purpose:
                       ref=="synthetic://fixture" and purpose=="analysis" and license_id=="synthetic-fixture")
        self.assertEqual(len(passes),2)
        self.assertTrue(all(not v["official_prediction"] for v in passes.values()))

    def test_missing_weather_is_not_substituted(self):
        s=sample("keirin")
        del s["environment"]["wind_mps"]
        with self.assertRaisesRegex(ModelInputError,"race environment"):
            predict(s)
        s=sample("autorace")
        s["environment"]["track_temp_c"]["value"]=float("nan")
        with self.assertRaisesRegex(ModelInputError,"missing / invalid"):
            predict(s)

    def test_exact_sport_field_sizes_and_surface(self):
        s=sample("keirin",size=9)
        self.assertEqual(predict(s)[MODEL_IDS[0]]["candidate_count"],9*8*7)
        s=sample("keirin",size=8)
        with self.assertRaisesRegex(ModelInputError,"sport field size"):
            predict(s)
        s=sample("horse")
        s["race"]["surface"]="water"
        with self.assertRaisesRegex(ModelInputError,"sport/course mismatch"):
            predict(s)

    def test_race_revision_and_entrant_identity_guard(self):
        s=sample("horse")
        s["participants"][1]["number"]=1
        with self.assertRaisesRegex(ModelInputError,"repeated"):
            predict(s)
        s=sample("horse")
        s["race"]["race_revision"]=0
        with self.assertRaisesRegex(ModelInputError,"race revision"):
            predict(s)


    def test_each_observed_optional_feature_changes_model_input_and_score(self):
        # A representative feature from each sport must affect the scoring,
        # rather than merely being listed in documentation.
        keys={"boat":"tide_response","keirin":"equipment_fit",
              "autorace":"vehicle_setup","horse":"pedigree_surface_fit"}
        for sport,key in keys.items():
            with self.subTest(sport=sport,key=key):
                raw=sample(sport)
                raw["participants"][0]["features"][key]=obs(.05)
                one=predict(raw)[MODEL_IDS[0]]
                raw["participants"][0]["features"][key]["value"]=.99
                two=predict(raw)[MODEL_IDS[0]]
                self.assertNotEqual(one["candidates"][0]["score"],
                                    two["candidates"][0]["score"])
                self.assertNotIn(key,one["missing_optional_by_participant"][1])

    def test_early_and_late_feature_snapshots_do_not_edit_prior_prediction(self):
        for sport,feature in (("boat","exhibition_performance"),
                              ("autorace","trial_performance")):
            with self.subTest(sport=sport):
                early=sample(sport)
                p0=predict(early)[MODEL_IDS[0]]
                self.assertIn(feature,p0["missing_optional_by_participant"][1])
                late=copy.deepcopy(early)
                late["participants"][0]["features"][feature]=obs(.96)
                p1=predict(late)[MODEL_IDS[0]]
                self.assertNotEqual(p0["prediction_sha256"],p1["prediction_sha256"])
                self.assertIn(feature,p0["missing_optional_by_participant"][1])
                self.assertNotIn(feature,p1["missing_optional_by_participant"][1])
                self.assertIsNone(p0["external_pre_cutoff_receipt"])
                self.assertFalse(p0["official_prediction"])

    def test_repeatability_and_uncertainty_disclosure(self):
        s=sample("horse")
        a=predict(s)
        b=predict(copy.deepcopy(s))
        self.assertEqual(a,b)
        self.assertEqual(a[MODEL_IDS[0]]["confidence_level"],"UNVERIFIED")
        self.assertFalse(a[MODEL_IDS[1]]["calibrated"])
        self.assertTrue(a[MODEL_IDS[1]]["source_proof_not_equivalent_to_authorization"])

if __name__=="__main__":
    unittest.main()
