"""Synthetic saved thirty-cell originals; no live source, grant or owner key.

This tests forecast admission only. Published source acquisition and the horse
card's membership in independently fetched input archives are separate gates.
"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai.manual_official_capture import TERMS_SCHEMA
from tests.test_all_existing_model_thirty_order_pdca_artifacts import full_fixture, EVALUATED
from tests.test_all_existing_model_native_future_v3 import KEY, NOW


def _pin(metadata):
    return dict(id=metadata['id'], digest=metadata['digest'],
                run_id=metadata['workflow_run']['id'], head_sha=metadata['workflow_run']['head_sha'])


def admission_manifest(fixture):
    """Author a new request around immutable synthetic saved native originals."""
    routes={
        'autorace':dict(kind='NORMAL_UI', ui_entry_url='https://autorace.jp/race_info/Live/isesaki',
                       ui_venue_name='伊勢崎', place_code=3),
        'keirin':dict(kind='NORMAL_UI', ui_entry_url='https://keirin.jp/pc/top', ui_venue_name='四日市競輪場'),
        'horse':dict(kind='JRA_CARD_PUBLISHED_GET',
                     card_url='https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0103203002011120300202/AA'),
    }
    day=EVALUATED.astimezone(timezone(timedelta(hours=9))).date().isoformat()
    cases=[]
    for sport in routes:
        request=next(r for r in fixture['requests'] if r['cell_key'].split('/', 1)[0]==sport)
        info=registry.identity(request['cell_key'].split('/', 1)[1], sport, request['native_payload'])
        cases.append(dict(sport=sport, race_id=info['race_id'], route=routes[sport]))
    terms=[]
    policies={'autorace':'https://autorace.jp/policy/', 'keirin':'https://keirin.jp/pc/dfw/portal/guest/sitepolicy/index.html',
              'horse':'https://www.jra.go.jp/copyright.html'}
    for case in cases:
        route=case['route']; url=route.get('ui_entry_url', route.get('card_url'))
        terms.append(dict(sport=case['sport'], terms_url=policies[case['sport']], policy_sha256='a'*64,
                          policy_captured_at=(NOW-timedelta(days=1)).isoformat(), source_urls=[url],
                          uses=['private_retention', 'private_factual_analysis']))
    return dict(schema='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V1', execution_day=day,
                target_event_day='2030-02-02', forecast_artifact=_pin(fixture['native_metadata']),
                origin_artifact=_pin(fixture['origin_metadata']), cases=cases,
                terms_manifest=dict(schema=TERMS_SCHEMA, execution_day=day, purpose='PRIVATE_FACTUAL_ANALYSIS',
                    public_redistribution=False, provider_model_training_permission_confirmed=False,
                    owner_instruction_ref='SYNTHETIC_ONLY_NO_ACTUAL_OWNER_INSTRUCTION', terms=terms),
                prior_journal_artifacts=[dict(id=800, digest='sha256:'+'b'*64, run_id=9, head_sha='c'*40)],
                maximum_requests=32, allow_order_only=True)


class FutureResultForecastAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import before the expensive shared fixture: RED is a missing API, not
        # a newly executed fit. full_fixture caches its one real-core fit.
        from race_ai import all_existing_model_future_result_capture as api
        cls.api=api
        cls.fixture=full_fixture()

    def setUp(self):
        self.value=deepcopy(self.fixture)
        self.manifest=admission_manifest(self.value)
        self.environment=patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        self.environment.start(); self.addCleanup(self.environment.stop)

    def admit(self, *, now=EVALUATED, **changes):
        args=dict(forecast_raw=self.value['native_raw'], forecast_metadata=self.value['native_metadata'],
                  origin_raw=self.value['origin_raw'], origin_metadata=self.value['origin_metadata'], now=now, key=KEY)
        args.update(changes)
        return self.api.admit_forecast(self.manifest, **args)

    def test_saved_full_thirty_originals_admit_three_due_sports_without_source_calls(self):
        before=deepcopy(self.manifest)
        with patch('urllib.request.urlopen', side_effect=AssertionError('NO_SOURCE_OR_NETWORK')):
            result=self.admit()
        self.assertEqual(len(result['records']), 30)
        expected={request['cell_key']:request['native_payload'] for request in self.value['requests']}
        self.assertEqual({r['cell_key'] for r in result['records']}, set(expected))
        self.assertTrue(all('pair' in r and r['native_payload']==expected[r['cell_key']] for r in result['records']))
        self.assertEqual({r['cell_key'].split('/', 1)[0] for r in result['records']},
                         {'boat', 'autorace', 'keirin', 'horse'})
        self.assertEqual({c['case']['sport'] for c in result['cases']}, {'autorace', 'keirin', 'horse'})
        self.assertEqual({c['case']['race_id'] for c in result['cases']}, {c['race_id'] for c in self.manifest['cases']})
        self.assertTrue(result['forecast_admission']['independent_pre_cutoff_receipt_verified'])
        self.assertEqual(result['forecast_admission']['frozen_input_only_partition_count'], 0)
        self.assertEqual(result['source_input_artifacts'], result['origin']['generation']['source_input_artifacts'])
        self.assertEqual(self.manifest, before)
        self.assertEqual(sha256(self.value['native_raw']).hexdigest(),
                         self.value['native_metadata']['digest'].removeprefix('sha256:'))

    def test_exact_forecast_server_pin_and_repository_identity_required(self):
        for field in ('id', 'digest', 'run_id', 'head_sha', 'repository', 'expired'):
            value=deepcopy(self.value['native_metadata'])
            if field=='id': value['id']+=1
            elif field=='digest': value['digest']='sha256:'+'f'*64
            elif field in ('run_id', 'head_sha'):
                value['workflow_run']['id' if field=='run_id' else 'head_sha']=43 if field=='run_id' else 'f'*40
            elif field=='repository': value['workflow_run']['head_repository_id']=1
            else: value['expired']=True
            with self.subTest(field=field), self.assertRaises(ValueError): self.admit(forecast_metadata=value)

    def test_origin_pin_full_cipher_and_same_run_head_are_required(self):
        for field in ('digest', 'head', 'run', 'bytes'):
            metadata=deepcopy(self.value['origin_metadata']); raw=self.value['origin_raw']
            if field=='digest': metadata['digest']='sha256:'+'f'*64
            elif field=='head': metadata['workflow_run']['head_sha']='f'*40
            elif field=='run': metadata['workflow_run']['id']=43
            else: raw=raw[:-1]+bytes([raw[-1]^1])
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.admit(origin_raw=raw, origin_metadata=metadata)

    def test_late_forecast_receipt_cannot_become_a_pre_cutoff_original(self):
        value=deepcopy(self.value['native_metadata'])
        value['created_at']='2030-02-02T23:50:01+09:00'
        with self.assertRaises(ValueError): self.admit(forecast_metadata=value)

    def test_each_requested_case_must_be_due_by_two_minutes(self):
        boundary=datetime.fromisoformat('2030-02-02T23:52:00+09:00')
        # Reauthor only the request's actual execution date; all saved source,
        # snapshot, forecast, receipt and origin clocks remain untouched.
        self.manifest['execution_day']='2030-02-02'
        self.manifest['terms_manifest']['execution_day']='2030-02-02'
        with self.assertRaises(ValueError): self.admit(now=boundary-timedelta(microseconds=1))
        self.assertEqual(len(self.admit(now=boundary)['cases']), 3)

    def test_foreign_race_or_native_day_cannot_join_saved_forecast(self):
        for change in ('race', 'day', 'missing_sport', 'duplicate_sport'):
            original=deepcopy(self.manifest)
            if change=='race': self.manifest['cases'][0]['race_id']='autorace:2030-02-02:isesaki:12'
            elif change=='day': self.manifest['target_event_day']='2030-02-01'
            elif change=='missing_sport': self.manifest['cases'].pop()
            else: self.manifest['cases'][-1]=deepcopy(self.manifest['cases'][0])
            with self.subTest(change=change), self.assertRaises(ValueError): self.admit()
            self.manifest=original

    def test_cash_scope_or_unsigned_extra_fields_do_not_expand_order_only_admission(self):
        for change in (dict(allow_order_only=False), dict(allow_order_only=1), dict(maximum_requests=True),
                       dict(maximum_requests=33), dict(label_evaluation_scope='CASH'), dict(schema='UNKNOWN')):
            original=deepcopy(self.manifest); self.manifest.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.admit()
            self.manifest=original

    def test_wrong_key_and_truncated_native_cipher_never_admit(self):
        with self.assertRaises(ValueError): self.admit(key=b'x'*32)
        with self.assertRaises(ValueError): self.admit(forecast_raw=self.value['native_raw'][:-1])


class FutureResultSourceCapsuleJoinTests(unittest.TestCase):
    """Unit-test the join after authentication, not a source-ZIP receipt claim.

    The archive reader is replaced only here. Forecast/origin ZIP authentication
    is exercised with the real codecs in FutureResultForecastAdmissionTests.
    """
    def setUp(self):
        from race_ai import all_existing_model_future_result_capture as api
        from tests.test_all_existing_model_common_eight_per_sport import common_records
        self.api=api
        row=next(row for row in common_records(1) if row['sport']=='keirin')
        self.record=dict(cell_key=row['sport']+'/'+row['model_id'], native_payload=deepcopy(row['native_payload']))
        self.capsule=dict(cell_key=self.record['cell_key'], input_sha256=digest(self.record['native_payload']),
                          native_payload=deepcopy(self.record['native_payload']))
        self.pin=dict(id=811, digest='sha256:'+'8'*64, run_id=21, head_sha='9'*40)
        self.audit=dict(artifact_id=811, artifact_digest=self.pin['digest'], saved_at=NOW.isoformat(),
                        record_sha256=['7'*64])
        self.admitted=dict(source_input_artifacts=[deepcopy(self.pin)],
            origin=dict(source_audit=dict(source_admissions=[deepcopy(self.audit)])), records=[deepcopy(self.record)])
        self.archive=dict(raw=b'SYNTHETIC_AUTHENTICATION_BOUNDARY_ONLY', metadata=dict(
            id=811, digest=self.pin['digest'], workflow_run=dict(id=21, head_sha='9'*40)))
        self.receipt={name:deepcopy(self.audit[name]) for name in ('artifact_digest', 'saved_at', 'record_sha256')}
        self.rows=[dict(captured_native_inputs=[deepcopy(self.capsule)])]

    def join(self, *, archives=None, receipt=None, rows=None):
        with patch.object(self.api, '_verified_private_pairs_artifact', return_value=(
                self.receipt if receipt is None else receipt, self.rows if rows is None else rows)):
            return self.api.admit_native_sources(self.admitted, [self.archive] if archives is None else archives,
                                                  now=EVALUATED, key=KEY)

    def test_exact_authenticated_capsule_join_preserves_original_native_value_and_clocks(self):
        before=deepcopy(self.admitted)
        result=self.join()
        self.assertEqual(result['source_input_artifact_count'], 1)
        self.assertEqual(result['source_input_pins_sha256'], digest([self.pin]))
        self.assertEqual(self.admitted, before)

    def test_missing_foreign_receipt_or_changed_capsule_cannot_supply_originals(self):
        with self.assertRaises(ValueError): self.join(archives=[])
        with self.assertRaises(ValueError): self.join(archives=[self.archive, self.archive])
        foreign=deepcopy(self.archive); foreign['metadata']['workflow_run']['head_sha']='f'*40
        with self.assertRaises(ValueError): self.join(archives=[foreign])
        receipt=deepcopy(self.receipt); receipt['record_sha256']=['f'*64]
        with self.assertRaises(ValueError): self.join(receipt=receipt)
        for change in ('payload', 'hash', 'cell', 'absent'):
            rows=deepcopy(self.rows); capsule=rows[0]['captured_native_inputs'][0]
            if change=='payload': capsule['native_payload']['scope']='ALTERED_SYNTHETIC_VALUE'
            elif change=='hash': capsule['input_sha256']='f'*64
            elif change=='cell': capsule['cell_key']='horse/FOREIGN_CELL'
            else: rows[0]['captured_native_inputs']=[]
            with self.subTest(change=change), self.assertRaises(ValueError): self.join(rows=rows)


if __name__=='__main__': unittest.main()
