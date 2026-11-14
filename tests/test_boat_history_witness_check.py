"""Exact GitHub reader callbacks only; no source, keys or live GitHub access."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_boat_venue_future_grid_nov7 as nov7


class HistoryWitnessCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nov7.Nov7WitnessTests.setUpClass();cls.fixture=nov7.Nov7WitnessTests
    def api(self):
        from scripts import boat_history_witness_check as api
        return api
    def check(self,*,manifest=None,log=None,mutate=None):
        api=self.api();f=self.fixture;value=deepcopy(f.manifest if manifest is None else manifest)
        run=deepcopy(f.actual_run);jobs=deepcopy(f.jobs)
        if mutate is not None:mutate(run,jobs)
        bodies={f'actions/runs/{f.actual_run["id"]}/attempts/1':json.dumps(run).encode(),
            f'actions/runs/{f.actual_run["id"]}/attempts/1/jobs?per_page=100':json.dumps(jobs).encode(),
            f'actions/jobs/{f.job["id"]}/logs':f.log if log is None else log}
        self.calls=[]
        def get(path):self.calls.append(path);return bodies[path]
        return api.check_witness(value,gh=get,now=datetime(2030,1,1,tzinfo=timezone.utc))
    def test_actual_fixture_bytes_only_three_registered_reads_and_aggregate_success(self):
        report=self.check();self.assertTrue(report['verified']);self.assertTrue(report['metadata_pass'])
        self.assertEqual(len(self.calls),3);self.assertEqual(len(set(self.calls)),3)
        self.assertEqual(report['actual_log_sha256'],self.fixture.fixture['log_sha256'])
        self.assertEqual(report['actual_log_bytes'],len(self.fixture.log))
        self.assertEqual(set(report),{'schema','state','stage','log_transport','verified','metadata_pass','actual_log_sha256',
            'expected_log_sha256','actual_log_bytes','reason'})
        self.assertNotIn('source_days',json.dumps(report));self.assertNotIn('projection',report)
    def test_byte_changed_bom_or_line_endings_are_hold_without_alternate_hash_acceptance(self):
        for raw in (self.fixture.log+b'changed',b'\xef\xbb\xbf'+self.fixture.log,self.fixture.log.replace(b'\n',b'\r\n')):
            with self.subTest(sha=sha256(raw).hexdigest()):
                report=self.check(log=raw);self.assertFalse(report['verified']);self.assertTrue(report['metadata_pass'])
                self.assertEqual(report['actual_log_sha256'],sha256(raw).hexdigest())
                self.assertEqual(report['expected_log_sha256'],self.fixture.fixture['log_sha256'])
                self.assertEqual(report['state'],'HOLD_HISTORY_WITNESS')
    def test_unregistered_manifest_is_rejected_before_callback_and_metadata_mismatch_is_not_pass(self):
        value=deepcopy(self.fixture.manifest);value['readback']['log_sha256']='f'*64
        report=self.check(manifest=value);self.assertFalse(report['verified']);self.assertEqual(self.calls,[])
        report=self.check(mutate=lambda r,j:r['actor'].update(id=1))
        self.assertFalse(report['verified']);self.assertFalse(report['metadata_pass'])
    def test_nonbytes_empty_or_oversize_transport_never_passes_or_prints_body(self):
        for raw in (self.fixture.log.decode(),b'',b'x'*(2*1024*1024+1)):
            with self.subTest(kind=type(raw).__name__,size=len(raw)):
                report=self.check(log=raw);self.assertFalse(report['verified'])
                self.assertNotIn('xxxx',json.dumps(report));self.assertIsNone(report['actual_log_sha256'])
    def test_actions_owner_scope_precedes_manifest_transport_and_never_looks_up_owner_key(self):
        api=self.api()
        with patch.dict(os.environ,{},clear=True),patch.object(api,'_prospective_grid_get',side_effect=AssertionError('NO_GITHUB')):
            with redirect_stdout(io.StringIO()) as output:self.assertEqual(api.main([]),1)
        report=json.loads(output.getvalue());self.assertFalse(report['verified'])
        self.assertFalse(report['metadata_pass']);self.assertIsNone(report['actual_log_sha256'])
    def test_fixed_public_input_and_verified_vs_hold_exit_status_are_preserved(self):
        api=self.api();event=dict(number=71,pull_request=dict(user=dict(login='haji84',id=173585154),
            head=dict(ref='feat/four-sport-forecast-audit-view-20261022',repo=dict(full_name='haji84/RACE-AI')),
            base=dict(ref='codex/actions-four-sport-e2e')))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/api.PUBLIC_INPUT;path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.fixture.manifest));event_path=root/'event.json';event_path.write_text(json.dumps(event))
            env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',
                GITHUB_EVENT_NAME='pull_request',GITHUB_RUN_ATTEMPT='1',GITHUB_ACTOR='haji84',GITHUB_ACTOR_ID='173585154',
                GITHUB_TRIGGERING_ACTOR='haji84',GITHUB_EVENT_PATH=str(event_path))
            for valid in (True,False):
                report=self.check(log=self.fixture.log if valid else b'different original raw bytes')
                with patch.dict(os.environ,env,clear=True),patch.object(api,'ROOT',root),patch.object(api,'check_witness',return_value=report) as check,redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(api.main([]),0 if valid else 1)
                self.assertEqual(json.loads(output.getvalue()),report);self.assertEqual(check.call_args.args[0],self.fixture.manifest)
                self.assertIs(check.call_args.kwargs['gh'],api._prospective_grid_get)
            for field in ('GITHUB_RUN_ATTEMPT','GITHUB_ACTOR_ID'):
                with patch.dict(os.environ,dict(env,**{field:'2'}),clear=True),patch.object(api,'check_witness') as check,redirect_stdout(io.StringIO()):
                    self.assertEqual(api.main([]),1);check.assert_not_called()


if __name__=='__main__':unittest.main()
