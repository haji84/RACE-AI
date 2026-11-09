"""Only synthetic WINTICKET indexed public links and SSR race list."""
from __future__ import annotations

from datetime import datetime
import json
import unittest

from race_ai.keirin_winticket_day_index import (
    extract_owner_winticket_day,safe_day_index_summary,
    WinticketDayIndexError
)

URL="https://www.winticket.jp/keirin/odds/20261110"
START_DAY="20261108"
RACES=[
  ("031220261110","aomori","12",3,3),
  ("047520261110","matsuyama","75",3,4),
  ("032120261110","yahiko","21",3,3),
]


def synthetic_day(*,alter=None,missing_link=None):
    rows=[]
    links=[]
    for key,slug,code,meetingday,number in RACES:
        rows.append({
            "id":key,"number":number,
            "closeAt":int(datetime.fromisoformat(
                "2026-11-10T09:26:00+09:00").timestamp()),
            "startAt":int(datetime.fromisoformat(
                "2026-11-10T09:31:00+09:00").timestamp()),
            "entriesNumber":7,
        })
        if missing_link!=key:
            links.append(
              f'<a href="/keirin/{slug}/odds/{START_DAY}{code}/'
              f'{meetingday}/{number}">Race</a>')
    state={
        "redux":{},
        "tanStackQuery":{"queries":[{
            "state":{"data":{"races":rows}}
        }]},
        "unixnow":1794300000,
    }
    if alter:alter(state,links)
    return ("<html><body>"+''.join(links)+
            '<script>window.__PRELOADED_STATE__ = '+
            json.dumps(state,separators=(",",":"))+
            ';</script></body></html>').encode("utf-8")


class WinticketDayIndexTests(unittest.TestCase):
    def test_matching_ssr_and_actual_venue_links_build_verified_roster(self):
        report=extract_owner_winticket_day(
            synthetic_day(),source_url=URL,event_day="2026-11-10")
        self.assertEqual(report["published_ssr_race_count"],3)
        self.assertEqual(report["linked_races_verified"],3)
        self.assertTrue(report["matching_public_ssr_and_href_coverage"])
        self.assertFalse(report["complete_national_schedule_independently_verified"])
        self.assertFalse(report["source_prediction_inputs_complete"])
        row=next(x for x in report["public_schedule_rows"]
                 if x["race_id"]=="202611101203")
        self.assertEqual(row["venue_code"],12)
        self.assertEqual(row["race_no"],3)
        self.assertEqual(row["odds_public_url"],
            "https://www.winticket.jp/keirin/aomori/odds/2026110812/3/3")
        self.assertEqual(row["racecard_public_url"],
            "https://www.winticket.jp/keirin/aomori/racecard/2026110812/3/3")
        safe=safe_day_index_summary(report)
        self.assertNotIn("public_schedule_rows",safe)
        self.assertEqual(safe["published_ssr_race_count"],3)

    def test_unpublished_or_missing_href_never_claims_complete_index(self):
        report=extract_owner_winticket_day(
            synthetic_day(missing_link="031220261110"),
            source_url=URL,event_day="2026-11-10")
        self.assertEqual(report["linked_races_verified"],2)
        self.assertFalse(report["matching_public_ssr_and_href_coverage"])
        row=next(x for x in report["public_schedule_rows"]
                 if x["race_id"]=="202611101203")
        self.assertIsNone(row["odds_public_url"])

    def test_untrusted_date_or_venue_race_identity_is_rejected(self):
        for altered in (
            lambda s,l:s["tanStackQuery"]["queries"][0]["state"]["data"][
                "races"][0].update(number=12),
            lambda s,l:s["tanStackQuery"]["queries"][0]["state"]["data"][
                "races"].append(s["tanStackQuery"]["queries"][0]["state"]["data"][
                "races"][0].copy()),
        ):
            with self.subTest(altered=repr(altered)):
                with self.assertRaises(WinticketDayIndexError):
                    extract_owner_winticket_day(
                        synthetic_day(alter=altered),
                        source_url=URL,event_day="2026-11-10")
        with self.assertRaises(WinticketDayIndexError):
            extract_owner_winticket_day(
                synthetic_day(),source_url=URL,
                event_day="2026-11-09")

    def test_duplicate_different_public_links_for_race_fail(self):
        def mutation(state,links):
            links.append(
                '<a href="/keirin/fakevenue/odds/2026110812/3/3">X</a>')
        with self.assertRaisesRegex(WinticketDayIndexError,
                                    "AMBIGUOUS_RACE_HREF"):
            extract_owner_winticket_day(
                synthetic_day(alter=mutation),
                source_url=URL,event_day="2026-11-10")


if __name__=="__main__":
    unittest.main()
