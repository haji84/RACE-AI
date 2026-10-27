"""All-sport pre-cutoff audit queue tests, no external providers."""
import unittest
from race_ai.cutoff_job_queue import plan, QueueError

class TestQueue(unittest.TestCase):
    def test_earliest_cutoff_all_sports_first(self):
        rows=[
            {"race_id":"boat:late","sport":"boat","cutoff_at":"2030-10-22T10:58:00+09:00","cutoff_verified":True,"source_permission_approved":True},
            {"race_id":"keirin:early","sport":"keirin","cutoff_at":"2030-10-22T08:27:00+09:00","cutoff_verified":True,"source_permission_approved":True},
            {"race_id":"boat:middle","sport":"boat","cutoff_at":"2030-10-22T08:35:00+09:00","cutoff_verified":True,"source_permission_approved":True},
            {"race_id":"autorace:missing","sport":"autorace","cutoff_at":None},
        ]
        result=plan(rows, now="2030-10-22T07:00:00+09:00")
        self.assertEqual([r["race_id"] for r in result["jobs"]],
                         ["keirin:early","boat:middle","boat:late","autorace:missing"])
        self.assertEqual(result["all_known_races"],4)
        self.assertEqual(result["jobs"][-1]["state"],"SALES_CUTOFF_NOT_DISCOVERED")
        self.assertTrue(all(j["forecast_frozen"] is False for j in result["jobs"]))

    def test_unverified_rights_or_clock_does_not_become_forecast(self):
        rows=[
            {"race_id":"a","cutoff_at":"2030-10-22T08:00:00+09:00","cutoff_verified":False},
            {"race_id":"b","cutoff_at":"2030-10-22T09:00:00+09:00","cutoff_verified":True},
            {"race_id":"c","cutoff_at":"2030-10-22T06:00:00+09:00","cutoff_verified":True},
        ]
        jobs={j["race_id"]:j for j in plan(rows,now="2030-10-22T07:00:00+09:00")["jobs"]}
        self.assertEqual(jobs["a"]["state"],"SALES_CUTOFF_UNVERIFIED")
        self.assertEqual(jobs["b"]["state"],"SOURCE_PERMISSION_NOT_ADMITTED")
        self.assertEqual(jobs["c"]["state"],"MISSED_DEADLINE")

    def test_duplicate_fails_closed(self):
        with self.assertRaisesRegex(QueueError,"duplicate"):
            plan([{"race_id":"a"},{"race_id":"a"}], now="2030-10-22T07:00:00+09:00")

if __name__ == "__main__":
    unittest.main()
