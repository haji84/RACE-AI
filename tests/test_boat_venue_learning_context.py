"""Synthetic encrypted candidates only; HTTP and clocks stay under test control."""
import base64
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.boat_observed_pairwise_models import MODEL_IDS, WEIGHTS
from race_ai.boat_venue_learning import fit_venue_rows, read_candidate, seal_candidate
from race_ai.github_freeze_receipt import BASE
from tests.test_boat_venue_learning import POINTER, venue_data
from tests import test_observed_weight_learning as observed_tests

NOW = observed_tests.NOW


class EncryptedLearningContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, observations = venue_data(8)
        cls.payload = fit_venue_rows(rows, observations, dataset_pointer=POINTER,
                                    now=NOW, allow_training=lambda *_: True)
        cls.key = base64.b64encode(os.urandom(32)).decode()
        with tempfile.TemporaryDirectory(prefix='venue-learning-context-test-') as tmp:
            root = Path(tmp)/'candidate'
            with patch.dict(os.environ, RACE_AI_STATE_KEY=cls.key):
                seal_candidate(cls.payload, root)
            cls.members = {name: (root/name).read_bytes()
                           for name in ('learning.enc', 'learning.json', 'summary.json')}

    def api(self):
        try:
            return importlib.import_module('race_ai.boat_venue_learning_context')
        except ModuleNotFoundError:
            self.fail('authenticated encrypted learning context adapter is missing')

    def archive(self, members=None):
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in (members or self.members).items():
                archive.writestr(name, value)
        return body.getvalue()

    def receipt(self, raw):
        return dict(id=700, name='boat-venue-learning-99-1',
                    created_at=(NOW+timedelta(seconds=2)).isoformat(),
                    updated_at=(NOW+timedelta(seconds=2)).isoformat(),
                    expires_at=(NOW+timedelta(days=7)).isoformat(),
                    expired=False, size_in_bytes=len(raw),
                    digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                    url=BASE+'/actions/artifacts/700',
                    archive_download_url=BASE+'/actions/artifacts/700/zip',
                    workflow_run=dict(id=99, repository_id=1416489937,
                                      head_repository_id=1416489937,
                                      head_branch='synthetic-only', head_sha='a'*40))

    def fetcher(self, receipt):
        def fetch(url):
            self.assertEqual(url, BASE+'/actions/artifacts/700')
            return deepcopy(receipt)
        return fetch

    def test_actual_encrypted_fit_uses_independently_fetched_receipt(self):
        api = self.api(); raw = self.archive(); receipt = self.receipt(raw)
        with patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
            context = api.context_from_encrypted_artifact(
                raw, 700, now=NOW+timedelta(minutes=1), _fetch=self.fetcher(receipt))
        self.assertEqual(context['training'], self.payload['training'])
        self.assertEqual(context['receipt'], receipt)
        self.assertEqual(context['training']['unique_races'], 8)
        self.assertEqual(context['training']['train_races'], 6)
        self.assertEqual(context['training']['validation_races'], 2)
        self.assertEqual(set(context), {'training', 'receipt'})

    def test_whole_second_artifact_clock_accepts_only_subsecond_training_precision(self):
        from race_ai.observed_weight_learning import seal
        api = self.api()
        for microseconds in (500_000, 999_999, 1_000_000, 1_000_001):
            with self.subTest(training_offset_microseconds=microseconds):
                payload = deepcopy(self.payload)
                training = payload['training']
                training['created_at'] = (NOW+timedelta(microseconds=microseconds)).isoformat()
                seal(training, 'training_sha256')
                payload['summary']['training_sha256'] = training['training_sha256']
                with tempfile.TemporaryDirectory(prefix='venue-learning-clock-test-') as tmp, \
                     patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
                    root = Path(tmp)/'candidate'; seal_candidate(payload, root)
                    raw = self.archive({name: (root/name).read_bytes() for name in self.members})
                    receipt = self.receipt(raw)
                    receipt['created_at'] = NOW.isoformat(timespec='seconds')
                    if microseconds >= 1_000_000:
                        with self.assertRaisesRegex(ValueError, 'ARTIFACT_CLOCK_INVALID'):
                            api.context_from_encrypted_artifact(raw, 700, now=NOW+timedelta(minutes=1),
                                                                _fetch=self.fetcher(receipt))
                    else:
                        try:
                            context = api.context_from_encrypted_artifact(
                                raw, 700, now=NOW+timedelta(minutes=1), _fetch=self.fetcher(receipt))
                        except ValueError as exc:
                            self.fail('whole-second receipt rejected subsecond training precision: '+str(exc))
                        self.assertEqual(context['training'], training)
                        self.assertEqual(context['receipt'], receipt)

    def test_artifact_precision_tolerance_keeps_now_and_expiry_strict(self):
        api = self.api(); raw = self.archive(); receipt = self.receipt(raw)
        receipt['created_at'] = NOW.isoformat()
        cases = [
            ('TRAINING_CLOCK_INVALID', receipt, NOW-timedelta(microseconds=1)),
            ('ARTIFACT_CLOCK_INVALID', dict(receipt, created_at=(NOW+timedelta(microseconds=1)).isoformat()), NOW),
            ('ARTIFACT_CLOCK_INVALID', dict(receipt, expires_at=NOW.isoformat()), NOW),
        ]
        with patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
            for reason, metadata, now in cases:
                with self.subTest(reason=reason, metadata=metadata, now=now), \
                     self.assertRaisesRegex(ValueError, reason):
                    api.context_from_encrypted_artifact(raw, 700, now=now, _fetch=self.fetcher(metadata))

    def test_missing_and_wrong_owner_keys_reject_before_http(self):
        api = self.api(); raw = self.archive()
        def forbidden(_):
            raise AssertionError('owner authentication must precede HTTP')
        wrong = base64.b64encode(os.urandom(32)).decode()
        for key in ('', 'not-base64', wrong):
            with self.subTest(key_kind='missing' if not key else 'invalid'), \
                 patch.dict(os.environ, RACE_AI_STATE_KEY=key), self.assertRaises(ValueError):
                api.context_from_encrypted_artifact(raw, 700, now=NOW, _fetch=forbidden)

    def test_actual_metadata_rejects_foreign_expired_future_and_changed_zip(self):
        api = self.api(); raw = self.archive(); original = self.receipt(raw)
        cases = []
        for name, value in (
            ('id', 701), ('id', True), ('expired', True), ('expired', 0),
            ('name', 'race-existing-cycle-99'), ('digest', 'sha256:'+'b'*64),
            ('size_in_bytes', len(raw)+1), ('size_in_bytes', True),
            ('created_at', (NOW+timedelta(minutes=2)).isoformat()),
            ('created_at', NOW.replace(tzinfo=None).isoformat()),
            ('created_at', (NOW-timedelta(seconds=1)).isoformat()),
            ('created_at', None), ('expires_at', NOW.isoformat())):
            receipt = deepcopy(original); receipt[name] = value
            cases.append((name, receipt))
        for name in ('repository_id', 'head_repository_id', 'id'):
            receipt = deepcopy(original); receipt['workflow_run'][name] = 77
            if name == 'id': receipt['workflow_run'][name] = False
            cases.append(('workflow_run.'+name, receipt))
        with patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
            for label, receipt in cases:
                with self.subTest(field=label), self.assertRaises(ValueError):
                    api.context_from_encrypted_artifact(raw, 700, now=NOW+timedelta(minutes=1),
                                                        _fetch=self.fetcher(receipt))
            for ident in (True, 0, -1, '700'):
                with self.subTest(artifact_id=ident), self.assertRaises(ValueError):
                    api.context_from_encrypted_artifact(raw, ident, now=NOW,
                        _fetch=lambda _: self.fail('invalid ID must not fetch'))
            with self.assertRaises(ValueError):
                api.context_from_encrypted_artifact(raw, 700, now=NOW.replace(tzinfo=None),
                    _fetch=lambda _: self.fail('naive clock must not fetch'))

    def test_malformed_metadata_fails_closed_without_receipt_context(self):
        api = self.api(); raw = self.archive(); receipt = self.receipt(raw)
        missing = deepcopy(receipt); missing.pop('created_at')
        malformed = [None, [], {}, missing, dict(receipt, workflow_run=None)]
        with patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
            for metadata in malformed:
                with self.subTest(kind=type(metadata).__name__), self.assertRaises(ValueError):
                    api.context_from_encrypted_artifact(raw, 700, now=NOW+timedelta(minutes=1),
                                                        _fetch=self.fetcher(metadata))

    def test_zip_requires_three_bounded_flat_regular_members(self):
        api = self.api()
        members = deepcopy(self.members)
        candidates = [b'not a ZIP', b'x'*(16*1024*1024+1),
                      self.archive(dict(members, extra=b'x'))]
        missing = deepcopy(members); missing.pop('summary.json')
        candidates.append(self.archive(missing))
        nested = deepcopy(members); nested['dir/summary.json'] = nested.pop('summary.json')
        candidates.append(self.archive(nested))
        huge = deepcopy(members); huge['summary.json'] = b' '*(1024*1024+1)
        candidates.append(self.archive(huge))
        huge_cipher = deepcopy(members); huge_cipher['learning.enc'] = b'x'*(12*1024*1024+1)
        candidates.append(self.archive(huge_cipher))
        duplicate = io.BytesIO()
        with zipfile.ZipFile(duplicate, 'w') as archive:
            for name, value in members.items(): archive.writestr(name, value)
            with self.assertWarns(UserWarning): archive.writestr('learning.json', members['learning.json'])
        candidates.append(duplicate.getvalue())
        symlink = io.BytesIO()
        with zipfile.ZipFile(symlink, 'w') as archive:
            for name, value in members.items():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (0o120777 if name == 'learning.enc' else 0o100600) << 16
                archive.writestr(info, value)
        candidates.append(symlink.getvalue())
        with patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
            for index, raw in enumerate(candidates):
                with self.subTest(case=index), self.assertRaises(ValueError):
                    api.context_from_encrypted_artifact(raw, 700, now=NOW,
                        _fetch=lambda _: self.fail('invalid ZIP must not fetch'))

    def test_cipher_manifest_and_count_only_summary_tampering_rejects(self):
        api = self.api()
        candidates = []
        for name in ('learning.enc', 'learning.json'):
            members = deepcopy(self.members); members[name] += b'bad'
            candidates.append(self.archive(members))
        members = deepcopy(self.members)
        summary = json.loads(members['summary.json']); summary['fitted_model_count'] = 999
        members['summary.json'] = json.dumps(summary).encode(); candidates.append(self.archive(members))
        with patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
            for raw in candidates:
                with self.subTest(case=hashlib.sha256(raw).hexdigest()[:8]), self.assertRaises(ValueError):
                    api.context_from_encrypted_artifact(raw, 700, now=NOW,
                        _fetch=lambda _: self.fail('unauthenticated data must not fetch'))

    def test_authenticated_training_must_be_fitted_and_available_before_receipt(self):
        from race_ai.observed_weight_learning import seal
        api = self.api()
        for case in ('not-fitted', 'created-after-receipt', 'data-after-creation'):
            payload = deepcopy(self.payload); training = payload['training']
            if case == 'not-fitted': training.update(state='INSUFFICIENT_VERIFIED_RACES', models={})
            elif case == 'created-after-receipt': training['created_at'] = (NOW+timedelta(seconds=3)).isoformat()
            else: training['data_available_until'] = (NOW+timedelta(seconds=1)).isoformat()
            seal(training, 'training_sha256')
            payload['summary'].update(state=training['state'], training_sha256=training['training_sha256'])
            with tempfile.TemporaryDirectory(prefix='venue-learning-context-test-') as tmp, \
                 patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
                root = Path(tmp)/'candidate'; seal_candidate(payload, root)
                members = {name: (root/name).read_bytes() for name in self.members}
                raw = self.archive(members)
                with self.subTest(case=case), self.assertRaises(ValueError):
                    api.context_from_encrypted_artifact(raw, 700, now=NOW+timedelta(minutes=1),
                                                        _fetch=self.fetcher(self.receipt(raw)))

    def test_private_future_shadows_roundtrip_without_mutating_baseline(self):
        api = self.api(); helper = observed_tests.LearningTests()
        snapshot, suite = helper.future(); raw = self.archive()
        before = deepcopy((snapshot, suite, WEIGHTS))
        with tempfile.TemporaryDirectory(prefix='venue-learning-shadows-test-') as tmp, \
             patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
            context = api.context_from_encrypted_artifact(raw, 700, now=NOW+timedelta(minutes=1),
                                                        _fetch=self.fetcher(self.receipt(raw)))
            root = Path(tmp)/'shadows'
            status = api.make_encrypted_shadows(snapshot, suite, context, root,
                                                now=NOW+timedelta(minutes=11))
            restored = read_candidate(root)
            self.assertEqual(status['learned_shadow_count'], 2)
            self.assertEqual(len(restored['shadows']), 2)
            self.assertEqual({s['model_id'] for s in restored['shadows']}, set(MODEL_IDS))
            self.assertTrue(all(len(s['ordered_top8']) == 8 for s in restored['shadows']))
            self.assertTrue(all(len(s['candidates']) == 120 for s in restored['shadows']))
            self.assertFalse(status['independent_pre_cutoff_receipt_verified'])
            self.assertFalse(status['production_promoted'])
            self.assertFalse(status['provider_rights_confirmed'])
            self.assertFalse(status['plaintext_published'])
            self.assertTrue(status['encrypted_readback_verified'])
            self.assertNotIn(b'weights', (root/'summary.json').read_bytes())
            self.assertNotIn(b'ordered_top8', (root/'summary.json').read_bytes())
            self.assertNotIn(b'LEARNED_SHADOW', (root/'learning.enc').read_bytes())
            self.assertEqual(set(p.name for p in root.iterdir()), set(self.members))
        self.assertEqual((snapshot, suite, WEIGHTS), before)

    def test_shadow_sealing_that_crosses_cutoff_never_claims_external_preproof(self):
        api = self.api(); snapshot, suite = observed_tests.LearningTests().future()
        context = dict(training=deepcopy(self.payload['training']), receipt=self.receipt(self.archive()))
        with tempfile.TemporaryDirectory(prefix='venue-learning-shadows-test-') as tmp, \
             patch.dict(os.environ, RACE_AI_STATE_KEY=self.key):
            root = Path(tmp)/'late'
            with patch.object(api.time, 'monotonic', side_effect=[100., 102.]), self.assertRaises(ValueError):
                api.make_encrypted_shadows(snapshot, suite, context, root,
                    now=NOW+timedelta(minutes=30)-timedelta(seconds=1))
            self.assertFalse(read_candidate(root)['summary']['independent_pre_cutoff_receipt_verified'])
            root = Path(tmp)/'already-late'
            with self.assertRaises(ValueError):
                api.make_encrypted_shadows(snapshot, suite, context, root,
                    now=NOW+timedelta(minutes=30))
            self.assertFalse(root.exists())


if __name__ == '__main__':
    unittest.main()
