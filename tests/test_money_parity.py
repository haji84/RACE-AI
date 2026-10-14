"""Run the same literal contract cases through Python and the shipped browser core."""
import importlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RACE = '20261015-18-01'
B = dict(race_id=RACE, bet_type='trifecta', combination=[1, 2, 3], stake_yen=100)
B2 = dict(B, combination=[2, 1, 3])
L = dict(budget_yen=1000)
O = dict(race_id=RACE, status='settled', confirmed=True, payouts=[])
PAYOUT = dict(bet_type='trifecta', combination=[1, 2, 3], payout_per_100_yen=1500)
P = dict(id='p1', race_id=RACE, purchased_at='2026-10-15T12:00:00+09:00', bets=[B])

CASES = [
    dict(name='100 yen 15 odds', op='estimate_bet', args=[100, '0.10', '15.0'],
         want=dict(payout_if_hit_yen='1500', expected_payout_yen='150', expected_profit_yen='50', expected_roi_percent='150')),
    dict(name='fractional decimal exactness', op='estimate_bet', args=[300, '0.123456', '15.1'], want=dict(expected_payout_yen='559.25568')),
    dict(name='numeric JSON integer semantics', op='estimate_bet', args=[100.0, 0.000001, 15], want=dict(expected_payout_yen='0.0015')),
    dict(name='numeric JSON lane semantics', op='validate_purchase', args=[[dict(B, combination=[1.0, 2.0, 3.0])], dict(budget_yen=1000.0, max_bets=8.0)], want=dict(total_stake_yen=100)),
    dict(name='max integer exact decimal aggregate', op='validate_purchase', args=[[
        dict(B, stake_yen=9007199254740900, probability='0.123456', odds='999999.999999')],
        dict(budget_yen=9007199254740900)], want=dict(expected_payout_yen='1111992791192180557608.8067074496',
            expected_profit_yen='1111983783992925816708.8067074496')),
    dict(name='numeric negative zero probability', op='estimate_bet', args=[100, -0.0, '15'], want=dict(expected_payout_yen='0')),
    dict(name='zero spending', op='estimate_bet', args=[0, '0.1', '15'], want=dict(expected_roi_percent=None)),
    dict(name='budget summary', op='validate_purchase', args=[[B, B2], L], want=dict(total_stake_yen=200, remaining_budget_yen=800)),
    dict(name='aggregate expected values', op='validate_purchase', args=[[
        dict(B, probability='0.1', odds='15'), dict(B2, stake_yen=200, probability='0.2', odds='8')], L],
        want=dict(expected_payout_yen='470', expected_profit_yen='170', expected_roi_percent='156.666667')),
    dict(name='empty purchase', op='validate_purchase', args=[[], L], want=dict(total_stake_yen=0, allocation_percent=[], expected_roi_percent=None)),
    dict(name='decimal allocation rounding', op='validate_purchase', args=[[B, B2, dict(B, combination=[3, 1, 2])], L],
        want=dict(allocation_percent=['33.34', '33.33', '33.33'])),
    dict(name='all misses', op='settle_bets', args=[[B, B2], O], want=dict(net_profit_yen=-200, actual_roi_percent='0')),
    dict(name='explicit verified market miss', op='settle_bets', args=[[B], dict(O, verified_market_types=['trifecta'])], want=dict(net_profit_yen=-100)),
    dict(name='official per100 payout', op='settle_bets', args=[[dict(B, stake_yen=200)], dict(O, payouts=[PAYOUT])],
        want=dict(payout_yen=3000, net_profit_yen=2800, actual_roi_percent='1500')),
    dict(name='four ticket result', op='settle_bets', args=[[
        B, B2, dict(B, combination=[3, 1, 2]), dict(B, combination=[1, 3, 2])], dict(O, payouts=[PAYOUT])],
        want=dict(payout_yen=1500, net_profit_yen=1100, actual_roi_percent='375')),
    dict(name='partial refund', op='settle_bets', args=[[dict(B, stake_yen=300), B2], dict(O, payouts=[PAYOUT], refunds=[
        dict(bet_type='trifecta', combination=[1, 2, 3], refund_yen=100)])],
        want=dict(refund_yen=100, effective_stake_yen=300, payout_yen=3000, cash_return_yen=3100, net_profit_yen=2700, actual_roi_percent='1000')),
    dict(name='full refund', op='settle_bets', args=[[B], dict(O, refunds=[dict(bet_type='trifecta', combination=[1, 2, 3])])],
        want=dict(refund_yen=100, net_profit_yen=0, actual_roi_percent=None)),
    dict(name='cancelled', op='settle_bets', args=[[B], dict(O, status='cancelled')], want=dict(refund_yen=100, net_profit_yen=0, actual_roi_percent=None)),
    dict(name='no contest', op='settle_bets', args=[[B], dict(O, status='no_contest')], want=dict(refund_yen=100, net_profit_yen=0, actual_roi_percent=None)),
    dict(name='dead heat', op='settle_bets', args=[[B, B2], dict(O, status='dead_heat', payouts=[PAYOUT,
        dict(bet_type='trifecta', combination=[2, 1, 3], payout_per_100_yen=800)])], want=dict(payout_yen=2300, net_profit_yen=2100)),
    dict(name='explicit special payout', op='settle_bets', args=[[dict(B, stake_yen=300)], dict(O, status='special', special_payouts=[
        dict(bet_type='trifecta', payout_per_100_yen=70)])], want=dict(payout_yen=210, net_profit_yen=-90, actual_roi_percent='70')),
    dict(name='no settlement spending', op='settle_bets', args=[[], O], want=dict(actual_roi_percent=None)),
    dict(name='manual ledger', op='append_purchase', args=[[], P, L]),
    dict(name='pending ledger summary', op='summarize_ledger', args=[[P]],
        want=dict(total_stake_yen=100, pending_stake_yen=100, net_profit_yen=0, actual_roi_percent=None)),
    dict(name='mixed pending and confirmed', op='summarize_ledger', args=[[
        P, dict(P, id='p2', bets=[B2], official_result=O)]],
        want=dict(total_stake_yen=200, pending_stake_yen=100, settled_effective_stake_yen=100, net_profit_yen=-100, actual_roi_percent='0')),
    dict(name='no model validation', op='recommend_allocation', args=[[dict(B, odds='15', probability='0.1')], L, {}],
        want=dict(status='skip', total_stake_yen=0)),
    dict(name='low expected value', op='recommend_allocation', args=[[dict(B, odds='5', probability='0.1')], L,
        dict(validated=True, data_complete=True)], want=dict(status='skip', total_stake_yen=0)),
    dict(name='conservative amount', op='recommend_allocation', args=[[dict(B, odds='15', probability='0.1')], dict(budget_yen=10000),
        dict(validated=True, data_complete=True)], want=dict(status='recommended', total_stake_yen=100, remaining_budget_yen=9900)),
    dict(name='bounded by risk budget', op='recommend_allocation', args=[[
        dict(B, odds='15', probability='0.1'), dict(B2, odds='10', probability='0.15')], dict(budget_yen=10000, loss_limit_yen=100),
        dict(validated=True, data_complete=True)], want=dict(total_stake_yen=100)),
]

