"""Synthetic durable forecast/result evaluation, not live accuracy evidence."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest

from web import race_contract, research_contract
from race_ai.official_race_updates import parse_update, endpoint
from tests.test_official_race_updates import DAY, page, results, preview
from tests.test_live_research_contract import fixture as program_fixture, NOW as PRE_RACE


NOW = datetime.fromisoformat('2026-10-15T09:10:00+09:00')
CAPTURE = datetime.fromisoformat('2026-10-15T09:00:00+09:00')
REVIEW = 'user-confirmation-2026-10-15-official-facts'
ROOT = Path(__file__).resolve().parents[1]


def fixture(body=None, kind='raceresult', capture=CAPTURE):
    feed, race = program_fixture()
    race.update(race_id='20261015-18-01', closed_at='2026-10-15T08:43:00+09:00')
    feed['venues'][0]['venue'] = '18'
    for boat in race['boats']:
        boat['name'] = '選手' + str(boat['lane'])
    snapshot = research_contract.build_research_bundle(feed, race, PRE_RACE)
    prediction_receipt = dict(schema_version=1, request_id='123456-1', snapshot=snapshot,
        cloud_saved_at=race_contract.stamp(PRE_RACE + timedelta(seconds=1)),
        cloud_eligible_pre_race=True, program_sha256=snapshot['program_sha256'])
    raw = page(kind, body if body is not None else (results() if kind == 'raceresult' else preview()))
    record = parse_update(raw, kind=kind, day=DAY, venue='18', race_no=1,
        source_url=endpoint(DAY, '18', 1, kind), captured_at=capture.isoformat())
    record['rights_review'] = REVIEW
    rehash(record)
    record['saved_at'] = race_contract.stamp(capture + timedelta(seconds=1))
    record['storage_eligible_pre_race'] = record['eligible_pre_race'] and capture + timedelta(seconds=1) < datetime.fromisoformat(race['closed_at'])
    receipt = dict(record=record, program_sha256=race_contract.program_digest(race),
        cloud_saved_at=race_contract.stamp(capture + timedelta(seconds=2)),
        cloud_eligible_pre_race=record['storage_eligible_pre_race'] and capture + timedelta(seconds=2) < datetime.fromisoformat(race['closed_at']))
    bundle = dict(schema_version=1, race_id=race['race_id'], date_jst='2026-10-15', closed_at=race['closed_at'],
        program_sha256=race_contract.program_digest(race), published_at=race_contract.stamp(capture + timedelta(seconds=3)),
        latest={kind:record['snapshot_id']}, records=[receipt])
    return prediction_receipt, bundle, race


def rehash(record):
    raw = {key:value for key,value in record.items() if key not in race_contract.STORE_FIELDS}
    record['snapshot_id'] = hashlib.sha256(race_contract.canonical(raw)).hexdigest()


class EvaluationContractTests(unittest.TestCase):
    def test_verified_payout_only_result_is_pending_and_cannot_be_reused_for_preview(self):
        prediction,bundle,race=fixture();record=bundle['records'][0]['record']
        record.update(status='PENDING',data=None,missing_reason='OFFICIAL_RESULT_PAYOUT_ONLY')
        rehash(record);bundle['latest']['raceresult']=record['snapshot_id']
        report=self.evaluate(prediction,bundle,race)
        self.assertEqual(report['status'],'RESULT_PENDING')
        self.assertEqual(report['models'],[])
        self.assertIsNone(report['result_proof']['top3'])
        summary={key:value for key,value in record.items() if key!='data'};summary['payload_omitted']=True
        race_contract.validate_summary(summary,race,NOW)
        prediction,bundle,race=fixture(kind='beforeinfo');record=bundle['records'][0]['record']
        record.update(status='PENDING',data=None,missing_reason='OFFICIAL_RESULT_PAYOUT_ONLY')
        rehash(record)
        with self.assertRaises(ValueError):race_contract.validate_record(record,race,NOW)
        summary={key:value for key,value in record.items() if key!='data'};summary['payload_omitted']=True
        with self.assertRaises(ValueError):race_contract.validate_summary(summary,race,NOW)

    @classmethod
    def setUpClass(cls):
        try:
            cls.c = importlib.import_module('web.evaluation_contract')
        except ModuleNotFoundError:
            cls.c = None

    def setUp(self):
        self.assertIsNotNone(self.c, 'standalone durable research evaluation must exist')

    def evaluate(self, prediction=None, bundle=None, race=None, now=NOW):
        if race is None:
            prediction, bundle, race = fixture()
        return self.c.build_research_evaluation(prediction, bundle, race, now)

    def test_uniform_hand_calculated_metrics_and_same_race_cohort(self):
        report = self.evaluate()
        self.assertEqual(report['status'], 'EVALUATED')
        self.assertEqual(report['common_race_ids'], ['20261015-18-01'])
        self.assertEqual(report['comparison_scope'], 'same_race_and_information_cutoff')
        self.assertEqual(report['purchase_recommendations'], [])
        self.assertEqual(report['validation_status'], 'UNVALIDATED')
        self.assertEqual(report['purchase_decision'], 'skip')
        self.assertIsNone(report['exclusion_reason'])
        self.assertEqual(len(report['models']), 2)
        uniform = report['models'][0]
        self.assertEqual(uniform['race_count'], 1)
        self.assertEqual(uniform['ticket_count'], 120)
        self.assertAlmostEqual(uniform['winner_probability'], 1 / 120, places=14)
        self.assertAlmostEqual(uniform['multiclass_brier'], 119 / 120, places=12)
        self.assertAlmostEqual(uniform['log_loss'], math.log(120), places=12)
        self.assertTrue(report['result_proof']['finish_confirmed'])
        self.assertFalse(report['result_proof']['financial_confirmed'])
        self.assertEqual(report['result_proof']['top3'], [1, 2, 3])

    def test_missing_prediction_and_result_are_explicit_without_metrics(self):
        prediction, bundle, race = fixture()
        cases = [(None, bundle, 'PREDICTION_NOT_SAVED', 'PREDICTION_DURABLE_PRE_RACE_PROOF_MISSING'),
                 (prediction, None, 'RESULT_NOT_OBTAINED', 'OFFICIAL_RESULT_NOT_OBTAINED'),
                 (None, None, 'PREDICTION_NOT_SAVED', 'PREDICTION_DURABLE_PRE_RACE_PROOF_MISSING')]
        for p, b, status, reason in cases:
            with self.subTest(status=status):
                report = self.evaluate(p, b, race)
                self.assertEqual(report['status'], status)
                self.assertEqual(report['exclusion_reason'], reason)
                self.assertEqual(report['models'], [])
                self.assertEqual(report['common_race_ids'], [])

    def test_preview_bundle_is_not_an_obtained_result(self):
        prediction, bundle, race = fixture(kind='beforeinfo', capture=PRE_RACE)
        report = self.evaluate(prediction, bundle, race)
        self.assertEqual(report['status'], 'RESULT_NOT_OBTAINED')
        self.assertIsNone(report['result_proof'])

    def test_pending_result_and_postponement_are_not_misses(self):
        for body in ('<p>結果はまだありません。</p>', '<span class="heading1_mainLabel">レース延期</span>'):
            prediction, bundle, race = fixture(body)
            report = self.evaluate(prediction, bundle, race)
            self.assertEqual(report['status'], 'RESULT_PENDING')
            self.assertEqual(report['exclusion_reason'], 'OFFICIAL_RESULT_PENDING')
            self.assertFalse(report['result_proof']['finish_confirmed'])
            self.assertEqual(report['models'], [])

    def test_ties_special_refund_and_cancellation_are_explicit_exclusions(self):
        bodies = [results().replace('<td>2</td><td class="is-boatColor2">', '<td>1</td><td class="is-boatColor2">'),
                  results().replace('1-2-3', '特払い').replace('¥610', '¥70'),
                  '<span class="heading1_mainLabel">レース中止</span>', results(refund=True)]
        for body in bodies:
            prediction, bundle, race = fixture(body)
            report = self.evaluate(prediction, bundle, race)
            self.assertEqual(report['status'], 'RESULT_UNSUPPORTED')
            self.assertEqual(report['models'], [])
        self.assertEqual(report['exclusion_reason'], 'OFFICIAL_REFUND_OUTCOME_UNSUPPORTED')

    def test_frozen_prediction_is_not_recomputed_from_later_program_points(self):
        prediction, bundle, race = fixture()
        original = self.evaluate(prediction, bundle, race)
        race['boats'][0]['national_win_rate'] = .5
        race['program_source_sha256'] = 'b' * 64
        self.assertEqual(self.evaluate(prediction, bundle, race), original)

    def test_prediction_without_actual_preclose_receipt_is_rejected(self):
        for changes in (dict(cloud_saved_at='2026-10-15T08:43:00+09:00'),
                        dict(cloud_saved_at='2026-10-15T07:32:59+09:00'),
                        dict(cloud_eligible_pre_race=False), dict(schema_version=True),
                        dict(request_id='../escape'), dict(program_sha256='b' * 64)):
            prediction, bundle, race = fixture()
            prediction.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.evaluate(prediction, bundle, race)

    def test_rehashed_model_probability_and_metadata_tampering_rejected(self):
        prediction, bundle, race = fixture()
        prediction['snapshot']['models'][0]['triples'][0]['probability'] = .5
        prediction['snapshot']['snapshot_id'] = research_contract._sha({k:v for k,v in prediction['snapshot'].items() if k != 'snapshot_id'})
        with self.assertRaises(ValueError):
            self.evaluate(prediction, bundle, race)

    def test_result_receipt_hash_source_roster_and_manifest_are_validated(self):
        mutations = [lambda b:b.update(program_sha256='b' * 64),
            lambda b:b['records'][0].update(program_sha256='b' * 64),
            lambda b:b['records'][0].update(cloud_eligible_pre_race=True),
            lambda b:b['records'][0]['record'].update(snapshot_id='b' * 64),
            lambda b:b['records'][0]['record'].update(source_url='https://attacker.example/result'),
            lambda b:b['records'][0]['record']['data']['results'][0].update(racer_registration_id='4999'),
            lambda b:b['latest'].update(raceresult='b' * 64),
            lambda b:b.update(schema_version=True)]
        for mutate in mutations:
            prediction, bundle, race = fixture()
            mutate(bundle)
            with self.subTest(mutation=repr(mutate)), self.assertRaises(ValueError):
                self.evaluate(prediction, bundle, race)

    def test_actual_save_and_published_clocks_cannot_precede_readback_or_asof(self):
        for field, stamp in (('cloud_saved_at', '2026-10-15T09:00:00+09:00'),
                             ('cloud_saved_at', '2026-10-15T09:11:00+09:00')):
            prediction, bundle, race = fixture()
            bundle['records'][0][field] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                self.evaluate(prediction, bundle, race)
        prediction, bundle, race = fixture()
        bundle['published_at'] = '2026-10-15T09:00:01+09:00'
        with self.assertRaises(ValueError):
            self.evaluate(prediction, bundle, race)
        with self.assertRaises(ValueError):
            self.evaluate(*fixture(), now=PRE_RACE)

    def test_invalid_timezone_offsets_are_rejected_at_every_proof_boundary(self):
        for location in ('prediction', 'cloud_result', 'manifest', 'captured_result'):
            prediction, bundle, race = fixture()
            invalid = '2026-10-15T09:00:00+09:99'
            if location == 'prediction': prediction['cloud_saved_at'] = invalid
            elif location == 'cloud_result': bundle['records'][0]['cloud_saved_at'] = invalid
            elif location == 'manifest': bundle['published_at'] = invalid
            else:
                bundle['records'][0]['record']['captured_at'] = invalid
                rehash(bundle['records'][0]['record'])
                bundle['latest']['raceresult'] = bundle['records'][0]['record']['snapshot_id']
            with self.subTest(location=location), self.assertRaises(ValueError):
                self.evaluate(prediction, bundle, race)

    def test_all_supplied_inputs_are_checked_even_when_another_is_absent(self):
        _, bundle, race = fixture()
        bundle['records'][0]['record']['source_sha256'] = False
        with self.assertRaises(ValueError):
            self.evaluate(None, bundle, race)
        prediction, _, race = fixture()
        prediction['cloud_eligible_pre_race'] = False
        with self.assertRaises(ValueError):
            self.evaluate(prediction, None, race)

    def test_duplicate_receipts_and_nonfinite_values_never_become_metrics(self):
        prediction, bundle, race = fixture()
        bundle['records'].append(copy.deepcopy(bundle['records'][0]))
        with self.assertRaises(ValueError):
            self.evaluate(prediction, bundle, race)
        prediction, bundle, race = fixture()
        prediction['snapshot']['models'][0]['triples'][0]['probability'] = float('nan')
        with self.assertRaises(ValueError):
            self.evaluate(prediction, bundle, race)

    def test_stdlib_web_root_import_requires_no_sqlite_money_or_api(self):
        prediction, bundle, race = fixture()
        script = """import sys,json,datetime
