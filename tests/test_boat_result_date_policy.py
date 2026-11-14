"""No fake same-day clock for verified past-date result audits."""
import unittest
from datetime import datetime, timezone
from race_ai.boat_result_date_policy import is_past_or_current_result_day


class ResultDayPolicyTests(unittest.TestCase):
    def test_yesterday_and_older_after_utc_midnight(self):
        now = datetime.fromisoformat('2026-11-03T16:26:00+00:00')  # 11/04 01:26 JST
        self.assertTrue(is_past_or_current_result_day('20261103', now))
        self.assertTrue(is_past_or_current_result_day('20261102', now))

    def test_same_day_and_future_at_jst_boundary(self):
        before = datetime.fromisoformat('2026-11-03T14:59:59+00:00')  # 11/03 23:59 JST
        after = datetime.fromisoformat('2026-11-03T15:00:00+00:00')   # 11/04 00:00 JST
        self.assertTrue(is_past_or_current_result_day('20261103', before))
        self.assertFalse(is_past_or_current_result_day('20261104', before))
        self.assertTrue(is_past_or_current_result_day('20261104', after))
        self.assertFalse(is_past_or_current_result_day('20261105', after))

    def test_invalid_date_or_naive_clock_fail_closed(self):
        now = datetime(2026, 11, 4, tzinfo=timezone.utc)
        for day in ('20261131', '2026-11-03', 'nonsense', '2026113'):
            with self.subTest(day=day), self.assertRaises(ValueError):
                is_past_or_current_result_day(day, now)
        with self.assertRaises(ValueError):
            is_past_or_current_result_day('20261103', datetime(2026, 11, 4))


if __name__ == '__main__':
    unittest.main()