for name, op, args in [
    ('negative spending', 'estimate_bet', [-100, '0.1', '15']),
    ('invalid purchase unit', 'estimate_bet', [150, '0.1', '15']),
    ('missing probability', 'estimate_bet', [100, None, '15']),
    ('nonfinite probability', 'estimate_bet', [100, 'NaN', '15']),
    ('too high probability', 'estimate_bet', [100, '10', '15']),
    ('nonfinite odds', 'estimate_bet', [100, '0.1', 'Infinity']),
    ('missing odds', 'estimate_bet', [100, '0.1', None]),
    ('exponent input', 'estimate_bet', [100, '1e-1', '15']),
    ('overprecision', 'estimate_bet', [100, '0.1234567', '15']),
    ('unsafe integer', 'estimate_bet', [9007199254741000, '0.1', '15']),
    ('duplicate ticket', 'validate_purchase', [[B, B], L]),
    ('invalid lanes', 'validate_purchase', [[dict(B, combination=[1, 1, 3])], L]),
    ('missing odds pair', 'validate_purchase', [[dict(B, probability='0.1')], L]),
    ('race budget exceeded', 'validate_purchase', [[dict(B, stake_yen=1100)], L]),
    ('daily budget exceeded', 'validate_purchase', [[B], dict(L, day_budget_yen=1000, day_spent_yen=1000)]),
    ('loss budget exceeded', 'validate_purchase', [[B], dict(L, loss_limit_yen=200, loss_used_yen=200)]),
    ('wrong cap', 'validate_purchase', [[B], dict(L, max_bets=9)]),
    ('negative budget', 'validate_purchase', [[B], dict(budget_yen=-100)]),
    ('wrong result race', 'settle_bets', [[B], dict(O, race_id='other')]),
    ('unconfirmed result', 'settle_bets', [[B], dict(O, confirmed=False)]),
    ('pending result', 'settle_bets', [[B], dict(O, status='pending')]),
    ('special payout guessed', 'settle_bets', [[B], dict(O, status='special')]),
    ('duplicate official payout', 'settle_bets', [[B], dict(O, payouts=[PAYOUT, PAYOUT])]),
    ('negative official payout', 'settle_bets', [[B], dict(O, payouts=[dict(PAYOUT, payout_per_100_yen=-1)])]),
    ('oversized refund', 'settle_bets', [[B], dict(O, refunds=[dict(bet_type='trifecta', combination=[1, 2, 3], refund_yen=200)])]),
    ('cancelled contradictory payout', 'settle_bets', [[B], dict(O, status='cancelled', payouts=[PAYOUT])]),
    ('repeated ledger ticket', 'append_purchase', [[P], dict(P, id='p2'), L]),
    ('naive ledger timestamp', 'append_purchase', [[], dict(P, purchased_at='2026-10-15T12:00:00'), L]),
    ('invalid timezone offset', 'append_purchase', [[], dict(P, purchased_at='2026-10-15T12:00:00+01:99'), L]),
    ('cumulative pending loss exposure', 'append_purchase', [[dict(P, bets=[dict(B, stake_yen=200)])],
        dict(P, id='p2', bets=[B2]), dict(L, day_budget_yen=10000, loss_limit_yen=200)]),
    ('invalid bet type object', 'validate_purchase', [[dict(B, bet_type=[])], L]),
    ('invalid status object', 'settle_bets', [[B], dict(O, status=[])]),
    ('unicode decimal input', 'estimate_bet', [100, '０.１', '15']),
    ('newline decimal input', 'estimate_bet', [100, '0.1\n', '15']),
    ('newline race identity', 'validate_purchase', [[dict(B, race_id=RACE + '\n')], L]),
    ('newline combination', 'validate_purchase', [[dict(B, combination='1-2-3\n')], L]),
    ('newline timestamp', 'append_purchase', [[], dict(P, purchased_at='2026-10-15T12:00:00Z\n'), L]),
    ('incoherent mutually exclusive probabilities', 'recommend_allocation', [[
        dict(B, probability='0.6', odds='15'), dict(B2, probability='0.6', odds='15')], L,
        dict(validated=True, data_complete=True)]),
    ('partial market must not settle other type', 'settle_bets', [[B], dict(O, verified_market_types=['exacta'])]),
]:
    CASES.append(dict(name=name, op=op, args=args, error=True))


