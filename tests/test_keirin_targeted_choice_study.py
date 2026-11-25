import unittest

import numpy as np

from scripts import keirin_targeted_choice_study as study
from tests.test_keirin_line_event_study import card


class TargetedChoiceTests(unittest.TestCase):
    def test_previous_day_can_teach_cross_line_second_and_passing_the_front(self):
        book = study.LineRoleHistory()
        book.observe(card('20260401'), (1, 4, 2, 3, 5), start=1, back=3)

        with self.assertRaisesRegex(ValueError, 'earlier days'):
            book.features(card('20260401'))
        next_day = book.features(card('20260402'))
        cross = study.METRICS.index('cross_line_second')
        passed = study.METRICS.index('beat_line_front')
        self.assertGreater(next_day[3, cross], 0)
        self.assertGreater(next_day[3, passed], 0)
        self.assertEqual(next_day[1, cross], 0)
        self.assertEqual(next_day[0, passed], 0)

    def test_rates_require_matching_rider_role_and_observed_b(self):
        book = study.LineRoleHistory()
        book.observe(card('20260401'), (1, 4, 2, 3, 5), start=1, back=None)
        from_other_back = study.METRICS.index('second_from_other_back_line')
        self.assertEqual(book.features(card('20260402'))[3, from_other_back], 0)
        changed = book.features(card('20260402', [[1, 2], [4, 3], [5]]))
        np.testing.assert_array_equal(changed[3], np.zeros(2 * len(study.METRICS)))

    def test_group_calibration_redistributes_only_between_eligible_outcomes(self):
        raw = np.array([[.0, .5, .3, .2], [.25, .25, .5, .0], [0, .8, .2, 0]])
        mask = np.array([[False, False, True, True],
                         [True, True, True, False],
                         [False, False, False, True]])
        adjusted = study.rescale_group(raw, mask, np.array([.6, .7, .9]))
        np.testing.assert_allclose(adjusted[0], [0, .4, .36, .24])
        np.testing.assert_allclose(adjusted[1:], raw[1:])
        np.testing.assert_allclose(adjusted.sum(axis=1), 1.)

    def test_calibration_learns_constant_underprediction(self):
        probabilities = np.full((120, 3), [0.5, 0.25, 0.25])
        member = np.full((120, 3), [False, False, True])
        design = np.ones((120, 1))
        targets = np.r_[np.ones(72), np.zeros(48)]
        correction = study.fit_group_offset(probabilities, member, design, targets)
        corrected = study.calibrate_group(probabilities, member, design, correction)
        self.assertGreater(corrected[0, -1], .55)
        self.assertLess(corrected[0, -1], .62)


if __name__ == '__main__':
    unittest.main()
