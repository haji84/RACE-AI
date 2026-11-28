"""Regression tests for the archive-only history window comparison."""
from copy import deepcopy
from datetime import date, timedelta
import unittest

from research.chatgpt_dt_r1 import history_window_study as study


DAY = date(2026, 7, 21)


def race(age):
    day = DAY - timedelta(days=age)
    riders = [dict(car=car, identity_key=f'rider-{car}', identity_usable=True)
              for car in range(1, 6)]
    outcomes = [dict(car=car, rank=car, incident=False, absence=False, cancelled=False,
                     half_lap_seconds=11.2, final_lap_seconds=23.4, sb_mark='SB')
                for car in range(1, 6)]
    return dict(day=day.isoformat(), race_id=f'{day:%Y%m%d}2401', riders=riders,
                venue_code='24', race_class='S', field_supported=True, result_rows=outcomes)


class HistoryWindowTests(unittest.TestCase):
    def test_accepts_both_oldest_allowed_days_and_never_target_or_future(self):
        rows = [race(age) for age in (31, 30, 8, 7, 1, 0, -1)]
        days = [(date.fromisoformat(row['day']), (row,)) for row in rows]
        actual = {}
        for width in (7, 30):
            state = study.prior_builder(days, DAY, width)
            actual[width] = [(DAY - result['date']).days for result in state.history['rider-1']]
        self.assertEqual(actual, {7: [7, 1], 30: [30, 8, 7, 1]})

    def test_removes_only_unavailable_historical_measurements_without_mutation(self):
        row = race(1)
        original = deepcopy(row)
        projected = study.history_projection(row)
        self.assertEqual(projected['race_class'], 'UNKNOWN')
        self.assertEqual(projected['riders'], original['riders'])
        self.assertEqual([result['rank'] for result in projected['result_rows']], [1, 2, 3, 4, 5])
        for result in projected['result_rows']:
            self.assertTrue(all(result.get(key) is None for key in
                                ('half_lap_seconds', 'final_lap_seconds', 'sb_mark')))
        self.assertEqual(row, original)
        self.assertEqual(study.history_projection(dict(row, race_class='L1'))['race_class'], 'L1')

    def test_partial_or_absent_starters_are_not_turned_into_history(self):
        row = race(1)
        self.assertIsNone(study.history_projection(dict(row, result_rows=row['result_rows'][:-1])))
        row['result_rows'][0].update(rank=None, absence=True)
        self.assertIsNone(study.history_projection(row))


if __name__ == '__main__':
    unittest.main()
