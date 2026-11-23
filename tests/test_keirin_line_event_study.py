import unittest

import numpy as np

from scripts import keirin_line_event_study as study


def card(day, lines=None):
    return {
        'race_id': day + '1101',
        'line_groups': [[1, 2], [3, 4], [5]] if lines is None else lines,
        'riders': [
            {'car': car, 'registration': f'{100000 + car}', 'class': 'A1',
             'competition_points': 80 + car, 'win_rate': 15, 'top2_rate': 28,
             'top3_rate': 41}
            for car in range(1, 6)
        ],
    }


class LineEventHistoryTests(unittest.TestCase):
    def test_observed_back_performance_never_enters_that_same_day(self):
        history = study.History()
        history.observe(card('20260401'), (2, 3, 1, 5, 4), start=3, back=1)
        with self.assertRaisesRegex(ValueError, 'earlier days'):
            history.features(card('20260401'))
        next_card = history.features(card('20260402'))
        np.testing.assert_array_equal(next_card.back_counts, [1, 1, 1, 1, 1])
        self.assertGreater(next_card.individual[1, 3], 0)
        self.assertLess(next_card.individual[0, 3], 0)

    def test_missing_phase_is_absent_and_pair_history_requires_same_current_line(self):
        history = study.History()
        history.observe(card('20260401'), (2, 1, 3, 5, 4), start=3, back=None)
        same = history.features(card('20260402'))
        split = history.features(card('20260402', [[1, 3], [2, 4], [5]]))
        np.testing.assert_array_equal(same.back_counts, np.zeros(5))
        self.assertEqual(same.pair_counts[0, 1], 1)
        self.assertEqual(split.pair_counts[0, 1], 0)

    def test_incomplete_finishes_are_rejected_without_partial_history(self):
        history = study.History()
        with self.assertRaisesRegex(ValueError, 'complete finish'):
            history.observe(card('20260401'), (1, 2, 3, 4, 4), start=3, back=1)
        self.assertTrue(np.all(history.features(card('20260401')).back_counts == 0))


if __name__ == '__main__':
    unittest.main()
