from itertools import permutations
import unittest

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, 'Research runtime requires NumPy')
class LearnedOrderTests(unittest.TestCase):
    def setUp(self):
        from race_ai import keirin_learned_order as order

        self.order = order
        self.race = dict(race_id='202608013101', meeting_grade='F1', round_stage='PRELIMINARY',
                         riders=[dict(car=car, points=100 - car, style='NIGE') for car in (1, 3, 4, 5, 7)],
                         line_groups=[[1, 3], [4, 7], [5]])

    def test_conditional_forecast_has_all_orders_and_consistent_exactas(self):
        row = self.order.context(self.race)

        class Model:
            def predict(self, data, **kwargs):
                return data[:, self_index] - data[:, stage_index] / 3

        self_index = self.order.FEATURES.index('points_vs_field')
        stage_index = self.order.FEATURES.index('stage')
        forecast, = self.order.predict(Model(), [row], temperature=1.1)
        self.assertEqual(set(forecast.trifectas()), set(permutations(row.cars, 3)))
        self.assertAlmostEqual(sum(forecast.trifectas().values()), 1.)
        self.assertAlmostEqual(sum(forecast.exactas().values()), 1.)
        self.assertGreater(forecast.trifectas()[1, 3, 4], forecast.trifectas()[7, 5, 4])

    def test_missing_lines_are_kept_and_result_fields_are_not_model_inputs(self):
        self.race['line_groups'] = None
        lineup = self.order.context(self.race)
        self.assertTrue(np.isnan(lineup.static[:, self.order.FEATURES.index('line_role')]).all())
        self.race['riders'][0]['finish_rank'] = 1
        with self.assertRaises(ValueError):
            self.order.context(self.race)

    def test_group_softmax_gradient_is_conditional_and_handles_smaller_fields(self):
        offsets = np.array([0, 3, 5])
        p = self.order.group_softmax(np.log([1, 2, 3, 2, 3]), offsets)
        np.testing.assert_allclose(p, [1/6, 2/6, 3/6, 2/5, 3/5])

    def test_paid_labels_preserve_ties_and_hold_conflicting_revisions(self):
        from scripts import keirin_learned_order_study as study

        row = dict(race_date='20261026', venue_code='31', rno=1, bet_type='3連単', combination='1-2-3',
                   payout=1500, fetched_at='2026-10-26T20:00:00')
        tied = dict(row, combination='1-3-2', payout=2100)
        late = dict(row, combination='2-3-1', fetched_at='2026-11-01T02:00:00')
        self.assertEqual(study._paid([row, tied, late], '20261031'),
                         {('202610263101', '3連単'): {(1, 2, 3): 1500, (1, 3, 2): 2100}})
        self.assertEqual(study._paid([row, dict(row, payout=1600)], '20261031'), {})
