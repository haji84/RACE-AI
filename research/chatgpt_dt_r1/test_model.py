"""Synthetic numerical/leakage checks; these do not measure real race accuracy."""
import copy
import unittest
from itertools import permutations

import numpy as np

from research.chatgpt_dt_r1.model import RankModel, fit_ranker, digest


def fixture(i=0, n=5, day='2026-01-01'):
    cars = list(range(1, n + 1))
    rng = np.random.default_rng(i)
    x = rng.normal(size=(n, 3))
    order = [cars[j] for j in np.argsort(-x[:, 0])]
    return {'race_id': f'synthetic-{i}', 'day': day, 'cohort': 'retrospective',
            'riders': [{'car': c, 'competition_points': 85. + x[j, 0]} for j, c in enumerate(cars)],
            'line_groups': [cars[:2]] + [[c] for c in cars[2:]], 'lines_known': True,
            'features': x, 'feature_names': ('signal', 'noise1', 'noise2'),
            'finish': order, 'top3': order[:3], 'input_sha256': digest({'id': i, 'x': x.tolist()})}


class RankerTests(unittest.TestCase):
    def test_exact_joint_law_and_marginals_every_field(self):
        for n in range(3, 10):
            row = fixture(n, n=n)
            model = RankModel.zero(row['feature_names'])
            dist = model.distribution(row, full=True)
            self.assertEqual(len(dist['trifectas']), n * (n - 1) * (n - 2))
            self.assertAlmostEqual(sum(t['probability'] for t in dist['trifectas']), 1., places=11)
            ranks = np.asarray([m['rank_probabilities'] for m in dist['riders']])
            np.testing.assert_allclose(ranks.sum(0), 1., atol=1e-11)
            np.testing.assert_allclose(ranks.sum(1), 1., atol=1e-11)
            np.testing.assert_allclose(ranks, 1 / n, atol=1e-11)
            pairs = {tuple(t['cars']): t['probability'] for t in dist['exactas']}
            for pair in pairs:
                self.assertAlmostEqual(pairs[pair], sum(t['probability'] for t in dist['trifectas'] if tuple(t['cars'][:2]) == pair))

    def test_subset_dynamic_program_matches_bruteforce(self):
        row = fixture(3, n=5)
        model = RankModel.zero(row['feature_names'])
        model.weights[:, 0] = [.3, -.2, .5, .1]
        model.pair_weights[1:, :3] = [[.5, .7, -.1], [.2, -.6, .3], [.3, .5, -.4]]
        full = model.distribution(row, full=True)
        mass = np.zeros((5, 5))
        for order in permutations(range(1, 6)):
            p = model.order_probability(row, order)
            for pos, car in enumerate(order):
                mass[car - 1, pos] += p
        np.testing.assert_allclose(mass, [r['rank_probabilities'] for r in full['riders']], atol=1e-11)

    def test_fit_learns_signal_without_target_input(self):
        train = [fixture(i, day='2026-01-01') for i in range(75)]
        model = fit_ranker(train, before='2026-02-01', ridge=.03, use_pairs=True, max_iter=100)
        held = [fixture(i + 100, day='2026-03-01') for i in range(30)]
        hits = 0
        for row in held:
            f = model.distribution(row)
            hits += f['trifectas'][0]['cars'] == row['top3']
            changed = copy.deepcopy(row)
            changed['finish'] = list(reversed(row['finish']))
            changed['top3'] = changed['finish'][:3]
            self.assertEqual(f, model.distribution(changed))
        self.assertGreater(hits, 20)

    def test_training_date_duplicate_and_schema_guards(self):
        rows = [fixture(i) for i in range(30)]
        with self.assertRaisesRegex(ValueError, 'TRAINING_DATE'):
            fit_ranker(rows, before='2026-01-01')
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            fit_ranker(rows + [rows[0]], before='2026-02-01')
        model = RankModel.zero(rows[0]['feature_names'])
        bad = copy.deepcopy(rows[0]); bad['features'][0, 0] = np.nan
        with self.assertRaises(ValueError):
            model.distribution(bad)
        bad = copy.deepcopy(rows[0]); bad['feature_names'] = ('wrong', 'noise1', 'noise2')
        with self.assertRaisesRegex(ValueError, 'FEATURE_SCHEMA'):
            model.distribution(bad)

    def test_serialization_is_verified_and_no_pickle(self):
        model = RankModel.zero(('a', 'b'))
        artifact = model.to_dict()
        loaded = RankModel.from_dict(artifact)
        self.assertEqual(artifact, loaded.to_dict())
        artifact['weights'][0][0] = 20.
        with self.assertRaisesRegex(ValueError, 'ARTIFACT_HASH'):
            RankModel.from_dict(artifact)

    def test_feature_digest_is_checked_and_training_bound(self):
        from research.chatgpt_dt_r1.features import _bind_feature_input
        row = fixture()
        row.update(feature_version='synthetic', history_evidence={}, feature_status='READY', feature_scope='synthetic')
        _bind_feature_input(row)
        row['features'][0, 0] += 10
        with self.assertRaisesRegex(ValueError, 'FEATURE_INPUT_HASH'):
            RankModel.zero(row['feature_names']).distribution(row)
        with self.assertRaisesRegex(ValueError, 'FEATURE_INPUT_HASH'):
            fit_ranker([dict(row, race_id=str(i)) for i in range(30)], before='2026-02-01')

    def test_feature_digest_binds_car_mapping_line_dependencies_and_clock_context(self):
        from research.chatgpt_dt_r1.features import _bind_feature_input
        row = fixture(n=3)
        row.update(feature_version='synthetic', history_evidence={}, feature_status='READY', feature_scope='synthetic')
        _bind_feature_input(row)
        changes = [lambda r: r.update(line_groups=[[1, 3], [2]]),
                   lambda r: r.update(lines_known=False), lambda r: r.update(lines_applicable=False),
                   lambda r: r['riders'].reverse(),
                   lambda r: r['riders'][0].update(competition_points=200.),
                   lambda r: r.update(day='2025-01-01')]
        for change in changes:
            altered = copy.deepcopy(row)
            change(altered)
            with self.assertRaisesRegex(ValueError, 'FEATURE_INPUT_HASH_MISMATCH'):
                RankModel.zero(row['feature_names']).distribution(altered)


if __name__ == '__main__':
    unittest.main()
