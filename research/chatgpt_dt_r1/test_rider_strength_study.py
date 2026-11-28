"""Regression fixtures for the prior-only archived opponent adjustment."""
from copy import deepcopy
from datetime import date, timedelta
from itertools import permutations
import unittest

from research.chatgpt_dt_r1 import rider_strength_study as study


DAY = date(2026, 5, 15)


def card(day, riders, ranks, statuses=None):
    statuses = statuses or [study.IDENTITY_STATUS] * len(riders)
    return dict(day=day.isoformat(), result_status='COMPLETE',
        riders=[dict(car=i, identity_key=key, identity_usable=True, identity_status=status)
                for i, (key, status) in enumerate(zip(riders, statuses, strict=True), 1)],
        result_rows=[dict(car=i, rank=rank) for i, rank in enumerate(ranks, 1)])


class RiderStrengthTests(unittest.TestCase):
    def test_beating_stronger_opponent_is_more_informative(self):
        old = study.PairStrength()
        for n in range(12):
            day = DAY - timedelta(days=12 - n)
            old.update_day(day, [card(day, ('strong', 'weak'), (1, 2))])
        strong, weak = deepcopy(old), deepcopy(old)
        strong.update_day(DAY, [card(DAY, ('new', 'strong'), (1, 2))])
        weak.update_day(DAY, [card(DAY, ('new', 'weak'), (1, 2))])
        tomorrow = DAY + timedelta(days=1)
        self.assertGreater(strong.strength('new', tomorrow), weak.strength('new', tomorrow))
        self.assertLess(strong.strength('new', DAY + timedelta(days=120)), strong.strength('new', tomorrow))

    def test_all_races_on_one_day_update_from_same_prior_state(self):
        one = card(DAY, ('a', 'b'), (1, 2))
        two = card(DAY, ('b', 'c'), (1, 2))
        left, right = study.PairStrength(), study.PairStrength()
        self.assertEqual(left.strength('b', DAY), 0.)
        left.update_day(DAY, [one, two])
        right.update_day(DAY, [two, one])
        tomorrow = DAY + timedelta(days=1)
        self.assertEqual(left.strength('b', tomorrow), 0.)
        self.assertEqual(left.strength('b', tomorrow), right.strength('b', tomorrow))
        with self.assertRaises(ValueError):
            left.strength('b', DAY)

    def test_ties_and_unbound_identity_do_not_create_phantom_pairs(self):
        ratings = study.PairStrength()
        race = card(DAY, ('a', 'b', 'c'), (1, 1, 3),
                    [study.IDENTITY_STATUS, study.IDENTITY_STATUS, 'OTHER_NAMESPACE'])
        ratings.update_day(DAY, [race])
        self.assertEqual(ratings.pairs, 0)
        self.assertEqual(ratings.strength('c', DAY + timedelta(days=1)), 0.)

    def test_adjustment_preserves_frozen_conditional_and_null_arm(self):
        orders = tuple(permutations((1, 2, 3)))
        base = {order: 1. / len(orders) for order in orders}
        strengths = {1: .5, 2: -.5, 3: 0.}
        self.assertIs(study.adjust_joint(base, strengths, 0., 1.), base)
        candidate = study.adjust_joint(base, strengths, 1., 1.)
        self.assertGreater(candidate[(1, 2, 3)], candidate[(2, 1, 3)])
        self.assertAlmostEqual(candidate[(1, 2, 3)], candidate[(1, 3, 2)])
        self.assertAlmostEqual(sum(candidate.values()), 1.)
