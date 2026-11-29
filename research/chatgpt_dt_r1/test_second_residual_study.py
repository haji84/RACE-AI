"""Checks for the conditional second-place DT-R1 experiment."""
from math import log
import unittest

import numpy as np

from research.chatgpt_dt_r1.boosted_first_study import _joint, marginal
from research.chatgpt_dt_r1.model import RankModel
from research.chatgpt_dt_r1.second_residual_study import _correct_joint, _second_groups


class ConditionalSecondStudyTests(unittest.TestCase):
    def setUp(self):
        self.frozen = RankModel.zero(('form',))
        self.frozen.weights[:, 0] = [.3, .6, -.5, -.1]
        self.row = dict(
            riders=[dict(car=car, competition_points=points)
                    for car, points in ((8, 90), (2, 70), (5, 80), (1, 85))],
            features=np.array([[.5], [1.], [2.], [-.5]]), feature_names=('form',),
            lines_known=True, line_groups=[[8, 2], [5], [1]],
        )

    def test_group_keeps_second_candidates_in_roster_order_and_pair_direction(self):
        group, = _second_groups(self.frozen, self.row, [0], observed_first=8)
        self.assertEqual(group.first, 8)
        self.assertEqual(group.seconds, (2, 5, 1))
        np.testing.assert_array_equal(group.features[:, :7], [
            [1., 1., 1., 0., 1., -1., 0.],
            [2., 0., 0., 0., 0., 0., 1.],
            [-.5, 0., 0., 0., 0., 0., 1.],
        ])
        np.testing.assert_allclose(group.features[:, 7], marginal(_joint(self.frozen, self.row), count=1)[(8,)])
        self.assertAlmostEqual(float(np.exp(group.offsets).sum()), 1.)

    def test_correction_moves_one_exacta_group_and_preserves_first_and_third(self):
        groups = _second_groups(self.frozen, self.row, [0])
        self.assertEqual([group.first for group in groups], [8, 2, 5, 1])
        for group in groups:
            self.assertEqual(len(group.seconds), 3)
            self.assertNotIn(group.first, group.seconds)
        frozen = _joint(self.frozen, self.row)
        corrected = _correct_joint(frozen, groups, np.array([log(2.), 0., 0., *([0.] * 9)]))
        old_pair, new_pair = marginal(frozen, count=2), marginal(corrected, count=2)
        self.assertEqual(corrected.keys(), frozen.keys())
        self.assertEqual(new_pair.keys(), old_pair.keys())
        np.testing.assert_allclose(list(marginal(corrected, count=1).values()),
                                   list(marginal(frozen, count=1).values()), atol=1e-12, rtol=0.)
        self.assertAlmostEqual(new_pair[(8, 2)] / new_pair[(8, 5)], 2 * old_pair[(8, 2)] / old_pair[(8, 5)])
        self.assertAlmostEqual(new_pair[(2, 5)], old_pair[(2, 5)])
        for order, probability in corrected.items():
            self.assertAlmostEqual(probability / new_pair[order[:2]], frozen[order] / old_pair[order[:2]])

    def test_zero_correction_preserves_every_trifecta_probability(self):
        groups = _second_groups(self.frozen, self.row, [0])
        frozen = _joint(self.frozen, self.row)
        corrected = _correct_joint(frozen, groups, np.zeros(12))
        np.testing.assert_allclose(list(corrected.values()), list(frozen.values()), atol=1e-12, rtol=0.)
        with self.assertRaises(ValueError):
            _correct_joint(frozen, groups, np.zeros(11))
