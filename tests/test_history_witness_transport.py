"""Fresh registered GitHub log reads; all transports are offline callbacks."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import io
import zipfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_boat_venue_future_grid_nov7 as nov7


class HistoryWitnessTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nov7.Nov7WitnessTests.setUpClass();cls.f=nov7.Nov7WitnessTests
    def test_registered_log_get_uses_exact_attempt_zip_while_default_metadata_bytes_stay_unchanged(self):
        from scripts import boat_all_model_cycle as cli
        from scripts import github_existing_cycle as transport
        log=f'actions/jobs/{self.f.job["id"]}/logs';run=f'actions/runs/{self.f.actual_run["id"]}/attempts/1'
        from race_ai.boat_venue_future_grid import READBACK_LOG_MEMBER
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr(READBACK_LOG_MEMBER,self.f.log)
        result=SimpleNamespace(returncode=0,stdout=stream.getvalue(),stderr=b'')
        with patch.object(transport.subprocess,'run',return_value=result) as wire:
            self.assertEqual(cli._prospective_grid_get(log),self.f.log)
            self.assertEqual(wire.call_args.args[0],['gh','api',f'repos/haji84/RACE-AI/actions/runs/{self.f.actual_run["id"]}/attempts/1/logs'])
            cli._prospective_grid_get(run)
            self.assertEqual(wire.call_args.args[0],['gh','api','repos/haji84/RACE-AI/'+run])
            transport._live_gh('actions/artifacts/100')
            self.assertEqual(wire.call_args.args[0],['gh','api','repos/haji84/RACE-AI/actions/artifacts/100'])
    def test_zip_mode_cannot_read_unregistered_runs_logs_or_arbitrary_urls(self):
        from scripts import boat_all_model_cycle as cli
        from scripts import github_existing_cycle as transport
        for path in ('actions/jobs/1/logs',f'actions/runs/{self.f.actual_run["id"]}/attempts/2/logs',
            'actions/runs/1/attempts/1/logs',
            'https://example.invalid/private-redirect','actions/jobs/'+str(self.f.job['id'])+'/logs?new=1'):
            with self.subTest(path=path),patch.object(transport.subprocess,'run') as wire,self.assertRaises(ValueError):
                cli._prospective_grid_get(path)
            wire.assert_not_called()
    def test_zip_403_remains_one_halt_without_stderr_or_redirect_fallback(self):
        from scripts import boat_all_model_cycle as cli
        from scripts import github_existing_cycle as transport
        result=SimpleNamespace(returncode=1,stdout=b'',stderr=b'gh: HTTP 403: PRIVATE_ERROR_TOKEN')
        with patch.object(transport.subprocess,'run',return_value=result) as wire,patch.object(transport.time,'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError,'^GITHUB_API_READ_HTTP_403_HALT$'):
                cli._prospective_grid_get(f'actions/jobs/{self.f.job["id"]}/logs')
            self.assertEqual(wire.call_count,1);sleep.assert_not_called()
    def check(self,*,failure=None,raw=None):
        from scripts import boat_history_witness_check as check
        run=self.f.actual_run;jobs=self.f.jobs
        def get(path):
            if path.endswith('/logs'):
                if failure is not None:raise RuntimeError(failure)
                return self.f.log if raw is None else raw
            return json.dumps(jobs if '/jobs?' in path else run).encode()
        return check.check_witness(self.f.manifest,gh=get,now=datetime(2030,1,1,tzinfo=timezone.utc))
    def test_raw_log_failure_has_safe_stage_and_allowlisted_error_without_private_text(self):
        report=self.check(failure='GITHUB_API_READ_HTTP_403_HALT')
        self.assertEqual(report['stage'],'RAW_LOG');self.assertEqual(report['reason'],'GITHUB_API_READ_HTTP_403_HALT')
        self.assertFalse(report['verified']);self.assertIsNone(report['actual_log_sha256'])
        self.assertEqual(report['expected_log_sha256'],self.f.fixture['log_sha256'])
        report=self.check(failure='GITHUB_API_READ_HTTP_403_HALT PRIVATE_ERROR_TOKEN')
        self.assertEqual(report['reason'],'HISTORY_WITNESS_CHECK_FAILED');self.assertNotIn('PRIVATE_ERROR_TOKEN',json.dumps(report))
    def test_verify_stage_retains_literal_hash_without_any_text_normalization(self):
        report=self.check(raw=self.f.log+b'changed')
        self.assertEqual(report['stage'],'VERIFY');self.assertFalse(report['verified']);self.assertTrue(report['metadata_pass'])
        self.assertEqual(report['expected_log_sha256'],self.f.fixture['log_sha256'])
        report=self.check();self.assertTrue(report['verified']);self.assertEqual(report['stage'],'VERIFIED')
    def test_timeout_diagnostic_is_safe_and_identifies_metadata_stage(self):
        from scripts import boat_history_witness_check as check
        def get(_):raise RuntimeError('GITHUB_API_TIMEOUT_HALT')
        report=check.check_witness(self.f.manifest,gh=get,now=datetime(2030,1,1,tzinfo=timezone.utc))
        self.assertEqual(report['stage'],'RUN_METADATA');self.assertEqual(report['reason'],'GITHUB_API_READ_TIMEOUT_HALT')


if __name__=='__main__':unittest.main()
