"""Offline failures, real CLI pipes, immutable ciphertext and local Git only."""
from contextlib import redirect_stderr
from hashlib import sha256
import io
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import boat_private_original_vault as cli
import tests.test_boat_private_original_vault as fixtures
KEY, HEAD, NOW, original, wire = fixtures.KEY, fixtures.HEAD, fixtures.NOW, fixtures.original, fixtures.wire


class ClassifiedRetryTests(unittest.TestCase):
    def call(self, endpoint, effects):
        log = io.StringIO()
        with patch.object(cli, '_gh_once', side_effect=effects) as get, \
             patch.object(cli.time, 'sleep') as sleep, redirect_stderr(log):
            result = cli._gh(endpoint)
        return result, get, sleep, log.getvalue()

    def test_503_then_timeout_then_success_reuses_exact_run(self):
        endpoint = 'actions/runs/2'
        value, get, sleep, log = self.call(endpoint, [
            ValueError('VAULT_GITHUB_HTTP_503'),
            ValueError('VAULT_GITHUB_READ_TIMEOUT'), b'original'])
        self.assertEqual(value, b'original')
        self.assertEqual([c.args for c in get.call_args_list], [(endpoint,)] * 3)
        self.assertEqual([c.args for c in sleep.call_args_list], [(2,), (4,)])
        rows = [json.loads(s) for s in log.splitlines()]
        self.assertEqual([r['status'] for r in rows], ['GITHUB_READ_RETRY']*2 + ['GITHUB_READ_RECOVERED'])
        self.assertTrue(all(r['endpoint_kind'] == 'RUN_METADATA' for r in rows))

    def test_each_exact_read_endpoint_can_recover(self):
        for endpoint in ('actions/artifacts/101', 'actions/artifacts/101/zip', 'actions/runs/2'):
            with self.subTest(endpoint=endpoint):
                value, get, sleep, _ = self.call(endpoint, [ValueError('VAULT_GITHUB_TRANSPORT_TRANSIENT'), b'bytes'])
                self.assertEqual(value, b'bytes')
                self.assertEqual(get.call_count, 2)
                sleep.assert_called_once_with(2)

    def test_exhaustion_is_three_attempts_not_an_infinite_loop(self):
        log = io.StringIO()
        with patch.object(cli, '_gh_once', side_effect=ValueError('VAULT_GITHUB_HTTP_502')) as get, \
             patch.object(cli.time, 'sleep') as sleep, redirect_stderr(log):
            with self.assertRaisesRegex(ValueError, '^VAULT_GITHUB_HTTP_502$'):
                cli._gh('actions/artifacts/101/zip')
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(json.loads(log.getvalue().splitlines()[-1])['status'], 'GITHUB_READ_FAILED')

    def test_denial_limit_unknown_and_integrity_never_retry(self):
        for reason in ('VAULT_GITHUB_HTTP_401', 'VAULT_GITHUB_HTTP_403', 'VAULT_GITHUB_HTTP_404',
                       'VAULT_GITHUB_HTTP_429', 'VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE',
                       'VAULT_GITHUB_RESPONSE_EMPTY', 'VAULT_GITHUB_READ_BOUND_INVALID',
                       'VAULT_GITHUB_READ_UNAVAILABLE', 'VAULT_LIVE_ARTIFACT_DIGEST_INVALID'):
            with self.subTest(reason=reason), patch.object(cli, '_gh_once', side_effect=ValueError(reason)) as get, \
                 patch.object(cli.time, 'sleep') as sleep, redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, '^'+reason+'$'):
                    cli._gh('actions/artifacts/101')
                get.assert_called_once()
                sleep.assert_not_called()

    def test_invalid_or_provider_endpoint_rejected_before_process(self):
        for endpoint in ('https://www.boatrace.jp/test', 'actions/artifacts/101?x=1',
                         'actions/runs/2/jobs', 'actions/artifacts/0'):
            with self.subTest(endpoint=endpoint), patch.object(cli, '_gh_once') as get:
                with self.assertRaises(ValueError):
                    cli._gh(endpoint)
                get.assert_not_called()

    def test_unrecognized_private_exception_does_not_leak_into_diagnostics(self):
        log = io.StringIO()
        with patch.object(cli, '_gh_once', side_effect=ValueError('SECRET-RAW-URL')), redirect_stderr(log):
            with self.assertRaises(ValueError):
                cli._gh('actions/runs/2')
        self.assertNotIn('SECRET', log.getvalue())