sys.path.insert(0,sys.argv[1]);import evaluation_contract as e
d=json.load(sys.stdin);r=e.build_research_evaluation(d['p'],d['b'],d['r'],datetime.datetime.fromisoformat(d['now']))
assert not any(k.startswith(('race_ai','api.')) or k=='sqlite3' for k in sys.modules)
print(json.dumps({'status':r['status'],'models':len(r['models'])}))"""
        execution = subprocess.run([sys.executable, '-I', '-S', '-c', script, str(ROOT / 'web')],
            input=json.dumps(dict(p=prediction,b=bundle,r=race,now=NOW.isoformat())),
            text=True, encoding='utf-8', capture_output=True)
        self.assertEqual(execution.returncode, 0, execution.stderr)
        self.assertEqual(json.loads(execution.stdout), dict(status='EVALUATED', models=2))

    def test_normal_result_without_a_unique_third_place_is_not_scored(self):
        body = results().replace('<td>3</td><td class="is-boatColor3">', '<td>欠</td><td class="is-boatColor3">')
        prediction, bundle, race = fixture(body)
        report = self.evaluate(prediction, bundle, race)
        self.assertEqual(report['result_proof']['status'], 'settled')
        self.assertIsNone(report['result_proof']['top3'])
        self.assertEqual(report['status'], 'RESULT_UNSUPPORTED')
        self.assertEqual(report['exclusion_reason'], 'OFFICIAL_TOP3_NOT_UNIQUE')
        self.assertEqual(report['models'], [])

    def test_returned_score_proof_cannot_mutate_the_source_receipt(self):
        prediction, bundle, race = fixture()
        report = self.evaluate(prediction, bundle, race)
        report['result_proof']['top3'][0] = 6
        self.assertEqual(bundle['records'][0]['record']['data']['top3'], [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
