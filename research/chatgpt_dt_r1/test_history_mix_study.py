"""Offline regression fixtures for preregistered DT-R1 history pooling."""
from datetime import date
from itertools import permutations
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research.chatgpt_dt_r1 import history_mix_study as study


class HistoryMixTests(unittest.TestCase):
    def test_joint_mixture_preserves_total_mass_and_exacta_marginals(self):
        orders = tuple(permutations((1, 2, 3)))
        cold = dict.fromkeys(orders, 0.)
        recent = cold.copy()
        cold[(1, 2, 3)], recent[(3, 1, 2)] = 1., 1.
        pooled = study.mix_joint(cold, recent, .25)
        self.assertEqual(study.exacta_marginal(pooled)[(1, 2)], .75)
        self.assertEqual(study.exacta_marginal(pooled)[(3, 1)], .25)
        self.assertEqual(sum(pooled.values()), 1.)
        self.assertEqual(study.mix_joint(cold, recent, 0.), cold)
        self.assertEqual(study.mix_joint(cold, recent, 1.), recent)
        with self.assertRaises(ValueError):
            study.mix_joint(cold, {(1, 2, 3): 1.}, .25)

    def test_prior_week_excludes_target_and_future_but_includes_first_day(self):
        target = date(2026, 7, 2)
        source = {date.fromisoformat(day): day for day in
                  ('2026-06-24', '2026-06-25', '2026-07-01', '2026-07-02', '2026-07-03')}
        self.assertEqual(list(study.prior_week(source.items(), target)), ['2026-06-25', '2026-07-01'])

    def test_same_day_forecasts_are_all_blinded_before_outcomes_enter_either_builder(self):
        observed = []
        days = ('2026-06-24', '2026-06-25', '2026-07-01', '2026-07-02', '2026-07-02', '2026-08-01')
        rows = [dict(day=day, race_id=str(i), input_sha256='fixed', outcome='private')
                for i, day in enumerate(days)]

        class Builder:
            def __init__(self):
                self.past = []

            def update_day(self, records):
                self.past.extend(row['day'] for row in records if row['outcome'])

            def transform(self, row):
                self_outer.assertNotIn('outcome', row)
                observed.append((row['race_id'], tuple(self.past)))
                return dict(row, feature_names=(), feature_status='READY')

        self_outer = self
        model = SimpleNamespace(feature_names=(), distribution=lambda _: {'trifectas': []})
        with (
            patch.object(study, 'FeatureBuilder', Builder),
            patch.object(study, 'blind_target', side_effect=lambda r: {k: v for k, v in r.items() if k != 'outcome'}),
            patch.object(study, 'augment_features', side_effect=lambda r, **_: r),
            patch.object(study, 'augment_agari', side_effect=lambda r: r),
            patch.object(study, 'augment_abilities', side_effect=lambda r: r),
        ):
            list(study._projected_days(rows, model, None, 'actual study clock'))
        expected = [(), ('2026-06-25', '2026-07-01'), ('2026-06-24', '2026-06-25', '2026-07-01')]
        for race_id in ('3', '4'):
            self.assertEqual([past for race, past in observed if race == race_id], expected)
        self.assertNotIn('5', [race for race, _ in observed])

    def test_top_ticket_choice_uses_declared_order_and_cold_proper_score_guard(self):
        def result(loss, tri1, ex1, tri2, tri4, ex2):
            return dict(tri_log_loss=loss, tri1=tri1, ex1=ex1, tri2=tri2, tri4=tri4, ex2=ex2)

        scores = {
            0.: result(.8, 3, 6, 6, 9, 8),
            .25: result(.7, 5, 6, 6, 9, 8),
            .5: result(.75, 5, 7, 7, 9, 8),
            .75: result(.76, 5, 7, 7, 9, 9),
            1.: result(.81, 9, 11, 10, 12, 12),
        }
        self.assertEqual(study.select_alphas(scores), {'log_loss': .25, 'top_ranks_guarded': .75})
        scores[.5] = scores[.75].copy()
        self.assertEqual(study.select_alphas(scores)['top_ranks_guarded'], .5)

    def test_day_bootstrap_is_paired_and_deterministic(self):
        days = {'2026-07-01': {'cold': {'n': 2, 'tri1': 1}, 'mixed': {'n': 2, 'tri1': 2}},
                '2026-07-02': {'cold': {'n': 5, 'tri1': 0}, 'mixed': {'n': 5, 'tri1': 0}}}
        first = study.paired_difference(days, 'mixed', 'cold', metrics=('tri1',))
        self.assertEqual(first, study.paired_difference(days, 'mixed', 'cold', metrics=('tri1',)))
        self.assertAlmostEqual(first['tri1']['delta'], 1 / 7)
        self.assertEqual(first['tri1']['ci95'], [0., .5])
