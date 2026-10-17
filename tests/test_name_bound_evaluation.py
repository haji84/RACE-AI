"""Offline frozen three-phase scores; synthetic labels are not live evidence."""
import copy
from datetime import timedelta
import hashlib
import importlib
import math
import unittest
from unittest.mock import patch

from tests.test_name_bound_prediction import packet_fixture, NOW as PRE_RACE
from tests.test_name_bound_inputs import base_fixture, bodies
from tests.test_official_race_updates import DAY, page, results
from tests.test_live_evaluation_contract import rehash
from race_ai.official_race_updates import parse_update, endpoint
from web import race_contract as facts
from web.name_bound_inputs import _context
from web.name_bound_prediction import build_name_bound_prediction, digest, validate_name_bound_envelope

REPORT = set('schema_version race_id date_jst as_of closed_at status research_only validation_status purchase_decision purchase_recommendations comparison_scope physical_exhibition_timing_verified common_race_ids models forecast_proof result_proof exclusion_reason'.split())
FORECAST_PROOF = set('request_id snapshot_id envelope_sha256 baseline_request_id baseline_snapshot_id baseline_receipt_sha256 name_binding_request_id input_snapshot_id generated_at cloud_saved_at receipt_confirmed_at'.split())
RESULT_PROOF = set('snapshot_id source_url source_sha256 captured_at cloud_saved_at status finish_confirmed financial_confirmed top3 refund_boats program_identity_sha256'.split())
MODEL = set('model_id model_version phase race_count ticket_count multiclass_brier log_loss winner_probability forecast_generated_at forecast_cloud_saved_at'.split())
SCOPE = 'SAME_RACE_DIFFERENT_FEATURE_PHASES_NOT_EQUAL_INFORMATION_CUTOFF'


def fixture(body=None, *, capture=None, uniform=False):
    """Return race, finalized forecast, result bundle, actual postclose clock."""
    def uniform_program():
        feed, race = base_fixture()
        for boat in race['boats']: boat['national_win_rate'] = None
        return feed, race
    if uniform:
        with patch('tests.test_name_bound_inputs.base_fixture', side_effect=uniform_program):
            race, baseline, binding, inputs = packet_fixture()
    else:
        preview, original, companion = bodies()
        varied = (preview.replace(b'<td>6.92</td>', b'<td>6.72</td>', 1),
            original.replace(b'36.42\t5.94\t6.93', b'36.92\t5.94\t6.93', 1),
            companion.replace(b'\t6.92\t', b'\t6.72\t', 1))
        with patch('tests.test_name_bound_inputs.bodies', return_value=varied):
            race, baseline, binding, inputs = packet_fixture()
    snapshot = build_name_bound_prediction(inputs, race, baseline, binding,
        runner_saved_at=PRE_RACE, parents_resolved_at=PRE_RACE, input_cloud_saved_at=PRE_RACE, now=PRE_RACE)
    receipt = dict(schema_version=1, request_id='123499-1', baseline_request_id=baseline['request_id'],
        name_binding_request_id=binding['receipt']['request_id'], snapshot=snapshot,
        cloud_saved_at=facts.stamp(PRE_RACE), cloud_eligible_pre_race=True)
    marker = dict(schema_version=1, race_id=race['race_id'], request_id=receipt['request_id'],
        snapshot_id=snapshot['snapshot_id'], input_snapshot_id=inputs['snapshot_id'],
        baseline_request_id=baseline['request_id'], name_binding_request_id=binding['receipt']['request_id'],
        receipt_sha256=digest(receipt), receipt_confirmed_at=facts.stamp(PRE_RACE))
    forecast = dict(receipt=receipt, finalization=marker, inputs=inputs, baseline=baseline, name_binding=binding)
    projected = _context(race, baseline, binding, PRE_RACE)[3]
    captured = capture if capture is not None else facts._time(race['closed_at']) + timedelta(minutes=1)
    raw = page('raceresult', (results() if body is None else body).replace('選手1', '松田 大志郎'))
    record = parse_update(raw, kind='raceresult', day=DAY, venue='18', race_no=1,
        source_url=endpoint(DAY, '18', 1, 'raceresult'), captured_at=facts.stamp(captured), entries=projected['boats'])
    record['rights_review'] = 'user-confirmation-2026-10-15-official-facts'
    rehash(record)
    record.update(saved_at=facts.stamp(captured + timedelta(seconds=1)), storage_eligible_pre_race=False)
    result = dict(record=record, program_sha256=facts.program_digest(projected),
        cloud_saved_at=facts.stamp(captured + timedelta(seconds=2)), cloud_eligible_pre_race=False)
    bundle = dict(schema_version=1, race_id=race['race_id'], date_jst='2026-10-15', closed_at=race['closed_at'],
        program_sha256=facts.program_digest(projected), published_at=facts.stamp(captured + timedelta(seconds=3)),
        latest={'raceresult':record['snapshot_id']}, records=[result])
    now = max(captured + timedelta(seconds=4), facts._time(race['closed_at']) + timedelta(minutes=2))
    validate_name_bound_envelope(forecast, race, now=now)
    facts.validate_cloud_bundle(bundle, projected, now)
    return race, forecast, bundle, now


class NameBoundEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.module = importlib.import_module('web.name_bound_evaluation')
        except ModuleNotFoundError: cls.module = None

    def setUp(self):
        self.assertIsNotNone(self.module, 'pure name-bound evaluation module required')

    def evaluate(self, race, forecast, bundle, now):
        return self.module.build_name_bound_evaluation(forecast, bundle, race, now)

    def test_three_scores_independently_replay_selected_baseline_and_frozen_models(self):
        race, forecast, bundle, now = args = fixture()
        before = copy.deepcopy(args)
        report = self.evaluate(*args)
        self.assertEqual(args, before)
        self.assertEqual(set(report), REPORT)
        self.assertIs(type(report['schema_version']), int)
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['status'], 'EVALUATED')
        self.assertEqual(report['common_race_ids'], [race['race_id']])
        self.assertEqual(report['comparison_scope'], SCOPE)
        self.assertIs(report['research_only'], True)
        self.assertIs(report['physical_exhibition_timing_verified'], False)
        self.assertEqual((report['validation_status'], report['purchase_decision'], report['purchase_recommendations']), ('UNVALIDATED', 'skip', []))
        self.assertIsNone(report['exclusion_reason'])
        self.assertEqual(report['as_of'], facts.stamp(now))
        self.assertEqual(report['closed_at'], facts.stamp(race['closed_at']))
        snapshot = forecast['receipt']['snapshot']
        selected = next(m for m in forecast['baseline']['snapshot']['models'] if m['model_id'] == snapshot['baseline_link']['model_id'])
        self.assertEqual(len(report['models']), 3)
        self.assertEqual(len({r['winner_probability'] for r in report['models']}), 3)
        for row, model, phase in zip(report['models'], [selected, *snapshot['models']], ['B_ONLY_BASELINE', 'DISPLAY_V2', 'ORIGINAL_V2']):
            self.assertEqual(set(row), MODEL)
            self.assertEqual((row['model_id'],row['model_version'],row['phase']), (model['model_id'],model['model_version'],phase))
            probabilities = [x['probability'] for x in model['triples']]
            target = [x['combination'] == [1,2,3] for x in model['triples']]
            winner = probabilities[target.index(True)]
            self.assertAlmostEqual(row['multiclass_brier'], sum((p-int(hit))**2 for p,hit in zip(probabilities,target)), places=13)
            self.assertAlmostEqual(row['log_loss'], -math.log(winner), places=13)
            self.assertEqual(row['winner_probability'], winner)
            self.assertIs(type(row['race_count']), int)
            self.assertEqual((row['race_count'],row['ticket_count']), (1,120))
            receipt = forecast['baseline'] if phase == 'B_ONLY_BASELINE' else forecast['receipt']
            self.assertEqual(row['forecast_generated_at'], receipt['snapshot']['generated_at'])
            self.assertEqual(row['forecast_cloud_saved_at'], receipt['cloud_saved_at'])
        proof = report['forecast_proof']
        self.assertEqual(set(proof), FORECAST_PROOF)
        self.assertEqual(proof, dict(request_id='123499-1',snapshot_id=snapshot['snapshot_id'],
            envelope_sha256=hashlib.sha256(facts.canonical(forecast)).hexdigest(),baseline_request_id=forecast['baseline']['request_id'],
            baseline_snapshot_id=forecast['baseline']['snapshot']['snapshot_id'],baseline_receipt_sha256=digest(forecast['baseline']),
            name_binding_request_id=forecast['name_binding']['receipt']['request_id'],input_snapshot_id=forecast['inputs']['snapshot_id'],
            generated_at=snapshot['generated_at'],cloud_saved_at=forecast['receipt']['cloud_saved_at'],receipt_confirmed_at=forecast['finalization']['receipt_confirmed_at']))
        result = report['result_proof']
        self.assertEqual(set(result), RESULT_PROOF)
        self.assertEqual(result['program_identity_sha256'], snapshot['validation_program_identity_sha256'])
        self.assertEqual(result['refund_boats'], [])
        record = bundle['records'][0]['record']
        self.assertEqual({k:result[k] for k in ('snapshot_id','source_url','source_sha256')},
            {k:record[k] for k in ('snapshot_id','source_url','source_sha256')})
        self.assertEqual(result['captured_at'], facts.stamp(record['captured_at']))
        self.assertEqual(result['cloud_saved_at'], bundle['records'][0]['cloud_saved_at'])
        self.assertEqual(result['status'], 'settled')
        self.assertIs(result['finish_confirmed'], True)
        self.assertIs(result['financial_confirmed'], False)
        report['result_proof']['top3'][0] = 6
        self.assertEqual(bundle['records'][0]['record']['data']['top3'], [1,2,3])

    def test_uniform_analytical_metrics_for_all_three_phases(self):
        report = self.evaluate(*fixture(uniform=True))
        for row in report['models']:
            self.assertAlmostEqual(row['winner_probability'], 1/120, places=14)
            self.assertAlmostEqual(row['multiclass_brier'], 119/120, places=13)
            self.assertAlmostEqual(row['log_loss'], math.log(120), places=13)

    def test_missing_pending_cancelled_special_tie_refund_and_missing_third_are_empty(self):
        cases = [('<p>結果はまだありません。</p>', 'RESULT_PENDING', 'OFFICIAL_RESULT_PENDING'),
            ('<span class="heading1_mainLabel">レース延期</span>', 'RESULT_PENDING', 'OFFICIAL_RESULT_PENDING'),
            ('<span class="heading1_mainLabel">レース中止</span>', 'RESULT_UNSUPPORTED', 'OFFICIAL_RESULT_STATUS_UNSUPPORTED'),
            (results().replace('1-2-3','特払い').replace('¥610','¥70'), 'RESULT_UNSUPPORTED', 'OFFICIAL_RESULT_STATUS_UNSUPPORTED'),
            (results().replace('<td>2</td><td class="is-boatColor2">','<td>1</td><td class="is-boatColor2">'), 'RESULT_UNSUPPORTED', 'OFFICIAL_RESULT_STATUS_UNSUPPORTED'),
            (results(refund=True), 'RESULT_UNSUPPORTED', 'OFFICIAL_REFUND_OUTCOME_UNSUPPORTED'),
            (results().replace('<td>3</td><td class="is-boatColor3">','<td>欠</td><td class="is-boatColor3">'), 'RESULT_UNSUPPORTED', 'OFFICIAL_TOP3_NOT_UNIQUE')]
        for body,status,reason in cases:
            with self.subTest(status=status, reason=reason):
                report = self.evaluate(*fixture(body))
                self.assertEqual((report['status'],report['exclusion_reason'],report['models'],report['common_race_ids']), (status,reason,[],[]))
        race, forecast, _, now = fixture()
        report = self.evaluate(race, forecast, None, now)
        self.assertEqual((report['status'],report['exclusion_reason']), ('RESULT_NOT_OBTAINED','OFFICIAL_RESULT_NOT_OBTAINED'))
        self.assertIsNone(report['result_proof'])

    def test_null_receipt_is_pending_and_refund_boats_are_sorted(self):
        race, forecast, bundle, now = fixture()
        record = bundle['records'][0]['record']
        record.update(status='PENDING', data=None, missing_reason='OFFICIAL_RESULT_PAYOUT_ONLY')
        rehash(record); bundle['latest']['raceresult'] = record['snapshot_id']
        report = self.evaluate(race,forecast,bundle,now)
        self.assertEqual(report['status'], 'RESULT_PENDING')
        self.assertEqual(report['result_proof']['refund_boats'], [])
        race, forecast, bundle, now = fixture(results(refund=True))
        record = bundle['records'][0]['record']; record['data']['refund_boats'] = [6,2]
        rehash(record); bundle['latest']['raceresult'] = record['snapshot_id']
        self.assertEqual(self.evaluate(race,forecast,bundle,now)['result_proof']['refund_boats'], [2,6])

    def test_all_result_receipts_require_postclose_even_pending_null_or_cancelled(self):
        for body in ('<p>結果はまだありません。</p>', '<span class="heading1_mainLabel">レース延期</span>', '<span class="heading1_mainLabel">レース中止</span>'):
            args = fixture(body, capture=PRE_RACE)
            with self.subTest(body=body), self.assertRaises(ValueError): self.evaluate(*args)
        for offset in (-1, 0):
            race, forecast, _, _ = fixture()
            args = fixture('<p>結果はまだありません。</p>',capture=facts._time(race['closed_at'])+timedelta(microseconds=offset))
            if offset < 0:
                with self.assertRaises(ValueError): self.evaluate(*args)
            else: self.assertEqual(self.evaluate(*args)['status'],'RESULT_PENDING')

    def test_wrong_identity_program_hash_or_forecast_proofs_reject_even_without_result(self):
        mutations = [lambda b: b.update(program_sha256='0'*64),
            lambda b: b['records'][0]['record']['data']['results'][0].update(name='松田大志'),
            lambda b: b['records'][0]['record']['data']['results'][0].update(racer_registration_id='4999'),
            lambda b: b['records'][0].update(cloud_eligible_pre_race=True)]
        for mutate in mutations:
            race, forecast, bundle, now = fixture(); mutate(bundle)
            record = bundle['records'][0]['record']; rehash(record); bundle['latest']['raceresult'] = record['snapshot_id']
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): self.evaluate(race,forecast,bundle,now)
        for mutate in (lambda f:f['finalization'].update(receipt_sha256='0'*64),
                lambda f:f['receipt']['snapshot']['models'][0]['triples'][0].update(probability=.5),
                lambda f:f['baseline'].update(request_id='123498-1')):
            race, forecast, bundle, now = fixture(); mutate(forecast)
            with self.assertRaises(ValueError): self.evaluate(race,forecast,None,now)
        race, forecast, bundle, now = fixture()
        for clock in (now.replace(tzinfo=None),facts.stamp(now),now+timedelta(days=1),PRE_RACE):
            with self.subTest(clock=clock),self.assertRaises(ValueError): self.evaluate(race,forecast,bundle,clock)
        with self.assertRaises(ValueError): self.evaluate(race,None,bundle,now)


if __name__ == '__main__': unittest.main()
