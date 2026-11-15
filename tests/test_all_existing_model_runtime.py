"""Fictional current inputs, real native fits/grid/AES, and no provider I/O."""
import base64
from copy import deepcopy
from datetime import timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai.all_existing_model_inputs import build_current_requests, write_private_pending_requests
from race_ai.all_existing_model_learning import fit, records_from_observed
from race_ai.all_existing_model_pairs import verify_private_pair
from race_ai.boat_observed_pairwise_models import MODEL_IDS, WEIGHTS, predict_pair
from race_ai.boat_venue_learning import read_candidate, seal_candidate
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
from race_ai.observed_p1_connection import build_bundle
from race_ai.observed_weight_learning import seal
from tests.test_boat_venue_research import NOW, personal_data, refs
from tests import test_boat_venue_feature_adapter as grid_tests
from tests.test_observed_p1_connection import inputs

CURRENT = NOW+timedelta(minutes=11)
FICTION_ONLY_KEY = base64.b64encode(bytes(range(32))).decode()


class CurrentAllModelRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grid_fixture = grid_tests.VenueFeatureTests(); cls.grid_fixture.setUp()
        cls.addClassCleanup(cls.grid_fixture.doCleanups)
        environment = patch.dict(os.environ, RACE_AI_STATE_KEY=FICTION_ONLY_KEY)
        environment.start(); cls.addClassCleanup(environment.stop)
        cls.grid, cls.pointer, _ = cls.grid_fixture.dataset(partial=True)
        rows, observations = personal_data(8)
        sid = 'official-venue-grid-'+cls.pointer['dataset_sha256'][:16]
        url = 'https://raw.githubusercontent.com/haji84/RACE-AI/'+cls.pointer['source_commit']+'/'+cls.pointer['dataset_path']
        for row in rows:
            snapshot = row['learning_snapshot']
            for source in snapshot['sources']:
                if source['source_id'].startswith('official-venue-grid-'):
                    source.update(source_id=sid, source_url=url, source_sha256=cls.pointer['dataset_sha256'])
            for participant in snapshot['participants']:
                for name in ('course_mean_finish', 'course_mean_st'):
                    if name in participant['features']:
                        participant['features'][name]['source_id'] = sid
            admitted = {(s['source_url'], s['source_rights_ref']) for s in snapshot['sources']}
            suite = predict_pair(snapshot, allow_source=lambda u,r,p:(u,r) in admitted and p == 'analysis')
            model = suite['models'][row['model_id']]
            row.update(learning_snapshot_sha256=digest(snapshot), model_sha256=model['prediction_sha256'],
                original_json_sha256=digest(suite), top8=model['ordered_top8'],
                ranked=[r['combination'] for r in model['candidates']])
        admitted = set(refs(rows, observations))
        cls.training = fit(records_from_observed(rows, observations), now=NOW,
            allow_source=lambda u,r,p:(u,r) in admitted and p == 'analysis',
            allow_training=lambda u,r,p:(u,r) in admitted and p == 'model_training')
        cls.training['venue_dataset_sha256'] = cls.pointer['dataset_sha256']; seal(cls.training, 'training_sha256')
        candidate = cls.grid_fixture.root/'runtime-candidate'
        seal_candidate(dict(training=cls.training, excluded=[], summary=dict(state='FITTED_SHADOW_ONLY',
            fitted_model_count=2, plaintext_published=False)), candidate)
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w') as archive:
            for name in ('learning.enc', 'learning.json', 'summary.json'):
                archive.writestr(name, (candidate/name).read_bytes())
        raw = body.getvalue()
        receipt = dict(id=700, name='all-existing-model-learning-99-1', expired=False,
            digest='sha256:'+hashlib.sha256(raw).hexdigest(), size_in_bytes=len(raw),
            created_at=(NOW+timedelta(seconds=2)).isoformat(), expires_at=(NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=99, repository_id=1416489937, head_repository_id=1416489937, head_sha='a'*40))
        cls.context = context_from_encrypted_artifact(raw, 700, now=CURRENT,
                                                     _fetch=lambda _: deepcopy(receipt))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fictional-native-runtime-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        environment = patch.dict(os.environ, RACE_AI_STATE_KEY=FICTION_ONLY_KEY)
        environment.start(); self.addCleanup(environment.stop)
        self.pending = self.root/'pending'; self.output = self.root/'pairs'
        base, extra, proof = inputs()
        base.update(race_id='20300401-17-01', captured_at=(NOW+timedelta(minutes=9)).isoformat(),
            cutoff_at=(NOW+timedelta(minutes=30)).astimezone(timezone(timedelta(hours=9))).isoformat())
        extra.update(race_id=base['race_id'], observed_at=base['captured_at'])
        proof.update(program_captured_at=(NOW+timedelta(minutes=8)).isoformat(),
                     preview_captured_at=base['captured_at'])
        for name in ('program_url', 'preview_url'):
            proof[name] = proof[name].replace('jcd=01', 'jcd=17')
        observed = build_bundle(base, extra, (NOW+timedelta(minutes=10)).isoformat(),
                                **proof, owner_reviewed=True)
        self.requests = build_current_requests(base, extra, observed, **proof)
        write_private_pending_requests(self.requests, self.pending)
        self.original_pending = (self.pending/'pending.json').read_bytes()
        self.runtime = dict(context=deepcopy(self.context), dataset_folder=self.grid,
            dataset_pointer=deepcopy(self.pointer), dataset_verified_at=(NOW+timedelta(minutes=5)).isoformat())

    def generate(self, **changes):
        from race_ai.all_existing_model_runtime import generate_current_pairs
        values = dict(now=CURRENT); values.update(changes)
        return generate_current_pairs(self.runtime, self.pending, self.output, **values)

    def assert_pending(self):
        self.assertEqual((self.pending/'pending.json').read_bytes(), self.original_pending)

    def test_full_grid_enrichment_native_pair_ciphertext_readback_precedes_raw_removal(self):
        before = deepcopy((self.requests, self.runtime, WEIGHTS))
        summary = self.generate()
        self.assertTrue(summary['pending_removed'])
        self.assertEqual(list(self.pending.iterdir()), [])
        self.assertEqual(self.pending.stat().st_mode & 0o777, 0o700)
        self.assertEqual((summary['partition_count'], summary['captured_native_input_count']), (2, 5))
        self.assertEqual(summary['captured_unfitted_native_input_count'], 3)
        self.assertEqual((self.requests, self.runtime, WEIGHTS), before)
        self.assertFalse(summary['independent_pre_cutoff_receipt_verified'])
        folders = [path for path in self.output.iterdir() if path.is_dir()]
        self.assertEqual(len(folders), 2)
        captured = []
        for folder in folders:
            self.assertIsNotNone(re.fullmatch('[a-f0-9]{64}', folder.name))
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            for path in folder.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            payload = read_candidate(folder); self.assertTrue(verify_private_pair(payload))
            native = payload['native_payload']; original = next(r['native_payload'] for r in self.requests
                if r['cell_key'] == payload['cell_key'])
            self.assertEqual(native['original_native_payload'], original)
            self.assertEqual(native['original_input_sha256'], digest(original))
            self.assertEqual(native['snapshot']['as_of'], CURRENT.isoformat())
            self.assertTrue(all('course_mean_st' in p['features'] for p in native['snapshot']['participants']))
            self.assertEqual(payload['pair']['input_sha256'], digest(native))
            captured.extend(payload.get('captured_native_inputs', []))
        self.assertEqual(len(captured), 5)
        for capsule in captured:
            if capsule['cell_key'] not in {'boat/'+mid for mid in MODEL_IDS}:
                original = next(r['native_payload'] for r in self.requests if r['cell_key'] == capsule['cell_key'])
                self.assertEqual(capsule['native_payload'], original)
        public = json.dumps(summary).encode()+(self.output/'summary.json').read_bytes()
        for key in (b'"weights"', b'"parameters"', b'"native_payload"', b'"source_url"',
                    b'"participants"', b'"ordered_top8"', FICTION_ONLY_KEY.encode()):
            self.assertNotIn(key, public)

    def test_key_is_required_before_context_paths_or_pending_are_read(self):
        from race_ai.all_existing_model_runtime import generate_current_pairs
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''):
            with self.assertRaisesRegex(ValueError, 'OWNER_STATE_KEY_REQUIRED'):
                generate_current_pairs(None, '/nonexistent/pending', '/nonexistent/output', now=None)
        self.assert_pending(); self.assertFalse(self.output.exists())

    def test_tampered_pending_and_existing_output_are_never_reset(self):
        record = json.loads(self.original_pending); record['requests_sha256'] = 'f'*64
        changed = json.dumps(record).encode(); (self.pending/'pending.json').write_bytes(changed)
        with self.assertRaisesRegex(ValueError, 'HASH'):
            self.generate()
        self.assertEqual((self.pending/'pending.json').read_bytes(), changed)
        self.assertFalse(self.output.exists())
        (self.pending/'pending.json').write_bytes(self.original_pending)
        self.output.mkdir(mode=0o700); (self.output/'preserve').write_bytes(b'original')
        with self.assertRaisesRegex(ValueError, 'DO_NOT_RESET'):
            self.generate()
        self.assertEqual((self.output/'preserve').read_bytes(), b'original'); self.assert_pending()

    def test_no_fitted_context_preserves_pending_without_creating_output(self):
        self.runtime['context']['training'] = fit([], now=NOW)
        summary = self.generate()
        self.assertEqual(summary['state'], 'HOLD_PRIVATE_NATIVE_INPUTS')
        self.assertFalse(summary['pending_removed']); self.assert_pending()
        self.assertFalse(self.output.exists())

    def test_unfitted_current_inputs_are_frozen_without_invented_observed_predictions(self):
        from race_ai.all_existing_model_pairs import INPUTS_SCHEMA, verify_private_record
        self.pending = self.root/'unfitted-pending'
        requests = [row for row in self.requests if row['cell_key'] not in {'boat/'+mid for mid in MODEL_IDS}]
        self.assertEqual(len(requests), 3)
        write_private_pending_requests(requests, self.pending)
        self.original_pending = (self.pending/'pending.json').read_bytes()
        summary = self.generate()
        self.assertEqual(summary['state'], 'ENCRYPTED_FROZEN_NATIVE_INPUTS_LOCAL_ONLY')
        self.assertEqual(summary['partition_count'], 1)
        self.assertEqual(summary['forecast_partition_count'], 0)
        self.assertEqual(summary['frozen_input_only_partition_count'], 1)
        self.assertEqual(summary['captured_native_input_count'], 3)
        self.assertEqual((summary['baseline_forecast_count'], summary['learned_forecast_count']), (0, 0))
        self.assertTrue(summary['pending_removed']); self.assertEqual(list(self.pending.iterdir()), [])
        folder = next(path for path in self.output.iterdir() if path.is_dir())
        payload = read_candidate(folder)
        self.assertEqual(payload['schema'], INPUTS_SCHEMA); self.assertTrue(verify_private_record(payload))
        self.assertNotIn('pair', payload); self.assertNotIn('cell_key', payload)
        self.assertEqual({(row['cell_key'], row['input_sha256']) for row in payload['captured_native_inputs']},
                         {(row['cell_key'], digest(row['native_payload'])) for row in requests})

    def test_pair_failure_incomplete_capture_and_quarantine_preserve_pending(self):
        from race_ai import all_existing_model_runtime as runtime
        with patch.object(runtime, 'make_private_pairs', side_effect=ValueError('PRIVATE_SEAL_FAILED')):
            with self.assertRaisesRegex(ValueError, 'PRIVATE_SEAL_FAILED'):
                self.generate()
        self.assert_pending(); self.assertFalse(self.output.exists())
        real = runtime.make_private_pairs
        def incomplete(*args, **kwargs):
            result = real(*args, **kwargs); result['captured_native_input_count'] -= 1
            return result
        with patch.object(runtime, 'make_private_pairs', side_effect=incomplete):
            summary = self.generate()
        self.assertEqual(summary['state'], 'HOLD_PRIVATE_NATIVE_INPUTS'); self.assert_pending()
        quarantine = dict(state='QUARANTINED_CUTOFF_ELAPSED_DURING_SEAL', partition_count=0)
        other = self.root/'quarantined'
        with patch.object(runtime, 'make_private_pairs', return_value=quarantine):
            held = runtime.generate_current_pairs(self.runtime, self.pending, other, now=CURRENT)
        self.assertEqual(held['state'], 'HOLD_PRIVATE_NATIVE_INPUTS'); self.assert_pending()
        with patch.object(runtime, 'make_private_pairs', side_effect=ValueError(
                'ALL_MODEL_PRIVATE_PAIRS_CUTOFF_ELAPSED_DURING_SEAL')):
            held = runtime.generate_current_pairs(self.runtime, self.pending, other, now=CURRENT)
        self.assertEqual(held['reason'], 'QUARANTINED_CUTOFF_ELAPSED_DURING_SEAL'); self.assert_pending()

    def test_independent_readback_rejects_corrupt_cipher_public_summary_and_permissions(self):
        from race_ai import all_existing_model_runtime as runtime
        real = runtime.make_private_pairs
        for kind in ('cipher', 'summary', 'permissions', 'training-summary', 'training-record', 'unfitted-count'):
            self.output = self.root/('readback-'+kind)
            def corrupted(*args, **kwargs):
                arguments = list(args)
                if kind == 'training-record':
                    alternative = deepcopy(arguments[0])
                    alternative['training']['created_at'] = (NOW+timedelta(microseconds=1)).isoformat()
                    seal(alternative['training'], 'training_sha256'); arguments[0] = alternative
                summary = real(*arguments, **kwargs)
                folder = next(path for path in self.output.iterdir() if path.is_dir())
                if kind == 'cipher':
                    path = folder/'learning.enc'; raw = path.read_bytes()
                    path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
                elif kind == 'summary':
                    path = folder/'summary.json'; document = json.loads(path.read_bytes())
                    document['captured_native_input_count'] = 999
                    path.write_text(json.dumps(document), encoding='utf-8')
                elif kind == 'permissions':
                    (folder/'learning.enc').chmod(0o644)
                else:
                    if kind == 'training-summary':
                        summary['training_sha256'] = 'f'*64
                    elif kind == 'training-record':
                        summary['training_sha256'] = self.runtime['context']['training']['training_sha256']
                    else:
                        summary['captured_unfitted_native_input_count'] += 1
                    (self.output/'summary.json').write_text(json.dumps(summary), encoding='utf-8')
                return summary
            with self.subTest(kind=kind), patch.object(runtime, 'make_private_pairs', side_effect=corrupted):
                with self.assertRaises(ValueError):
                    self.generate()
            self.assert_pending()

    def test_changed_pending_batch_after_sealing_is_not_removed_as_old_cleanup(self):
        from race_ai import all_existing_model_runtime as runtime
        real = runtime.make_private_pairs
        def pending_changed(*args, **kwargs):
            summary = real(*args, **kwargs)
            (self.pending/'pending.json').write_bytes(b'changed private batch')
            return summary
        with patch.object(runtime, 'make_private_pairs', side_effect=pending_changed):
            with self.assertRaises(ValueError):
                self.generate()
        self.assertEqual((self.pending/'pending.json').read_bytes(), b'changed private batch')
        self.assertTrue(self.output.exists())

    def test_directory_replacement_at_final_readback_preserves_both_pending_batches(self):
        from race_ai import all_existing_model_runtime as runtime
        from race_ai.all_existing_model_inputs import read_private_pending_requests
        old = self.root/'old-pending'; seen = 0
        previous = sys.getprofile()
        def replace_after_read(frame, event, value):
            nonlocal seen
            if event == 'return' and frame.f_code is read_private_pending_requests.__code__:
                seen += 1
                if seen == 2:
                    self.pending.rename(old)
                    write_private_pending_requests(self.requests[:3], self.pending)
        sys.setprofile(replace_after_read)
        try:
            with self.assertRaisesRegex(ValueError, 'PENDING_DIRECTORY_CHANGED'):
                self.generate()
        finally:
            sys.setprofile(previous)
        self.assertEqual((old/'pending.json').read_bytes(), self.original_pending)
        self.assertEqual(read_private_pending_requests(self.pending), self.requests[:3])
        self.assertTrue(self.output.exists())

    def test_late_input_and_public_paths_fail_without_removing_originals(self):
        with self.assertRaises(ValueError):
            self.generate(now=NOW+timedelta(minutes=31))
        self.assert_pending(); self.assertFalse(self.output.exists())
        self.pending.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'PERMISSIONS'):
            self.generate()
        self.pending.chmod(0o700); self.assert_pending()
        self.runtime['dataset_folder'] = self.root
        self.root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'PERMISSIONS'):
            self.generate()
        self.root.chmod(0o700); self.assert_pending()


if __name__ == '__main__':
    unittest.main()
