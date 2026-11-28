"""Synthetic checks for the nonlinear DT-R1 winner-stage experiment."""
from datetime import date
from itertools import permutations
from math import log
import unittest
from unittest.mock import patch

from research.chatgpt_dt_r1 import boosted_first_study as study


class BoostedFirstStudyTests(unittest.TestCase):
    def test_joint_reweight_preserves_conditionals_and_exact_a_marginal(self):
        o = list(permutations((1, 2, 3)))
        base = dict(zip(o, (.20, .10, .25, .05, .30, .10), strict=True))
        first = {1: .10, 2: .30, 3: .60}
        joint = study.reweight_joint(base, first)
        ex = study.marginal(joint, count=2)
        self.assertEqual(set(joint), set(base))
        for car, expected in first.items():
            self.assertAlmostEqual(sum(p for t, p in ex.items() if t[0] == car), expected)
            for order in (t for t in o if t[0] == car):
                self.assertAlmostEqual(joint[order] / expected,
                                       base[order] / sum(base[t] for t in o if t[0] == car))
        with self.assertRaises(ValueError):
            study.reweight_joint(base, {1: .5, 2: .5})

    def test_calendar_phase_bounds_and_exact_prior_week(self):
        self.assertEqual(tuple(study.SPLITS.values()), (
            ('2025-10-01', '2026-05-31'), ('2026-06-01', '2026-06-30'), ('2026-07-01', '2026-07-31')))
        dates = ('2026-06-23', '2026-06-24', '2026-06-30', '2026-07-01', '2026-07-01', '2026-08-01')
        rows = [dict(day=d, label='synthetic') for d in dates]
        day, targets, earlier = next(study.week_groups(rows, *study.SPLITS['july']))
        self.assertEqual(day, date(2026, 7, 1))
        self.assertEqual(len(targets), 2)
        self.assertEqual([day.isoformat() for day, _ in earlier], ['2026-06-24', '2026-06-30'])
        self.assertEqual(len(list(study.week_groups(rows, *study.SPLITS['july']))), 1)

    def test_evaluation_requires_every_expected_unique_race_and_no_substitutes(self):
        ids = [f'synthetic-{i}' for i in range(study.EXPECTED_JULY)]
        study.validate_july(ids, ids)
        for actual in (ids[:-1], ids[:-1] + [ids[0]], ids[:-1] + ['different']):
            with self.subTest(size=len(actual)), self.assertRaises(ValueError):
                study.validate_july(ids, actual)

    def test_july_frames_build_cold_and_recent_from_identical_target_cards(self):
        earlier = dict(day='2026-06-30', race_id='earlier')
        day = '2026-07-01'
        targets = [dict(day=day, race_id='a'), dict(day=day, race_id='b')]
        calls = []

        class Builder:
            def __init__(self):
                self.seen = []

            def update_day(self, rows):
                self.seen.extend(row['race_id'] for row in rows)

        def view(rows, builder, *args):
            calls.append(([r['race_id'] for r in rows], builder.seen))
            return rows

        with (
            patch.object(study, 'FeatureBuilder', Builder),
            patch.object(study, '_result_key', return_value=(1, 2, 3)),
            patch.object(study, '_features', side_effect=view),
        ):
            frames = list(study._frames([earlier, *targets], 'july', None, None, None))
        self.assertEqual(frames[0][1], frames[0][2])
        self.assertEqual(calls, [(['a', 'b'], ['earlier']), (['a', 'b'], [])])

    def test_june_temperature_tie_prefers_lower_value_and_probability_normalizes(self):
        flat = study.softmax((10000, 10000), .8)
        self.assertEqual(tuple(flat), (.5, .5))
        tuning, losses = study.pick_temperature([((2., 2., 2.), 1)] * 3)
        self.assertEqual(tuning, min(study.TEMPERATURES))
        for value in losses.values():
            self.assertAlmostEqual(value, -log(1 / 3))