class BoundedPipeTests(unittest.TestCase):
    def fake_process(self, out=b'', err=b'', code=0, delay=0):
        real = subprocess.Popen
        def launch(command, **kwargs):
            self.assertEqual(command[:2], ['gh', 'api'])
            program = ('import os,time;os.write(1,'+repr(out)+');os.write(2,'+repr(err)+');'
                       +'time.sleep('+str(delay)+');raise SystemExit('+str(code)+')')
            return real([sys.executable, '-c', program], **kwargs)
        return launch

    def test_http_status_is_preserved_without_private_stderr(self):
        for status in (401,403,404,429,500,502,503,504):
            with self.subTest(status=status), patch.object(cli.subprocess, 'Popen', side_effect=self.fake_process(
                    err=f'gh: PRIVATE TOKEN (HTTP {status})'.encode(), code=1)):
                with self.assertRaisesRegex(ValueError, f'^VAULT_GITHUB_HTTP_{status}$'):
                    cli._gh_once('actions/artifacts/101')

    def test_recognized_connection_reset_is_transient(self):
        with patch.object(cli.subprocess, 'Popen', side_effect=self.fake_process(err=b'connection reset by peer',code=1)):
            with self.assertRaisesRegex(ValueError, '^VAULT_GITHUB_TRANSPORT_TRANSIENT$'):
                cli._gh_once('actions/runs/2')

    def test_unknown_and_conflicting_http_remain_unknown(self):
        for message in (b'private unknown failure', b'HTTP 503 HTTP 403', b'HTTP 403 connection reset by peer'):
            with self.subTest(message=message), patch.object(cli.subprocess, 'Popen', side_effect=self.fake_process(err=message,code=1)):
                expected='VAULT_GITHUB_HTTP_403' if message.startswith(b'HTTP 403 ') else 'VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE'
                with self.assertRaisesRegex(ValueError, '^'+expected+'$'):
                    cli._gh_once('actions/runs/2')

    def test_success_returns_exact_binary_without_stderr_mixing(self):
        original = bytes(range(256))*128
        with patch.object(cli.subprocess, 'Popen', side_effect=self.fake_process(out=original,err=b'nonfatal diagnostic')):
            self.assertEqual(cli._gh_once('actions/artifacts/101/zip'), original)

    def test_stderr_is_bounded_and_cannot_deadlock_reader(self):
        with patch.object(cli.subprocess, 'Popen', side_effect=self.fake_process(err=b'x'*65536,code=1)):
            with self.assertRaisesRegex(ValueError, '^VAULT_GITHUB_DIAGNOSTIC_BOUND_INVALID$'):
                cli._gh_once('actions/runs/2')


class ImmutableRecoveryTests(unittest.TestCase):
    def test_transient_result_read_recovers_and_second_capture_is_idempotent(self):
        fixture=fixtures.VaultTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        raw,metadata=original(encrypted=True)
        info=wire(dict(id=2,head_sha=HEAD,workflow_id=405276784,
            head_branch='feat/four-sport-forecast-audit-view-20261022',event='push',
            repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937,full_name='haji84/RACE-AI')))
        responses={'actions/artifacts/101':metadata,'actions/runs/2':info,'actions/artifacts/101/zip':raw}
        calls=[]
        def read(endpoint):
            calls.append(endpoint)
            if calls.count(endpoint)==1:
                raise ValueError('VAULT_GITHUB_HTTP_503')
            return responses[endpoint]
        import base64
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(KEY).decode()}), \
             patch.object(cli,'_gh_once',side_effect=read), patch.object(cli.time,'sleep'), redirect_stderr(io.StringIO()):
            report=cli._capture([101],fixture.writer.repo,fixture.parent,fixture.writer,fixture.reader,cli._gh,NOW)
            saved=fixture.restore(report['locators'][0])
            self.assertEqual(saved['raw_zip'],raw)
            self.assertEqual(saved['metadata_raw'],metadata)
            self.assertTrue(report['independent_git_readback_verified'])
            commit=fixture.writer.head()
            with patch.object(cli,'_gh_once',side_effect=AssertionError('duplicate live read')):
                again=cli._capture([101],fixture.writer.repo,commit,fixture.writer,fixture.reader,cli._gh,NOW)
            self.assertEqual(again['status'],'EXACT_ORIGINAL_VAULT_UNCHANGED')
            self.assertEqual(fixture.writer.head(),commit)
        self.assertEqual(len(calls),6)
        self.assertEqual(sha256(saved['raw_zip']).digest(),sha256(raw).digest())


if __name__=='__main__':
    unittest.main()
