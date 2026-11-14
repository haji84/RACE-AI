"""Synthetic page anchor tests, no external web calls or footage."""
import copy
import unittest
from race_ai.keirin_daily_public_catalog import (
  SOURCE_RACECARD,SOURCE_RESULTS,combine,assess_daily_manifest,CatalogError,
)

def entry(meet="2026110812",day=2,n=1,kind="racecard",slug="aomori"):
    return {"href":f"https://www.winticket.jp/keirin/{slug}/{kind}/{meet}/{day}/{n}",
            "text":f"{n}R"}
def index(kind,items,day="2026年11月9日"):
    return {"source_url":SOURCE_RACECARD if kind=="racecard" else SOURCE_RESULTS,
            "heading":f"本日 {day} 出走表一覧",
            "links":items}
class DailySiteCatalogTests(unittest.TestCase):
    def test_dynamic_discovery_not_fixed_83_races(self):
        result=combine("2026-11-09",[
          index("racecard",[
             entry(n=1),entry(n=2),
             entry(meet="2026110774",day=3,n=1,slug="kochi"),
             entry(meet="2026110931",day=1,n=12,slug="matsudo")
          ]),
          index("raceresult",[
              entry(n=1,kind="raceresult"),
              entry(meet="2026110774",day=3,n=1,slug="kochi",kind="raceresult")
          ])])
        self.assertEqual(result["discovered_race_count"],4)
        self.assertEqual(result["discovered_venue_count"],3)
        self.assertEqual(sum(v["listed_on_raceresult_index"] for v in result["races"]),2)
        self.assertFalse(any(x["video_player_verified"] for x in result["races"]))
        self.assertFalse(any(x["rider_tactical_labels_approved"] for x in result["races"]))
        self.assertTrue(assess_daily_manifest(result,target_day_jst="2026-11-09"))

    def test_new_day_meeting_turnover_and_different_race_counts(self):
        result=combine("2026-11-10",[
            index("racecard",[
                entry(meet="2026110812",day=3,n=1,slug="aomori"),
                entry(meet="2026110931",day=2,n=3,slug="matsudo"),
                entry(meet="2026110984",day=2,n=5,slug="takeo")],
                  day="2026年11月10日"),
            index("raceresult",[
                entry(meet="2026110812",day=3,n=1,slug="aomori",kind="raceresult")],
                  day="2026年11月10日")
        ])
        self.assertEqual(result["discovered_race_count"],3)
        self.assertEqual(result["date_jst"],"2026-11-10")
        self.assertNotIn("20261109",result["races"][0]["race_id"])
        self.assertTrue(all(x["race_id"].startswith("20261110")
                         for x in result["races"]))

    def test_wrong_day_header_rejected(self):
        with self.assertRaisesRegex(CatalogError,"PAGE_IS_NOT_REQUESTED_JST_DATE"):
            combine("2026-11-10",[index("racecard",[entry()]),
                index("raceresult",[entry(kind="raceresult")])])

    def test_meet_day_date_mismatch_rejected(self):
        with self.assertRaisesRegex(CatalogError,"RACE_MEETING_DATE_MISMATCH"):
            combine("2026-11-09",[index("racecard",[entry(meet="2026110812",day=1)]),
                index("raceresult",[entry(kind="raceresult")])])

    def test_checksum_detects_any_race_or_cohort_edit(self):
        s=combine("2026-11-09",[
            index("racecard",[entry()]),
            index("raceresult",[entry(kind="raceresult")])])
        s["races"][0]["cohort"]="TRAIN_CANDIDATE" if s["races"][0]["cohort"] != "TRAIN_CANDIDATE" else "UNSEEN_VIDEO_HOLDOUT"
        with self.assertRaisesRegex(CatalogError,"MANIFEST_DIGEST_MISMATCH"):
            assess_daily_manifest(s,target_day_jst="2026-11-09")
    def test_duplicate_meeting_urls_cannot_double_count_same_race(self):
        s=combine("2026-11-09",[
            index("racecard",[entry(),entry()]),
            index("raceresult",[entry(kind="raceresult")])])
        self.assertEqual(s["discovered_race_count"],1)
        self.assertEqual(len({x["race_id"] for x in s["races"]}),1)
    def test_unknown_domains_and_irrelevant_links_excluded(self):
        s=combine("2026-11-09",[
            index("racecard",[entry(),{"href":"https://evil.example/keirin/aomori/racecard/2026110812/2/5","text":"5R"}]),
            index("raceresult",[entry(kind="raceresult"),{"href":"https://www.winticket.jp/keirin/results/","text":"listing"}])])
        self.assertEqual(s["discovered_race_count"],1)

if __name__=="__main__":unittest.main()
