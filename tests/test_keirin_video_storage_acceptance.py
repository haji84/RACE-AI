"""Offline regression for the production storage acceptance boundary.

No account, footage, credentials or provider access is used in these tests.
"""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts' / 'keirin_video_storage_acceptance.py'
RUN = 42678096029
SHA = 'd8730e8e91f15ce11965e1d094567cf61e379994'


def event():
    return {'workflow_run': {
        'id': RUN, 'head_sha': SHA, 'head_branch': 'main',
        'event': 'schedule', 'conclusion': 'success',
        'path': '.github/workflows/keirin-github-autonomous.yml',
        'repository': {'id': 1416489937},
        'head_repository': {'id': 1416489937},
    }}


def log(data=b'encrypted-fixture-only'):
    return '2026-11-09T19:00:00.000Z ' + json.dumps({
        'status': 'DURABLE_CIPHERTEXT_READBACK_VERIFIED',
        'day_jst': '2026-11-09', 'github_run_id': str(RUN),
        'cipher_objects': 2, 'sha256': sha256(data).hexdigest()})


class StorageAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(HELPER.is_file(), 'INDEPENDENT_STORAGE_ACCEPTANCE_NOT_IMPLEMENTED')
        spec = importlib.util.spec_from_file_location('acceptance', HELPER)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_missing_configuration_is_explicit_and_never_exposes_values(self):
        result = self.module.configuration_status({})
        self.assertFalse(result['configured'])
        self.assertEqual(set(result['missing']), {
            'RACE_AI_KEIRIN_S3_BUCKET', 'RACE_AI_KEIRIN_S3_ACCESS_KEY_ID',
            'RACE_AI_KEIRIN_S3_SECRET_ACCESS_KEY'})
        env = {'ARCHIVE_BUCKET': 'owner-private-example',
               'AWS_ACCESS_KEY_ID': 'DO_NOT_LOG_ID',
               'AWS_SECRET_ACCESS_KEY': 'DO_NOT_LOG_SECRET'}
        result = self.module.configuration_status(env)
        self.assertTrue(result['configured'])
        text = json.dumps(result)
        for value in env.values():
            self.assertNotIn(value, text)

    def test_only_expected_main_producers_are_accepted(self):
        source = self.module.validate_producer(event())
        self.assertEqual(source['id'], RUN)
        for field, value in [('head_branch', 'untrusted-pr'), ('event', 'pull_request'),
                             ('path', '.github/workflows/unrelated.yml')]:
            changed = event()
            changed['workflow_run'][field] = value
            with self.assertRaises(ValueError):
                self.module.validate_producer(changed)
        changed = event()
        changed['workflow_run']['head_repository']['id'] = 1
        with self.assertRaises(ValueError):
            self.module.validate_producer(changed)

    def test_missing_or_multiple_upload_attestations_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'UPLOAD_ATTESTATION'):
            self.module.parse_attestation('No encrypted archive uploaded', RUN)
        with self.assertRaisesRegex(ValueError, 'UPLOAD_ATTESTATION'):
            self.module.parse_attestation(log() + '\n' + log(), RUN)

    def test_attestation_is_bound_to_source_run_and_calendar_day(self):
        record = self.module.parse_attestation(log(), RUN)
        self.assertEqual(record['github_run_id'], str(RUN))
        with self.assertRaises(ValueError):
            self.module.parse_attestation(log(), RUN + 1)
        with self.assertRaises(ValueError):
            self.module.parse_attestation(log().replace('2026-11-09', '2026-02-30'), RUN)
        with self.assertRaises(ValueError):
            self.module.parse_attestation(log().replace('2026-11-09', '../private'), RUN)

    def test_downloaded_bytes_must_match_not_just_head_metadata(self):
        record = self.module.parse_attestation(log(), RUN)
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / 'archive.zip'
            p.write_bytes(b'encrypted-fixture-only')
            self.assertEqual(self.module.verify_bytes(p, record), record['sha256'])
            p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'INDEPENDENT_READBACK_SHA_MISMATCH'):
                self.module.verify_bytes(p, record)

    def test_object_path_cannot_be_selected_by_untrusted_log_text(self):
        record = self.module.parse_attestation(log(), RUN)
        self.assertEqual(self.module.object_key(record),
                         f'keirin/2026-11-09/{RUN}/rsa-aes-sealed-wave.zip')
        record['object_key'] = 'unrelated/private/key.pem'
        self.assertEqual(self.module.object_key(record),
                         f'keirin/2026-11-09/{RUN}/rsa-aes-sealed-wave.zip')

    def test_wrong_job_or_failed_archive_step_cannot_authorize_readback(self):
        valid = {'jobs': [{'id': 12, 'name': 'capture-completed-races',
                 'steps': [{'name': 'Owner-private S3 upload must fail visibly if configured and readback fails',
                            'conclusion': 'success'}]}]}
        self.assertEqual(self.module.archive_job_id(valid), 12)
        valid['jobs'][0]['steps'][0]['conclusion'] = 'skipped'
        with self.assertRaises(ValueError):
            self.module.archive_job_id(valid)
        valid['jobs'][0]['steps'][0]['conclusion'] = 'success'
        valid['jobs'][0]['name'] = 'unit'
        with self.assertRaises(ValueError):
            self.module.archive_job_id(valid)


    def test_scheduled_capture_without_archive_is_not_green(self):
        """A scheduled producer lacking an archive cannot pass acceptance."""
        from unittest.mock import patch
        import os

        with TemporaryDirectory() as tmp:
            evt = Path(tmp) / 'source-event.json'
            evt.write_text(json.dumps(event()), encoding='utf-8')

            def fake_github(route):
                if route.endswith(f'/actions/runs/{RUN}'):
                    return json.dumps(event()['workflow_run']).encode()
                if route.endswith(f'/actions/runs/{RUN}/jobs?per_page=100'):
                    return json.dumps({'jobs': [{
                        'id': 23,
                        'name': 'capture-completed-races',
                        'steps': [{'name': self.module.ARCHIVE_STEP,
                                   'conclusion': 'skipped'}]
                    }]}).encode()
                self.fail('Unexpected API route: ' + route)

            env = {'GITHUB_EVENT_PATH': str(evt),
                   'GITHUB_RUN_ID': str(RUN + 1),
                   'GITHUB_REPOSITORY': 'haji84/RACE-AI',
                   'GH_TOKEN': 'SYNTHETIC_ONLY'}
            with patch.dict(os.environ, env), patch.object(
                    self.module, 'github', side_effect=fake_github):
                result, code = self.module.readback()
            self.assertEqual(result['status'], 'SOURCE_ARCHIVE_NOT_ATTESTED')
            self.assertFalse(result['independent_readback_verified'])
            self.assertNotEqual(code, 0, 'Missing archive must not pass CI')


if __name__ == '__main__':
    unittest.main()
