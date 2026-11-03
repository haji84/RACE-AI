"""Offline deadline queue tests: NO historical outcomes and NO source calls."""
import unittest
from copy import deepcopy
from race_ai.boat_deadline_queue import select_due_races

CLOCK = "2026-11-03T11:20:00+09:00"

def race(venue, number, hhmm):
    return {"race_id": f"20261103-{venue:02d}-{number:02d}",
            "cutoff_at": f"2026-11-03T{hhmm}:00+09:00",
            "schedule_captured_at": "2026-11-03T11:00:00+09:00",
            "source_sha256": "a"*64}

class DeadlineQueueTests(unittest.TestCase):
    def test_nationwide_cutoff_order_and_tie_break(self):
        rows = [race(17, 4, "11:47"), race(7, 3, "11:28"),
                race(22, 3, "11:25"), race(1, 5, "11:28")]
        out = select_due_races(rows, CLOCK)
        self.assertEqual([x["race_id"] for x in out["eligible"]],
                         ["20261103-22-03", "20261103-01-05", "20261103-07-03"])
        self.assertEqual(len(out["deferred"]), 1)
        self.assertFalse(out["freeze_proven"])
        self.assertFalse(out["forecast_generated"])

    def test_no_late_or_repeated_forecast_and_safe_boundary(self):
        rows = [race(17, 3, "11:19"), race(17, 4, "11:23"),
                race(17, 5, "11:24"), race(17, 6, "11:25")]
        o = select_due_races(rows, CLOCK, already_frozen=frozenset({"20261103-17-06"}))
        self.assertEqual([v["race_id"] for v in o["eligible"]], ["20261103-17-05"])
        self.assertEqual([x["reason"] for x in o["rejected"]],
                         ["TOO_LATE_OR_UNSAFE", "TOO_LATE_OR_UNSAFE", "ALREADY_FROZEN"])

    def test_invalid_clock_sha_capture_duplicate_and_dates_fail_closed(self):
        row = race(17, 4, "11:30")
        bad=[]
        for key, value in (("schedule_captured_at", "2026-11-03T11:21:00+09:00"),
                           ("cutoff_at", "2026-11-04T11:30:00+09:00"),
                           ("source_sha256", "bad"), ("race_id", "20261103-99-01")):
            x = deepcopy(row); x[key] = value; bad.append([x])
        bad.extend([[row, deepcopy(row)], [{**row, "result": "1-2-3"}]])
        for rows in bad:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                select_due_races(rows, CLOCK)
        with self.assertRaises(ValueError):
            select_due_races([row], "2026-11-03T11:20:00")

    def test_empty_and_capacity(self):
        self.assertEqual(select_due_races([], CLOCK)["eligible"], [])
        rows = [race(i, 1, "11:31") for i in (17, 11, 24)]
        o=select_due_races(rows, CLOCK, max_items=1)
        self.assertEqual(o["eligible"][0]["race_id"], "20261103-11-01")
        self.assertEqual([x["reason"] for x in o["deferred"]],
                         ["CAPACITY_DEFERRED", "CAPACITY_DEFERRED"])

if __name__ == "__main__":
    unittest.main()
