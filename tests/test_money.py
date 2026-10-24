"""Behavior contracts for money; all figures here are synthetic calculations."""
import importlib
import unittest
from decimal import Decimal


RACE = '20261015-18-01'


def bet(combination=(1, 2, 3), stake=100, **extra):
    return dict(race_id=RACE, bet_type='trifecta',
                combination=list(combination), stake_yen=stake, **extra)


def result(**extra):
    return dict(race_id=RACE, status='settled', confirmed=True, payouts=[], **extra)


class MoneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.money = importlib.import_module('race_ai.money')
        except ModuleNotFoundError:
            cls.money = None

    def setUp(self):
        self.assertIsNotNone(self.money, 'shared money engine must exist')

    def test_hit_payout_is_distinct_from_expected_payout_and_profit(self):
        value = self.money.estimate_bet(100, '0.10', '15.0')
        self.assertEqual(value, dict(stake_yen=100, probability='0.1', odds='15',
            payout_if_hit_yen='1500', profit_if_hit_yen='1400',
            expected_payout_yen='150', expected_profit_yen='50',
            expected_roi_percent='150', expected_profit_percent='50'))

    def test_odds_update_recalculates_exact_decimal_expectation(self):
        before = self.money.estimate_bet(300, Decimal('0.123456'), Decimal('15.1'))
        after = self.money.estimate_bet(300, '0.123456', '14.9')
        self.assertEqual(before['expected_payout_yen'], '559.25568')
        self.assertEqual(after['expected_payout_yen'], '551.84832')

    def test_zero_stake_has_no_return_rate(self):
        self.assertIsNone(self.money.estimate_bet(0, '0.1', '15')['expected_roi_percent'])
        settled = self.money.settle_bets([], result())
        self.assertEqual(settled['net_profit_yen'], 0)
        self.assertIsNone(settled['actual_roi_percent'])

    def test_all_purchases_count_towards_actual_profit(self):
        bets = [bet(c) for c in ((1, 3, 2), (1, 2, 3), (3, 1, 2), (1, 3, 5))]
        official = result()
        official['payouts'] = [dict(bet_type='trifecta', combination=[1, 3, 2],
                                   payout_per_100_yen=1500)]
        settled = self.money.settle_bets(bets, official)
        self.assertEqual(settled['payout_yen'], 1500)
        self.assertEqual(settled['net_profit_yen'], 1100)
        self.assertEqual(settled['actual_roi_percent'], '375')

    def test_all_misses_lose_effective_stake(self):
        settled = self.money.settle_bets([bet(stake=400)], result())
        self.assertEqual(settled['net_profit_yen'], -400)
        self.assertEqual(settled['actual_roi_percent'], '0')

    def test_official_per_100_payout_overrides_prediction_odds(self):
        official = result()
        official['payouts'] = [dict(bet_type='trifecta', combination=[1, 2, 3],
                                   payout_per_100_yen=1430)]
        settled = self.money.settle_bets([bet(stake=200, odds='15', probability='0.1')], official)
        self.assertEqual(settled['payout_yen'], 2860)

    def test_partial_refund_reduces_roi_denominator(self):
        official = result(refunds=[dict(bet_type='trifecta', combination=[1, 2, 3], refund_yen=100)])
        official['payouts'] = [dict(bet_type='trifecta', combination=[1, 2, 3], payout_per_100_yen=1500)]
        settled = self.money.settle_bets([bet(stake=300), bet((2, 1, 3))], official)
        self.assertEqual(settled['refund_yen'], 100)
        self.assertEqual(settled['effective_stake_yen'], 300)
        self.assertEqual(settled['payout_yen'], 3000)
        self.assertEqual(settled['cash_return_yen'], 3100)
        self.assertEqual(settled['net_profit_yen'], 2700)
        self.assertEqual(settled['actual_roi_percent'], '1000')

    def test_full_refund_and_cancelled_race_have_no_roi_or_loss(self):
        for status in ('cancelled', 'no_contest', 'postponed'):
            official = dict(race_id=RACE, status=status, confirmed=True, payouts=[])
            settled = self.money.settle_bets([bet(stake=400)], official)
            self.assertEqual(settled['refund_yen'], 400)
            self.assertEqual(settled['net_profit_yen'], 0)
            self.assertIsNone(settled['actual_roi_percent'])
        settled = self.money.settle_bets([bet()], result(refunds=[dict(
            bet_type='trifecta', combination=[1, 2, 3])]))
        self.assertEqual(settled['effective_stake_yen'], 0)
        self.assertIsNone(settled['actual_roi_percent'])

    def test_dead_heat_pays_each_official_winning_combination(self):
        official = dict(race_id=RACE, status='dead_heat', confirmed=True, payouts=[
            dict(bet_type='trifecta', combination=[1, 2, 3], payout_per_100_yen=700),
            dict(bet_type='trifecta', combination=[2, 1, 3], payout_per_100_yen=800)])
        settled = self.money.settle_bets([bet(), bet((2, 1, 3), 200)], official)
        self.assertEqual(settled['payout_yen'], 2300)
        self.assertEqual(settled['net_profit_yen'], 2000)

    def test_special_payout_requires_explicit_official_value(self):
        official = dict(race_id=RACE, status='special', confirmed=True, payouts=[],
                        special_payouts=[dict(bet_type='trifecta', payout_per_100_yen=70)])
        settled = self.money.settle_bets([bet(stake=300)], official)
        self.assertEqual(settled['payout_yen'], 210)
        self.assertEqual(settled['net_profit_yen'], -90)
        self.assertEqual(settled['actual_roi_percent'], '70')
        del official['special_payouts']
        with self.assertRaises(self.money.MoneyError):
            self.money.settle_bets([bet()], official)

    def test_pending_or_mismatched_results_never_become_zero_payout(self):
        for changes in ({'confirmed': False}, {'race_id': 'different'}, {'status': 'pending'}):
            official = result()
            official.update(changes)
            with self.assertRaises(self.money.MoneyError):
                self.money.settle_bets([bet()], official)

    def test_invalid_yen_probabilities_and_odds_are_rejected(self):
        for value in (-100, 1, 150, True, None, '100', float('nan'), 2**53):
            with self.subTest(stake=value), self.assertRaises(self.money.MoneyError):
                self.money.estimate_bet(value, '0.1', '15')
        for value in ('NaN', 'Infinity', '-0.1', '1.1', None, True, '1e-2', '0.1234567', Decimal('sNaN')):
            with self.subTest(probability=value), self.assertRaises(self.money.MoneyError):
                self.money.estimate_bet(100, value, '15')
        for value in (None, '-1', '0', '0.9', 'NaN', float('inf'), True):
            with self.subTest(odds=value), self.assertRaises(self.money.MoneyError):
                self.money.estimate_bet(100, '0.1', value)

    def test_budget_daily_and_loss_caps_reject_excess(self):
        for limits in (dict(budget_yen=100),
                       dict(budget_yen=500, day_budget_yen=500, day_spent_yen=400),
                       dict(budget_yen=500, loss_limit_yen=200, loss_used_yen=100)):
            with self.subTest(limits=limits), self.assertRaises(self.money.MoneyError):
                self.money.validate_purchase([bet(stake=200)], limits)

    def test_duplicate_and_invalid_combinations_rejected(self):
        for bets in ([bet(), bet()], [bet((1, 1, 2))], [bet((1, 2, 7))],
                     [bet((1, 2))], [bet(probability='0.1')]):
            with self.subTest(bets=bets), self.assertRaises(self.money.MoneyError):
                self.money.validate_purchase(bets, dict(budget_yen=1000))
        trio = dict(race_id=RACE, bet_type='trio', combination=[3, 2, 1], stake_yen=100)
        duplicate = dict(trio, combination=[1, 2, 3])
        with self.assertRaises(self.money.MoneyError):
            self.money.validate_purchase([trio, duplicate], dict(budget_yen=1000))

    def test_percentages_sum_to_100_with_deterministic_remainder(self):
        purchase = self.money.validate_purchase([bet(), bet((2, 1, 3)), bet((3, 1, 2))], dict(budget_yen=1000))
        self.assertEqual(purchase['allocation_percent'], ['33.34', '33.33', '33.33'])
        self.assertEqual(purchase['remaining_budget_yen'], 700)

    def test_aggregate_expectation_is_sum_of_bets(self):
        purchase = self.money.validate_purchase([bet(odds='15', probability='0.1'),
            bet((2, 1, 3), 200, odds='8', probability='0.2')], dict(budget_yen=1000))
        self.assertEqual(purchase['expected_payout_yen'], '470')
        self.assertEqual(purchase['expected_profit_yen'], '170')
        self.assertEqual(purchase['expected_roi_percent'], '156.666667')
        manual = self.money.validate_purchase([bet()], dict(budget_yen=1000))
        self.assertIsNone(manual['expected_payout_yen'])

    def test_conservative_allocation_skips_unverified_and_low_ev_models(self):
        candidate = bet(odds='15', probability='0.1')
        for model in ({}, {'validated': False}, {'validated': True, 'data_complete': False}):
            allocation = self.money.recommend_allocation([candidate], dict(budget_yen=10000), model)
            self.assertEqual(allocation['status'], 'skip')
            self.assertEqual(allocation['total_stake_yen'], 0)
        good = dict(validated=True, data_complete=True)
        allocation = self.money.recommend_allocation([candidate], dict(budget_yen=10000), good)
        self.assertEqual(allocation['total_stake_yen'], 100)
        self.assertEqual(allocation['remaining_budget_yen'], 9900)
        low = self.money.recommend_allocation([bet(odds='5', probability='0.1')], dict(budget_yen=10000), good)
        self.assertEqual(low['status'], 'skip')

    def test_configured_bet_count_limits_are_enforced(self):
        candidates = [bet((a, b, c), odds='300', probability='0.005')
                      for a in range(1, 7) for b in range(1, 7) for c in range(1, 7)
                      if len({a, b, c}) == 3]
        for cap in (8, 16, 24, 32):
            allocation = self.money.recommend_allocation(candidates, dict(budget_yen=100000, max_bets=cap),
                                                        dict(validated=True, data_complete=True))
            self.assertEqual(len(allocation['bets']), cap)
            self.assertEqual(allocation['total_stake_yen'], cap * 100)
        with self.assertRaises(self.money.MoneyError):
            self.money.validate_purchase(candidates[:9], dict(budget_yen=1000))

    def test_manual_ledger_is_immutable_and_rejects_repeat_or_overspending(self):
        record = dict(id='purchase-1', race_id=RACE, purchased_at='2026-10-15T12:00:00+09:00', bets=[bet()])
        original = []
        ledger = self.money.append_purchase(original, record, dict(budget_yen=1000, day_budget_yen=1000))
        self.assertEqual(original, [])
        self.assertEqual(ledger[0]['purchase_day'], '2026-10-15')
        self.assertEqual(ledger[0]['source'], 'manual')
        for next_record in (record, dict(record, id='purchase-2')):
            with self.assertRaises(self.money.MoneyError):
                self.money.append_purchase(ledger, next_record, dict(budget_yen=1000, day_budget_yen=1000))
        second = dict(record, id='purchase-2', bets=[bet((2, 1, 3), 200)])
        with self.assertRaises(self.money.MoneyError):
            self.money.append_purchase(ledger, second, dict(budget_yen=1000, day_budget_yen=200))

    def test_ledger_summary_does_not_treat_pending_results_as_losses(self):
        ledger = [dict(id='p1', race_id=RACE, purchased_at='2026-10-15T12:00:00+09:00', bets=[bet()]),
                  dict(id='p2', race_id=RACE, purchased_at='2026-10-15T12:01:00+09:00', bets=[bet((2, 1, 3))], official_result=result())]
        summary = self.money.summarize_ledger(ledger)
        self.assertEqual(summary['total_stake_yen'], 200)
        self.assertEqual(summary['pending_stake_yen'], 100)
        self.assertEqual(summary['settled_effective_stake_yen'], 100)
        self.assertEqual(summary['net_profit_yen'], -100)
        self.assertEqual(summary['actual_roi_percent'], '0')
        self.assertIsNone(self.money.summarize_ledger([])['actual_roi_percent'])

    def test_json_integer_values_and_small_numeric_decimal_match_browser(self):
        self.assertEqual(self.money.estimate_bet(100.0, 0.000001, 15)['expected_payout_yen'], '0.0015')
        purchase = self.money.validate_purchase([bet((1.0, 2.0, 3.0))], dict(budget_yen=1000.0, max_bets=8.0))
        self.assertEqual(purchase['bets'][0]['combination'], [1, 2, 3])
        self.assertIs(type(purchase['bets'][0]['stake_yen']), int)

    def test_malformed_object_fields_raise_money_error(self):
        for malformed in ([], {}, 1, None, True):
            with self.subTest(kind=malformed), self.assertRaises(self.money.MoneyError):
                self.money.validate_purchase([dict(bet(), bet_type=malformed)], dict(budget_yen=1000))
        for malformed in ([], {}, 1):
            with self.subTest(status=malformed), self.assertRaises(self.money.MoneyError):
                self.money.settle_bets([bet()], dict(result(), status=malformed))

    def test_ledger_loss_limit_accounts_for_pending_and_realized_losses(self):
        record = dict(id='p1', race_id=RACE, purchased_at='2026-10-15T12:00:00+09:00', bets=[bet(stake=200)])
        next_record = dict(record, id='p2', bets=[bet((2, 1, 3))])
        policy = dict(budget_yen=1000, day_budget_yen=10000, loss_limit_yen=200)
        for existing in (record, dict(record, official_result=result())):
            with self.subTest(settled='official_result' in existing), self.assertRaises(self.money.MoneyError):
                self.money.append_purchase([existing], next_record, policy)

    def test_timestamp_uses_jst_day_and_rejects_invalid_calendar_or_offset(self):
        record = dict(id='p1', race_id=RACE, purchased_at='2026-10-14T15:00:00Z', bets=[bet()])
        self.assertEqual(self.money.append_purchase([], record, dict(budget_yen=1000))[0]['purchase_day'], '2026-10-15')
        for timestamp in ('2026-02-30T12:00:00Z', '2026-10-15T12:00:00+01:99',
                          '2026-10-15T24:00:00Z', '2026-10-15T12:00:00+24:00'):
            with self.subTest(timestamp=timestamp), self.assertRaises(self.money.MoneyError):
                self.money.append_purchase([], dict(record, purchased_at=timestamp), dict(budget_yen=1000))

    def test_mutually_exclusive_probability_sum_cannot_exceed_one(self):
        for kind, combinations in (('trifecta', ([1, 2, 3], [2, 1, 3])),
                                   ('trio', ([1, 2, 3], [1, 2, 4])),
                                   ('win', ([1], [2]))):
            rows = [dict(race_id=RACE, bet_type=kind, combination=c, stake_yen=100,
                         probability='0.6', odds='15') for c in combinations]
            with self.subTest(kind=kind), self.assertRaises(self.money.MoneyError):
                self.money.recommend_allocation(rows, dict(budget_yen=10000), dict(validated=True, data_complete=True))
        overlapping = [dict(race_id=RACE, bet_type='place', combination=[lane], stake_yen=100,
                            probability='0.8', odds='2') for lane in (1, 2)]
        self.assertEqual(self.money.validate_purchase(overlapping, dict(budget_yen=1000))['total_stake_yen'], 200)

    def test_explicit_partial_market_evidence_cannot_settle_an_unverified_type(self):
        official = result(verified_market_types=['exacta'])
        with self.assertRaises(self.money.MoneyError):
            self.money.settle_bets([bet()], official)
        checked = self.money.settle_bets([bet()], result(verified_market_types=['trifecta']))
        self.assertEqual(checked['net_profit_yen'], -100)


if __name__ == '__main__':
    unittest.main()
