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
    racecard_from_public_html,safe_public_racecard_counts,EmbeddedRacecardError
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
            "standing":no%3,"back":no%4,
            "gearRatio":3.92,"style":"両",
            "comment":"fictional research comment",
            "firstRate":22.0,"secondRate":12.0,"thirdRate":18.0,
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
        self.assertGreater(doc["registry_unavailable_count"],300)
        self.assertFalse(doc["full_347_or_437_verified"])
        self.assertNotIn("race/line_order_all_riders",
                         doc["direct_verified_fields"])
        self.assertNotIn("race/late_scratches_substitutions_revisions",
                         doc["direct_verified_fields"])
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
        self.assertGreater(doc["registry_unavailable_count"],300)
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


if __name__=="__main__":
    unittest.main()
