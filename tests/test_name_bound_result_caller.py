"""Bounded label publication with synthetic sources and actual backup replay."""
import copy
from contextlib import ExitStack, redirect_stdout
from datetime import timedelta
import hashlib
from io import BytesIO, StringIO
import importlib
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tests.test_name_bound_result import label_fixture
from web import name_bound_result as contract
from web.name_bound_evaluation import build_name_bound_evaluation
from web.race_contract import canonical, stamp, _time as instant

COMMIT='a'*40
BASE='https://race-ai-preview-test-qq1130034-1738.vercel.app/api'


class Response(BytesIO):
    def __init__(self,raw,url):
        super().__init__(raw); self.url=url; self.status=200; self.headers={'Content-Type':'application/json'}
    def geturl(self): return self.url


def absent(url,body=None,code=404):
    return HTTPError(url,code,'private',{'Content-Type':'application/json'},BytesIO(canonical(body or {'error':'NAME_BOUND_RESULT_NOT_SAVED'})))


class Opener:
    def __init__(self,bodies): self.bodies=bodies; self.calls=[]; self.on_open=lambda request:None
    def open(self,request,timeout):
        self.calls.append(request); self.on_open(request)
        body=self.bodies[len(self.calls)-1]
        if isinstance(body,Exception): raise body
        return Response(canonical(body) if not isinstance(body,bytes) else body,request.full_url)


class ResultCallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.c=importlib.import_module('scripts.publish_name_bound_result')
        except ModuleNotFoundError: cls.c=None

    def setUp(self):
        self.assertIsNotNone(self.c,'bounded result caller required')
        self.race,self.forecast,self.result,self.now=label_fixture(contract)
        self.fid=self.forecast['receipt']['request_id']; self.nonce='123500-1'
        self.source_time=instant(self.result['receipt']['snapshot']['parents_read_at'])
        self.runner_time=instant(self.result['receipt']['runner_saved_at'])
        self.latest=BASE+'/name-bound-result?race_id='+self.race['race_id']+'&forecast_request_id='+self.fid
        self.feed=dict(date_jst='2026-10-15',schedule_verified=True,redistribution_authorized=True,
            venues=[dict(venue=f'{n:02}',status='READY' if n==18 else 'NO_EVENT',races=[self.race] if n==18 else []) for n in range(1,25)])
        self.report=build_name_bound_evaluation(self.forecast,contract.result_bundle(self.result,self.race,self.forecast,now=self.now),self.race,self.now)
        import sys
        with patch.object(sys,'path',[str(Path('web').resolve())]+sys.path):
            store=importlib.import_module('api.name_bound_result_store')
        self.meta=dict(store.metadata(self.result,self.race),commit_sha=COMMIT)
        self.bodies=[self.feed,self.forecast,absent(self.latest),self.meta,self.result,self.report]
        self.opener=Opener(self.bodies); self.elapsed=[0]; self.current=[self.source_time]
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.folder=Path(self.tmp.name)/'output'
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(self.c.os.environ,{'RACE_AI_NAME_BOUND_RESULT_PUBLISH_URL':BASE+'/publish-name-bound-result',
            'RACE_AI_NAME_BOUND_RESULT_COMMIT_SHA':COMMIT,'GITHUB_RUN_ID':'123500','GITHUB_RUN_ATTEMPT':'1'}))
        self.stack.enter_context(patch.object(self.c,'utc_now',side_effect=lambda:self.current[0]))
        self.stack.enter_context(patch.object(self.c.time,'monotonic',side_effect=lambda:self.elapsed[0]))
        self.session=self.stack.enter_context(patch.object(self.c,'workflow_session',return_value=(self.opener,{'X-Race-AI-Commit':COMMIT})))
        def collect(race,forecast,**kwargs):
            self.assertEqual(kwargs['parents_read_at'],stamp(self.source_time))
            kwargs['transport']('synthetic',timeout=10,max_bytes=1000000)
            self.current[0]=self.runner_time
            return dict(status='COLLECTED',official_source_requests=1,snapshot=copy.deepcopy(self.result['receipt']['snapshot']))
        self.collect=self.stack.enter_context(patch.object(self.c,'collect_name_bound_result',side_effect=collect))
        self.transport=self.stack.enter_context(patch.object(self.c,'fetch_update',return_value=None))
        def opened(request):
            if request.get_method()=='POST':
                self.assertEqual((self.folder/'request.json').read_bytes(),request.data)
                self.current[0]=self.now
        self.opener.on_open=opened

    def run_caller(self): return self.c.run(self.race['race_id'],self.fid,self.folder,execute=True)
    def retained(self): return json.loads((self.folder/'manifest.json').read_bytes())
    def fresh_bodies(self):return [copy.deepcopy(x) if not isinstance(x,Exception) else absent(self.latest) for x in self.bodies]

    def test_dry_run_zero_filesystem_clocks_auth_and_sources(self):
        with patch.object(self.c,'Path',side_effect=AssertionError('filesystem')),patch.object(self.c.time,'monotonic',side_effect=AssertionError('clock')):
            self.assertIsNone(self.c.run('bad','bad','missing'))
        self.session.assert_not_called(); self.collect.assert_not_called(); self.transport.assert_not_called()

    def test_full_pipeline_exact_counts_preserved_request_links_times_and_full_replay(self):
        manifest=self.run_caller()
        self.assertEqual(manifest['status'],'COMPLETED'); self.assertEqual(manifest,self.retained())
        self.assertEqual((manifest['reads_used'],manifest['posts_attempted'],manifest['official_source_requests'],manifest['max_seconds']),(5,1,1,240))
        self.assertEqual(manifest['operation'],'NAME_BOUND_RESULT_PUBLICATION')
        self.assertEqual([r.get_method() for r in self.opener.calls],['GET','GET','GET','POST','GET','GET'])
        self.assertEqual(self.opener.calls[4].full_url,self.latest+'&request_id='+self.nonce)
        self.assertEqual({p.name for p in self.folder.iterdir()},self.c.ALLOWED)
        request=json.loads((self.folder/'request.json').read_bytes())
        self.assertEqual(request['runner_saved_at'],self.result['receipt']['runner_saved_at'])
        self.assertEqual(request['snapshot'],self.result['receipt']['snapshot'])
        for name in self.c.PAYLOADS:
            raw=(self.folder/name).read_bytes(); self.assertEqual(canonical(json.loads(raw)),raw)
            self.assertEqual(manifest['backups'][name],dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        self.c.verify_backups(self.folder,manifest)

    def test_existing_valid_label_stops_three_gets_without_source_or_post(self):
        self.opener.bodies[2]=self.result; self.current[0]=self.now
        manifest=self.run_caller()
        self.assertEqual((manifest['status'],manifest['reads_used'],manifest['posts_attempted'],manifest['official_source_requests']),('STOPPED',3,0,0))
        self.collect.assert_not_called(); self.transport.assert_not_called()

    def test_only_exact_expected_404_allows_source(self):
        for index,error in enumerate([absent(self.latest,{'error':'AUTH_REQUIRED'}),absent(self.latest,{'error':'NAME_BOUND_RESULT_NOT_SAVED','extra':1}),
                absent(self.latest,code=401),absent(self.latest,code=302),absent(BASE+'/other'),OSError('secret'),b'{',b' '*256001,b'null',{'error':'NAME_BOUND_RESULT_NOT_SAVED'}]):
            self.folder=Path(self.tmp.name)/str(index);self.opener.calls=[];self.opener.bodies=list(self.bodies);self.opener.bodies[2]=error
            with self.subTest(index=index):
                manifest=self.run_caller(); self.assertEqual((manifest['status'],manifest['reads_used'],manifest['posts_attempted']),('STOPPED',3,0))
                self.assertEqual(manifest,self.retained()); self.collect.assert_not_called()

    def test_absence_rejects_duplicate_error_keys_wrong_content_type_and_empty_body(self):
        errors=[HTTPError(self.latest,404,'private',{'Content-Type':'application/json'},BytesIO(b'{"error":"AUTH_REQUIRED","error":"NAME_BOUND_RESULT_NOT_SAVED"}')),
            HTTPError(self.latest,404,'private',{'Content-Type':'text/html'},BytesIO(canonical({'error':'NAME_BOUND_RESULT_NOT_SAVED'}))),
            HTTPError(self.latest,404,'private',{'Content-Type':'application/json'},BytesIO(b''))]
        for index,error in enumerate(errors):
            self.folder=Path(self.tmp.name)/str(index);self.opener.calls=[];self.opener.bodies=list(self.bodies);self.opener.bodies[2]=error
            with self.subTest(index=index):
                manifest=self.run_caller();self.assertEqual((manifest['status'],manifest['reads_used'],manifest['posts_attempted']),('STOPPED',3,0))
                self.assertEqual(self.collect.call_count,0)

    def test_source_pending_failure_and_counted_throw_never_post_or_retry(self):
        for index,status in enumerate(['RESULT_PENDING','SOURCE_INVALID','SOURCE_UNAVAILABLE']):
            self.folder=Path(self.tmp.name)/str(index);self.opener.calls=[];self.opener.bodies=list(self.bodies)
            self.opener.bodies[2]=absent(self.latest)
            def collect(*args,**kwargs):
                kwargs['transport']('synthetic',timeout=10,max_bytes=1000000)
                return dict(status=status,official_source_requests=1)
            self.collect.side_effect=collect
            with self.subTest(status=status):
                manifest=self.run_caller();self.assertEqual((manifest['status'],manifest['official_source_requests'],manifest['posts_attempted']),('STOPPED',1,0))
        self.folder=Path(self.tmp.name)/'throw';self.opener.calls=[];self.opener.bodies=list(self.bodies);self.opener.bodies[2]=absent(self.latest)
        self.transport.side_effect=OSError('secret'); manifest=self.run_caller()
        self.assertEqual((manifest['status'],manifest['official_source_requests'],manifest['posts_attempted']),('STOPPED',1,0))

    def test_post_failure_keeps_exclusive_normalized_request(self):
        self.opener.bodies[3]=OSError('secret transport detail'); manifest=self.run_caller()
        self.assertEqual((manifest['status'],manifest['posts_attempted'],manifest['reads_used']),('STOPPED',1,3))
        self.assertEqual(set(manifest['backups']),{'program.json','forecast.json','request.json'})
        self.assertNotIn('secret',(self.folder/'manifest.json').read_text())
        self.c.verify_backups(self.folder,manifest)

    def test_manifest_callbacks_retain_old_defaults_and_new_inventory(self):
        manifest=self.run_caller();self.assertEqual(manifest['status'],'COMPLETED')
        self.assertIn('request.json',manifest['backups'])

    def test_invalid_config_nonce_and_target_stop_before_directory_or_auth(self):
        for changes in [{'GITHUB_RUN_ID':'0'},{'GITHUB_RUN_ATTEMPT':'0'}, {'RACE_AI_NAME_BOUND_RESULT_COMMIT_SHA':'A'*40},
                {'RACE_AI_NAME_BOUND_RESULT_PUBLISH_URL':BASE+'/race'},
                {'RACE_AI_NAME_BOUND_RESULT_PUBLISH_URL':'https://attacker.example/api/publish-name-bound-result'}]:
            with self.subTest(changes=changes),patch.dict(self.c.os.environ,changes),self.assertRaises(ValueError):self.run_caller()
        for rid,fid in [('20260230-18-01',self.fid),(self.race['race_id'],'../escape')]:
            with self.assertRaises(ValueError):self.c.run(rid,fid,self.folder,execute=True)
        self.session.assert_not_called();self.assertFalse(self.folder.exists())

    def test_current_day_preclose_and_unknown_selected_race_stop_before_sources(self):
        for index,mode in enumerate(['nextday','preclose','missing','duplicate','wrongforecast','wrongparent']):
            self.folder=Path(self.tmp.name)/str(index);self.opener.calls=[];self.opener.bodies=self.fresh_bodies()
            self.current[0]=self.source_time
            if mode=='nextday':self.current[0]=self.now+timedelta(days=1)
            elif mode=='preclose':self.current[0]=instant(self.race['closed_at'])-timedelta(seconds=1)
            elif mode=='missing':self.opener.bodies[0]['venues'][17]['races']=[]
            elif mode=='duplicate':self.opener.bodies[0]['venues'][17]['races'].append(copy.deepcopy(self.race))
            elif mode=='wrongforecast':self.opener.bodies[1]['receipt']['request_id']='123498-1'
            else:self.opener.bodies[1]['baseline']['request_id']='123498-1'
            with self.subTest(mode=mode):
                manifest=self.run_caller();self.assertEqual((manifest['status'],manifest['posts_attempted'],manifest['official_source_requests']),('STOPPED',0,0))
                self.collect.assert_not_called()

    def test_auth_source_post_and_readback_budgets_and_no_retry(self):
        def slow_auth(commit):self.elapsed[0]=241;return self.opener,{}
        self.session.side_effect=slow_auth
        manifest=self.run_caller();self.assertEqual((manifest['status'],manifest['reads_used']),('TIME_LIMIT_REACHED',0))
        self.session.side_effect=OSError('private auth detail');self.elapsed[0]=0;self.folder=Path(self.tmp.name)/'auth'
        manifest=self.run_caller();self.assertEqual((manifest['status'],manifest['reads_used']),('STOPPED',0))
        self.session.side_effect=None
        original=self.opener.on_open
        for index,point in enumerate([1,3,4,5,6]):
            self.folder=Path(self.tmp.name)/('budget'+str(index));self.opener.calls=[];self.opener.bodies=list(self.bodies);self.opener.bodies[2]=absent(self.latest)
            self.elapsed[0]=0;self.current[0]=self.source_time
            def opened(request):
                original(request)
                if len(self.opener.calls)==point:self.elapsed[0]=241
            self.opener.on_open=opened
            with self.subTest(point=point):
                manifest=self.run_caller();self.assertEqual(manifest['status'],'TIME_LIMIT_REACHED')
                self.assertEqual(len(self.opener.calls),point)
        self.opener.on_open=original;self.folder=Path(self.tmp.name)/'source-budget';self.elapsed[0]=0;self.current[0]=self.source_time
        self.opener.calls=[];self.opener.bodies=list(self.bodies);self.opener.bodies[2]=absent(self.latest)
        self.transport.side_effect=lambda *a,**k:self.elapsed.__setitem__(0,241)
        manifest=self.run_caller();self.assertEqual((manifest['status'],manifest['official_source_requests'],manifest['posts_attempted']),('TIME_LIMIT_REACHED',1,0))

    def test_readback_wrong_nonce_parent_report_hash_or_source_cannot_complete(self):
        for index,mode in enumerate(['nonce','snapshot','metadata','scores','physical','truncated','oversize']):
            self.folder=Path(self.tmp.name)/str(index);self.opener.calls=[];self.opener.bodies=self.fresh_bodies();self.current[0]=self.source_time
            if mode=='nonce':self.opener.bodies[4]['receipt']['request_id']='123501-1'
            elif mode=='snapshot':self.opener.bodies[4]['receipt']['snapshot']['forecast_link']['envelope_sha256']='0'*64
            elif mode=='metadata':self.opener.bodies[3]['sha256']='0'*64
            elif mode=='scores':self.opener.bodies[5]['models'][0]['log_loss']+=1
            elif mode=='physical':self.opener.bodies[5]['physical_exhibition_timing_verified']=True
            elif mode=='truncated':self.opener.bodies[4]=b'{'
            else:self.opener.bodies[4]=b' '*256001
            with self.subTest(mode=mode):
                manifest=self.run_caller();self.assertEqual(manifest['status'],'STOPPED')
                self.assertEqual(manifest['posts_attempted'],1);self.assertLessEqual(manifest['reads_used'],5)
                self.assertNotIn('evaluation.json',manifest['backups'])

    def test_restore_rejects_every_payload_change_even_after_rehash(self):
        manifest=self.run_caller();original={p.name:p.read_bytes() for p in self.folder.iterdir()}
        mutations={'program.json':lambda v:v.update(race_id='20261015-18-02'),
            'forecast.json':lambda v:v['name_binding']['receipt'].update(request_id='123498-1'),
            'request.json':lambda v:v.update(runner_saved_at=stamp(self.now)),
            'result.json':lambda v:v['finalization'].update(receipt_confirmed_at=stamp(self.now+timedelta(seconds=1))),
            'evaluation.json':lambda v:v['models'][0].update(log_loss=0)}
        for name,mutate in mutations.items():
            with self.subTest(name=name):
                bad=copy.deepcopy(manifest);value=json.loads(original[name]);mutate(value);raw=canonical(value)
                (self.folder/name).write_bytes(raw);bad['backups'][name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
                (self.folder/'manifest.json').write_bytes(canonical(bad))
                with self.assertRaises(ValueError):self.c.verify_backups(self.folder,bad)
                for item,raw in original.items():(self.folder/item).write_bytes(raw)
        self.c.verify_backups(self.folder,manifest)

    def test_restore_rejects_literal_types_schema_counters_coverage_and_identity(self):
        manifest=self.run_caller()
        for field,value in [('schema_version',True),('max_seconds',240.0),('reads_used',True),('reads_used',4),
                ('posts_attempted',False),('official_source_requests',False),('request_id','123501-1'),('forecast_request_id','123498-1'),
                ('operation','OTHER'),('commit_sha','A'*40),('extra',1),('backups',{}),('failure_reason','OTHER')]:
            bad=dict(manifest,**{field:value});(self.folder/'manifest.json').write_bytes(canonical(bad))
            with self.subTest(field=field),self.assertRaises(ValueError):self.c.verify_backups(self.folder,bad)
        (self.folder/'manifest.json').write_bytes(canonical(manifest)+b'\n')
        with self.assertRaises(ValueError):self.c.verify_backups(self.folder,manifest)

    def test_full_replay_keeps_report_asof_and_only_60second_remote_allowance(self):
        self.report['as_of']=stamp(self.now+timedelta(seconds=60));self.opener.bodies[5]=self.report
        manifest=self.run_caller();self.assertEqual(manifest['status'],'COMPLETED')
        self.assertEqual(json.loads((self.folder/'evaluation.json').read_bytes())['as_of'],self.report['as_of'])
        for point in [self.now+timedelta(seconds=60,microseconds=1),self.now+timedelta(days=1)]:
            self.folder=Path(self.tmp.name)/str(point.microsecond);self.opener.calls=[];self.opener.bodies=list(self.bodies);self.opener.bodies[2]=absent(self.latest)
            self.opener.bodies[5]=dict(self.report,as_of=stamp(point));self.current[0]=self.source_time
            with self.subTest(point=point):self.assertEqual(self.run_caller()['status'],'STOPPED')

    def test_actual_partial_write_inventory_and_exclusive_files(self):
        original=self.c.write_checked
        def partial(folder,name,value):
            if name=='request.json':(folder/name).write_bytes(b'{"truncated":');raise OSError('private')
            return original(folder,name,value)
        with patch.object(self.c,'write_checked',side_effect=partial):manifest=self.run_caller()
        self.assertEqual(manifest['status'],'STOPPED');self.assertEqual(manifest['posts_attempted'],0)
        self.c.verify_backups(self.folder,manifest)
        with self.assertRaises(ValueError):self.run_caller()
        before=(self.folder/'program.json').read_bytes()
        with self.assertRaises(FileExistsError):self.c.write_checked(self.folder,'program.json',{})
        self.assertEqual((self.folder/'program.json').read_bytes(),before)
        for name,value in [('raw.html',{}),('evaluation.json',{'x':'x'*256000})]:
            with self.assertRaises(ValueError):self.c.write_checked(self.folder,name,value)

    def test_final_close_errors_delays_and_late_verification_persist_failed(self):
        original=Path.open
        for mode,expected in [('close','STOPPED'),('delay','TIME_LIMIT_REACHED'),('read','TIME_LIMIT_REACHED')]:
            self.folder=Path(self.tmp.name)/mode;self.opener.calls=[];self.opener.bodies=list(self.bodies);self.opener.bodies[2]=absent(self.latest);self.current[0]=self.source_time;self.elapsed[0]=0
            caller=self
            class Handle:
                def __init__(self,handle):self.handle=handle
                def __enter__(self):return self
                def __getattr__(self,name):return getattr(self.handle,name)
                def read(self,*args):
                    raw=self.handle.read(*args)
                    if mode=='read' and b'"status":"COMPLETED"' in raw:caller.elapsed[0]=241
                    return raw
                def __exit__(self,*args):
                    result=self.handle.__exit__(*args)
                    if mode=='close':raise OSError('private final close')
                    if mode=='delay':caller.elapsed[0]=241
                    return result
            def faulty(path,*args,**kwargs):
                handle=original(path,*args,**kwargs)
                return Handle(handle) if path.name=='manifest.json' and args and args[0]=='x+b' else handle
            with self.subTest(mode=mode),patch.object(Path,'open',faulty):manifest=self.run_caller()
            self.assertEqual(manifest['status'],expected);self.assertEqual(manifest,self.retained())

    def test_failed_final_replay_and_inventory_persist_stopped_before_error(self):
        def fail(folder,manifest):
            (folder/'request.json').write_bytes(b'x'*256001);raise ValueError('private')
        with patch.object(self.c,'verify_backups',side_effect=fail),self.assertRaises(ValueError):self.run_caller()
        self.assertEqual(self.retained()['status'],'STOPPED')

    def test_final_close_recovery_does_not_replace_foreign_manifest(self):
        original=Path.open;retained=Path(self.tmp.name)/'owned.json'
        class Handle:
            def __init__(self,handle,path):self.handle=handle;self.path=path
            def __enter__(self):return self
            def __getattr__(self,name):return getattr(self.handle,name)
            def __exit__(self,*args):
                self.handle.__exit__(*args);self.path.rename(retained);self.path.write_bytes(b'foreign');raise OSError('private')
        def replaced(path,*args,**kwargs):
            handle=original(path,*args,**kwargs)
            return Handle(handle,path) if path.name=='manifest.json' and args and args[0]=='x+b' else handle
        with patch.object(Path,'open',replaced),self.assertRaises(ValueError):self.run_caller()
        self.assertEqual((self.folder/'manifest.json').read_bytes(),b'foreign')

    def test_inventory_rejects_symlink_before_following_payload_or_manifest(self):
        self.run_caller();original=Path.is_symlink
        for name in ['request.json','manifest.json']:
            def link(path):return True if path==self.folder/name else original(path)
            with self.subTest(name=name),patch.object(Path,'is_symlink',link),self.assertRaises(ValueError):self.c.inventory(self.folder)

    def test_wall_clock_rollback_and_budget_reservations_stop_further_work(self):
        self.opener.on_open=lambda request:self.current.__setitem__(0,self.source_time-timedelta(microseconds=1))
        manifest=self.run_caller();self.assertEqual((manifest['status'],manifest['reads_used']),('STOPPED',1))
        self.folder=Path(self.tmp.name)/'reservation';self.current[0]=self.source_time;self.opener.calls=[]
        self.opener.on_open=lambda request:self.elapsed.__setitem__(0,211)
        manifest=self.run_caller();self.assertEqual((manifest['status'],manifest['reads_used']),('TIME_LIMIT_REACHED',1))

    def test_workflow_is_manual_and_replays_all_six_files(self):
        workflow=Path('.github/workflows/boat-blob-e2e.yml').read_text()
        self.assertIn('name-bound-result]',workflow)
        tail=workflow[workflow.index('      - name: Publish bounded name-bound official result'):]
        condition=re.search(r'^        if: (.+)$',tail,re.M).group(1)
        for event,mode,want in [('push','name-bound-result',False),('workflow_dispatch','name-bound-result',True),('workflow_dispatch','result',False)]:
            expr=condition.replace('github.event_name',repr(event)).replace('inputs.collection',repr(mode)).replace('&&','and')
            self.assertEqual(eval(expr,{'__builtins__':{}},{}),want)
        self.assertIn('name: name-bound-result-${{ github.run_id }}-${{ github.run_attempt }}',tail)
        self.assertIn('retention-days: 14',tail)
        for block in re.findall(r"python - <<'PY'\n(.*?)^          PY",workflow,re.M|re.S): compile(textwrap.dedent(block),'<workflow>','exec')
        self.run_caller();root=Path(self.tmp.name)
        shutil.copytree(self.folder,root/'race-ai-name-bound-result');shutil.copytree(self.folder,root/'race-ai-name-bound-result-restored')
        block=textwrap.dedent(tail.split("python - <<'PY'\n",1)[1].split('          PY',1)[0])
        with patch.dict(self.c.os.environ,{'RUNNER_TEMP':str(root)}),redirect_stdout(StringIO()):exec(compile(block,'<workflow>','exec'),{})
        (root/'race-ai-name-bound-result-restored'/'request.json').write_bytes(b'changed')
        with patch.dict(self.c.os.environ,{'RUNNER_TEMP':str(root)}),self.assertRaises(SystemExit):exec(compile(block,'<workflow>','exec'),{})


if __name__=='__main__': unittest.main()
