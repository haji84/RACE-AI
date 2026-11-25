from hashlib import sha256
import itertools
import math
import unittest

from race_ai.keirin_joint_finish import JointFinish
from race_ai.keirin_joint_forecast import META, build_forecast, validate_forecast
from race_ai.keirin_nationwide_auto_generator import canonical, digest
from scripts.keirin_market_third_study import MarketThirds, prepare_trial
from tests.test_keirin_joint_finish import thirds
from tests.test_keirin_note_collect_inputs import DAY, kd_page, kd_trifecta_board, rid, urls


class MarketThirdStudyTests(unittest.TestCase):
    def setUp(self):
        self.cars = (1, 2, 3, 4, 5, 6)
        self.joint = JointFinish(self.cars, thirds(self.cars), tail=(1.1, -.4))
        self.prior = build_forecast(self.joint, race_id=rid(2), generated_at=DAY+'T11:45:00+09:00',
            cutoff_at=DAY+'T12:12:00+09:00', source_as_of=DAY+'T11:40:00+09:00',
            model_id='B', model_version='saved-B', input_sha256='1'*64, source_packet_sha256='2'*64,
            source_forecast_generated_at=DAY+'T11:45:00+09:00',
            riders=[dict(car=car, name=f'EXAMPLE_RIDER_{car}', registration=f'{car:06d}') for car in self.cars])
        self.pin = digest(self.prior)
        self.clock = DAY+'T12:01:00+09:00'
        self.raw = kd_page(2, '12:12').replace(b'</body>', kd_trifecta_board(2)+b'</body>')

    def receipt(self, raw, **updates):
        return canonical(dict(url=urls(2)[1], bytes_sha256=sha256(raw).hexdigest(), bytes=len(raw),
                              status=200, captured_at=DAY+'T12:00:00+09:00') | updates)+b'\n'

    def run_trial(self, raw=None, *, receipt=None, joint=None, **overrides):
        return prepare_trial(self.prior, self.joint if joint is None else joint, **(dict(
            expected_original_sha256=self.pin, generated_at=self.clock, market_raw=raw, receipt_raw=receipt,
            expected_receipt_sha256=sha256(receipt).hexdigest() if receipt is not None else None) | overrides))

    def test_ready_standard_cohort_row_matches_same_budget_and_keeps_exacta(self):
        result = self.run_trial(self.raw, receipt=self.receipt(self.raw))
        row, trial = result['row'], validate_forecast(result['comparison'])
        self.assertEqual(result['state'], 'MARKET_THIRD_COMPARISON_READY')
        self.assertEqual(set(row), {'race_id', 'cutoff_at', 'starter_cars', 'published', 'trial'})
        self.assertTrue(result['evidence']['market']['eligible_full_priority'])
        self.assertEqual(result['evidence']['original_forecast_sha256'], self.pin)
        self.assertEqual(result['evidence']['market']['source_sha256'], sha256(self.raw).hexdigest())
        self.assertEqual(trial['generated_at'], self.clock)
        self.assertEqual(trial['source_forecast_generated_at'], self.prior['source_forecast_generated_at'])
        self.assertEqual(trial['source_as_of'], self.prior['source_as_of'])
        self.assertEqual(trial['exactas'], self.prior['exactas'])
        self.assertNotEqual(trial['trifectas'], self.prior['trifectas'])
        for cap in (1, 4, 8):
            self.assertEqual(len(row['published'][:cap]), len(row['trial'][:cap]))
        self.assertEqual(digest(self.prior), self.pin)

    def test_unavailable_partial_late_wrong_roster_or_cutoff_use_original(self):
        fallback = self.run_trial()
        self.assertEqual(fallback['state'], 'MARKET_UNAVAILABLE')
        for raw, updates in ((self.raw.replace(b'15.2', b'9999.9'), {}),
                             (self.raw.replace(b'EXAMPLE_RIDER_1', b'OTHER_RIDER_1'), {}),
                             (self.raw.replace(b'>12:12<', b'>12:14<'), {}),
                             (self.raw, {'captured_at': DAY+'T12:02:00+09:00'}),
                             (self.raw, {'captured_at': '0001-01-01T00:00:00+09:00'}),
                             (self.raw, {'bytes_sha256': '3'*64})):
            with self.subTest(updates=updates):
                value = self.run_trial(raw, receipt=self.receipt(raw, **updates))
                self.assertEqual(value['row'], fallback['row'])
                self.assertIsNone(value['comparison'])
        missing_pin = self.run_trial(self.raw, receipt=self.receipt(self.raw), expected_receipt_sha256=None)
        self.assertEqual(missing_pin['row'], fallback['row'])

    def test_a_late_or_unmatched_earlier_joint_never_becomes_a_challenger(self):
        for fields in ({'expected_original_sha256': 'a'*64},
                       {'generated_at': DAY+'T12:12:00+09:00'},
                       {'generated_at': DAY+'T11:44:00+09:00'},
                       {'joint': JointFinish(self.cars, thirds(self.cars), tail=(.0, .0))}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.run_trial(self.raw, receipt=self.receipt(self.raw), **fields)

    def test_degenerate_pair_marginal_may_equal_one_after_market_reweighting(self):
        podium = dict.fromkeys(thirds(self.cars), 0.)
        odds = dict.fromkeys(podium, 20.)
        for k in (3, 4, 5):
            podium[1, 2, k] = 1 / 3
            odds[1, 2, k] = float(k - 2)
        original = JointFinish(self.cars, podium, tail=(1.1, -.4))
        trial = MarketThirds(original, odds)
        forecast = build_forecast(trial, **{key:self.prior[key] for key in META}, riders=self.prior['riders'])
        self.assertEqual(forecast['riders'][0]['rank_probabilities'][0], 1.)
        self.assertEqual(forecast['riders'][1]['rank_probabilities'][1], 1.)


    def test_market_changes_only_conditional_third_and_keeps_tail_law(self):
        cars = (1, 2, 3, 4, 5)
        podium = thirds(cars)
        podium[1, 2, 5] += podium[1, 2, 4]
        podium[1, 2, 4] = 0.
        base = JointFinish(cars, podium, tail=(1.1, -0.4))
        prices = dict.fromkeys(podium, 20.)
        prices[1, 2, 3], prices[1, 2, 4] = 5., 1.
        trial = MarketThirds(base, prices)
        changed = trial.trifectas()
        self.assertEqual(base.trifectas(), podium)
        self.assertEqual(base.exactas(), trial.exactas())
        pair = base.exactas()[1, 2]
        self.assertAlmostEqual(changed[1, 2, 3], pair * .8)
        self.assertAlmostEqual(changed[1, 2, 5], pair * .2)
        self.assertEqual(changed[1, 2, 4], 0.)
        self.assertNotEqual(changed, podium)
        self.assertAlmostEqual(math.fsum(changed.values()), 1.)
        for order in itertools.permutations(cars):
            top = order[:3]
            if podium[top]:
                self.assertAlmostEqual(base.order_probability(order) / podium[top],
                                       trial.order_probability(order) / changed[top])
        for car, probabilities in trial.marginals().items():
            self.assertAlmostEqual(math.fsum(probabilities), 1.)
            for pos in (0, 1):
                self.assertAlmostEqual(probabilities[pos], base.marginals()[car][pos])

    def test_market_requires_full_numeric_board_even_for_zero_mass_pairs(self):
        cars = (1, 2, 3, 4, 5)
        podium = dict.fromkeys(itertools.permutations(cars, 3), 0.)
        podium[1, 2, 3] = 1.
        base = JointFinish(cars, podium, tail=(1., 1.))
        prices = dict.fromkeys(podium, 20.)
        self.assertEqual(MarketThirds(base, prices).trifectas(), podium)
        for invalid in (True, 0., float('nan'), 9999.9, '100'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MarketThirds(base, dict(prices) | {(2, 3, 1): invalid})
        del prices[2, 3, 1]
        with self.assertRaises(ValueError):
            MarketThirds(base, prices)

if __name__ == '__main__':
    unittest.main()
