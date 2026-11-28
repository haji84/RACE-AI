from itertools import permutations
import unittest

import numpy as np
from scipy.optimize import check_grad

from . import ranking_objective_study as study


class RankingObjectiveTests(unittest.TestCase):
    def sample(self):
        rates = np.array([.42, .22, .13, .10, .08, .05])
        features = np.arange(6 * 8, dtype=float).reshape(6, 8) / 12.
        return study.batch([(np.log(rates), features, 1)])

    def test_zero_tilt_reproduces_frozen_law_and_complete_exacta(self):
        log_base = self.sample().base
        weights = np.zeros(8)
        actual = study.probabilities(self.sample(), weights)
        np.testing.assert_allclose(actual, np.exp(log_base), atol=1e-14)
        self.assertEqual(study.exactas(actual, 3).shape, (1, 6))
        tickets = list(permutations(range(4), 3))
        uniform = study.exactas(np.ones((1, len(tickets))) / len(tickets), 4)
        np.testing.assert_allclose(uniform, [[1 / 12] * 12])

    def test_both_analytic_gradients_and_fixed_frozen_rival(self):
        group = self.sample()
        self.assertEqual(group.rival.tolist(), [0])
        for penalty in (0., .25):
            cost = lambda w: study.objective([group], w, penalty)
            self.assertLess(check_grad(lambda w: cost(w)[0], lambda w: cost(w)[1],
                                       np.full(8, .1)), 2e-6)

    def test_june_uses_proper_guard_before_rank_priority(self):
        proper = dict.fromkeys(study.PROPER_METRICS, 1.)
        rows = {'frozen': dict(n=100, tri1=10, ex1=30, **proper),
                'nll': dict(n=100, tri1=14, ex1=29, **proper),
                'nll_rank': dict(n=100, tri1=20, ex1=34, **dict(proper, ex_brier=1.01))}
        self.assertEqual(study.select(rows), 'nll')
        rows['nll']['tri_log_loss'] = 1.01
        self.assertEqual(study.select(rows), 'frozen')
