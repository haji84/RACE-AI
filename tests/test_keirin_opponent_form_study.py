import unittest

import numpy as np

from scripts import keirin_opponent_form_study as study
from tests.test_keirin_line_event_study import card


class OpponentFormTests(unittest.TestCase):
    def test_full_finishing_order_changes_the_form_even_below_the_podium(self):
        comparison = card('20260401')
        fast = study.OpponentForm()
        slow = study.OpponentForm()
        fast.observe(comparison, (1, 2, 3, 4, 5))
        slow.observe(comparison, (1, 2, 3, 5, 4))
        next_race = card('20260402')
        index = study.FEATURES.index('recent_all_opponents')
        self.assertGreater(fast.features(next_race)[3, index], slow.features(next_race)[3, index])
        with self.assertRaisesRegex(ValueError, 'earlier days'):
            fast.features(comparison)

    def test_missing_scores_do_not_count_as_losses_or_expectation(self):
        previous = card('20260401')
        previous['riders'][3]['competition_points'] = None
        book = study.OpponentForm()
        book.observe(previous, (4, 5, 3, 2, 1))
        np.testing.assert_array_equal(book.features(card('20260402'))[3], np.zeros(len(study.FEATURES)))

    def test_same_venue_form_needs_a_recent_observation_at_that_venue(self):
        book = study.OpponentForm()
        book.observe(card('20260401'), (5, 4, 3, 2, 1))
        tag = study.FEATURES.index('venue_all_opponents_support')
        self.assertGreater(book.features(card('20260403'))[4, tag], 0)
        self.assertEqual(book.features(card('20260405'))[4, tag], 0)
        other = card('20260403')
        other['race_id'] = '202604031201'
        self.assertEqual(book.features(other)[4, tag], 0)

    def test_duplicate_race_rejected(self):
        book = study.OpponentForm()
        race = card('20260401')
        book.observe(race, (1, 2, 3, 4, 5))
        with self.assertRaisesRegex(ValueError, 'already observed'):
            book.observe(race, (1, 2, 3, 4, 5))


class DynamicHeadToHeadTests(unittest.TestCase):
    def test_freezes_all_same_day_features_before_observing_the_day(self):
        day = 900
        race = (('000001', '000002'), (80, 80), (0, 1), (1, 2))
        book = study.DynamicHeadToHead()
        other = study.DynamicHeadToHead()
        np.testing.assert_array_equal(book.features(day, race[0]), np.zeros((2, 2)))
        book.observe_day(day, [race, race])
        other.observe_day(day, [race])
        np.testing.assert_allclose(book.features(day + 1, race[0]), other.features(day + 1, race[0]))
        np.testing.assert_allclose(book.features(day + 60, race[0])[:, 0], [0.06, -0.06])
        with self.assertRaisesRegex(ValueError, 'earlier days'):
            book.features(day, race[0])
        with self.assertRaisesRegex(ValueError, 'increasing'):
            book.observe_day(day, [race])

    def test_missing_identity_and_single_line_have_no_cross_line_comparisons(self):
        book = study.DynamicHeadToHead()
        entries = ('000001', '000002', None)
        book.observe_day(20, [(entries, (80, 80, 90), (0, 0, 1), (2, 3, 1))])
        observed = book.features(21, entries)
        self.assertGreater(observed[0, 0], 0)
        self.assertLess(observed[1, 0], 0)
        np.testing.assert_array_equal(observed[:, 1], np.zeros(3))
        np.testing.assert_array_equal(observed[2], np.zeros(2))


if __name__ == '__main__':
    unittest.main()
