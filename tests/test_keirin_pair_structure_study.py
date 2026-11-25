import unittest
from itertools import permutations

import numpy as np

from scripts import keirin_pair_structure_study as study


class PairStructureTests(unittest.TestCase):
    def setUp(self):
        self.orders = np.array(list(permutations(range(5), 3)))
        probability = np.arange(1., len(self.orders) + 1.)
        self.triples = np.vstack((probability / probability.sum(), probability[::-1] / probability.sum()))
        self.groups = np.array([[0, 0, 1, 1, 2], [0, 0, 0, 1, 1]])
        self.positions = np.array([[0, 1, 0, 1, 0], [0, 1, 2, 0, 1]])
        self.pairs = study.pair_mass(self.orders, self.triples, 5)
        self.features = study.pair_features(self.pairs, self.groups, self.positions)
        self.weights = np.linspace(-.2, .3, self.features.shape[-1])

    def test_both_rider_margins_and_conditional_third_are_preserved(self):
        trial, new = study.adjust_triples(self.orders, self.triples, self.pairs, self.features, self.weights)
        np.testing.assert_allclose(new.sum(1), self.pairs.sum(1), atol=1e-10)
        np.testing.assert_allclose(new.sum(2), self.pairs.sum(2), atol=1e-10)
        np.testing.assert_allclose(study.pair_mass(self.orders, trial, 5), new, atol=1e-10)
        a, b = self.orders[:, :2].T
        np.testing.assert_allclose(trial / new[:, a, b], self.triples / self.pairs[:, a, b], atol=1e-10)
        self.assertGreater(float(np.max(np.abs(new - self.pairs))), 1e-4)

    def test_projected_likelihood_gradient_matches_finite_differences(self):
        result = np.array([[0, 1], [3, 2]])
        objective = lambda w: study.loss_and_gradient(w, [(self.pairs, self.features, result)])[0]
        numeric = [(objective(self.weights + axis) - objective(self.weights - axis)) / 2e-5
                   for axis in np.eye(len(self.weights)) * 1e-5]
        _, gradient = study.loss_and_gradient(self.weights, [(self.pairs, self.features, result)])
        np.testing.assert_allclose(gradient, numeric, atol=1e-7)

    def test_zero_weights_preserve_the_original_probability(self):
        trial, new = study.adjust_triples(self.orders, self.triples, self.pairs, self.features,
                                          np.zeros_like(self.weights))
        np.testing.assert_allclose(trial, self.triples, atol=1e-12)
        np.testing.assert_allclose(new, self.pairs, atol=1e-12)
