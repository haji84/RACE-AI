"""Synthetic-only K manifest and strict PR64 exhibition/weather feature tests."""
import copy
import unittest

from race_ai.boat_k_history_dedup_contract import (
    HistoricalSourceError, index_admitted_K_sources, prior_rows_by_racer
)
from race_ai.boat_preview_weather_evidence import (
    PreviewGateError, normalize_existing_PR64_beforeinfo, relative_wind_to_course,
)

ASOF="2030-04-01T10:40:00+09:00"
DAY="2030-04-01"
CUT="2030-04-01T11:00:00+09:00"
CAP="2030-04-01T10:35:00+09:00"
PUB="2030-04-01T09:00:00+09:00"

def source(day="2030-03-31",sha="a"*64):
    import datetime
    d=datetime.date.fromisoformat(day)
    return {"kind":"K","event_date_jst":day,
            "source_url":f"https://www1.mbrace.or.jp/od2/K/{d:%Y%m}/k{d:%y%m%d}.lzh",
            "sha256":sha,"captured_at":"2030-04-01T08:00:00+09:00",
            "published_at":"2030-03-31T23:00:00+09:00",
            "purpose_rights_ref":"fictional-agreement",
            "admitted_for_history":True}

def admitted(*args):return True

def Krow():
    return {"race_id":"20300331-18-01","lane":1,"racer_id":"4001",
            "course":1,"st":.17,"st_status":"OK","finish":1,
            "source_sha256":"a"*64,
            "captured_at":"2030-04-01T08:00:00+09:00",
            "published_at":"2030-03-31T23:00:00+09:00"}

def preview():
    return {"race_id":"20300401-18-01","kind":"beforeinfo","status":"AVAILABLE",
            "body_identity_verified":True,"closed_at":CUT,
            "captured_at":CAP,
            "data":{"boats":[{"lane":i,"racer_registration_id":f"400{i}",
                              "display_time":6.8,
                              "preview_st_status":"OK" if i!=6 else "F",
                              "preview_st":.15 if i!=6 else None} for i in range(1,7)],
                    "weather":{"wind_speed_mps":7.0,"wave_height_cm":12.0,
                               "wind_direction_source_code":4}}}

def bearing():
    return {"source_ref":"https://example.org/fictional-bearing",
            "observed_or_valid_at":PUB,"captured_at":CAP,
            "source_rights_ref":"fictional-rights-only",
            "reviewed_by":"fictional-reviewer","review_reference":"fictional-review",
            "coordinate_system":"TRUE_NORTH_DEGREES"}

class KManifestTests(unittest.TestCase):
    def test_dedup_exact_archive_and_rows_without_double_counting(self):
        src=source()
        man=index_admitted_K_sources([src,src],as_of=ASOF,event_date_jst=DAY,
                                      assert_rights=admitted)
        self.assertEqual(man["duplicate_exact_sources_skipped"],1)
        self.assertEqual(man["source_count"],1)
        rows=prior_rows_by_racer([Krow(),Krow()],man,as_of=ASOF,
                   event_date_jst=DAY,racer_ids=[f"400{i}" for i in range(1,7)])
        self.assertEqual(len(rows["4001"]),1)
        self.assertEqual(len(rows["4002"]),0)

    def test_duplicate_date_conflicting_revision_fails(self):
        with self.assertRaisesRegex(HistoricalSourceError,"conflicting"):
            index_admitted_K_sources([source(),source(sha="b"*64)],
                                     as_of=ASOF,event_date_jst=DAY,assert_rights=admitted)

    def test_publication_and_source_rights_are_not_fabricated(self):
        for wrong in (None,lambda *_: False):
            with self.subTest(wrong=str(wrong)),self.assertRaises(HistoricalSourceError):
                index_admitted_K_sources([source()],as_of=ASOF,
                    event_date_jst=DAY,assert_rights=wrong)
        s=source()
        s["published_at"]=None
        with self.assertRaises(HistoricalSourceError):
            index_admitted_K_sources([s],as_of=ASOF,event_date_jst=DAY,
                                     assert_rights=admitted)

    def test_future_K_and_after_cutoff_K_are_rejected(self):
        s=source(day="2030-04-01")
        with self.assertRaisesRegex(HistoricalSourceError,"target-day"):
            index_admitted_K_sources([s],as_of=ASOF,event_date_jst=DAY,
                                     assert_rights=admitted)
        s=source()
        s["captured_at"]="2030-04-01T11:01:00+09:00"
        with self.assertRaisesRegex(HistoricalSourceError,"unavailable"):
            index_admitted_K_sources([s],as_of=ASOF,event_date_jst=DAY,
                                     assert_rights=admitted)

    def test_K_F_never_means_numeric_ST_zero(self):
        man=index_admitted_K_sources([source()],as_of=ASOF,
                            event_date_jst=DAY,assert_rights=admitted)
        r=Krow()
        r["st_status"]="F";r["st"]=None
        rows=prior_rows_by_racer([r],man,as_of=ASOF,event_date_jst=DAY,
                                  racer_ids=[f"400{i}" for i in range(1,7)])
        self.assertEqual(rows["4001"][0]["st_status"],"F")
        invalid=copy.deepcopy(r)
        invalid["st"]=0
        with self.assertRaisesRegex(HistoricalSourceError,"numeric zero"):
            prior_rows_by_racer([invalid],man,as_of=ASOF,event_date_jst=DAY,
                                racer_ids=[f"400{i}" for i in range(1,7)])

    def test_retrospective_result_cannot_become_pre_cutoff_evidence(self):
        man=index_admitted_K_sources([source()],as_of=ASOF,
                            event_date_jst=DAY,assert_rights=admitted)
        r=Krow()
        r["captured_at"]="2030-04-01T12:00:00+09:00"
        with self.assertRaisesRegex(HistoricalSourceError,"future K"):
            prior_rows_by_racer([r],man,as_of=ASOF,event_date_jst=DAY,
                               racer_ids=[f"400{i}" for i in range(1,7)])

