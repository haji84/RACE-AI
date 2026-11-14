"""Explicit one-case caller contracts; fake server metadata and no source I/O."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest

try:
    from race_ai import boat_prospective_forward as forward
except ImportError:
    forward = None


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(forward, 'explicit existing-push caller admission is missing')
        self.now = datetime(2030, 1, 15, 0, 0, tzinfo=timezone.utc)
        self.grid = b'fixture grid'; self.runtime = b'fixture runtime'
        self.request = dict(schema=forward.SCHEMA, day_jst='2030-01-15', max_cases=1,
            grid_input_path=forward.GRID_PATH, grid_input_sha256=sha256(self.grid).hexdigest(),
            runtime_pointer_sha256=sha256(self.runtime).hexdigest(),
            target=dict(race_id='20300115-01-01', cutoff_at='2030-01-15T12:00:00+09:00',
                active_count=6, roster_sha256=digest({str(i):str(4000+i) for i in range(1,7)})),
            predecessor=dict(run_id=10, lifetime_requests=9059, lifetime_completed_rounds=524,
                receipt=dict(id=11, digest='sha256:'+'b'*64, created_at='2030-01-14T23:00:00Z')))
        self.raw = json.dumps(self.request).encode()
        self.activation = dict(tested_head_sha='a'*40, tested_run_id=20, request_sha256=sha256(self.raw).hexdigest())
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937', GITHUB_REF='refs/heads/feat/four-sport-forecast-audit-view-20261022',
            GITHUB_RUN_ID='30', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='c'*40, GITHUB_ACTOR='haji84')
        self.env['GITHUB_WORKFLOW_REF']='haji84/RACE-AI/.github/workflows/boat-nationwide-ab-one-shot.yml@refs/heads/'+forward.BRANCH
        run = dict(id=20, head_sha='a'*40, run_attempt=1, status='completed', conclusion='success',
            workflow_id=392270247, path='.github/workflows/forecast-audit-ui.yml', event='pull_request',
            head_branch='feat/four-sport-forecast-audit-view-20261022', actor=dict(id=173585154,login='haji84'),
            triggering_actor=dict(id=173585154,login='haji84'), repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'),pull_requests=[dict(number=71)])
        self.responses = {'actions/runs/20/attempts/1':run,
            'actions/runs/20/attempts/1/jobs?per_page=100':dict(total_count=2,jobs=[
                dict(name=name,status='completed',conclusion='success') for name in
                ('Viewer audit contract','Pinned PR64 store and PDCA synthetic E2E')]),
            'compare/'+'a'*40+'...'+'c'*40:dict(status='ahead',total_commits=1,
                base_commit=dict(sha='a'*40),merge_base_commit=dict(sha='a'*40),
                commits=[dict(sha='c'*40,parents=[dict(sha='a'*40)])],
                files=[dict(filename=forward.TRIGGER,status='modified')])}
        for status in ('in_progress','queued','pending','waiting'):
            self.responses[f'actions/workflows/405276784/runs?status={status}&per_page=100'] = dict(total_count=0,workflow_runs=[])
        self.calls=[]

    def admit(self, **changes):
        options=dict(raw=self.raw,activation=self.activation,env=self.env,get=self.get,now=self.now,
                     grid_raw=self.grid,runtime_raw=self.runtime)
        options.update(changes)
        return forward.admit(**options)

    def get(self,path):
        self.calls.append(path);return deepcopy(self.responses[path])

    def test_admits_exact_tested_parent_trigger_only_child_and_fixed_inputs(self):
        admitted=self.admit()
        self.assertEqual(admitted['request'],self.request)
        self.assertEqual(admitted['head_sha'],'c'*40)
        self.assertEqual(admitted['tested_head_sha'],'a'*40)

    def test_owner_attempt_case_clock_hash_and_unknown_field_fail_before_server_reads(self):
        for key,value in [('GITHUB_RUN_ATTEMPT','2'),('GITHUB_ACTOR','other'),('GITHUB_EVENT_NAME','workflow_dispatch')]:
            with self.subTest(key=key),self.assertRaises(ValueError):self.admit(env=dict(self.env,**{key:value}))
        for mutate in (lambda r:r.update(max_cases=2), lambda r:r.update(unknown=True),
                       lambda r:r['target'].update(cutoff_at='2030-01-15T09:10:00+09:00'),
                       lambda r:r['target'].update(cutoff_at='2030-01-15T03:00:00Z'),
                       lambda r:r['target'].update(race_id='20300116-01-01')):
            value=deepcopy(self.request);mutate(value);raw=json.dumps(value).encode()
            with self.assertRaises(ValueError):self.admit(raw=raw,activation=dict(self.activation,request_sha256=sha256(raw).hexdigest()))
        with self.assertRaises(ValueError):self.admit(grid_raw=self.grid+b'changed')
        self.assertEqual(self.calls,[])

    def test_active_or_pending_worker_failed_ci_or_changed_runtime_child_holds(self):
        paths=list(self.responses)
        mutations=[(paths[0],lambda x:x.update(conclusion='failure')),
            (paths[1],lambda x:x['jobs'][0].update(conclusion='skipped')),
            (paths[2],lambda x:x['files'].append(dict(filename='scripts/changed.py',status='modified'))),
            ('actions/workflows/405276784/runs?status=queued&per_page=100',
             lambda x:x.update(total_count=1,workflow_runs=[dict(id=31,workflow_id=405276784,
                head_branch='feat/four-sport-forecast-audit-view-20261022',display_title='boat-cycle: pending')]))]
        for path,mutate in mutations:
            old=deepcopy(self.responses[path]);mutate(self.responses[path])
            with self.subTest(path=path),self.assertRaises(ValueError):self.admit()
            self.responses[path]=old

    def test_predecessor_requires_exact_authenticated_counters_and_no_open_round_or_wait(self):
        control=dict(previous_run_id=10,lifetime_requests=9059,lifetime_completed_rounds=524,
            receipt=self.request['predecessor']['receipt'],prepared_round=None,source_wait=None,
            previous_halted_reason=None,previous_stop_reason='DAY_HANDOFF')
        forward.check_predecessor(self.request,control)
        for change in (dict(prepared_round=1),dict(source_wait=dict(state='SOURCE_REVIEW_WAIT')),
                       dict(lifetime_requests=0),dict(previous_run_id=9),dict(previous_halted_reason='UNKNOWN')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                forward.check_predecessor(self.request,dict(control,**change))

    def test_activation_is_explicit_and_cannot_be_inferred_from_request_presence(self):
        line=forward.ACTIVATION+' '+json.dumps(self.activation)
        subject='boat-grid-forward: '+self.activation['request_sha256']
        self.assertEqual(forward.activation(line+'\n',subject),self.activation)
        self.assertIsNone(forward.activation(line+'\n','boat-cycle: ordinary'))
        with self.assertRaises(ValueError):forward.activation('ordinary trigger\n',subject)

    def test_exact_fourteen_one_case_receipt_and_full_six_hundred_second_margin(self):
        rows=[dict(cell_key='boat/model'+str(i),native_payload=dict(n=i)) for i in range(14)]
        info=dict(race_id='20300115-01-01',cutoff_at=self.request['target']['cutoff_at'],
                  roster={str(i):str(4000+i) for i in range(1,7)},as_of='2030-01-15T09:01:00+09:00')
        with patch('race_ai.boat_venue_future_grid.prospective_requests',side_effect=lambda x,**k:x), \
                patch('race_ai.all_existing_model_registry.identity',return_value=info):
            proof=forward.check_rows(self.request,rows,now=datetime(2030,1,15,2,49,58,500000,tzinfo=timezone.utc),saved_at='2030-01-15T02:49:58Z')
            self.assertEqual(proof['native_cell_count'],14)
            for changed in (rows[:-1],rows+rows[:1]):
                with self.assertRaises(ValueError):forward.check_rows(self.request,changed,now=datetime(2030,1,15,2,49,58,500000,tzinfo=timezone.utc),saved_at='2030-01-15T02:49:58Z')
            with self.assertRaises(ValueError):forward.check_rows(self.request,rows,now=datetime(2030,1,15,2,49,59,tzinfo=timezone.utc),saved_at='2030-01-15T02:49:59Z')
            with self.assertRaises(ValueError):forward.check_rows(dict(self.request,target=dict(self.request['target'],roster_sha256='f'*64)),rows,now=self.now,
                saved_at='2030-01-15T02:49:58Z')

    def test_default_admission_does_not_read_keys_files_server_or_runtime(self):
        from scripts import boat_prospective_forward as cli
        with patch.dict(os.environ,{'RACE_AI_FORWARD_REQUEST':''}), \
             patch.object(cli,'_cycle',side_effect=AssertionError('runtime forbidden')), \
             patch.object(cli,'_key',side_effect=AssertionError('key forbidden')), \
             patch.object(cli,'_get',side_effect=AssertionError('server forbidden')), \
             patch.object(cli,'_outputs'):
            self.assertEqual(cli.admit()['status'],'ORDINARY_PUSH_UNCHANGED')

    def test_fresh_default_cli_needs_no_dependency_bootstrap_or_owner_key(self):
        import subprocess,sys
        env=dict(os.environ,RACE_AI_FORWARD_REQUEST='')
        result=subprocess.run([sys.executable,'-m','scripts.boat_prospective_forward','admit'],
            cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'ORDINARY_PUSH_UNCHANGED')

    def test_fresh_activated_import_bootstraps_the_same_pinned_reference_before_runtime(self):
        import subprocess,sys
        code="""import sys,types,pathlib,race_ai
