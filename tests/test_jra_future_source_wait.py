"""Authored metadata and physical clocks only; no provider or owner secret."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.test_jra_future_source_capture import manifest, NOW
from tests.test_official_issue_transport import FakeGitHub, PARENT


class FakeClock:
    def __init__(self, now=NOW):self.now=now;self.elapsed=0.;self.sleeps=[]
    def utc(self):return self.now
    def mono(self):return self.elapsed
    def advance(self, seconds):
        self.sleeps.append(seconds);self.elapsed+=seconds;self.now+=timedelta(seconds=seconds)


class JraSourceWaitTests(unittest.TestCase):
    def setUp(self):
        self.wrapper=importlib.import_module('scripts.jra_future_source_capture')
        self.assertTrue(callable(getattr(self.wrapper,'wait_for_prior_window',None)),
            'JRA generation needs a source-free, bounded actual-prior waiter')
        self.value=manifest();self.clock=FakeClock();self.env=dict(run_id=42,head_sha='b'*40,run_attempt=1)
        self.server=FakeGitHub();self.transport=self.wrapper.core.MarkerTransport(self.server)
        self.routes=[];self.documents={};self.latest=NOW-timedelta(seconds=601)
        self.set_latest(self.latest)

    def set_latest(self, latest):
        for number,pin in enumerate(self.value['prior_journal_artifacts']):
            saved=latest-timedelta(seconds=2+number)
            actor=dict(id=173585154,login='haji84')
            repo=dict(id=1416489937,full_name='haji84/RACE-AI')
            self.documents['actions/runs/'+str(pin['run_id'])]=dict(id=pin['run_id'],head_sha=pin['head_sha'],
                run_attempt=2,status='completed',conclusion='cancelled' if number==0 else 'success',
                updated_at=latest.isoformat(),run_started_at=(saved-timedelta(hours=1)).isoformat(),
                repository=repo,head_repository=deepcopy(repo),pull_requests=[dict(number=71)],
                workflow_id=392270247,path='.github/workflows/forecast-audit-ui.yml',
                head_branch='feat/four-sport-forecast-audit-view-20261022',event='pull_request',
                actor=actor,triggering_actor=deepcopy(actor))
            self.documents['actions/artifacts/'+str(pin['id'])]=dict(id=pin['id'],digest=pin['digest'],expired=False,
                name='official-result-collection-journal-'+str(pin['run_id']),size_in_bytes=200,
                created_at=saved.isoformat(),expires_at=(NOW+timedelta(days=1)).isoformat(),
                workflow_run=dict(id=pin['run_id'],head_sha=pin['head_sha'],repository_id=1416489937,head_repository_id=1416489937))

    def reader(self, route):self.routes.append(route);return deepcopy(self.documents[route])
    def wait(self, **kwargs):
        return self.wrapper.wait_for_prior_window(self.value,self.env,reader=kwargs.pop('reader',self.reader),
            marker_transport=self.transport,clock=kwargs.pop('clock',self.clock.utc),
            sleeper=kwargs.pop('sleeper',self.clock.advance),monotonic=kwargs.pop('monotonic',self.clock.mono),**kwargs)

    def test_waits_to_actual_boundary_with_no_source_key_file_or_git_write(self):
        boundary=self.latest+timedelta(seconds=3601)
        with tempfile.TemporaryDirectory() as temp,patch.object(self.wrapper,'state_key') as key,\
            patch.object(self.wrapper,'collect') as collect,patch.object(self.wrapper.core,'reserve') as reserve:
            result=self.wait()
            self.assertEqual(list(Path(temp).iterdir()),[])
        self.assertIsNone(result);self.assertEqual(self.clock.now,boundary)
        self.assertTrue(self.clock.sleeps);self.assertLessEqual(max(self.clock.sleeps),45)
        self.assertAlmostEqual(sum(self.clock.sleeps),3000)
        self.assertTrue(all(method=='GET' for method,_,_ in self.server.calls))
        self.assertTrue(all('/zip' not in route for route in self.routes))
        self.assertEqual(set(self.routes),set(self.documents))
        self.assertTrue(all(self.routes.count(route)==2 for route in self.documents))
        key.assert_not_called();collect.assert_not_called();reserve.assert_not_called()

    def test_boundary_exact_or_already_elapsed_returns_without_sleep_and_keeps_legacy_cancelled(self):
        for offset in (0,1):
            with self.subTest(offset=offset):
                self.clock=FakeClock(self.latest+timedelta(seconds=3601+offset));self.routes=[]
                self.assertIsNone(self.wait());self.assertEqual(self.clock.sleeps,[])
                self.assertTrue(all(self.routes.count(route)==2 for route in self.documents))

    def test_nonterminal_or_wrong_scope_or_metadata_stops_before_wait_or_mutation(self):
        runroute=next(r for r in self.documents if '/runs/' in r)
        metaroute=next(r for r in self.documents if '/artifacts/' in r)
        original=deepcopy(self.documents)
        for mutation in ('running','foreign_run','wrong_actor','wrong_head','wrong_repo','digest','expired','name','size','future_created','missing'):
            self.documents=deepcopy(original);self.clock=FakeClock()
            if mutation=='running':self.documents[runroute]['status']='in_progress'
            elif mutation=='foreign_run':self.documents[runroute]['id']+=1
            elif mutation=='wrong_actor':self.documents[runroute]['actor']['id']=1
            elif mutation=='wrong_head':self.documents[runroute]['head_sha']='c'*40
            elif mutation=='wrong_repo':self.documents[metaroute]['workflow_run']['repository_id']=1
            elif mutation=='digest':self.documents[metaroute]['digest']='sha256:'+'0'*64
            elif mutation=='expired':self.documents[metaroute]['expires_at']=NOW.isoformat()
            elif mutation=='name':self.documents[metaroute]['name']='unrelated-artifact'
            elif mutation=='size':self.documents[metaroute]['size_in_bytes']=0
            elif mutation=='future_created':self.documents[metaroute]['created_at']=(NOW+timedelta(seconds=1)).isoformat()
            else:del self.documents[metaroute]['workflow_run']['head_sha']
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.wait()
            self.assertEqual(self.clock.sleeps,[])
        self.assertTrue(all(method=='GET' for method,_,_ in self.server.calls))

    def test_existing_once_marker_holds_before_any_history_read_or_sleep(self):
        self.server.snapshots[PARENT][self.wrapper.core.PATH]=b'existing-unknown'
        self.server._commit(PARENT,self.server.snapshots[PARENT])
        with self.assertRaisesRegex(ValueError,'ONCE_ALREADY_CONSUMED'):self.wait()
        self.assertEqual(self.routes,[]);self.assertEqual(self.clock.sleeps,[])

    def test_final_all_fact_refresh_moves_boundary_without_resetting_budget(self):
        reads=[0];original=self.reader
        def changing(route):
            reads[0]+=1
            if reads[0]==len(self.documents)+1:self.set_latest(self.latest+timedelta(seconds=100))
            return original(route)
        self.wait(reader=changing)
        self.assertEqual(self.clock.now,self.latest+timedelta(seconds=3701))
        self.assertAlmostEqual(self.clock.elapsed,3100)
        self.assertTrue(all(self.routes.count(route)==3 for route in self.documents))

    def test_a_prior_becoming_nonterminal_at_final_read_holds_without_restarting(self):
        count=[0];original=self.reader
        def changing(route):
            count[0]+=1
            if count[0]==len(self.documents)+1:
                self.documents[next(r for r in self.documents if '/runs/' in r)]['status']='in_progress'
            return original(route)
        with self.assertRaises(ValueError):self.wait(reader=changing)
        self.assertAlmostEqual(self.clock.elapsed,3000)

    def test_repeated_prior_revisions_cannot_exhaust_the_public_api_budget(self):
        count=[0];revision=[0];original=self.reader;width=len(self.documents)
        def changing(route):
            if count[0] and count[0]%width==0:
                revision[0]+=1;self.set_latest(self.latest+timedelta(seconds=revision[0]))
            count[0]+=1
            return original(route)
        with self.assertRaises(ValueError):self.wait(reader=changing)
        self.assertLessEqual(len(self.routes),8*len(self.value['prior_journal_artifacts']))

    def test_fixed_monotonic_budget_and_utc_rollback_never_advance_the_source(self):
        self.set_latest(NOW)
        def stalled(seconds):self.clock.sleeps.append(seconds);self.clock.elapsed+=seconds
        with self.assertRaisesRegex(ValueError,'WAIT_BUDGET'):self.wait(sleeper=stalled)
        self.assertLessEqual(self.clock.elapsed,3605)
        self.clock=FakeClock()
        def backwards(seconds):self.clock.elapsed+=seconds;self.clock.now-=timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError,'WAIT_CLOCK'):self.wait(sleeper=backwards)

    def test_network_error_or_slow_api_is_not_automatically_retried(self):
        calls=[]
        def failing(route):calls.append(route);raise RuntimeError('private transport details')
        with self.assertRaises(RuntimeError):self.wait(reader=failing)
        self.assertEqual(len(calls),1);self.assertEqual(self.clock.sleeps,[])
        def slow(route):self.clock.elapsed=3606;return self.reader(route)
        with self.assertRaisesRegex(ValueError,'WAIT_BUDGET'):self.wait(reader=slow)

    def test_default_metadata_transport_is_single_attempt_without_archive_or_host_fallback(self):
        transport=importlib.import_module('race_ai.all_existing_model_official_issue_transport')
        legacy=importlib.import_module('scripts.github_existing_cycle')
        for failure in ('503','timeout'):
            self.clock=FakeClock();server=FakeGitHub();metadata_calls=[];commands=[]
            def run(args,**kwargs):
                commands.append(args)
                route=next(a.removeprefix('repos/haji84/RACE-AI/') for a in args if a.startswith('repos/haji84/RACE-AI/'))
                method=args[args.index('--method')+1] if '--method' in args else 'GET'
                if route.startswith('actions/'):
                    metadata_calls.append(route);self.clock.elapsed+=50
                    if failure=='timeout':raise subprocess.TimeoutExpired(args,50)
                    return subprocess.CompletedProcess(args,1,b'',b'gh: HTTP 503 private details')
                return subprocess.CompletedProcess(args,0,server(method,route),b'')
            with self.subTest(failure=failure),patch.object(transport.subprocess,'run',side_effect=run),\
                patch.object(legacy.time,'sleep',side_effect=self.clock.advance),\
                patch.object(legacy,'original_reader',return_value=None):
                with self.assertRaises((ValueError,RuntimeError)):
                    self.wrapper.wait_for_prior_window(self.value,self.env,clock=self.clock.utc,monotonic=self.clock.mono)
            self.assertEqual(len(metadata_calls),1);self.assertEqual(self.clock.elapsed,50)
            self.assertTrue(all('--hostname' in args and args[args.index('--hostname')+1]=='github.com' for args in commands))

    def test_forward_utc_jump_does_not_shorten_interval_even_when_initial_clock_read_is_delayed(self):
        reads=[0];jumped=[False]
        def mono():
            reads[0]+=1
            if reads[0]==2:self.clock.advance(30)
            return self.clock.elapsed
        def forwards(seconds):
            self.clock.advance(seconds)
            if not jumped[0]:self.clock.now+=timedelta(seconds=1200);jumped[0]=True
        self.wait(monotonic=mono,sleeper=forwards)
        self.assertAlmostEqual(self.clock.elapsed,3000)

    def test_expiry_day_or_cutoff_that_cannot_cover_wait_holds_without_moving_clocks(self):
        original=deepcopy(self.documents)
        for mutation in ('expiry','cutoff','day'):
            self.documents=deepcopy(original);self.clock=FakeClock();self.value=manifest()
            if mutation=='expiry':
                for route in self.documents:
                    if '/artifacts/' in route:self.documents[route]['expires_at']=(NOW+timedelta(seconds=200)).isoformat()
            elif mutation=='cutoff':self.value['cutoff_at']=(NOW+timedelta(seconds=3600)).isoformat()
            else:
                def jump(seconds):self.clock.elapsed+=seconds;self.clock.now+=timedelta(days=1)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                self.wait(**({'sleeper':jump} if mutation=='day' else {}))
        self.assertTrue(all(method=='GET' for method,_,_ in self.server.calls))

    def call_main(self,root,*options):
        source=root/'request.json';source.write_text(json.dumps(self.value));source.chmod(0o600)
        env=dict(self.env,temp=root)
        with patch.object(self.wrapper,'environment',return_value=env),patch.object(self.wrapper,'utc_now',side_effect=self.clock.utc),\
            patch.dict(self.wrapper.os.environ,{'GITHUB_OUTPUT':''}),redirect_stdout(io.StringIO()):
            result=self.wrapper.main(['--input',str(source),'--out-dir',str(root/'output'),*options])
        return result,json.loads((root/'output.status.json').read_text())

    def test_main_waits_only_for_generation_then_fresh_admission_can_hold(self):
        events=[]
        def waited(*args):events.append('wait')
        def fresh(*args):events.append('generate');raise ValueError('JRA_FUTURE_SOURCE_FRESH_ADMISSION_HOLD')
        with tempfile.TemporaryDirectory() as temp,patch.object(self.wrapper,'wait_for_prior_window',side_effect=waited),\
            patch.object(self.wrapper,'generate',side_effect=fresh):
            result,status=self.call_main(Path(temp))
            self.assertFalse((Path(temp)/'output').exists())
        self.assertEqual(events,['wait','generate']);self.assertEqual(result,0)
        self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],0)

    def test_main_wait_hold_never_invokes_generate_or_creates_capture_directory(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(self.wrapper,'wait_for_prior_window',
            side_effect=ValueError('JRA_FUTURE_SOURCE_WAIT_PRIOR_NOT_TERMINAL')) as wait,\
            patch.object(self.wrapper,'generate') as generate:
            _,status=self.call_main(Path(temp))
            self.assertFalse((Path(temp)/'output').exists())
            self.assertFalse((Path(temp)/'output.jra-cache').exists())
        wait.assert_called_once();generate.assert_not_called()
        self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],0)

    def test_main_readbacks_bypass_wait_and_generation(self):
        for args,method in ((['--readback-source','801'],'readback_source'),
            (['--readback-source','801','--readback-native','800'],'readback')):
            with self.subTest(method=method),tempfile.TemporaryDirectory() as temp,\
                patch.object(self.wrapper,'wait_for_prior_window') as wait,patch.object(self.wrapper,'generate') as generate,\
                patch.object(self.wrapper,method,return_value=dict(ready=False,source_requests=0)) as readback:
                result,_=self.call_main(Path(temp),*args)
            self.assertEqual(result,0);wait.assert_not_called();generate.assert_not_called();readback.assert_called_once()


if __name__=='__main__':unittest.main()
