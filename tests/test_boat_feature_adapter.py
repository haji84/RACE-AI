"""No live scraping: adapter contract tests use only synthetic source-like facts."""
import unittest
from copy import deepcopy

from race_ai.boat_feature_adapter import from_approved_features, FeatureModelError
from race_ai.boat_multi_feature_models import run_models

def data():
    racelist={
        "race_id":"20300401-16-01","venue":"16","date_jst":"2030-04-01",
        "closed_at":"2030-04-01T10:59:00+09:00",
        "source_url":"https://example.org/fictional_racelist",
        "first_observed_at":"2030-04-01T10:01:00+09:00",
        "boats":[{"lane":i,"racer_registration_id":str(4000+i),
                  "motor_no":20+i,"national_win_rate":float(3+i),
                  "local_win_rate":float(2+i/2)} for i in range(1,7)]
    }
    common={"source_ref":"https://example.org/fictional_form",
            "published_at":"2030-04-01T10:01:00+09:00",
            "captured_at":"2030-04-01T10:35:00+09:00"}
    history={}
    motor={}
    exhibition={}
    for i in range(1,7):
        pid=str(4000+i)
        prior=[{"race_id":f"r{20300331-j}-{pid}","race_day":f"2030-03-{31-j:02d}",
                 "finish_position":1+(i+j)%6,"start_seconds":0.1+0.01*j}
               for j in range(5)]
        history[pid]={**common,"last_races":prior}
        motor[str(20+i)]={**common,"motor_two_place_rate_percent":20.+8*i}
        exhibition[str(i)]={**common,"exhibition_time_seconds":6.8-0.03*i,
                            "exhibition_start_seconds":.11+0.02*i}
    weather={**common,"wind_speed_mps":5,"wave_height_cm":12,
             "wind_relative_to_course":0.65,"wet_surface_factor":.0}
    aux={"as_of":"2030-04-01T10:42:00+09:00",
         "history_by_racer":history,"motor_by_number":motor,
         "exhibition_by_lane":exhibition,"weather":weather}
    return racelist,aux

def admitted(_source,_purpose):
    return True

class FeatureAdapterTest(unittest.TestCase):
    def test_denies_unauthorized_input_by_default(self):
        racelist,aux=data()
        with self.assertRaisesRegex(FeatureModelError,"not admitted"):
            from_approved_features(racelist,aux)

    def test_maps_every_required_field_and_predicts_both_models(self):
        racelist,aux=data()
        s=from_approved_features(racelist,aux,admit_source=admitted)
        self.assertEqual(len(s["entrants"]),6)
        self.assertEqual(s["entrants"][0]["features"]["ability_rating"],40.)
        self.assertEqual(s["entrants"][0]["features"]["motor_rating"],28.)
        self.assertGreater(s["entrants"][0]["features"]["recent_form_rating"],0)
        self.assertEqual(s["scope"],"OPERATOR_SUPPLIED_RESEARCH")
        outcomes=run_models(s)
        self.assertEqual(len(outcomes),2)
        self.assertTrue(all(len(v["candidates"])==120 for v in outcomes.values()))
        self.assertTrue(all(not v["official_prediction"] for v in outcomes.values()))

    def test_missing_history_exhibition_or_motor_fails_closed(self):
        for section,key in (("history_by_racer","4001"),("motor_by_number","21"),("exhibition_by_lane","1")):
            with self.subTest(section=section):
                racelist,aux=data()
                del aux[section][key]
                with self.assertRaisesRegex(FeatureModelError,"missing"):
                    from_approved_features(racelist,aux,admit_source=admitted)

    def test_same_day_result_is_not_a_historical_input(self):
        racelist,aux=data()
        aux["history_by_racer"]["4001"]["last_races"][0]["race_day"]="2030-04-01"
        with self.assertRaisesRegex(FeatureModelError,"historical result leakage"):
            from_approved_features(racelist,aux,admit_source=admitted)

    def test_future_exhibition_is_not_a_prediction_input(self):
        racelist,aux=data()
        aux["exhibition_by_lane"]["1"]["captured_at"]="2030-04-01T10:50:00+09:00"
        with self.assertRaisesRegex(FeatureModelError,"not prior"):
            from_approved_features(racelist,aux,admit_source=admitted)

    def test_neither_method_reads_odds_or_other_race_results(self):
        racelist,aux=data()
        racelist["boats"][0]["odds3t"]=100.0
        # Adapter consumes only explicit allowed racelist columns.
        # Upstream must never pass arbitrary market fields to feature model.
        with self.assertRaisesRegex(FeatureModelError,"market"):
            from_approved_features(racelist,aux,admit_source=admitted)

if __name__=="__main__":
    unittest.main()
