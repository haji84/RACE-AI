"""Contract for actual daily-B cutoff ordering independent of odds or popularity."""
from datetime import datetime
import unittest
from race_ai.boat_deadline_first_selector import all_closing_candidates,pick_first_ready,CloseWindowError

JST="2026-10-24T13:19:56+09:00"
SOURCE={
  "20261024-13-06":"2026-10-24T13:21:00+09:00",
  "20261024-05-07":"2026-10-24T13:23:00+09:00",
  "20261024-09-07":"2026-10-24T13:25:00+09:00",
  "20261024-07-08":"2026-10-24T14:08:00+09:00",
  "20261024-11-08":"2026-10-24T13:31:00+09:00",
}
class DeadlineFirstSelectorTests(unittest.TestCase):
  def test_all_venues_sorted_and_far_future_filtered(self):
    got=all_closing_candidates(SOURCE,now=datetime.fromisoformat(JST),day_jst="20261024")
    self.assertEqual([x["race_id"] for x in got],
                     ["20261024-05-07","20261024-09-07"])
    self.assertTrue(all(2<=x["minutes_remaining_at_selection"]<=10 for x in got))
  def test_extra_venue_before_earliest_candidate_wins(self):
    m=dict(SOURCE,**{"20261024-03-08":"2026-10-24T13:22:00+09:00"})
    result=all_closing_candidates(m,now=datetime.fromisoformat(JST),day_jst="20261024")
    self.assertEqual(result[0]["race_id"],"20261024-03-08")
  def test_cross_midnight_timezone_and_source_date_rejected(self):
    with self.assertRaisesRegex(CloseWindowError,"date mismatch"):
      all_closing_candidates({"20261024-05-07":"2026-10-25T13:23:00+09:00"},
                             now=datetime.fromisoformat(JST),day_jst="20261024")
    with self.assertRaisesRegex(CloseWindowError,"offset"):
      all_closing_candidates({"20261024-05-07":"2026-10-24T13:23:00"},
                             now=datetime.fromisoformat(JST),day_jst="20261024")
  def test_preflight_earliest_complete_not_earliest_incomplete(self):
    a={"race_id":"20261024-05-07","scheduled_cutoff":"2026-10-24T13:23:00+09:00",
       "preview_identity_matched":True,"display_numeric_count":6,"ST_numeric_count":5,
       "wind_available":True,"wave_available":True,
       "collected_before_scheduled_cutoff":True}
    b=dict(a,race_id="20261024-09-07",scheduled_cutoff="2026-10-24T13:25:00+09:00",
           ST_numeric_count=6)
    got=pick_first_ready([a,b])
    self.assertEqual(got["race_id"],"20261024-09-07")
    self.assertIsNone(pick_first_ready([a]))
  def test_earliest_when_all_complete(self):
    a={"race_id":"20261024-05-07","scheduled_cutoff":"2026-10-24T13:23:00+09:00",
       "preview_identity_matched":True,"display_numeric_count":6,"ST_numeric_count":6,
       "wind_available":True,"wave_available":True,
       "collected_before_scheduled_cutoff":True}
    b=dict(a,race_id="20261024-09-07",scheduled_cutoff="2026-10-24T13:25:00+09:00")
    self.assertEqual(pick_first_ready([b,a])["race_id"],a["race_id"])
  def test_does_not_accept_later_observation(self):
    a={"race_id":"20261024-05-07","scheduled_cutoff":"2026-10-24T13:23:00+09:00",
       "preview_identity_matched":True,"display_numeric_count":6,"ST_numeric_count":6,
       "wind_available":True,"wave_available":True,
       "collected_before_scheduled_cutoff":False}
    self.assertIsNone(pick_first_ready([a]))

if __name__=="__main__":unittest.main()
