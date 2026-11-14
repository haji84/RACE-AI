"""Encrypted fictional native rounds and independently supplied result fixtures."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import boat_all_model_cycle as engine, boat_all_model_store as store
from race_ai import all_existing_model_registry as registry
from tests import test_boat_all_model_cycle as fixtures

KEY = bytes(range(32))  # Deliberately public fixture-only key.


class RoundIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fitted = fixtures.fitted_ranker()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'RACE_AI_STATE_KEY': base64.b64encode(KEY).decode()})
        env.start(); self.addCleanup(env.stop)
        self.payload = engine.forecast_round([fixtures.source_context()], self.runtime(fitted=True), now=fixtures.NOW)
        self.raw, self.metadata = self.artifact(self.payload)
        self.now = datetime.fromisoformat('2030-04-01T21:05:00+09:00')

    def runtime(self, *, fitted=False):
        return fixtures.AllModelCycleTests.runtime(self, fitted=fitted)

    def module(self):
        from race_ai import all_existing_model_round_intake
        return all_existing_model_round_intake

    def artifact(self, payload, *, saved='2030-04-01T18:00:20+09:00', members=None):
        cipher = store.seal_forecasts(payload, run_id='42', round_no=1, key=KEY)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in (members or [('forecasts.enc', cipher)]):
                archive.writestr(name, body)
        raw = output.getvalue()
        metadata = dict(id=201, name='boat-all-model-forecasts-42-r1', expired=False,
            digest='sha256:'+sha256(raw).hexdigest(), size_in_bytes=len(raw), created_at=saved,
            expires_at='2030-04-08T18:00:20+09:00',
            workflow_run=dict(id=42, head_sha=fixtures.HEAD, repository_id=1416489937, head_repository_id=1416489937))
        return raw, metadata

    def result(self, payload=None, **changes):
        payload = payload or self.payload
        capsule = payload['native_input_capsules'][0]
        group = next(iter(capsule['native_inputs']))
        mid = capsule['group_model_ids'][group][0]
        info = registry.identity(mid, 'boat', capsule['native_inputs'][group])
        captured = datetime.fromisoformat(info['race_cutoff_at'])+timedelta(minutes=5)
        value = dict(race_id=info['race_id'], sport='boat', status='settled',
            ordered_top3=list(map(int, sorted(info['roster'], key=int)[:3])), roster=info['roster'],
            captured_at=captured.isoformat(), published_at=None, source_ref='https://www.boatrace.jp/fixture-result',
            source_rights_ref='fixture-result', source_sha256='d'*64, identity_verified=True,
            payout_per_100_yen=500, refund_numbers=[], closed_at=info['race_cutoff_at'])
        value.update(changes)
        return value

    def intake(self, observations=None, *, raw=None, metadata=None):
        return self.module().records_from_round_artifact(self.raw if raw is None else raw,
            self.metadata if metadata is None else metadata,
            [self.result()] if observations is None else observations, now=self.now,
            expected_run_id=42, expected_head_sha=fixtures.HEAD)

    def test_actual_codec_native_groups_join_settled_results_and_preserve_exact_evidence(self):
        result = self.intake()
        self.assertGreaterEqual(len(result['records']), 4)
        self.assertGreaterEqual(sum(registry.group(r['model_id']) == 'shared' for r in result['records']), 2)
        self.assertTrue(any(registry.group(r['model_id']) == 'boat_full' for r in result['records']))
        from race_ai.all_existing_model_learning import _record
        capsule = self.payload['native_input_capsules'][0]
        for row in result['records']:
            group = registry.group(row['model_id']); frozen = capsule['native_inputs'][group]
            self.assertEqual(row['frozen_native_payload'], frozen)
            self.assertEqual(row['input_sha256'], digest(row['native_payload']))
            proof = row['input_receipt']
            self.assertEqual(proof['frozen_native_input_sha256'], digest(frozen))
            self.assertEqual(proof['model_input_sha256'], row['input_sha256'])
            self.assertEqual(proof['capsule_sha256'], capsule['capsule_sha256'])
            self.assertEqual(proof['artifact_metadata'], self.metadata)
            self.assertTrue(proof['independent_pre_cutoff_receipt_verified'])
            self.assertEqual(row['result']['published_at'], None)
            self.assertEqual(_record(row, self.now, lambda *_: True, lambda *_: True), row)
        self.assertEqual(result['receipt']['payload_sha256'], digest(self.payload))
        self.assertTrue(result['summary']['independent_pre_cutoff_receipt_verified'])
        self.assertNotIn('native_payload', result['summary'])
        self.assertNotIn('source_ref', str(result['summary']))

    def test_pending_special_missing_and_duplicate_results_never_become_losses(self):
        for observations, field in (([], 'missing_result_native_input_count'),
            ([self.result(status='pending')], 'pending_result_native_input_count'),
            ([self.result(status='special')], 'special_result_native_input_count')):
            result = self.intake(observations)
            self.assertEqual(result['records'], [])
            self.assertGreater(result['summary'][field], 0)
        from race_ai.existing_model_dispatch import _race_key
        alias = self.result(); alias['race_id'] = _race_key(alias['race_id'], 'boat')
        duplicate = self.intake([self.result(), alias])
        self.assertEqual(duplicate['summary']['duplicate_result_count'], 1)
        conflicting = self.result(payout_per_100_yen=700)
        with self.assertRaises(ValueError):
            self.intake([self.result(), conflicting])

    def test_key_and_cipher_authentication_precede_observation_use(self):
        module = self.module()
        with patch.object(module, '_results', side_effect=AssertionError('labels inspected before authentication')):
            with patch.dict(os.environ, {'RACE_AI_STATE_KEY': ''}), self.assertRaises(ValueError):
                module.records_from_round_artifact(b'invalid', {}, [], now=self.now,
                    expected_run_id=42, expected_head_sha=fixtures.HEAD)
            with patch.dict(os.environ, {'RACE_AI_STATE_KEY': base64.b64encode(bytes(reversed(range(32)))).decode()}), \
                    self.assertRaises(ValueError):
                self.intake()

    def test_actual_metadata_digest_head_round_expiry_and_strict_save_clock_are_required(self):
        changes = ({'digest': 'sha256:'+'f'*64}, {'size_in_bytes': len(self.raw)+1},
            {'expired': True}, {'expires_at': self.now.isoformat()},
            {'name': 'boat-all-model-forecasts-42-r2'})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.intake(metadata=dict(self.metadata, **change))
        for change in ({'head_sha': 'f'*40}, {'head_repository_id': 1}, {'repository_id': 1}):
            metadata = deepcopy(self.metadata); metadata['workflow_run'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.intake(metadata=metadata)
        cutoff = self.result()['closed_at']
        raw, metadata = self.artifact(self.payload, saved=cutoff)
        with self.assertRaises(ValueError): self.intake(raw=raw, metadata=metadata)
        raw, metadata = self.artifact(self.payload, saved=(datetime.fromisoformat(cutoff)-timedelta(seconds=1)).isoformat())
        with self.assertRaises(ValueError): self.intake(raw=raw, metadata=metadata)

    def test_only_bounded_single_cipher_zip_and_original_native_capsules_are_admitted(self):
        for members in ([('other.enc', b'x')], [('forecasts.enc', b'x'), ('extra.json', b'{}')]):
            raw, metadata = self.artifact(self.payload, members=members)
            with self.assertRaises(ValueError): self.intake(raw=raw, metadata=metadata)
        raw = self.raw+b'padding'
        metadata = dict(self.metadata, digest='sha256:'+sha256(raw).hexdigest(), size_in_bytes=len(raw))
        with self.assertRaises(ValueError): self.intake(raw=raw, metadata=metadata)
        legacy = deepcopy(self.payload); legacy.pop('native_input_capsules')
        raw, metadata = self.artifact(legacy)
        result = self.intake(raw=raw, metadata=metadata)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['summary']['state'], 'NATIVE_INPUT_CAPSULES_MISSING')
        self.assertFalse(result['summary']['independent_pre_cutoff_receipt_verified'])

    def test_rehashed_roster_and_source_clock_tampering_are_rejected(self):
        for changed in (self.result(roster={'1': '9999'}),
                        self.result(captured_at='2030-04-01T18:00:00+09:00'),
                        self.result(captured_at='2030-04-02T18:00:00+09:00')):
            with self.subTest(changed=changed), self.assertRaises(ValueError): self.intake([changed])

    def test_authenticated_but_rehashed_native_or_stage_forgery_fails_before_labels(self):
        mutations = (
            lambda c: c['native_inputs']['boat_full']['snapshot']['entrants'][0].update(participant_id='9999'),
            lambda c: c['native_inputs']['shared'].update(stage='P0'),
        )
        for mutate in mutations:
            payload = deepcopy(self.payload); capsule = payload['native_input_capsules'][0]
            mutate(capsule)
            capsule['native_payload_sha256'] = {g: digest(p) for g, p in capsule['native_inputs'].items()}
            input_hash = digest({capsule['race_id']: {capsule['stage']: capsule['native_inputs']}})
            capsule['dispatch_input_sha256'] = payload['dispatch_reports'][0]['input_sha256'] = input_hash
            capsule['capsule_sha256'] = digest({k: v for k, v in capsule.items() if k != 'capsule_sha256'})
            raw, metadata = self.artifact(payload)
            with patch.object(self.module(), '_results', side_effect=AssertionError('unverified native labels inspected')), \
                    self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.intake(raw=raw, metadata=metadata)

    def test_p0_stage_is_explicitly_bound_without_changing_frozen_native_payload(self):
        from tests.test_frozen_day_cycle import sample
        document, _, _ = sample(); now = datetime.fromisoformat('2030-04-01T01:44:00+00:00')
        prior = fixtures.receipt(document, artifact=99, saved='2030-04-01T01:43:00Z')
        payload = engine.forecast_saved_p0(document, prior, self.runtime(fitted=True), now=now)
        raw, metadata = self.artifact(payload, saved='2030-04-01T01:44:05Z')
        result = self.intake([self.result(payload)], raw=raw, metadata=metadata)
        self.assertGreaterEqual(len(result['records']), 2)
        for row in result['records']:
            self.assertEqual(row['stage'], 'P0')
            self.assertEqual(row['native_payload']['stage'], 'P0')
            self.assertNotIn('stage', row['frozen_native_payload'])
            self.assertNotEqual(row['input_sha256'], row['input_receipt']['frozen_native_input_sha256'])
            canonical = deepcopy(row['frozen_native_payload']); canonical['stage'] = 'P0'
            self.assertEqual(row['native_payload'], canonical)
            self.assertEqual(row['input_receipt']['stage_binding_semantics'],
                             'CANONICAL_INPUT_FROM_FROZEN_NATIVE_AND_SAVED_STAGE')
            self.assertEqual(row['as_of'], now.isoformat())
            from race_ai.all_existing_model_learning import _record
            self.assertEqual(_record(row, self.now, lambda *_: True, lambda *_: True), row)


if __name__ == '__main__':
    unittest.main()
