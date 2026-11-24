import unittest
from datetime import date

import numpy as np

from scripts import keirin_tactical_history_study as study
from tests.test_keirin_line_event_study import card


class TacticalHistoryTests(unittest.TestCase):
    def test_methods_and_matchups_are_based_on_earlier_registered_riders(self):
        book = study.TacticalHistory()
        sample = card('20260401')
        book.observe(sample, (1, 2, 3, 4, 5), methods=(1, 3), phase=(None,None,None))
        with self.assertRaisesRegex(ValueError, 'earlier days'):
            book.features(sample)
        future = card('20260402')
        normal = book.features(future)
        self.assertGreater(normal.methods[0, 1], 0)
        self.assertGreater(normal.methods[1, 6], 0)
        self.assertGreater(normal.matchups[0, 2, 1], 0)
        self.assertGreater(normal.matchups[1, 0, 6], 0)
        future['riders'][2]['registration'] = '200087'
        np.testing.assert_array_equal(book.features(future).matchups[0, 2], 0)

    def test_same_line_result_does_not_follow_a_changed_line_relationship(self):
        book = study.TacticalHistory()
        book.observe(card('20260401'), (1, 2, 3, 4, 5), methods=(1, 3), phase=(None,None,None))
        new_lineup = card('20260402', [[1, 3], [2, 4], [5]])
        np.testing.assert_array_equal(book.features(new_lineup).matchups[1, 0], 0)

    def test_unknown_method_or_home_does_not_make_a_negative_observation(self):
        book = study.TacticalHistory()
        book.observe(card('20260401'), (1, 2, 3, 4, 5), methods=(None, None), phase=(None,None,1))
        info = book.features(card('20260402'))
        np.testing.assert_array_equal(info.methods, 0)
        self.assertEqual(info.movement[0, 1], 0)
        self.assertGreater(info.movement[0, 2], 0)

    def test_report_uses_publication_day_and_preserves_unknown_contact(self):
        book = study.TacticalHistory()
        book.observe_report(date(2026,4,2), [('100001',1)], [('100001','100002',False)])
        with self.assertRaisesRegex(ValueError, 'earlier days'):
            book.features(card('20260402'))
        info = book.features(card('20260403'))
        self.assertGreater(info.movement[0, study.PHASE_WIDTH+1], 0)
        self.assertLess(info.following[1, 0, 0], 0)
        self.assertGreater(info.following[1, 0, 1], 0)
        np.testing.assert_array_equal(info.following[3, 2], 0)

    def test_archive_with_unknown_line_only_contributes_to_available_history(self):
        book = study.TacticalHistory()
        book.observe_archive('202604011101', ['100001', '100002', '100003', '100004', '100005'],
                             methods=(1, 3))
        info = book.features(card('20260402'))
        self.assertGreater(info.methods[1, 6], 0)
        np.testing.assert_array_equal(info.methods[:, 9:], 0)
        self.assertGreater(info.matchups[1, 0, 6], 0)
        np.testing.assert_array_equal(info.movement, 0)

    def test_archive_runner_method_can_fill_a_missing_grouped_method(self):
        book = study.TacticalHistory()
        book.observe_archive('202604011101', ['100001', '100002', '100003', '100004', '100005'],
                             methods=(1, 3))
        book.observe(card('20260402'), (1, 3, 2, 4, 5), methods=(1, None), phase=(None, None, None))
        history = book.features(card('20260403'))
        self.assertGreater(history.matchups[1, 0, 6], 0)
        self.assertEqual(history.matchup_starts[1, 0], 1)

    def test_invalid_labels_never_create_a_partial_observation(self):
        book = study.TacticalHistory()
        with self.assertRaises(ValueError):
            book.observe(card('20260401'), (1, 2, 3, 4, 5), methods=(3, None), phase=(None,None,None))
        np.testing.assert_array_equal(book.features(card('20260401')).methods, 0)


if __name__ == '__main__':
    unittest.main()
