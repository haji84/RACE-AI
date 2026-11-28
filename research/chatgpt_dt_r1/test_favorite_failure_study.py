from itertools import permutations
from math import fsum
import unittest

import numpy as np

from research.chatgpt_dt_r1 import favorite_failure_study as study
from research.chatgpt_dt_r1.history_mix_study import exacta_marginal


class FavoriteFailureStudyTests(unittest.TestCase):
    def test_favorite_uses_the_winner_marginal_and_lexical_tie_break(self):
        joint = {(1, 2, 3): .22, (1, 3, 2): .18,
                 (2, 1, 3): .33, (2, 3, 1): .07,
                 (3, 1, 2): .13, (3, 2, 1): .07}
        self.assertEqual(study.favorite(dict(reversed(tuple(joint.items())))), (1, .4))

    def test_rescaling_preserves_both_conditional_laws_and_exacta_mass(self):
        joint = {key: 1 / 24 for key in permutations(range(1, 5), 3)}
        corrected = study.correct_joint(joint, 1, .25, .6)
        self.assertEqual(study.correct_joint(joint, 1, .25, .25), joint)
        self.assertEqual(corrected.keys(), joint.keys())
        self.assertAlmostEqual(fsum(corrected.values()), 1.)
        self.assertAlmostEqual(fsum(p for key, p in corrected.items() if key[0] == 1), .6)
        for key, p in joint.items():
            self.assertAlmostEqual(corrected[key] / (.6 if key[0] == 1 else .4),
                                   p / (.25 if key[0] == 1 else .75))
        self.assertAlmostEqual(fsum(exacta_marginal(corrected).values()), 1.)

    def test_context_reads_only_declared_pre_race_line_information(self):
        row = dict(lines_known=True, line_groups=[[4, 1], [2, 3], [5]])
        expected = study.context(row, 1)
        self.assertEqual(expected, (1., 0., .125, .125))
        self.assertEqual(study.context(dict(row, finish=(2, 1, 3), archived_weather='rain'), 1), expected)
        self.assertEqual(study.context(dict(row, lines_known=False), 1), (1., 1., 0., 0.))

    def test_fitter_keeps_frozen_offset_and_regularizes_the_intercept(self):
        design = np.ones((12, 1))
        offset = np.zeros(12)
        labels = np.array([1.] * 9 + [0.] * 3)
        weights, _ = study.fit(design, offset, labels)
        self.assertGreater(weights[0], 0.)
        self.assertLess(weights[0], np.log(3.))
        adjusted = study.adjusted_win_probability(.4, (1.,), np.zeros(1))
        self.assertEqual(adjusted, .4)

    def test_candidate_must_improve_primary_rank_after_all_four_guards(self):
        proper = dict.fromkeys(study.PROPER_METRICS, 1.)
        same = dict(n=100, tri1=10, ex1=30, **proper)
        rows = {'frozen': same, 'intercept': dict(same, tri_brier=.98),
                'context': dict(same, tri1=12, ex_brier=1.01)}
        self.assertEqual(study.select_candidate(rows), 'frozen')
        rows['context']['ex_brier'] = .99
        self.assertEqual(study.select_candidate(rows), 'context')

    def test_target_day_is_never_part_of_its_seven_day_history(self):
        rows = [{'day': day} for day in
                ['2026-02-21', '2026-02-22', '2026-02-28', '2026-03-01', '2026-03-01', '2026-03-02']]
        [(day, targets, earlier)] = list(study.week_groups(rows, '2026-03-01', '2026-03-01'))
        self.assertEqual(str(day), '2026-03-01')
        self.assertEqual(len(targets), 2)
        self.assertEqual([str(d) for d, _ in earlier], ['2026-02-22', '2026-02-28'])
