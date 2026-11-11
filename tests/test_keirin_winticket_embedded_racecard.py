"""Synthetic versions of the actual 2026-11-09 WINTICKET SSR collections.

The proven public racecard had entries, players, records and races arrays.
No real rider data or prices are used by these tests.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import unittest

from race_ai.keirin_winticket_embedded_racecard import (
    racecard_from_public_html,safe_public_racecard_counts,
    safe_public_racecard_key_inventory,EmbeddedRacecardError
)


RACE="202611091203"
URL="https://www.winticket.jp/keirin/aomori/racecard/2026110812/2/3"
CUTOFF="2026-11-09T09:26:00+09:00"
START="2026-11-09T09:31:00+09:00"
CAPTURE="2026-11-09T08:55:16+09:00"
SITE_ID="031220261109"


def fixture(*,size=7,mutation=None):
    players=[]
    records=[]
    entrants=[]
    for no in range(1,size+1):
        ident="P"+str(no)
        entrants.append({
            "number":no,"raceId":SITE_ID,"absent":False,
            "playerId":ident,"playerCurrentTermClass":"A1",
        })
        players.append({"id":ident,"name":"fictional-rider-"+str(no)})
        records.append({
            "playerId":ident,"racePoint":100.5+no,
            "standing":no%3,"home":no%5,"back":no%4,
            "gearRatio":3.92,"style":"両",
            "comment":"fictional research comment",
            "firstRate":22.0,"secondRate":34.0,"thirdRate":52.0,
        })
    meta={"id":SITE_ID,"number":3,"closeAt":int(
            datetime.fromisoformat(CUTOFF).timestamp()),
          "startAt":int(datetime.fromisoformat(START).timestamp()),
          "distance":2000}
    source={
        "entries":entrants,"players":players,
        "records":records,"races":[meta]
    }
    if mutation:
        mutation(source)
    preloaded={
        "redux":{},
        "tanStackQuery":{
            "queries":[{"state":{"data":source}}],
        },
        "unixnow":int(datetime.fromisoformat(CAPTURE).timestamp())
    }
    return (
        "<html><head><script>window.__PRELOADED_STATE__ = "
        + json.dumps(preloaded,separators=(",",":"),ensure_ascii=False)
        + ";</script></head></html>"
    ).encode("utf-8")


class WinticketPublicRacecardTests(unittest.TestCase):
    def parse(self,body=None,**opts):
        return racecard_from_public_html(
            fixture() if body is None else body,
            url=opts.get("url",URL),
            race_id=opts.get("race_id",RACE),
            captured_at=opts.get("captured_at",CAPTURE),
            expected_cutoff_at=opts.get("cutoff_at",CUTOFF)
        )

    def test_real_shape_seven_riders_partial_347_with_unknowns_preserved(self):
        doc=self.parse()
        self.assertEqual(doc["schema"],
                         "RACE_AI_KEIRIN_WINTICKET_RACECARD_SOURCE_PARTIAL_V1")
        self.assertEqual(len(doc["riders"]),7)
        self.assertEqual(doc["registry_checked_count"],347)
        self.assertEqual(doc["registry_verified_count"]+
                         doc["registry_unavailable_count"],347)
        self.assertGreater(doc["registry_verified_count"],7)
        self.assertGreater(doc["registry_unavailable_count"],200)
        self.assertFalse(doc["full_347_or_437_verified"])
        self.assertNotIn("race/line_order_all_riders",
                         doc["direct_verified_fields"])
        self.assertNotIn("race/late_scratches_substitutions_revisions",
                         doc["direct_verified_fields"])
        for no in range(1,8):
            self.assertEqual(doc["direct_verified_fields"][
                f"rider/{no}/home_H_count"],no%5)
        self.assertEqual(doc["direct_verified_fields"]["rider/1/race_score"],
                         101.5)
        self.assertFalse(doc["forecasts_created"])
        s=safe_public_racecard_counts(doc)
        self.assertEqual(s["rider_identity_count"],7)
        self.assertEqual(s["registry_checked_count"],347)
        self.assertNotIn("fictional-rider",json.dumps(s))
        self.assertNotIn("race_point",json.dumps(s))
        self.assertFalse(s["full_model_input_verified"])

    def test_nine_riders_437_factors_no_210_model_switch(self):
        doc=self.parse(fixture(size=9))
        self.assertEqual(len(doc["riders"]),9)
        self.assertEqual(doc["registry_checked_count"],437)
        self.assertGreater(doc["registry_unavailable_count"],200)
        self.assertFalse(doc["full_347_or_437_verified"])
        self.assertEqual(doc["riders"][8]["car_number"],9)

    def test_duplicate_and_wrong_race_players_and_close_clock_fail(self):
        mutations=[
            lambda d:d["entries"].__setitem__(
                1,deepcopy(d["entries"][0])),
            lambda d:d["entries"][0].update(raceId="OTHER"),
            lambda d:d["players"][0].update(id="OTHER"),
            lambda d:d["records"][0].update(playerId="OTHER"),
            lambda d:d["races"][0].update(closeAt=1),
            lambda d:d["entries"][0].update(absent=True),
        ]
        for fn in mutations:
            with self.subTest(fn=repr(fn)),self.assertRaises(
                    EmbeddedRacecardError):
                self.parse(fixture(mutation=fn))

    def test_after_cutoff_or_changed_cutoff_no_retrospective_evidence(self):
        with self.assertRaises(EmbeddedRacecardError):
            self.parse(captured_at="2026-11-09T09:30:00+09:00")
        with self.assertRaises(EmbeddedRacecardError):
            self.parse(cutoff_at="2026-11-09T10:00:00+09:00")
        with self.assertRaises(EmbeddedRacecardError):
            self.parse(url="https://keirin.kdreams.jp/aomori/racecard/2026110812/2/3")

    def test_unobserved_numbers_are_not_backfilled_and_absurd_scores_rejected(self):
        def remove(d):
            d["records"][0].pop("racePoint")
            d["records"][1]["racePoint"]="NOT_A_NUMBER"
        doc=self.parse(fixture(mutation=remove))
        self.assertNotIn("rider/1/race_score",doc["direct_verified_fields"])
        self.assertNotIn("rider/2/race_score",doc["direct_verified_fields"])
        self.assertFalse(doc["full_347_or_437_verified"])



    def test_source_percentages_and_start_time_are_evidence_not_invented_scores(self):
        doc=self.parse()
        values=doc["direct_verified_fields"]
        for car in range(1,8):
            with self.subTest(car=car):
                self.assertAlmostEqual(values[f"rider/{car}/win_rate"],.22)
                self.assertAlmostEqual(values[f"rider/{car}/second_place_rate"],.12)
                self.assertAlmostEqual(values[f"rider/{car}/third_place_rate"],.18)
                self.assertAlmostEqual(values[f"rider/{car}/top_three_rate"],.52)
        self.assertEqual(datetime.fromisoformat(values["race/start_time"]),
                         datetime.fromisoformat(START))
        self.assertEqual(doc["rate_transform"],
                         "WINTICKET_CUMULATIVE_TOP1_TOP2_TOP3_TO_EXCLUSIVE_V2")
        self.assertFalse(doc["rate_denominator_and_reporting_period_independently_verified"])
        self.assertFalse(doc["source_field_rights_independently_verified"])
        self.assertFalse(doc["full_347_or_437_verified"])
        self.assertEqual(doc["registry_checked_count"],347)
        self.assertEqual(doc["registry_verified_count"]+
                         doc["registry_unavailable_count"],347)

    def test_realistic_cumulative_rates_and_high_nonadditive_values(self):
        # Real observed profile example: 8.3 / 19 / 41.6 percent.
        # Top3 is 41.6%, NOT 8.3+19+41.6%.
        def observed(data):
            data["records"][0].update(
                firstRate=8.3,secondRate=19.0,thirdRate=41.6)
            data["records"][1].update(
                firstRate=90.0,secondRate=95.0,thirdRate=99.0)
        values=self.parse(fixture(mutation=observed))["direct_verified_fields"]
        self.assertAlmostEqual(values["rider/1/win_rate"],.083)
        self.assertAlmostEqual(values["rider/1/second_place_rate"],.107)
        self.assertAlmostEqual(values["rider/1/third_place_rate"],.226)
        self.assertAlmostEqual(values["rider/1/top_three_rate"],.416)
        self.assertAlmostEqual(values["rider/2/top_three_rate"],.99)
        self.assertAlmostEqual(values["rider/2/second_place_rate"],.05)
        self.assertAlmostEqual(values["rider/2/third_place_rate"],.04)

    def test_unavailable_or_invalid_home_count_does_not_create_zero(self):
        for invalid in (None,-2,"7",4.5,True):
            def absent(data):
                data["records"][0]["home"]=invalid
            doc=self.parse(fixture(mutation=absent))
            self.assertNotIn("rider/1/home_H_count",
                             doc["direct_verified_fields"])
            self.assertFalse(doc["full_347_or_437_verified"])
        def reported_zero(data):
            data["records"][0]["home"]=0
        doc=self.parse(fixture(mutation=reported_zero))
        self.assertEqual(doc["direct_verified_fields"]["rider/1/home_H_count"],0)

    def test_exact_wind_units_and_source_observed_athlete_age_term(self):
        def real_source_shape(data):
            data["races"][0]["windSpeed"]="2.5 m/s"
            for rider in data["players"]:
                rider["age"]=35
                rider["term"]=112
        report=self.parse(fixture(mutation=real_source_shape))
        observed=report["direct_verified_fields"]
        self.assertAlmostEqual(observed["race/wind_speed"],2.5)
        for number in range(1,8):
            self.assertEqual(observed[f"rider/{number}/age_term_experience"],{
                "age_years":35,"training_term_number":112})
        self.assertEqual(report["registry_verified_count"],83)
        self.assertEqual(report["registry_unavailable_count"],264)
        self.assertFalse(report["source_field_rights_independently_verified"])
        self.assertFalse(report["official_organizer_cutoff_certified"])
        self.assertFalse(report["forecasts_created"])

    def test_wind_without_explicit_mps_or_unknown_age_term_stays_unavailable(self):
        for wind in ("2.5","2.5 km/h","静穏","-1m/s","41 m/s",
                     None,2.5,True,{}, "NaN m/s"):
            def source(data):
                data["races"][0]["windSpeed"]=wind
                data["players"][0]["age"]=-1
                data["players"][0]["term"]="112"
            record=self.parse(fixture(mutation=source))
            with self.subTest(wind=repr(wind)):
                self.assertNotIn("race/wind_speed",
                                 record["direct_verified_fields"])
                self.assertNotIn("rider/1/age_term_experience",
                                 record["direct_verified_fields"])
        def exact_zero(data):
            data["races"][0]["windSpeed"]="0 m/s"
        verified=self.parse(fixture(mutation=exact_zero))
        self.assertEqual(verified["direct_verified_fields"]["race/wind_speed"],0.0)

    def test_missing_or_inconsistent_rates_cannot_fabricate_top_three(self):
        for value in (None, "74", 101, -1):
            def alter(data):
                data["records"][0]["firstRate"]=value
            result=self.parse(fixture(mutation=alter))
            for field in ("win_rate","second_place_rate","third_place_rate",
                          "top_three_rate"):
                self.assertNotIn("rider/1/"+field,
                                 result["direct_verified_fields"])
            self.assertFalse(result["full_347_or_437_verified"])

        # Nonfinite JavaScript NaN is not valid JSON. Reject the whole SSR,
        # rather than attempting to treat its rate as a missing numeric value.
        from race_ai.keirin_winticket_embedded_odds import EmbeddedOddsError
        def nan_value(data):
            data["records"][0]["firstRate"]=float("nan")
        with self.assertRaises(EmbeddedOddsError):
            self.parse(fixture(mutation=nan_value))

        def conflict(data):
            data["records"][0].update(firstRate=74.0,secondRate=37.0,
                                      thirdRate=11.0)
        result=self.parse(fixture(mutation=conflict))
        self.assertNotIn("rider/1/top_three_rate",
                         result["direct_verified_fields"])
        self.assertNotIn("rider/1/win_rate",
                         result["direct_verified_fields"])

    def test_no_start_time_does_not_infer_unverified_schedule(self):
        def remove(data):
            data["races"][0].pop("startAt")
        result=self.parse(fixture(mutation=remove))
        self.assertNotIn("race/start_time",
                         result["direct_verified_fields"])
        self.assertIsNone(result["source_scheduled_start_at_utc"])



    def test_public_safe_field_keys_help_find_missing_source_inputs_only(self):
        html=fixture()
        packet=self.parse(html)
        record=safe_public_racecard_key_inventory(packet,html)
        self.assertEqual(record["race_id"],RACE)
        self.assertEqual(set(record["collection_field_names"]),
                         {"races","players","records","entries"})
        self.assertIn("racePoint",record["collection_field_names"]["records"])
        self.assertIn("firstRate",record["collection_field_names"]["records"])
        self.assertIn("playerId",record["collection_field_names"]["entries"])
        self.assertIn("startAt",record["collection_field_names"]["races"])
        self.assertFalse(record["count_as_verified_347_factors"])
        self.assertFalse(record["new_source_rights_granted"])
        self.assertFalse(record["public_rider_values_or_names_logged"])
        self.assertNotIn("fictional-rider",str(record))
        self.assertNotIn("100.5",str(record))

    def test_field_keys_require_original_sha_no_hidden_values(self):
        packet=self.parse()
        with self.assertRaises(EmbeddedRacecardError):
            safe_public_racecard_key_inventory(
                packet,b"<html>untrusted altered</html>")
        packet["html_sha256"]="0"*64
        with self.assertRaises(EmbeddedRacecardError):
            safe_public_racecard_key_inventory(packet,fixture())


if __name__=="__main__":
    unittest.main()
