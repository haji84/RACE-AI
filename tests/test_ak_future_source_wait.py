"""Authored clocks and public metadata; no provider or owner-secret use."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from contextlib import redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_all_existing_model_future_source_capture import manifest_fixture
from tests.test_jra_future_source_wait import FakeClock
from tests.test_official_issue_transport import FakeGitHub,PARENT

NOW=datetime(2030,1,15,0,tzinfo=timezone.utc)


class AkSourceWaitTests(unittest.TestCase):
    def setUp(self):
        self.wrapper=importlib.import_module('scripts.all_existing_model_future_source_capture')
        self.assertTrue(callable(getattr(self.wrapper,'wait_for_prior_window',None)),
            'AUTO/KEIRIN needs the shared source-free cooldown waiter')
        self.value=manifest_fixture()
        for case in self.value['cases']:case['cutoff_at']='2030-01-15T16:16:00+09:00'
        self.clock=FakeClock(NOW);self.env=dict(run_id=42,head_sha='b'*40,run_attempt=1)
        self.server=FakeGitHub();self.transport=self.wrapper.once.FutureSourceMarkerTransport(self.server)
        self.documents={};self.routes=[];self.latest=NOW-timedelta(seconds=601)
        for index,pin in enumerate(self.value['prior_journal_artifacts']):
            saved=self.latest-timedelta(seconds=index+2);actor=dict(id=173585154,login='haji84')
            repo=dict(id=1416489937,full_name='haji84/RACE-AI')
            self.documents['actions/runs/'+str(pin['run_id'])]=dict(id=pin['run_id'],head_sha=pin['head_sha'],
                run_attempt=2,status='completed',conclusion='cancelled' if index==0 else 'success',
                updated_at=self.latest.isoformat(),run_started_at=(saved-timedelta(hours=1)).isoformat(),
                repository=repo,head_repository=deepcopy(repo),pull_requests=[dict(number=71)],
                workflow_id=392270247,path='.github/workflows/forecast-audit-ui.yml',
                head_branch='feat/four-sport-forecast-audit-view-20261022',event='pull_request',
                actor=actor,triggering_actor=deepcopy(actor))
            self.documents['actions/artifacts/'+str(pin['id'])]=dict(id=pin['id'],digest=pin['digest'],expired=False,
                name='official-result-collection-journal-'+str(pin['run_id']),size_in_bytes=200,
                created_at=saved.isoformat(),expires_at=(NOW+timedelta(days=1)).isoformat(),
                workflow_run=dict(id=pin['run_id'],head_sha=pin['head_sha'],repository_id=1416489937,head_repository_id=1416489937))

    def reader(self,route):self.routes.append(route);return deepcopy(self.documents[route])

    def wait(self,**options):
        return self.wrapper.wait_for_prior_window(self.value,self.env,reader=options.pop('reader',self.reader),
            marker_transport=options.pop('marker_transport',self.transport),clock=self.clock.utc,
            sleeper=options.pop('sleeper',self.clock.advance),monotonic=self.clock.mono,**options)

    def test_actual_boundary_is_waited_without_key_capture_or_marker_mutation(self):
        with patch.object(self.wrapper,'state_key') as key,patch.object(self.wrapper,'capture_browser') as capture,\
            patch.object(self.wrapper.once,'reserve') as reserve:
            self.assertIsNone(self.wait())
        self.assertEqual(self.clock.now,self.latest+timedelta(seconds=3601))
        self.assertEqual(self.clock.elapsed,3000);self.assertLessEqual(max(self.clock.sleeps),45)
        self.assertTrue(all(self.routes.count(route)==2 for route in self.documents))
        self.assertTrue(all(method=='GET' for method,_,_ in self.server.calls))
        key.assert_not_called();capture.assert_not_called();reserve.assert_not_called()

    def test_distinct_once_paths_preserve_horse_marker_and_reject_wrong_transport(self):
        horse=importlib.import_module('race_ai.jra_future_source_capture')
        self.server.snapshots[PARENT][horse.PATH]=b'old horse marker'
        self.server._commit(PARENT,self.server.snapshots[PARENT])
        self.assertIsNone(self.wait())
        self.clock=FakeClock(NOW);self.routes=[]
        with self.assertRaisesRegex(ValueError,'CANONICAL_ONCE_PATH'):
            self.wait(marker_transport=horse.MarkerTransport(self.server))
        self.assertEqual(self.routes,[])
        self.server.snapshots[PARENT][self.wrapper.once.PATH]=b'unknown AUTO/KEIRIN marker'
        self.server._commit(PARENT,self.server.snapshots[PARENT])
        with self.assertRaisesRegex(ValueError,'ONCE_ALREADY_CONSUMED'):self.wait()
        self.assertEqual(self.routes,[])

    def test_earliest_of_both_cutoffs_must_cover_wait_and_existing_capture_window(self):
        self.value['cases'][1]['cutoff_at']=(NOW+timedelta(seconds=3600)).isoformat()
        with self.assertRaisesRegex(ValueError,'WAIT_WINDOW_UNAVAILABLE'):self.wait()
        self.assertEqual(self.clock.sleeps,[])

    def test_nonterminal_tampered_and_failed_metadata_never_reach_source(self):
        original=deepcopy(self.documents)
        for change in ('running','digest','actor','expired'):
            self.documents=deepcopy(original);self.clock=FakeClock(NOW)
            run=next(value for route,value in self.documents.items() if '/runs/' in route)
            meta=next(value for route,value in self.documents.items() if '/artifacts/' in route)
            if change=='running':run['status']='in_progress'
            elif change=='digest':meta['digest']='sha256:'+'0'*64
            elif change=='actor':run['actor']['id']=1
            else:meta['expired']=True
            with self.subTest(change=change),self.assertRaises(ValueError):self.wait()
            self.assertEqual(self.clock.sleeps,[])
        calls=[]
        def failed(route):calls.append(route);raise RuntimeError('authored network failure')
        with self.assertRaises(RuntimeError):self.wait(reader=failed)
        self.assertEqual(len(calls),1)

    def test_forward_utc_jump_cannot_shorten_monotonic_wait(self):
        jumped=[False]
        def forward(seconds):
            self.clock.advance(seconds)
            if not jumped[0]:self.clock.now+=timedelta(seconds=1200);jumped[0]=True
        self.wait(sleeper=forward);self.assertEqual(self.clock.elapsed,3000)

    def test_only_two_source_schemas_are_supported(self):
        self.value['schema']='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V1'
        with self.assertRaisesRegex(ValueError,'WAIT_SCHEMA'):self.wait()
        self.assertEqual(self.routes,[]);self.assertEqual(self.clock.sleeps,[])

    def test_each_wrapper_refuses_to_wait_under_the_other_sources_once_scope(self):
        shared=importlib.import_module('race_ai.future_source_cooldown')
        horse=importlib.import_module('scripts.jra_future_source_capture')
        from tests.test_jra_future_source_capture import manifest as horse_manifest
        for wrapper,value in ((horse,self.value),(self.wrapper,horse_manifest())):
            with self.subTest(wrapper=wrapper.__name__),patch.object(shared,'wait_for_prior_window') as delegated:
                with self.assertRaisesRegex(ValueError,'WAIT_SCHEMA'):wrapper.wait_for_prior_window(value,self.env)
            delegated.assert_not_called()

    def test_both_actual_source_environments_defer_the_owner_key_until_generation(self):
        current=deepcopy(next(value for route,value in self.documents.items() if '/runs/' in route))
        current.update(id=42,head_sha=self.env['head_sha'],run_attempt=1,status='in_progress',conclusion=None)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);event=root/'event.json'
            event.write_text(json.dumps(dict(number=71,pull_request=dict(head=dict(repo=dict(full_name='haji84/RACE-AI'))))))
            env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',
                GITHUB_EVENT_NAME='pull_request',GITHUB_RUN_ID='42',RUNNER_TEMP=temp,GITHUB_EVENT_PATH=str(event))
            for name in ('scripts.all_existing_model_future_source_capture','scripts.jra_future_source_capture'):
                with self.subTest(wrapper=name),patch.dict(os.environ,env,clear=True),\
                    patch.object(self.wrapper.future,'state_key',side_effect=AssertionError('key before cooldown')) as key,\
                    patch.object(self.wrapper.future,'gh',return_value=json.dumps(current).encode()) as gh:
                    result=importlib.import_module(name).environment(check_owner_key=False)
                    self.assertEqual(result['run_id'],42);self.assertEqual(result['run_attempt'],1)
                    key.assert_not_called()
                    self.assertTrue(all(call.args==('actions/runs/42',) for call in gh.call_args_list))

    def test_other_future_environment_callers_keep_the_default_owner_key_check(self):
        with patch.object(self.wrapper.future,'state_key',side_effect=ValueError('AUTHORED_OWNER_KEY_HOLD')) as key,\
            patch.object(self.wrapper.future,'gh') as gh:
            with self.assertRaisesRegex(ValueError,'AUTHORED_OWNER_KEY_HOLD'):self.wrapper.future.environment()
        key.assert_called_once_with('production');gh.assert_not_called()

    def test_common_environment_default_keeps_the_existing_result_collector_key_check(self):
        current=deepcopy(next(value for route,value in self.documents.items() if '/runs/' in route))
        current.update(id=42,head_sha=self.env['head_sha'],run_attempt=1,status='in_progress',conclusion=None)
        with tempfile.TemporaryDirectory() as temp:
            event=Path(temp)/'event.json'
            event.write_text(json.dumps(dict(number=71,pull_request=dict(head=dict(repo=dict(full_name='haji84/RACE-AI'))))))
            env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',
                GITHUB_EVENT_NAME='pull_request',GITHUB_RUN_ID='42',RUNNER_TEMP=temp,GITHUB_EVENT_PATH=str(event))
            with patch.dict(os.environ,env,clear=True),\
                patch.object(self.wrapper.future,'state_key',side_effect=ValueError('AUTHORED_OWNER_KEY_HOLD')) as key,\
                patch.object(self.wrapper.future,'gh',return_value=json.dumps(current).encode()) as gh:
                with self.assertRaisesRegex(ValueError,'AUTHORED_OWNER_KEY_HOLD'):self.wrapper.environment()
            key.assert_called_once_with('production');gh.assert_not_called()

    def call_main(self,root,*options):
        path=root/'input.json';path.write_text(json.dumps(self.value));path.chmod(0o600)
        env=dict(self.env,temp=root)
        with patch.object(self.wrapper,'environment',return_value=env) as environment,\
            patch.object(self.wrapper,'utc_now',side_effect=self.clock.utc),\
            patch.dict(self.wrapper.os.environ,{'GITHUB_OUTPUT':''}),redirect_stdout(io.StringIO()):
            result=self.wrapper.main(['--input',str(path),'--out-dir',str(root/'out'),*options])
            self.environment_kwargs=dict(environment.call_args.kwargs)
        return result,json.loads((root/'out.status.json').read_text())

    def test_main_reaches_unchanged_generator_key_lookup_only_after_actual_wait(self):
        shared=importlib.import_module('race_ai.future_source_cooldown')
        original=self.transport.json;events=[]
        def read(route):return self.reader(route) if route.startswith('actions/') else original(route)
        def sleep(seconds):
            self.assertEqual(events,[]);self.clock.advance(seconds)
        def key(*args):
            self.assertGreaterEqual(self.clock.now,self.latest+timedelta(seconds=3601))
            events.append('key');raise ValueError('ALL_MODEL_FUTURE_SOURCE_AUTHORED_POST_WAIT_HOLD')
        with tempfile.TemporaryDirectory() as temp,\
            patch.object(self.wrapper.once,'FutureSourceMarkerTransport',return_value=self.transport),\
            patch.object(self.transport,'json',side_effect=read),\
            patch.object(shared.time,'sleep',side_effect=sleep),\
            patch.object(shared.time,'monotonic',side_effect=self.clock.mono),\
            patch.object(self.wrapper,'state_key',side_effect=key),\
            patch.object(self.wrapper,'capture_browser') as capture,patch.object(self.wrapper.once,'reserve') as reserve:
            result,status=self.call_main(Path(temp))
            self.assertFalse((Path(temp)/'out').exists())
        self.assertEqual(events,['key']);self.assertEqual(result,0)
        self.assertEqual(self.environment_kwargs,{'check_owner_key':False})
        self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],0)
        capture.assert_not_called();reserve.assert_not_called()

    def test_main_wait_hold_does_not_lookup_key_or_enter_generator(self):
        with tempfile.TemporaryDirectory() as temp,\
            patch.object(self.wrapper,'wait_for_prior_window',side_effect=ValueError('ALL_MODEL_FUTURE_SOURCE_WAIT_PRIOR_NOT_TERMINAL')),\
            patch.object(self.wrapper,'generate') as generate,patch.object(self.wrapper,'state_key') as key:
            _,status=self.call_main(Path(temp));self.assertFalse((Path(temp)/'out').exists())
        self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],0)
        generate.assert_not_called();key.assert_not_called()

    def test_jra_main_also_waits_before_unchanged_generator_first_key_lookup(self):
        from tests.test_jra_future_source_wait import JraSourceWaitTests
        authored=JraSourceWaitTests('runTest');authored.setUp()
        wrapper=authored.wrapper;shared=importlib.import_module('race_ai.future_source_cooldown')
        original=authored.transport.json;events=[]
        def read(route):return authored.reader(route) if route.startswith('actions/') else original(route)
        def sleep(seconds):
            self.assertEqual(events,[]);authored.clock.advance(seconds)
        def key(*args):
            self.assertGreaterEqual(authored.clock.now,authored.latest+timedelta(seconds=3601))
            events.append('key');raise ValueError('JRA_FUTURE_SOURCE_AUTHORED_POST_WAIT_HOLD')
        with tempfile.TemporaryDirectory() as temp,\
            patch.object(wrapper.core,'MarkerTransport',return_value=authored.transport),\
            patch.object(authored.transport,'json',side_effect=read),\
            patch.object(shared.time,'sleep',side_effect=sleep),\
            patch.object(shared.time,'monotonic',side_effect=authored.clock.mono),\
            patch.object(wrapper,'state_key',side_effect=key),\
            patch.object(wrapper,'collect') as collect,patch.object(wrapper.core,'reserve') as reserve:
            path=Path(temp)/'request.json';path.write_text(json.dumps(authored.value));path.chmod(0o600)
            with patch.object(wrapper,'environment',return_value=dict(authored.env,temp=Path(temp))) as environment,\
                patch.object(wrapper,'utc_now',side_effect=authored.clock.utc),\
                patch.dict(wrapper.os.environ,{'GITHUB_OUTPUT':''}),redirect_stdout(io.StringIO()):
                wrapper.main(['--input',str(path),'--out-dir',str(Path(temp)/'out')])
            environment.assert_called_once_with(check_owner_key=False)
            status=json.loads((Path(temp)/'out.status.json').read_text())
            self.assertFalse((Path(temp)/'out').exists())
        self.assertEqual(events,['key']);self.assertEqual(authored.clock.elapsed,3000)
        self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],0)
        collect.assert_not_called();reserve.assert_not_called()

    def test_readback_routes_never_wait_or_enter_generator(self):
        for options,method in ((['--readback-source','801'],'readback_source'),
            (['--readback-source','801','--readback-native','800'],'readback')):
            with self.subTest(method=method),tempfile.TemporaryDirectory() as temp,\
                patch.object(self.wrapper,'wait_for_prior_window') as wait,patch.object(self.wrapper,'generate') as generate,\
                patch.object(self.wrapper,method,return_value=dict(ready=False,source_requests=0)) as readback:
                self.call_main(Path(temp),*options)
            wait.assert_not_called();generate.assert_not_called();readback.assert_called_once()
            self.assertEqual(self.environment_kwargs,{'check_owner_key':True})


if __name__=='__main__':unittest.main()
