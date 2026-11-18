"""Exact current-upload readback through the existing immutable-artifact reader."""
from contextlib import contextmanager, redirect_stderr
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import unittest
from unittest.mock import patch
import zipfile

from scripts import boat_all_model_cycle as models
from scripts import boat_private_original_vault as vault
from scripts import github_existing_cycle as cycle
from tests import test_boat_private_original_vault_live_artifact_retry as fixtures


class NewDayUploadVisibilityTests(unittest.TestCase):
    def setUp(self):
        fixtures.FreshOwnUploadRetryTests.setUp(self)
        self.name = 'boat-all-model-forecasts-99-r0'
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w') as archive:
            archive.writestr('forecasts.enc', b'immutable-synthetic-owner-cipher')
        self.archive = body.getvalue()
        self.digest = 'sha256:' + sha256(self.archive).hexdigest()
        self.metadata.update(name=self.name, digest=self.digest, size_in_bytes=len(self.archive))
        self.receipts = [dict(artifact_id='123', name=self.name, digest=self.digest)]
        self.env['RACE_AI_FRESH_UPLOAD_RECEIPTS'] = json.dumps(self.receipts)
        self.requests = []

    @contextmanager
    def transport(self, *, responses=None, env=None, zip_body=None):
        responses = iter(responses if responses is not None else [
            ValueError('VAULT_GITHUB_HTTP_404'), json.dumps(self.metadata).encode()])
        def once(endpoint):
            self.requests.append(endpoint)
            self.assertEqual(endpoint, 'actions/artifacts/123')
            result = next(responses)
            if isinstance(result, Exception):raise result
            return result
        def command(argv, **kwargs):
            route = argv[-1].removeprefix('repos/haji84/RACE-AI/')
            if route == 'actions/runs/99':
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.run).encode(), b'')
            if route == 'actions/artifacts/123/zip':
                return subprocess.CompletedProcess(argv, 0,
                    self.archive if zip_body is None else zip_body, b'')
            return subprocess.CompletedProcess(argv, 1, b'', b'gh: HTTP 404')
        with patch.dict(os.environ, self.env if env is None else env, clear=True), \
                patch.object(cycle, 'original_reader', return_value=None), \
                patch.object(cycle, 'datetime') as clock, \
                patch.object(cycle.subprocess, 'run', side_effect=command), \
                patch.object(vault.subprocess, 'check_output', return_value=(self.head+'\n').encode()), \
                patch.object(vault, '_gh_once', side_effect=once), \
                patch.object(vault.time, 'sleep'), redirect_stderr(io.StringIO()):
            clock.now.return_value = self.now
            yield

    def artifact(self):
        with patch.object(models, 'utc_now', return_value=self.now):
            return models._artifact(123, member='forecasts.enc', expected_name=self.name,
                expected_run='99', expected_head=self.head)

    def test_current_upload_404_then_metadata_reaches_unchanged_all_model_zip_binding(self):
        with self.transport():
            try:body, metadata = self.artifact()
            except (RuntimeError, ValueError):self.fail('fresh current-upload metadata remained an immediate HOLD')
        self.assertEqual(body, b'immutable-synthetic-owner-cipher')
        self.assertEqual(metadata['digest'], self.digest)
        self.assertEqual(self.requests, ['actions/artifacts/123'] * 2)

    def test_fresh_upload_permanent_404_has_three_reads_and_no_forecast_reexecution(self):
        with self.transport(responses=[ValueError('VAULT_GITHUB_HTTP_404')] * 3):
            with self.assertRaises((RuntimeError, ValueError)):
                cycle.gh(self.endpoint)
        self.assertEqual(self.requests, ['actions/artifacts/123'] * 3)

    def test_no_receipt_keeps_original_one_read_404_hold(self):
        env = dict(self.env);env.pop('RACE_AI_FRESH_UPLOAD_RECEIPTS')
        with self.transport(env=env), self.assertRaisesRegex(RuntimeError, 'GITHUB_API_READ_HTTP_404_HALT'):
            cycle.gh(self.endpoint)
        self.assertEqual(self.requests, [])

    def test_other_artifact_old_run_and_untrusted_attempt_do_not_get_fresh_metadata_retry(self):
        cases = [dict(GITHUB_RUN_ID='100'), dict(GITHUB_RUN_ATTEMPT='2'),
                 dict(GITHUB_REF='refs/heads/main'), dict(RACE_AI_FRESH_UPLOAD_RECEIPTS='[]')]
        for change in cases:
            self.requests.clear()
            with self.subTest(fields=tuple(change)), self.transport(env=dict(self.env, **change)):
                with self.assertRaises((RuntimeError, ValueError)):
                    cycle.gh(self.endpoint)
            self.assertEqual(self.requests, [])
        with self.transport(), self.assertRaises((RuntimeError, ValueError)):
            cycle.gh('actions/artifacts/124')
        self.assertEqual(self.requests, [])

    def test_fresh_upload_auth_rate_and_integrity_failures_never_retry(self):
        for reason in ('VAULT_GITHUB_HTTP_403', 'VAULT_GITHUB_HTTP_429',
                       'VAULT_LIVE_ARTIFACT_DIGEST_INVALID'):
            self.requests.clear()
            with self.subTest(reason=reason), self.transport(responses=[ValueError(reason)]):
                with self.assertRaises((RuntimeError, ValueError)):
                    cycle.gh(self.endpoint)
            self.assertEqual(self.requests, ['actions/artifacts/123'])

    def test_fresh_metadata_does_not_bypass_the_original_zip_hash_check(self):
        with self.transport(responses=[json.dumps(self.metadata).encode()], zip_body=self.archive+b'changed'):
            try:
                with self.assertRaisesRegex(ValueError, 'ARTIFACT_ARCHIVE_HASH_MISMATCH'):
                    self.artifact()
            except RuntimeError:self.fail('fresh metadata stopped before the unchanged ZIP hash check')

    def test_archive_selection_still_precedes_any_live_fresh_upload_read(self):
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(cycle, 'original_reader', return_value=lambda endpoint:b'authenticated archive'), \
                patch.object(cycle, '_live_gh', side_effect=AssertionError('archive selection bypassed')):
            self.assertEqual(cycle.gh(self.endpoint), b'authenticated archive')

    def test_existing_owner_r0_consumers_bind_their_own_receipt_to_readback_and_capture(self):
        path = Path(__file__).resolve().parents[1]/'.github/workflows/boat-nationwide-ab-one-shot.yml'
        steps = re.split(r'(?m)^      - name: ', path.read_text())[1:]
        for producer in ('new_day_models_freeze',):
            upload_index = next(i for i, step in enumerate(steps) if '\n        id: '+producer+'\n' in step)
            upload_name = re.search(r'(?m)^          name: (.+)$', steps[upload_index])[1]
            upload_name = upload_name.replace('${{ github.run_id }}', '99')
            for step in steps[upload_index+1:upload_index+3]:
                command = re.search(r'(?m)^        run: (.+)$', step)[1]
                with self.subTest(producer=producer, command=command.split()[:4]):
                    receipt = re.search(r'(?m)^          RACE_AI_FRESH_UPLOAD_RECEIPTS: >-\n            (.+)$', step)
                    self.assertIsNotNone(receipt, 'r0 consumer lacks its upload receipt binding')
                    receipt_text = receipt[1]
                    variables = {'steps.'+producer+'.outputs.artifact-id':'123', 'steps.'+producer+'.outputs.artifact-digest':self.digest,
                                 'github.run_id':'99'}
                    def render(match):return variables[match.group(1).strip()]
                    rendered = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', render, receipt_text)
                    self.assertEqual(json.loads(rendered), [dict(artifact_id='123', name=upload_name, digest=self.digest)])
                    if 'boat_private_original_vault' in command:
                        command = command.replace('${{ steps.'+producer+'.outputs.artifact-id }}', '123')
                        command = command.replace('${{ runner.temp }}', '/private-fixture')
                        args = vault._parser().parse_args(shlex.split(command)[3:])
                        self.assertTrue(args.fresh_upload, 'capture does not enable the verified receipt retry')


if __name__ == '__main__':
    unittest.main()
