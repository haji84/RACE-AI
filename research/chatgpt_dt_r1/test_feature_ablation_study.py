"""Parity fixtures for frozen single-column coefficient omissions."""
from dataclasses import replace
import unittest

import numpy as np

from research.chatgpt_dt_r1 import feature_ablation_study as study
from research.chatgpt_dt_r1.model import RankModel


class FeatureAblationTests(unittest.TestCase):
    def fixture(self, seed=42):
        rng = np.random.default_rng(seed)
        frozen = RankModel.zero(('signal', 'flat', 'second', 'tail', 'unused'))
        frozen.weights[:, :] = rng.normal(size=frozen.weights.shape)
        frozen.weights[:3, 3:] = 0.
        frozen.pair_weights[:, :] = rng.normal(size=frozen.pair_weights.shape)
        frozen.temperature = .83
        cars = [4, 2, 1, 7, 3]
        row = dict(feature_names=frozen.feature_names, feature_status='READY', lines_known=True,
            lines_applicable=True, line_groups=[[4, 2, 1], [7, 3]],
            riders=[dict(car=c, competition_points=90 + c) for c in cars],
            features=np.column_stack([rng.normal(size=5), [2.] * 5, rng.normal(size=(5, 3))]))
        return frozen, row

    def test_exact_zero_columns_and_vectorized_probabilities_match_reference(self):
        model, row = self.fixture()
        seen, selected, _, _ = study.batch_trials(model, row, np.arange(5))
        self.assertEqual(seen.tolist(), [True, False, True, False, False])
        self.assertEqual(selected.tolist(), [0, 2])
        stats = study.profile_race(model, row, (4, 2, 7), np.arange(5))
        for i in range(5):
            clone = replace(model, weights=model.weights.copy())
            clone.weights[:3, i] = 0.
            expected = study.native_metrics(clone, row, (4, 2, 7))
            np.testing.assert_allclose(stats.impacts[i], expected - stats.baseline, atol=1e-12, rtol=0.)

    def test_stable_ties_follow_native_order_even_when_car_list_is_unsorted(self):
        model, row = self.fixture()
        model.weights[:, :] = 0.
        model.pair_weights[:, :] = 0.
        model.weights[0, 0] = -.25
        truth = (1, 2, 3)
        stats = study.profile_race(model, row, truth, np.arange(5))
        self.assertEqual(stats.fallbacks, 1)
        clone = replace(model, weights=np.zeros_like(model.weights))
        expected = study.native_metrics(clone, row, truth)
        np.testing.assert_array_equal(stats.impacts[0, :5], (expected - stats.baseline)[:5])
        self.assertEqual(expected[:5].tolist(), [1., 1., 1., 1., 1.])

    def test_vectorized_and_native_controls_agree_across_supported_fields(self):
        for length in (3, 4, 5, 6, 7, 8, 9):
            with self.subTest(length=length):
                model, row = self.fixture(length)
                rng = np.random.default_rng(length)
                cars = rng.permutation(list(range(1, length + 1))).tolist()
                row['features'] = rng.normal(size=(length, 5))
                row['riders'] = [dict(car=car, competition_points=100 + car) for car in cars]
                row['line_groups'] = [cars[:2], cars[2:]]
                truth = tuple(cars[:3])
                profile = study.profile_race(model, row, truth, np.arange(5))
                for column in (0, 1, 2):
                    clone = replace(model, weights=model.weights.copy())
                    clone.weights[:3, column] = 0.
                    expected = study.native_metrics(clone, row, truth) - profile.baseline
                    np.testing.assert_array_equal(profile.impacts[column, :5], expected[:5])
                    np.testing.assert_allclose(profile.impacts[column, 5:], expected[5:], atol=1e-12, rtol=0.)
