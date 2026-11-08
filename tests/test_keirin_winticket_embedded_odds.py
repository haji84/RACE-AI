"""Synthetic boundary tests for actual WINTICKET preloaded trifecta parser."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime,timezone
from itertools import permutations
import json
import unittest

from race_ai.keirin_winticket_embedded_odds import (
    EmbeddedOddsError,private_winticket_trifecta,
)
from race_ai.keirin_variable_selection import ODDS_SCHEMA

URL="https://www.winticket.jp/keirin/aomori/odds/2026110812/2/3"
RACE="202611091203"
SOURCE_ID="031220261109"
NOW="2026-11-09T08:50:36+09:00"
CUTOFF="2026-11-09T09:26:00+09:00"
UPDATED=1794181601

def page(mutate=None):
    rows=[]
    for index,comb in enumerate(permutations(range(1,8),3)):
        value=25+0.2*index
        rows.append({
            "id":"synthetic-"+str(index),
            "key":list(comb),
            "raceId":SOURCE_ID,
            "absent":False,
            "type":3,
            "unitPrice":100,
            "payoffUnitPrice":100,
            "popularityOrder":index+1,
            "odds":round(value,1),
            "oddsStr":f"{value:.1f}",
            "minOdds":int(value),
            "minOddsStr":str(int(value)),
            "maxOdds":int(value),
            "maxOddsStr":str(int(value))
        })
    data={
        "trifecta":rows,
        "oddsUpdatedAt":UPDATED,
        "oddsDelayed":False,
        "isAggregated":True,
        "finalOdds":False,
    }
    if mutate:
        mutate(data)
    state={
        "redux":{},
        "tanStackQuery":{"queries":[{
            "queryKey":["odds",{"raceNumber":3},1],
            "state":{"data":data}
        }]},
        "unixnow":UPDATED
    }
    return (
        "<html><body><script>window.__PRELOADED_STATE__ = "
        + json.dumps(state,ensure_ascii=False,separators=(",",":"))
        + ";</script></body></html>"
    ).encode("utf-8")


class EmbeddedTrifectaOddsTests(unittest.TestCase):
    def parse(self,html=None,**kwargs):
        return private_winticket_trifecta(
            page() if html is None else html,
            url=kwargs.get("url",URL),
            race_id=kwargs.get("race_id",RACE),
            captured_at=kwargs.get("captured_at",NOW),
            official_cutoff_at=kwargs.get("cutoff_at",CUTOFF)
        )

    def test_all_210_real_shaped_number_and_string_rows_verified(self):
        result=self.parse()
        p=result["odds"]
        r=result["receipt"]
        self.assertEqual(p["schema"],ODDS_SCHEMA)
        self.assertEqual(len(p["prices"]),210)
        self.assertEqual(len({tuple(x["triple"]) for x in p["prices"]}),210)
        self.assertEqual(p["race_id"],RACE)
        self.assertEqual(r["winticket_race_id"],SOURCE_ID)
        self.assertTrue(r["all_combinations_unique"])
        self.assertTrue(r["all_observed_price_numbers_valid"])
        self.assertTrue(r["all_source_display_odds_equal"])
        self.assertFalse(r["publisher_timestamp_independently_attested"])
        self.assertFalse(r["production_forecasts_saved"])
        self.assertEqual(r["source_odds_updated_at_utc"],
                         datetime.fromtimestamp(UPDATED,timezone.utc).isoformat())

    def test_price_injection_and_undocumented_origin_denied(self):
        for change in (
            {"url":"https://api.winticket.jp/internal/odds"},
            {"url":"https://www.winticket.jp/keirin/aomori/odds/2026110812/3/3"},
            {"url":"https://www.winticket.jp/keirin/aomori/odds/2026110812/2/4"},
            {"race_id":"202611091204"},
            {"cutoff_at":"2026-11-09T08:50:00+09:00"},
            {"captured_at":"2026-11-09T09:25:20+09:00"},
        ):
            with self.subTest(change=change),self.assertRaises(EmbeddedOddsError):
                self.parse(**change)

    def test_one_missing_and_one_duplicate_ticket_both_denied(self):
        cases=[
            lambda d:d["trifecta"].pop(),
            lambda d:d["trifecta"].__setitem__(
                1,deepcopy(d["trifecta"][0])),
            lambda d:d["trifecta"][0].update(key=[1,1,2]),
            lambda d:d["trifecta"][0].update(raceId="OTHER_RACE"),
            lambda d:d["trifecta"][0].update(odds=9999.9),
            lambda d:d["trifecta"][0].update(odds=0),
            lambda d:d["trifecta"][0].update(oddsStr="not available"),
            lambda d:d["trifecta"][0].update(absent=True),
            lambda d:d.update(oddsDelayed=True),
            lambda d:d.update(isAggregated=False),
            lambda d:d.update(finalOdds=True),
            lambda d:d.update(oddsUpdatedAt=1500000000),
        ]
        for alter in cases:
            with self.subTest(alter=repr(alter)):
                with self.assertRaises(EmbeddedOddsError):
                    self.parse(page(alter))

    def test_duplicate_preloaded_state_denied(self):
        html=page()
        self.assertRaises(
            EmbeddedOddsError,self.parse,html+b"window.__PRELOADED_STATE__ = {};"
        )

if __name__=="__main__":
    unittest.main()
