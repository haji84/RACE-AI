"""Synthetic and manifest-only checks; never download today's race footage."""
from datetime import datetime,timedelta
import unittest

from race_ai.keirin_20261109_83_manifest import VENUES,JST,manifest,digest
from scripts.keirin_today_83_clip_wave import eligible_for_wave

class Nov09Daily83ManifestTests(unittest.TestCase):
 def test_exact_83_races_eight_venues_no_duplicates(self):
  day=manifest()
  self.assertEqual(day["scheduled_races"],83)
  self.assertEqual(day["venues"],8)
  self.assertEqual(len(VENUES),8)
  self.assertEqual(len(day["races"]),83)
  self.assertEqual(len({v["race_id"] for v in day["races"]}),83)
  self.assertEqual(len({v["url"] for v in day["races"]}),83)
  self.assertTrue(all(v["url"].startswith(
      "https://www.winticket.jp/keirin/") for v in day["races"]))
  self.assertTrue(all(not x["full_four_laps_assumed"] for x in day["races"]))
  self.assertTrue(all(not x["actual_start_verified"] for x in day["races"]))

 def test_event_ids_and_meet_day_and_race_number(self):
  rows={v["race_id"]:v for v in manifest()["races"]}
  self.assertEqual(rows["202611091203"]["url"],
    "https://www.winticket.jp/keirin/aomori/raceresult/2026110812/2/3")
  self.assertEqual(rows["202611097403"]["url"],
    "https://www.winticket.jp/keirin/kochi/raceresult/2026110774/3/3")
  self.assertEqual(rows["202611093102"]["url"],
    "https://www.winticket.jp/keirin/matsudo/raceresult/2026110931/1/2")
  self.assertEqual(rows["202611095309"]["scheduled_start_jst"],
    "2026-11-09T23:30:00+09:00")
  self.assertEqual(rows["202611097509"]["scheduled_start_jst"],
    "2026-11-09T23:20:00+09:00")

 def test_only_past_start_plus_delay_in_wave(self):
  now=datetime.fromisoformat("2026-11-09T09:16:00+09:00")
  due=eligible_for_wave(manifest()["races"],now=now,
    window_hours=2.2,max_attempts=40)
  self.assertEqual({x["race_id"] for x in due},
                   {"202611091201","202611091202"})
  self.assertFalse(any(x["race_id"]=="202611091203" for x in due))
  self.assertFalse(any(x["venue_slug"]!="aomori" for x in due))

 def test_no_races_from_wrong_day_or_late_betting(self):
  # An actual start time delay remains a separate status, never filled in.
  at=datetime.fromisoformat("2026-11-09T23:34:00+09:00")
  due=eligible_for_wave(manifest()["races"],now=at,
    window_hours=2.2,max_attempts=40)
  self.assertNotIn("202611095309",{x["race_id"] for x in due})
  at=at+timedelta(minutes=5)
  due=eligible_for_wave(manifest()["races"],now=at,
    window_hours=2.2,max_attempts=40)
  self.assertIn("202611095309",{x["race_id"] for x in due})
  self.assertEqual(
   sum(x["cohort"]=="UNSEEN_VIDEO_HOLDOUT" for x in manifest()["races"]),
   13)
  # Note: real race cancellation/reschedule must be verified independently.
  self.assertTrue(manifest()["start_times_not_official_live_delay_proof"])

 def test_impossible_windows_rejected(self):
  with self.assertRaisesRegex(ValueError,"WINDOW_TOO_WIDE"):
   eligible_for_wave(manifest()["races"],
     now=datetime.now(JST),window_hours=9)
  with self.assertRaisesRegex(ValueError,"UNBOUNDED_CAPTURE_COUNT"):
   eligible_for_wave(manifest()["races"],
     now=datetime.now(JST),max_attempts=83)

if __name__=="__main__":
 unittest.main()
