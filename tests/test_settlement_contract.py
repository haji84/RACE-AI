"""Synthetic receipt projections; no purchases or official requests are made."""
import copy
from datetime import timedelta
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from race_ai.money import settle_bets
from tests.test_live_evaluation_contract import fixture, rehash, NOW
from tests.test_official_race_updates import results


MARKETS = ['exacta', 'place', 'quinella', 'quinella_place', 'trifecta', 'trio', 'win']
ROOT = Path(__file__).resolve().parents[1]


def refresh(bundle):
    record = bundle['records'][0]['record']
    rehash(record)
    bundle['latest'][record['kind']] = record['snapshot_id']


def complete_fixture():
    _, bundle, race = fixture()
    data = bundle['records'][0]['record']['data']
    data.update(confirmed=True, settlement_ready=True,
        available_market_types=MARKETS.copy(), verified_market_types=MARKETS.copy(),
        winning_coverage_status={kind: 'VERIFIED' for kind in MARKETS},
        payouts=[dict(bet_type=kind, combination=combo, payout_per_100_yen=amount)
            for kind, combo, amount in [
                ('trifecta', [1, 2, 3], 1580), ('trio', [1, 2, 3], 470),
                ('exacta', [1, 2], 370), ('quinella', [1, 2], 220),
                ('quinella_place', [1, 2], 110), ('quinella_place', [1, 3], 190),
                ('quinella_place', [2, 3], 230), ('win', [1], 150),
                ('place', [1], 110), ('place', [2], 130)]])
    refresh(bundle)
    return bundle, race


class SettlementContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.contract = importlib.import_module('web.settlement_contract')
        except ModuleNotFoundError:
            cls.contract = None

    def setUp(self):
        self.assertIsNotNone(self.contract, 'pure official settlement report must exist')

    def build(self, bundle=None, race=None, now=NOW):
        if race is None:
            bundle, race = complete_fixture()
        return self.contract.build_settlement_report(bundle, race, now)

    def test_complete_markets_settle_winning_and_losing_tickets_using_money(self):
        report = self.build()
        self.assertEqual(set(report), {'schema_version', 'race_id', 'date_jst', 'as_of', 'closed_at',
            'program_sha256', 'status', 'markets', 'excluded_market_types', 'result_proof', 'exclusion_reason'})
        self.assertEqual(report['status'], 'SETTLEMENT_READY')
        self.assertIsNone(report['exclusion_reason'])
        self.assertEqual(report['excluded_market_types'], [])
        self.assertEqual([m['verified_market_types'][0] for m in report['markets']], MARKETS)
        market = next(m for m in report['markets'] if m['verified_market_types'] == ['trifecta'])
        self.assertEqual(set(market), {'race_id', 'status', 'confirmed', 'verified_market_types', 'payouts', 'refunds', 'special_payouts'})
        bets = [dict(race_id=report['race_id'], bet_type='trifecta', combination=[1, 2, 3], stake_yen=400),
                dict(race_id=report['race_id'], bet_type='trifecta', combination=[3, 2, 1], stake_yen=100)]
        settled = settle_bets(bets, market)
        self.assertEqual(settled['payout_yen'], 6320)
        self.assertEqual(settled['net_profit_yen'], 5820)
        self.assertEqual(settled['rows'][1]['payout_yen'], 0)
        self.assertTrue(report['result_proof']['financial_confirmed'])

    def test_partial_receipt_exports_only_complete_market(self):
        _, bundle, race = fixture()
        report = self.build(bundle, race)
        self.assertEqual(report['status'], 'SETTLEMENT_PARTIAL')
        self.assertEqual([m['verified_market_types'] for m in report['markets']], [['trifecta']])
        self.assertEqual(report['excluded_market_types'], ['exacta', 'place', 'quinella', 'quinella_place', 'trio', 'win'])
        self.assertFalse(report['result_proof']['financial_confirmed'])

    def test_incomplete_multiwinner_markets_never_prove_a_loss(self):
        for kind, combination in [('place', [2]), ('quinella_place', [2, 3])]:
            bundle, race = complete_fixture()
            data = bundle['records'][0]['record']['data']
            data['payouts'] = [p for p in data['payouts'] if not (p['bet_type'] == kind and p['combination'] == combination)]
            data['verified_market_types'].remove(kind)
            data['winning_coverage_status'][kind] = 'INCOMPLETE'
            data.update(confirmed=False, settlement_ready=False)
            refresh(bundle)
            report = self.build(bundle, race)
            self.assertEqual(report['status'], 'SETTLEMENT_PARTIAL')
            self.assertEqual(report['excluded_market_types'], [kind])
            self.assertNotIn([kind], [m['verified_market_types'] for m in report['markets']])

    def test_forged_complete_coverage_and_invented_winners_rejected_after_rehash(self):
        mutations = [lambda d: d['payouts'].pop(),
            lambda d: d['payouts'][0].update(combination=[3, 2, 1]),
            lambda d: d['payouts'].append(copy.deepcopy(d['payouts'][0])),
            lambda d: d['payouts'][0].update(payout_per_100_yen=True),
            lambda d: d['payouts'][0].update(payout_per_100_yen=9007199254740992)]
        for mutate in mutations:
            bundle, race = complete_fixture()
            mutate(bundle['records'][0]['record']['data']); refresh(bundle)
            with self.subTest(mutate=repr(mutate)), self.assertRaises(ValueError):
                self.build(bundle, race)

    def test_missing_or_preview_only_receipts_are_empty_reports(self):
        _, _, race = fixture()
        for bundle in (None, fixture(kind='beforeinfo')[1]):
            report = self.build(bundle, race)
            self.assertEqual(report['status'], 'RESULT_NOT_OBTAINED')
            self.assertEqual(report['markets'], [])
            self.assertEqual(report['excluded_market_types'], MARKETS)
            self.assertIsNone(report['result_proof'])

    def test_pending_payout_only_and_unconfirmed_postponement_cannot_settle(self):
        for body in ['<p>結果はまだありません。</p>', '<span class="heading1_mainLabel">レース延期</span>']:
            _, bundle, race = fixture(body)
            report = self.build(bundle, race)
            self.assertEqual(report['status'], 'RESULT_PENDING')
            self.assertEqual(report['markets'], [])
        _, bundle, race = fixture()
        record = bundle['records'][0]['record']
        record.update(status='PENDING', data=None, missing_reason='OFFICIAL_RESULT_PAYOUT_ONLY')
        refresh(bundle)
        report = self.build(bundle, race)
        self.assertEqual(report['status'], 'RESULT_PENDING')
        self.assertFalse(report['result_proof']['financial_confirmed'])

    def test_explicit_full_refund_covers_all_seven_markets(self):
        _, bundle, race = fixture('<span class="heading1_mainLabel">レース中止</span>')
        for status in ['cancelled', 'no_contest', 'postponed']:
            bundle['records'][0]['record']['data']['status'] = status
            refresh(bundle)
            report = self.build(bundle, race)
            self.assertEqual(report['status'], 'SETTLEMENT_READY')
            self.assertEqual(len(report['markets']), 7)
            market = next(m for m in report['markets'] if m['verified_market_types'] == ['win'])
            settled = settle_bets([dict(race_id=race['race_id'], bet_type='win', combination=[6], stake_yen=400)], market)
            self.assertEqual(settled['refund_yen'], 400)
            self.assertEqual(settled['effective_stake_yen'], 0)

    def test_full_refund_without_positive_disposition_evidence_rejected(self):
        for changes in [dict(refund_policy_status='REFUND_DISPOSITION_NOT_CONFIRMED'), dict(refunds=None),
                        dict(confirmed=False), dict(verified_market_types=['trifecta'])]:
            _, bundle, race = fixture('<span class="heading1_mainLabel">レース中止</span>')
            bundle['records'][0]['record']['data'].update(changes); refresh(bundle)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(bundle, race)

    def test_returned_boats_and_unverified_ties_are_empty_unsupported_reports(self):
        bodies = [results(refund=True), results().replace('<td>2</td><td class="is-boatColor2">', '<td>1</td><td class="is-boatColor2">')]
        for body in bodies:
            _, bundle, race = fixture(body)
            report = self.build(bundle, race)
            self.assertEqual(report['status'], 'SETTLEMENT_UNSUPPORTED')
            self.assertEqual(report['markets'], [])
            self.assertEqual(report['excluded_market_types'], MARKETS)

    def test_explicit_special_payout_settles_only_that_market_and_rate(self):
        _, bundle, race = fixture(results().replace('1-2-3', '特払い').replace('¥610', '¥70'))
        report = self.build(bundle, race)
        self.assertEqual(report['status'], 'SETTLEMENT_PARTIAL')
        market = report['markets'][0]
        self.assertEqual(market['status'], 'special')
        self.assertEqual(market['payouts'], [])
        settled = settle_bets([dict(race_id=race['race_id'], bet_type='trifecta', combination=[6, 5, 4], stake_yen=400)], market)
        self.assertEqual(settled['payout_yen'], 280)
        self.assertEqual(settled['net_profit_yen'], -120)

    def test_mixed_special_and_normal_markets_use_independent_money_statuses(self):
        bundle, race = complete_fixture()
        data = bundle['records'][0]['record']['data']
        data['payouts'] = [p for p in data['payouts'] if p['bet_type'] != 'win']
        data.update(status='special', top3=None, confirmed=False, settlement_ready=False,
            special_payouts=[dict(bet_type='win', payout_per_100_yen=70)], verified_market_types=['win'],
            winning_coverage_status={kind: ('VERIFIED_EXPLICIT_SPECIAL_PAYOUT' if kind == 'win' else 'INCOMPLETE') for kind in MARKETS})
        refresh(bundle)
        report = self.build(bundle, race)
        self.assertEqual([m['verified_market_types'] for m in report['markets']], [['win']])
        self.assertEqual(report['markets'][0]['status'], 'special')

    def test_rehashed_source_and_roster_tampering_rejected(self):
        mutations = [lambda r: r.update(source_url='https://attacker.example/result'),
            lambda r: r.update(source_sha256='invalid'), lambda r: r.update(rights_review='unreviewed'),
            lambda r: r['data']['results'][0].update(racer_registration_id='4999'),
            lambda r: r['data']['results'][0].update(source_url='https://attacker.example/result')]
        for mutate in mutations:
            bundle, race = complete_fixture(); mutate(bundle['records'][0]['record']); refresh(bundle)
            with self.subTest(mutate=repr(mutate)), self.assertRaises(ValueError): self.build(bundle, race)

    def test_manifest_hash_identity_receipt_coverage_and_cloud_clocks_are_checked(self):
        mutations = [lambda b: b.update(program_sha256='b' * 64),
            lambda b: b.update(race_id='20261015-18-02'), lambda b: b.update(schema_version=True),
            lambda b: b['latest'].update(raceresult='b' * 64),
            lambda b: b['records'].append(copy.deepcopy(b['records'][0])),
            lambda b: b['records'][0].update(program_sha256='b' * 64),
            lambda b: b['records'][0].update(cloud_eligible_pre_race=True),
            lambda b: b['records'][0].update(cloud_saved_at='2026-10-15T09:00:00+09:00'),
            lambda b: b['records'][0].update(cloud_saved_at='2026-10-15T09:11:00+09:00'),
            lambda b: b.update(published_at='2026-10-15T09:00:01+09:00'),
            lambda b: b.update(published_at='2026-10-15T09:00:03+09:99'),
            lambda b: b['records'][0]['record'].update(source_sha256='b' * 64)]
        for mutate in mutations:
            bundle, race = complete_fixture(); mutate(bundle)
            with self.subTest(mutate=repr(mutate)), self.assertRaises(ValueError): self.build(bundle, race)

    def test_current_jst_day_and_actual_timezone_clock_required_even_without_result(self):
        _, _, race = fixture()
        for clock in [NOW + timedelta(days=1), NOW - timedelta(days=1), NOW.replace(tzinfo=None), NOW.isoformat()]:
            with self.subTest(clock=clock), self.assertRaises(ValueError): self.build(None, race, clock)

    def test_inputs_and_returned_nested_results_do_not_alias(self):
        bundle, race = complete_fixture()
        original = copy.deepcopy((bundle, race))
        report = self.build(bundle, race)
        self.assertEqual((bundle, race), original)
        report['markets'][0]['payouts'][0]['combination'][0] = 6
        report['result_proof']['top3'][0] = 6
        self.assertEqual((bundle, race), original)

    def test_contract_import_and_projection_need_no_api_storage_or_money_package(self):
        bundle, race = complete_fixture()
        script = '''import sys,json,datetime
sys.path.insert(0,sys.argv[1]);import settlement_contract as s
d=json.load(sys.stdin);r=s.build_settlement_report(d['b'],d['r'],datetime.datetime.fromisoformat(d['now']))
assert not any(k.startswith(('race_ai','api.')) or k=='sqlite3' for k in sys.modules)
print(json.dumps({'status':r['status'],'markets':len(r['markets'])}))'''
        run = subprocess.run([sys.executable, '-I', '-S', '-c', script, str(ROOT / 'web')],
            input=json.dumps(dict(b=bundle, r=race, now=NOW.isoformat())), text=True, encoding='utf-8', capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), dict(status='SETTLEMENT_READY', markets=7))


if __name__ == '__main__': unittest.main()
