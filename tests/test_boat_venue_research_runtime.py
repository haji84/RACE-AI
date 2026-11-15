"""Private research preloading with invented pointers and stubbed I/O only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.github_freeze_receipt import BASE


NOW = datetime(2030, 4, 1, 8, tzinfo=timezone.utc)
CONFIG = dict(schema='RACE_AI_BOAT_VENUE_LEARNING_CONTEXT_INPUT_V1',
              repository_id='1416489937', artifact_id=700,
              training_sha256='c'*64, head_sha='a'*40, run_id=99)
POINTER = dict(schema='RACE_AI_BOAT_VENUE_DATASET_INPUT_V1', status='READY',
               repository_id='1416489937', source_commit='b'*40,
               dataset_sha256='d'*64,
               dataset_path='state/boat-venue-history/v1/datasets/'+'d'*64+'/dataset.json')


class VenueResearchRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='venue-runtime-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config_path = self.root/'context.json'
        self.dataset_path = self.root/'dataset-input.json'
        self.config_path.write_text(json.dumps(CONFIG))
        self.dataset_path.write_text(json.dumps(POINTER))
        self.runtime = self.root/'private-runtime'
        self.training = dict(training_sha256=CONFIG['training_sha256'],
                             venue_dataset_sha256=POINTER['dataset_sha256'])
        self.receipt = dict(id=700, expired=False,
                            expires_at=(NOW+timedelta(days=1)).isoformat(),
                            workflow_run=dict(id=99, head_sha='a'*40))
        self.events = []

    def api(self):
        try:
            return importlib.import_module('race_ai.boat_venue_research_runtime')
        except ModuleNotFoundError:
            self.fail('private venue learning runtime preloader is missing')

    def gh(self, path):
        self.events.append(path)
        if path == 'actions/artifacts/700/zip':
            return b'invented encrypted archive'
        if path == 'actions/artifacts/700':
            return json.dumps(self.receipt).encode()
        self.fail('unexpected GitHub request: '+path)

    def authenticate(self, raw, artifact_id, *, now, _fetch):
        self.assertEqual((raw, artifact_id, now), (b'invented encrypted archive', 700, NOW))
        return dict(training=deepcopy(self.training),
                    receipt=_fetch(BASE+'/actions/artifacts/700'))

    def restore(self, pointer, output, repo):
        self.events.append('restore')
        self.assertEqual(pointer, POINTER)
        self.assertEqual(Path(repo), self.root)
        Path(output).mkdir(mode=0o700)
        return dict(status='ENCRYPTED_ALL_VENUE_GRID_READBACK_VERIFIED',
                    plaintext_published=False)

    def preload(self, api, *, gh=None, clock=None, authenticate=None, restore=None):
        def key(mode):
            self.events.append('key')
            self.assertEqual(mode, 'production')
        with patch.object(api, 'state_key', side_effect=key), \
             patch.object(api, 'context_from_encrypted_artifact', side_effect=authenticate or self.authenticate), \
             patch.object(api, 'readback_dataset', side_effect=restore or self.restore):
            return api.preload_venue_research(
                self.config_path, self.dataset_path, self.runtime, self.root,
                gh=gh or self.gh, clock=clock or iter((NOW, NOW+timedelta(seconds=3))).__next__)

    def test_preloads_only_pinned_candidate_and_records_clock_after_dataset_restore(self):
        api = self.api()
        def clock():
            self.events.append('clock')
            return NOW if self.events.count('clock') == 1 else NOW+timedelta(seconds=3)
        result = self.preload(api, clock=clock)
        self.assertEqual(set(result), {'context', 'dataset_folder', 'dataset_pointer', 'dataset_verified_at'})
        self.assertEqual(result['context'], dict(training=self.training, receipt=self.receipt))
        self.assertEqual(result['dataset_pointer'], POINTER)
        self.assertEqual(result['dataset_folder'], self.runtime/'dataset')
        self.assertEqual(result['dataset_verified_at'], '2030-04-01T08:00:03+00:00')
        self.assertEqual(self.events, ['key', 'clock', 'actions/artifacts/700/zip',
                                       'actions/artifacts/700', 'restore', 'clock'])
        self.assertEqual(self.runtime.stat().st_mode & 0o077, 0)

    def test_missing_owner_key_fails_before_any_config_or_external_io(self):
        api = self.api()
        self.config_path.unlink()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''), \
             patch.object(api, 'context_from_encrypted_artifact', side_effect=AssertionError('no artifact I/O')), \
             patch.object(api, 'readback_dataset', side_effect=AssertionError('no dataset I/O')):
            with self.assertRaisesRegex(ValueError, 'OWNER_STATE_KEY_REQUIRED'):
                api.preload_venue_research(self.config_path, self.dataset_path, self.runtime,
                                          self.root, gh=lambda _: self.fail('no GitHub without owner key'))
        self.assertFalse(self.runtime.exists())

    def test_invalid_config_never_falls_back_or_contacts_github(self):
        api = self.api()
        cases = [dict(CONFIG, schema='FOREIGN'), dict(CONFIG, repository_id='1'),
                 dict(CONFIG, repository_id=1416489937), dict(CONFIG, extra=True),
                 dict(CONFIG, artifact_id=True), dict(CONFIG, artifact_id=0),
                 dict(CONFIG, artifact_id='700'), dict(CONFIG, run_id=True),
                 dict(CONFIG, run_id=-1), dict(CONFIG, run_id='99'),
                 dict(CONFIG, training_sha256='C'*64), dict(CONFIG, training_sha256='c'*63),
                 dict(CONFIG, head_sha='main'), dict(CONFIG, head_sha='a'*39)]
        missing = dict(CONFIG); missing.pop('head_sha'); cases.extend((missing, [], None))
        for config in cases:
            with self.subTest(config=config):
                self.config_path.write_text(json.dumps(config))
                with self.assertRaisesRegex(ValueError, 'CONTEXT_INPUT_INVALID'):
                    self.preload(api, gh=lambda _: self.fail('invalid config must not request GitHub'))
        self.assertFalse(self.runtime.exists())

    def test_missing_malformed_and_duplicate_config_are_learning_errors(self):
        api = self.api()
        self.config_path.unlink()
        with self.assertRaisesRegex(ValueError, 'CONTEXT_INPUT_INVALID'):
            self.preload(api, gh=lambda _: self.fail('missing config must not fetch'))
        for raw in (b'{bad', b'{"schema": 1, "schema": 2}', b'x'*8193):
            with self.subTest(raw_length=len(raw)):
                self.config_path.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, 'CONTEXT_INPUT_INVALID'):
                    self.preload(api, gh=lambda _: self.fail('malformed config must not fetch'))

    def test_invalid_dataset_pointer_is_rejected_before_github(self):
        api = self.api()
        for change in (dict(repository_id='foreign'), dict(status='WAITING_ENCRYPTED_INPUT'),
                       dict(source_commit='main'), dict(dataset_path='../dataset.json'),
                       dict(dataset_sha256='D'*64), dict(extra=True)):
            with self.subTest(change=change):
                self.dataset_path.write_text(json.dumps(dict(POINTER, **change)))
                with self.assertRaisesRegex(ValueError, 'DATASET_INPUT_INVALID'):
                    self.preload(api, gh=lambda _: self.fail('invalid dataset must not request GitHub'))

    def test_training_and_dataset_hash_mismatches_fail_before_restoring_grid(self):
        api = self.api()
        for field, reason in (('training_sha256', 'TRAINING_PIN_MISMATCH'),
                              ('venue_dataset_sha256', 'DATASET_PIN_MISMATCH')):
            with self.subTest(field=field):
                self.training[field] = 'e'*64
                with self.assertRaisesRegex(ValueError, reason):
                    self.preload(api, restore=lambda *a: self.fail('mismatched corpus must not restore'))
                self.training = dict(training_sha256=CONFIG['training_sha256'],
                                     venue_dataset_sha256=POINTER['dataset_sha256'])

    def test_actual_metadata_must_match_configured_run_and_head(self):
        api = self.api()
        for change in (dict(id=100), dict(head_sha='f'*40)):
            with self.subTest(change=change):
                self.receipt['workflow_run'] = dict(id=99, head_sha='a'*40)
                self.receipt['workflow_run'].update(change)
                with self.assertRaisesRegex(ValueError, 'RUN_PIN_MISMATCH'):
                    self.preload(api, restore=lambda *a: self.fail('wrong actual metadata must not restore'))

    def test_missing_or_expired_candidate_never_restores_dataset(self):
        api = self.api()
        with self.assertRaisesRegex(ValueError, 'ARTIFACT_UNAVAILABLE'):
            self.preload(api, gh=lambda _: (_ for _ in ()).throw(ValueError('artifact missing')),
                         restore=lambda *a: self.fail('missing candidate must not restore'))
        with self.assertRaisesRegex(ValueError, 'ARTIFACT_CLOCK_INVALID'):
            self.preload(api, authenticate=lambda *a, **k: (_ for _ in ()).throw(
                ValueError('VENUE_LEARNING_CONTEXT_ARTIFACT_CLOCK_INVALID')),
                restore=lambda *a: self.fail('expired candidate must not restore'))

    def test_external_failures_are_sanitized_learning_errors(self):
        api = self.api()
        for failed_path in ('actions/artifacts/700/zip', 'actions/artifacts/700'):
            with self.subTest(failed_path=failed_path):
                def unavailable(path):
                    if path == failed_path:
                        raise RuntimeError('private transport detail')
                    return self.gh(path)
                with self.assertRaises(Exception) as rejected:
                    self.preload(api, gh=unavailable,
                                 restore=lambda *a: self.fail('missing artifact must not restore'))
                self.assertIsInstance(rejected.exception, ValueError)
                self.assertRegex(str(rejected.exception), 'ARTIFACT_UNAVAILABLE')
                self.assertNotIn('private transport detail', str(rejected.exception))
        with self.assertRaises(Exception) as rejected:
            self.preload(api, restore=lambda *a: (_ for _ in ()).throw(RuntimeError('private grid detail')))
        self.assertIsInstance(rejected.exception, ValueError)
        self.assertRegex(str(rejected.exception), 'DATASET_READBACK_REJECTED')
        self.assertNotIn('private grid detail', str(rejected.exception))

    def test_private_runtime_never_resets_existing_files_or_accepts_git_storage(self):
        api = self.api()
        self.runtime.mkdir(mode=0o700)
        marker = self.runtime/'keep'; marker.write_text('original')
        with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS_DO_NOT_RESET'):
            self.preload(api, gh=lambda _: self.fail('occupied runtime must not fetch'))
        self.assertEqual(marker.read_text(), 'original')
        marker.unlink(); self.runtime.rmdir()
        (self.root/'.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_GIT_REQUIRED'):
            self.preload(api, gh=lambda _: self.fail('runtime inside Git must not fetch'))

    def test_failed_restore_and_untrusted_clocks_never_return_private_runtime(self):
        api = self.api()
        with self.assertRaisesRegex(ValueError, 'DATASET_READBACK_REQUIRED'):
            self.preload(api, restore=lambda *a: dict(status='HOLD_OWNER_STATE_KEY_MISSING'))
        self.runtime.rmdir()
        for end, reason in ((NOW-timedelta(microseconds=1), 'CLOCK_REGRESSED'),
                            (NOW.replace(tzinfo=None), 'AWARE_CLOCK_REQUIRED'),
                            (NOW+timedelta(days=1), 'ARTIFACT_EXPIRED_DURING_RESTORE')):
            with self.subTest(end=end):
                with self.assertRaisesRegex(ValueError, reason):
                    self.preload(api, clock=iter((NOW, end)).__next__)
                (self.runtime/'dataset').rmdir(); self.runtime.rmdir()
        with self.assertRaisesRegex(ValueError, 'AWARE_CLOCK_REQUIRED'):
            self.preload(api, clock=lambda: NOW.replace(tzinfo=None),
                         gh=lambda _: self.fail('invalid initial clock must not request GitHub'))


if __name__ == '__main__':
    unittest.main()