class MoneyParityTests(unittest.TestCase):
    def test_browser_and_python_match_literal_contract(self):
        browser_core = ROOT / 'web' / 'money.js'
        self.assertTrue(browser_core.exists(), 'browser shared money engine must exist')
        money = importlib.import_module('race_ai.money')
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required to verify UI/API money parity')
        script = """const m=require(process.argv[1]); let raw='';
process.stdin.setEncoding('utf8'); process.stdin.on('data',x=>raw+=x);
process.stdin.on('end',()=>console.log(JSON.stringify(JSON.parse(raw).map(c=>{
  try { return {value:m[c.op](...c.args)}; }
  catch(e) { if(e instanceof m.MoneyError) return {error:true}; throw e; }
}))));"""
        execution = subprocess.run([node, '-e', script, str(browser_core)],
            input=json.dumps(CASES), text=True, encoding='utf-8', capture_output=True, check=True)
        browser = json.loads(execution.stdout)
        for case, actual in zip(CASES, browser):
            with self.subTest(case=case['name']):
                try:
                    python = dict(value=getattr(money, case['op'])(*case['args']))
                except money.MoneyError:
                    python = dict(error=True)
                self.assertEqual(actual, python)
                if case.get('error'):
                    self.assertEqual(actual, dict(error=True))
                else:
                    self.assertIn('value', actual)
                    for key, value in case.get('want', {}).items():
                        self.assertEqual(actual['value'][key], value)
        self.assertEqual(len(browser), len(CASES))


if __name__ == '__main__':
    unittest.main()