class ExhibitionWeatherEvidenceTests(unittest.TestCase):
    def test_pr64_exhibition_ST_F_kept_non_numeric_and_weather_gaps(self):
        r=normalize_existing_PR64_beforeinfo(preview(),as_of=ASOF)
        self.assertEqual(r["observed_display_count"],6)
        self.assertEqual(r["observed_ST_numeric_count"],5)
        self.assertEqual(r["missing_by_lane"]["6"]["exhibition_start_seconds"],
                         "NON_NUMERIC_F_L")
        self.assertNotIn("exhibition_start_seconds",
                         r["observed_exhibition_by_lane"]["6"]["features"])
        self.assertEqual(r["observed_weather"]["wind_speed_mps"],7)
        self.assertEqual(r["source_wind_direction_code_uninterpreted"],4)
        self.assertEqual(r["missing_environment"]["wind_relative_to_course"],
                         "GEOMETRY_UNKNOWN")
        self.assertFalse(r["fully_admitted_for_PR71"])

    def test_asof_after_cutoff_or_before_capture_rejected(self):
        with self.assertRaisesRegex(PreviewGateError,"cutoff"):
            normalize_existing_PR64_beforeinfo(preview(),
                                                as_of="2030-04-01T11:00:00+09:00")
        with self.assertRaisesRegex(PreviewGateError,"before cutoff"):
            normalize_existing_PR64_beforeinfo(preview(),
                                                as_of="2030-04-01T10:30:00+09:00")

    def test_missing_ST_is_not_imputed_and_source_status_mismatch_rejected(self):
        obj=preview()
        obj["data"]["boats"][5]["preview_st"]=0
        with self.assertRaisesRegex(PreviewGateError,"conflicts"):
            normalize_existing_PR64_beforeinfo(obj,as_of=ASOF)

    def test_known_bearing_cosine_sign_is_explicit(self):
        ev=bearing()
        out=relative_wind_to_course(wind_from_true_degrees=90,
             outbound_race_course_true_degrees=90,
             wind_evidence=ev,course_geometry_evidence=ev)
        self.assertEqual(out["wind_relative_to_course"],1.0)
        opposite=relative_wind_to_course(wind_from_true_degrees=270,
             outbound_race_course_true_degrees=90,
             wind_evidence=ev,course_geometry_evidence=ev)
        self.assertEqual(opposite["wind_relative_to_course"],-1.0)
        self.assertFalse(out["verified_for_model_admission"])

    def test_icon_number_is_not_a_bearing(self):
        ev=bearing()
        ev["coordinate_system"]="BOATRACE_CSS_ICON"
        with self.assertRaisesRegex(PreviewGateError,"not true bearing"):
            relative_wind_to_course(wind_from_true_degrees=4,
                outbound_race_course_true_degrees=90,
                wind_evidence=ev,course_geometry_evidence=bearing())

if __name__=="__main__":
    unittest.main()
