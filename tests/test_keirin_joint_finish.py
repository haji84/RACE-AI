import itertools
import math
import unittest
from datetime import date

from race_ai.keirin_joint_finish import JointFinish, TailTrainingRace, fit_tail


def thirds(cars):
    orders = list(itertools.permutations(cars, 3))
    normalizer = sum(range(1, len(orders) + 1))
    return {o: k / normalizer for k, o in enumerate(orders, start=1)}


class JointFinishTests(unittest.TestCase):
    def test_marginals_agree_with_every_possible_full_finish(self):
        cars = (1, 3, 4, 6, 7)
        top = thirds(cars)
        model = JointFinish(cars, top, tail=(1.1, -0.4))
        finish = model.marginals()
        orders = {o: model.order_probability(o) for o in itertools.permutations(cars)}
        self.assertAlmostEqual(math.fsum(orders.values()), 1.0)
        self.assertEqual(model.trifectas(), top)

        for p in top:
            self.assertAlmostEqual(math.fsum(x for o, x in orders.items() if o[:3] == p), top[p])
        for pair, p in model.exactas().items():
            self.assertAlmostEqual(math.fsum(x for o, x in orders.items() if o[:2] == pair), p)
        for car, row in finish.items():
            self.assertAlmostEqual(math.fsum(row), 1.0)
            for pos, p in enumerate(row):
                self.assertAlmostEqual(math.fsum(x for o, x in orders.items() if o[pos] == car), p)
        for column in zip(*finish.values(), strict=True):
            self.assertAlmostEqual(math.fsum(column), 1.0)

    def test_reject_incomplete_wrong_order_and_nonfinite_mass(self):
        cars = (1, 2, 3, 4, 5)
        top = thirds(cars)
        malformed = dict(top)
        malformed[1, 2, 3] = float('nan')
        bad_key = dict(top)
        bad_key[3] = bad_key.pop((1, 2, 3))
        for bad in ({(1, 2, 3): 1.0}, malformed, bad_key):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                JointFinish(cars, bad, tail=(0., 0.))
        with self.assertRaises(ValueError):
            JointFinish((True, 2, 3), thirds((1, 2, 3)))
        with self.assertRaises(ValueError):
            JointFinish(cars, top, tail=(1e308, -1e308))
        with self.assertRaises(ValueError):
            JointFinish(cars, top, tail=(0., 0.)).order_probability((1, 2, 3, 4, 6))

    def test_unknown_tail_is_explicit_and_deterministic_tail_needs_no_weights(self):
        with self.assertRaisesRegex(ValueError, 'tail'):
            JointFinish((1, 2, 3, 4, 5), thirds((1, 2, 3, 4, 5)))
        model = JointFinish((1, 2, 3, 4), thirds((1, 2, 3, 4)))
        self.assertAlmostEqual(math.fsum(model.marginals()[4]), 1.0)

    def test_nine_cars_allow_known_zero_probability_orders(self):
        cars = tuple(range(1, 10))
        top = dict.fromkeys(itertools.permutations(cars, 3), 0.)
        top[1, 2, 3] = 1.
        model = JointFinish(cars, top, tail=(1., 1.))
        grid = model.marginals()
        self.assertEqual(grid[1], (1.,) + (0.,) * 8)
        self.assertEqual(grid[2][1], 1.)
        self.assertEqual(grid[3][2], 1.)
        for car in range(4, 10):
            self.assertEqual(grid[car][:3], (0.,) * 3)
            for probability in grid[car][3:]:
                self.assertAlmostEqual(probability, 1 / 6)

    def test_rider_summary_uses_same_marginals_and_prefers_first_rank_on_ties(self):
        cars = (1, 2, 3, 4, 5)
        top = dict.fromkeys(itertools.permutations(cars, 3), 0.)
        top[1, 2, 3] = 1.
        model = JointFinish(cars, top, tail=(0., 0.))
        data = model.rider_summary()
        self.assertEqual(data['calibration_status'], 'unavailable')
        self.assertIn('conditional', data['premise'])
        for car, raw in model.marginals().items():
            value = data['riders'][car]
            self.assertAlmostEqual(value['top2_probability'], math.fsum(raw[:2]))
            self.assertAlmostEqual(value['top3_probability'], math.fsum(raw[:3]))
            self.assertAlmostEqual(value['outside_top3_probability'], math.fsum(raw[3:]))
            self.assertAlmostEqual(value['expected_rank'],
                                   math.fsum(pos * probability for pos, probability in enumerate(raw, 1)))
        self.assertEqual(data['riders'][4]['most_likely_rank'], 4)

    def test_training_rejects_same_day_or_future_finishes_and_nonfinishers(self):
        cars = (1, 2, 3, 4, 5)
        probabilities = thirds(cars)
        before = date(2026, 11, 25)
        for when in (date(2026, 11, 25), date(2026, 11, 26)):
            with self.assertRaises(ValueError):
                fit_tail([TailTrainingRace(when, cars, probabilities, cars)], before=before)
        with self.assertRaises(ValueError):
            fit_tail([TailTrainingRace(date(2026, 11, 24), cars, probabilities, cars[:-1])], before=before)

    def test_training_uses_remaining_competitors_beyond_the_podium(self):
        cars = (1, 2, 3, 4, 5)
        top = thirds(cars)
        # Car 5 is more often near the top, but the label says it also beats 4
        # when neither is in the observed podium.
        when = date(2026, 11, 24)
        tail = fit_tail([TailTrainingRace(when, cars, top, (1, 2, 3, 5, 4)) for _ in range(7)],
                        before=date(2026, 11, 25))
        fitted = JointFinish(cars, top, tail=tail)
        self.assertGreater(fitted.order_probability((1, 2, 3, 5, 4)),
                           fitted.order_probability((1, 2, 3, 4, 5)))


if __name__ == '__main__':
    unittest.main()