from scripts import boat_prospective_forward as cli
sys.modules['scripts.boat_all_model_cycle']=types.ModuleType('scripts.boat_all_model_cycle')
cli._cycle()
assert str(pathlib.Path(cli.__file__).resolve().parents[1]/'pr64-reference/race_ai') in race_ai.__path__
"""
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],
            capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_legacy_optional_grid_still_prepares_without_new_request(self):
        from scripts import boat_prospective_forward as cli
        with patch.object(cli,'active',return_value=False),patch.object(cli,'_cycle') as cycle:
            cli.prepare(1,forward.GRID_PATH)
            cycle.return_value.prepare_runtime.assert_called_once_with(round_no=1,prospective_grid_input=forward.GRID_PATH)
            cycle.return_value.require_prospective_prepared.assert_not_called()

    def test_preload_authenticates_closed_control_before_grid_and_bootstrap_get(self):
        from scripts import boat_prospective_forward as cli, first_p0_bootstrap as first
        control=dict(previous_run_id=10,lifetime_requests=9059,lifetime_completed_rounds=524,
            receipt=self.request['predecessor']['receipt'],prepared_round=None,source_wait=None,
            previous_halted_reason=None,previous_stop_reason='DAY_HANDOFF')
        bootstrap=dict(requests_used=0,source_wait=None,previous_halted_reason=None,
            inherited_source_receipt=control['receipt'],lifetime_requests_base=9059)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); calls=[]
            cycle=SimpleNamespace(ROOT=root,_environment=lambda:dict(run_id='30',head='c'*40),
                _read=lambda path,limit:self.grid if path.name.endswith('grid-input.json') else self.runtime,
                prepare_runtime=lambda **kw:(calls.append(('prepare',kw)) or dict(prospective_grid={'actual':'fixture'})))
            def closed(*args,**kwargs):calls.append(('authenticated_control',kwargs));return control
            with patch.object(cli,'active',return_value=True),patch.object(cli,'_cycle',return_value=cycle), \
                 patch.object(cli,'_load',return_value=dict(request=self.request,request_sha256='f'*64)), \
                 patch.object(cli,'_save') as save,patch.object(cli,'utc_now',return_value=self.now), \
                 patch.object(first,'previous_source_control',side_effect=closed), \
                 patch.object(first,'bootstrap_control',return_value=bootstrap), \
                 patch.object(forward,'no_other_workers'):
                cli.preload()
                self.assertEqual([c[0] for c in calls],['authenticated_control','prepare'])
                self.assertEqual(calls[-1][1],dict(round_no=1,prospective_grid_input=forward.GRID_PATH))
                save.assert_called_once()
                calls.clear();bootstrap['requests_used']=1
                with self.assertRaisesRegex(ValueError,'BEFORE_BOOTSTRAP_SOURCE'):cli.preload()
                self.assertEqual([c[0] for c in calls],['authenticated_control'])

    def test_round_preparation_reuses_original_capability_without_retiming(self):
        from scripts import boat_prospective_forward as cli
        with patch.object(cli,'active',return_value=True),patch.object(cli,'request',return_value=self.request),patch.object(cli,'_cycle') as cycle, \
                patch.object(cli,'_load',return_value=dict(grid_capability_sha256=digest({'original':'actual'}))):
            cycle.return_value.require_prospective_prepared.return_value=SimpleNamespace(record={'original':'actual'})
            cli.prepare(1,forward.GRID_PATH)
            cycle.return_value.require_prospective_prepared.assert_called_once_with(1,forward.GRID_PATH)
            cycle.return_value.prepare_runtime.assert_not_called()
            cycle.return_value.require_prospective_prepared.return_value=SimpleNamespace(record={'retimed':'later'})
            with self.assertRaisesRegex(ValueError,'ORIGINAL_PRE_BOOTSTRAP_CAPABILITY_CHANGED'):
                cli.prepare(1,forward.GRID_PATH)

    def test_slow_actual_readback_cannot_emit_ready_inside_six_hundred_seconds(self):
        from scripts import boat_prospective_forward as cli, github_existing_cycle as existing
        summary=dict(independent_pre_cutoff_receipt_verified=True,partition_count=14,cell_count=14,
            unique_races=1,captured_native_input_count=14)
        metadata=dict(name='all-existing-model-pairs-30-1',created_at='2030-01-14T23:59:00Z',digest='sha256:'+'d'*64)
        rows=[dict(cell_key='boat/fake'+str(i),native_payload={}) for i in range(14)]
        payloads=[dict(captured_native_inputs=rows)]
        late=datetime(2030,1,15,2,59,tzinfo=timezone.utc)
        cycle=SimpleNamespace(_environment=lambda:dict(run_id='30',head='c'*40))
        for clocks in ([self.now,late,late],[self.now,self.now,late]):
            with self.subTest(clocks=clocks),patch.object(cli,'request',return_value=self.request), \
                 patch.object(cli,'_cycle',return_value=cycle),patch.object(cli,'_key',return_value=b'k'*32), \
                 patch.object(cli,'utc_now',side_effect=clocks), \
                 patch.object(existing,'gh',side_effect=[json.dumps(metadata).encode(),b'offline zip']), \
                 patch('race_ai.all_existing_model_receipt._verified_private_pairs_artifact',return_value=(summary,payloads)), \
                 patch.object(cli,'validate_rows'),patch.object(cli,'_load',return_value=dict(request_sha256='f'*64)), \
                 patch.object(cli,'_save') as save,patch.object(forward,'check_rows',return_value=dict(native_cell_count=14)):
                with self.assertRaisesRegex(ValueError,'FRESH_READBACK_SIX_HUNDRED_MARGIN'):cli.prove(1,123)
                save.assert_not_called()

    def test_verified_actual_artifact_identity_is_retained_in_ready_proof(self):
        from scripts import boat_prospective_forward as cli, github_existing_cycle as existing
        summary=dict(independent_pre_cutoff_receipt_verified=True,partition_count=14,cell_count=14,
            unique_races=1,captured_native_input_count=14)
        metadata=dict(name='all-existing-model-pairs-30-1',created_at='2030-01-14T23:59:00Z',digest='sha256:'+'d'*64)
        payloads=[dict(captured_native_inputs=[dict(cell_key='boat/fake'+str(i),native_payload={}) for i in range(14)])]
        cycle=SimpleNamespace(_environment=lambda:dict(run_id='30',head='c'*40))
        with patch.object(cli,'request',return_value=self.request),patch.object(cli,'_cycle',return_value=cycle), \
             patch.object(cli,'_key',return_value=b'k'*32),patch.object(cli,'utc_now',return_value=self.now), \
             patch.object(existing,'gh',side_effect=[json.dumps(metadata).encode(),b'offline zip']), \
             patch('race_ai.all_existing_model_receipt._verified_private_pairs_artifact',return_value=(summary,payloads)) as verify, \
             patch.object(cli,'validate_rows'),patch.object(cli,'_load',return_value=dict(request_sha256='f'*64)), \
             patch.object(cli,'_save') as save,patch.object(forward,'check_rows',return_value=dict(native_cell_count=14)):
            proof=cli.prove(1,123)
            self.assertEqual(proof['artifact_id'],123)
            self.assertEqual(proof['artifact_digest'],metadata['digest'])
            self.assertEqual(proof['verified_at'],self.now.isoformat())
            self.assertEqual(verify.call_args.kwargs['expected_run_id'],30)
            self.assertEqual(verify.call_args.kwargs['expected_head_sha'],'c'*40)
            self.assertEqual(save.call_args.args[0],'ready.json')

    def test_ready_skips_remaining_rounds_without_preparing_or_charging_session(self):
        from scripts import boat_prospective_forward as cli, github_existing_cycle as existing
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(os.environ,{'GITHUB_OUTPUT':str(Path(temporary)/'out')}), \
             patch.object(cli,'active',return_value=True),patch.object(cli,'done',return_value=True), \
             patch('race_ai.repeated_cycle.prepare',side_effect=AssertionError('session must remain untouched')):
            self.assertFalse(existing.repeat_prepare('2030-01-15',2)['active'])

    def test_request_cannot_reach_forecast_without_the_explicit_prepared_grid(self):
        from scripts import boat_prospective_forward as cli, github_existing_cycle as existing
        with patch.object(cli,'request',return_value=self.request), \
             patch.object(existing,'load_state',side_effect=AssertionError('source path must remain unreachable')):
            with self.assertRaisesRegex(ValueError,'EXPLICIT_FORWARD_GRID_REQUIRED'):
                existing.forecast('2030-01-15',round_no=1)


if __name__ == '__main__': unittest.main()
