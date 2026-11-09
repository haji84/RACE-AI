"""Synthetic boundary tests for actual WINTICKET preloaded trifecta parser."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime,timezone
from itertools import permutations
import json
import unittest

from race_ai.keirin_winticket_embedded_odds import (
    EmbeddedOddsError,private_winticket_trifecta,
    stage_private_winticket_odds,
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

    def test_nationwide_nine_riders_full_504_and_private_sha_readback(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import os
        source=page()
        raw=source.decode("utf-8").split("window.__PRELOADED_STATE__ = ",1)[1].split(";</script>",1)[0]
        pre=json.loads(raw)
        data=pre["tanStackQuery"]["queries"][0]["state"]["data"]
        site_id="037520261109"
        data["trifecta"]=[]
        for n,comb in enumerate(permutations(range(1,10),3)):
            price=round(20.5+n/10,1)
            data["trifecta"].append({
                "id":"synthetic-9-"+str(n),
                "key":list(comb),"raceId":site_id,
                "absent":False,"type":3,"unitPrice":100,
                "payoffUnitPrice":100,
                "odds":price,"oddsStr":f"{price:.1f}"
            })
        html=("<html><script>window.__PRELOADED_STATE__ = "
              + json.dumps(pre,separators=(",",":"))
              + ";</script></html>").encode("utf-8")
        kwargs={
            "url":"https://www.winticket.jp/keirin/matsuyama/odds/2026110875/2/3",
            "race_id":"202611097503",
            "captured_at":NOW,"official_cutoff_at":CUTOFF,
        }
        result=private_winticket_trifecta(html,**kwargs)
        self.assertEqual(len(result["odds"]["prices"]),504)
        self.assertEqual(result["receipt"]["combination_count"],504)
        self.assertEqual(result["receipt"]["winticket_race_id"],site_id)
        self.assertEqual(result["receipt"]["schema"],
                         "RACE_AI_KEIRIN_WINTICKET_504_VERIFIED_RECEIPT_V1")
        self.assertEqual(len({tuple(x["triple"]) for x in
                              result["odds"]["prices"]}),504)
        with TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{"GITHUB_ACTIONS":"false","GITHUB_WORKSPACE":""}):
                report=stage_private_winticket_odds(Path(tmp),result)
                self.assertEqual(report["observed_trifecta_rows"],504)
                self.assertEqual(report["full_210_observed_rows"],0)
                self.assertEqual(report["full_504_observed_rows"],504)
                self.assertEqual(report["private_odds_created"],1)
                second=stage_private_winticket_odds(Path(tmp),result)
                self.assertEqual(second["private_odds_created"],0)

    def test_nationwide_url_does_not_accept_another_race_or_wrong_venue_code(self):
        for source in (
            "https://www.winticket.jp/keirin/matsuyama/odds/2026110875/2/3",
            "https://www.winticket.jp/keirin/aomori/odds/2026110875/2/3",
            "https://www.winticket.jp/keirin/aomori/odds/2026110812/3/3",
            "https://www.winticket.jp/keirin/aomori/odds/2026110812/2/4",
            "https://www.winticket.jp/keirin/internal/api/2026110812/2/3"
        ):
            with self.subTest(url=source),self.assertRaises(EmbeddedOddsError):
                self.parse(url=source)

    def test_private_existing_odds_path_saved_once_and_sha_readback(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import os
        from hashlib import sha256
        with TemporaryDirectory() as temp:
            root=Path(temp)
            verified=self.parse()
            with patch.dict(os.environ,{
                "GITHUB_ACTIONS":"false","GITHUB_WORKSPACE":""
            }):
                first=stage_private_winticket_odds(root,verified)
                self.assertEqual(first["private_odds_created"],1)
                self.assertTrue(first["full_210_observed_rows"]==210)
                files=list((root/"odds").glob("*.json"))
                self.assertEqual(len(files),1)
                original=files[0].read_bytes()
                self.assertEqual(len(json.loads(original)["prices"]),210)
                second=stage_private_winticket_odds(root,verified)
                self.assertEqual(second["private_odds_created"],0)
                self.assertEqual(files[0].read_bytes(),original)
                self.assertEqual(len(list(
                    (root/"odds_winticket_receipts").glob("*.json"))),1)
                self.assertEqual(first["observed_price_set_sha256"],
                                 verified["receipt"]["full_210_prices_sha256"])
            self.assertFalse(first["actual_forecast_saved"])

    def test_changed_subsequent_odds_do_not_rewrite_first_saved(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import os
        with TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.dict(os.environ,{
                "GITHUB_ACTIONS":"false","GITHUB_WORKSPACE":""
            }):
                original=self.parse()
                stage_private_winticket_odds(root,original)
                file=next((root/"odds").glob("*.json"))
                original_bytes=file.read_bytes()
                def changed(data):
                    data["trifecta"][0]["odds"]=27.7
                    data["trifecta"][0]["oddsStr"]="27.7"
                    data["oddsUpdatedAt"]=UPDATED+30
                newer=self.parse(page(changed),
                                 captured_at="2026-11-09T08:52:00+09:00")
                report=stage_private_winticket_odds(root,newer)
                self.assertTrue(report["newer_price_candidate_not_overwritten"])
                self.assertEqual(file.read_bytes(),original_bytes)
                self.assertEqual(len(list(
                    (root/"odds_winticket_receipts").glob("*.json"))),2)

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
