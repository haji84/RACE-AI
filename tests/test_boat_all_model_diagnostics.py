"""Expose an existing bounded GitHub failure class without private messages."""
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from scripts import boat_all_model_cycle as cli


class AllModelDiagnosticTests(unittest.TestCase):
    def test_fixed_git_valueerror_survives_without_changing_failure_or_ready(self):
        for reason in ('STATE_GIT_OPERATION_TIMEOUT','STATE_GIT_FETCH_TIMEOUT',
                       'VAULT_GIT_REMOTE_LOOKUP_TIMEOUT','VAULT_GIT_PUSH_TIMEOUT',
                       'STATE_GIT_OPERATION_FAILED_LOCAL_UNKNOWN',
                       'VAULT_GIT_OPERATION_FAILED_FETCH_HTTP_403'):
            out = io.StringIO()
            with self.subTest(reason=reason), patch.object(cli,'readback',side_effect=ValueError(reason)) as call, \
                 patch.object(cli,'_outputs') as outputs, redirect_stdout(out):
                code = cli.main(['readback','--round','0','--artifact','101'])
            self.assertEqual(code,2); self.assertEqual(call.call_count,1)
            outputs.assert_called_once_with(dict(ready=False))
            report = json.loads(out.getvalue())
            self.assertEqual(report['reason'],'ALL_MODEL_CLI_OPERATION_FAILED')
            self.assertEqual(report.get('upstream_reason'),reason)

    def test_git_diagnostic_rejects_private_suffixes_unknown_enums_and_wrong_exception_family(self):
        for private in ('STATE_GIT_OPERATION_TIMEOUT private-token','STATE_GIT_OPERATION_TIMEOUT\nsecret',
                        'VAULT_GIT_OPERATION_FAILED_FETCH_HTTP_403 https://private.invalid/token',
                        'STATE_GIT_LOCAL_TIMEOUT','STATE_GIT_OPERATION_FAILED_FETCH_HTTP_200',
                        'STATE_GIT_UNREVIEWED_PRIVATE_VALUE'):
            with self.subTest(private=private):
                report = cli._error_diagnostic(ValueError(private))
                self.assertNotIn('upstream_reason',report); self.assertNotIn(private,json.dumps(report))
        for error in (RuntimeError('STATE_GIT_OPERATION_TIMEOUT'),cli.CycleError('STATE_GIT_OPERATION_TIMEOUT')):
            self.assertNotIn('upstream_reason',cli._error_diagnostic(error))

    def test_exact_upstream_status_survives_optional_model_failure(self):
        out = io.StringIO()
        with patch.object(cli, 'generate', side_effect=RuntimeError('GITHUB_API_READ_HTTP_404_HALT')), \
             patch.object(cli, '_outputs') as outputs, redirect_stdout(out):
            code = cli.main(['generate', '--round', '1'])
        self.assertEqual(code, 2)
        outputs.assert_called_once_with(dict(ready=False))
        report = json.loads(out.getvalue())
        self.assertEqual(report['reason'], 'ALL_MODEL_CLI_OPERATION_FAILED')
        self.assertEqual(report['upstream_reason'], 'GITHUB_API_READ_HTTP_404_HALT')

    def test_rejection_and_wait_statuses_are_diagnostic_only(self):
        for status in (401, 403, 429, 503):
            with self.subTest(status=status):
                reason = f'GITHUB_API_READ_HTTP_{status}_HALT'
                self.assertEqual(cli._error_diagnostic(RuntimeError(reason))['upstream_reason'], reason)

    def test_unrecognized_messages_are_never_copied(self):
        for private in ('GITHUB_API_READ_HTTP_404_HALT private-token',
                        'private-source-race-and-key',
                        'GITHUB_API_READ_HTTP_404_HALT\nsecret',
                        'HTTP 404 at private/url', 'GITHUB_API_READ_HTTP_200_HALT'):
            with self.subTest(private=private):
                report = cli._error_diagnostic(RuntimeError(private))
                self.assertNotIn('upstream_reason', report)
                self.assertNotIn(private, json.dumps(report))


if __name__ == '__main__':
    unittest.main()
