"""Bounded read-only verification with synthetic API and filesystem faults."""
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

from tests.test_name_bound_evaluation import fixture
from web.name_bound_evaluation import build_name_bound_evaluation
from web.race_contract import canonical, stamp, JST

COMMIT = 'a'*40
BASE = 'https://race-ai-preview-test-qq1130034-1738.vercel.app/api'
FIELDS = set('schema_version status failure_reason race_id forecast_request_id commit_sha backups reads_used posts_attempted official_source_requests max_seconds validation_status purchase_decision purchase_recommendations'.split())


class Response(BytesIO):
    def __init__(self, raw, url):
        super().__init__(raw); self.url=url; self.status=200; self.headers={'Content-Type':'application/json'}
    def geturl(self): return self.url


class Opener:
    def __init__(self, bodies): self.bodies=bodies; self.calls=[]; self.on_open=lambda count:None
    def open(self, request, timeout):
        if request.get_method()!='GET' or request.data is not None: raise AssertionError('no POST allowed')
        self.calls.append((request.full_url,timeout,dict(request.header_items())))
        self.on_open(len(self.calls))
        body=self.bodies[len(self.calls)-1]
        if isinstance(body,Exception): raise body
        return Response(body,request.full_url)


class EvaluationCallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.c=importlib.import_module('scripts.verify_name_bound_evaluation')
        except ModuleNotFoundError: cls.c=None
        cls.args=fixture()

    def setUp(self):
        self.assertIsNotNone(self.c,'bounded name-bound evaluation caller required')
        self.race,self.forecast,self.result,self.now=copy.deepcopy(self.args)
        self.nonce=self.forecast['receipt']['request_id']
        self.report=build_name_bound_evaluation(self.forecast,self.result,self.race,self.now)
        self.feed=dict(date_jst='2026-10-15',schedule_verified=True,redistribution_authorized=True,
            venues=[dict(venue=f'{n:02}',status='READY' if n==18 else 'NO_EVENT',races=[self.race] if n==18 else []) for n in range(1,25)])
        self.bodies=[canonical(x) for x in (self.feed,self.forecast,self.result,self.report)]
        self.opener=Opener(self.bodies); self.elapsed=[0]
        self.folder_context=TemporaryDirectory(); self.addCleanup(self.folder_context.cleanup)
        self.folder=Path(self.folder_context.name)/'output'
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(self.c.os.environ,{'RACE_AI_NAME_BOUND_EVALUATION_URL':BASE+'/name-bound-evaluation','RACE_AI_NAME_BOUND_EVALUATION_COMMIT_SHA':COMMIT}))
        self.stack.enter_context(patch.object(self.c,'utc_now',return_value=self.now))
        self.stack.enter_context(patch.object(self.c.time,'monotonic',side_effect=lambda:self.elapsed[0]))
        self.session=self.stack.enter_context(patch.object(self.c,'workflow_session',return_value=(self.opener,{'X-Race-AI-Commit':COMMIT})))

    def run_caller(self):
        return self.c.run(self.race['race_id'],self.nonce,self.folder,execute=True)

    def retained(self): return json.loads((self.folder/'manifest.json').read_bytes())

    def test_dry_run_touches_neither_paths_clocks_nor_auth(self):
        with patch.object(self.c,'Path',side_effect=AssertionError('filesystem')),patch.object(self.c.time,'monotonic',side_effect=AssertionError('clock')):
            self.assertIsNone(self.c.run('bad','bad','missing'))
        self.session.assert_not_called()

    def test_success_exact_four_gets_limits_and_full_artifact_replay(self):
        result=self.run_caller()
        self.assertEqual(set(result),FIELDS)
        self.assertEqual(result['status'],'COMPLETED')
        self.assertIsNone(result['failure_reason'])
        self.assertEqual(result,self.retained())
        self.assertEqual((result['reads_used'],result['posts_attempted'],result['official_source_requests'],result['max_seconds']),(4,0,0,180))
        self.assertEqual([x[0] for x in self.opener.calls],[BASE+'/today',BASE+'/name-bound-exhibition?race_id='+self.race['race_id']+'&request_id='+self.nonce,
            BASE+'/race?race_id='+self.race['race_id'],BASE+'/name-bound-evaluation?race_id='+self.race['race_id']+'&forecast_request_id='+self.nonce])
        self.assertTrue(all(timeout==30 and headers['X-race-ai-commit']==COMMIT for _,timeout,headers in self.opener.calls))
        self.assertEqual({p.name for p in self.folder.iterdir()},self.c.ALLOWED)
        for name,value in [('program.json',self.race),('forecast.json',self.forecast),('result.json',self.result),('evaluation.json',self.report)]:
            raw=(self.folder/name).read_bytes()
            self.assertEqual(raw,canonical(value))
            self.assertEqual(result['backups'][name],dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        self.c.verify_backups(self.folder,result)
        self.session.assert_called_once_with(COMMIT)

    def test_malformed_target_commit_race_or_nonce_stops_before_auth(self):
        for url,commit,race,nonce in [(BASE+'/race',COMMIT,self.race['race_id'],self.nonce),
            ('https://attacker.example/api/name-bound-evaluation',COMMIT,self.race['race_id'],self.nonce),
            (BASE+'/name-bound-evaluation','A'*40,self.race['race_id'],self.nonce),
            (BASE+'/name-bound-evaluation',COMMIT,'20260230-18-01',self.nonce),
            (BASE+'/name-bound-evaluation',COMMIT,self.race['race_id'],'../escape')]:
            with self.subTest(url=url,commit=commit,race=race,nonce=nonce),patch.dict(self.c.os.environ,{'RACE_AI_NAME_BOUND_EVALUATION_URL':url,'RACE_AI_NAME_BOUND_EVALUATION_COMMIT_SHA':commit}):
                with self.assertRaises(ValueError): self.c.run(race,nonce,self.folder,execute=True)
        self.session.assert_not_called(); self.assertFalse(self.folder.exists())

    def test_selected_program_and_exact_nonce_cannot_be_substituted(self):
        for kind in ('missing','duplicate','day','nonce','parent'):
            feed=copy.deepcopy(self.feed); forecast=copy.deepcopy(self.forecast)
            if kind=='missing': feed['venues'][17]['races']=[]
            elif kind=='duplicate': feed['venues'][17]['races'].append(copy.deepcopy(self.race))
            elif kind=='day': feed['date_jst']='2026-10-14'
            elif kind=='nonce': forecast['receipt']['request_id']='123500-1'
            else: forecast['baseline']['request_id']='123500-1'
            self.opener.bodies=[canonical(x) for x in (feed,forecast,self.result,self.report)]
            self.opener.calls=[]; self.folder=Path(self.folder_context.name)/kind
            with self.subTest(kind=kind):
                result=self.run_caller(); self.assertEqual(result['status'],'STOPPED')
                self.assertLessEqual(result['reads_used'],2)
                self.assertEqual(result,self.retained())

    def test_missing_result_stops_after_three_gets_and_retains_prior_proofs(self):
        self.opener.bodies[2]=b'null'
        result=self.run_caller()
        self.assertEqual((result['status'],result['reads_used']),('STOPPED',3))
        self.assertEqual(set(result['backups']),{'program.json','forecast.json'})
        self.assertEqual(len(self.opener.calls),3)

    def test_transport_truncation_oversize_and_malformed_report_are_not_retried(self):
        for kind,raw in [('truncated',b'{'),('oversize',b' '*256001),('http',OSError('credential-detail')),
                ('score',canonical(dict(self.report,models=[]))),('extra',canonical(dict(self.report,raw_source='secret')))]:
            self.opener.bodies=list(self.bodies); self.opener.bodies[3]=raw
            self.opener.calls=[]; self.folder=Path(self.folder_context.name)/kind
            with self.subTest(kind=kind):
                result=self.run_caller()
                self.assertEqual((result['status'],result['reads_used']),('STOPPED',4))
                self.assertEqual(len(self.opener.calls),4)
                self.assertNotIn('credential-detail',(self.folder/'manifest.json').read_text())
                self.assertNotIn('evaluation.json',result['backups'])
        self.opener.calls=[]; self.opener.bodies=list(self.bodies); self.opener.bodies[0]=b' '*6000001
        self.folder=Path(self.folder_context.name)/'large-day'
        self.assertEqual(self.run_caller()['reads_used'],1)

    def test_replay_preserves_actual_asof_and_rejects_future_midnight_or_tampering(self):
        args=(self.report,self.forecast,self.result,self.race,self.nonce,self.now)
        before=copy.deepcopy(args)
        self.c.verify_response(*args); self.assertEqual(args,before)
        for change in ({'as_of':'2026-10-15T00:45:00.000001+00:00'}, {'as_of':'2026-10-16T00:00:00.000000+00:00'},
                {'schema_version':True}, {'physical_exhibition_timing_verified':True}, {'forecast_proof':{}}):
            with self.subTest(change=change),self.assertRaises(ValueError): self.c.verify_response(dict(self.report,**change),*args[1:])
        with self.assertRaises(ValueError): self.c.verify_response(*args[:-1],self.now.replace(tzinfo=None))

    def test_remote_report_clock_allows_exactly_60_seconds_without_rewriting(self):
        remote=dict(self.report,as_of=stamp(self.now+timedelta(seconds=60)))
        before=copy.deepcopy(remote)
        try: checked=self.c.verify_response(remote,self.forecast,self.result,self.race,self.nonce,self.now)
        except ValueError: self.fail('exact 60-second remote report clock skew must be accepted')
        self.assertEqual(checked,before)
        self.assertEqual(remote,before)
        over=dict(self.report,as_of=stamp(self.now+timedelta(seconds=60,microseconds=1)))
        with self.assertRaises(ValueError): self.c.verify_response(over,self.forecast,self.result,self.race,self.nonce,self.now)
        near_midnight=self.now.astimezone(JST).replace(hour=23,minute=59,second=59)
        next_day=dict(self.report,as_of=stamp(near_midnight+timedelta(seconds=2)))
        with self.assertRaises(ValueError): self.c.verify_response(next_day,self.forecast,self.result,self.race,self.nonce,near_midnight)

    def test_180_second_budget_includes_auth_and_each_get(self):
        self.assertTrue(issubclass(self.c.BudgetExhausted,RuntimeError))
        def slow_auth(commit): self.elapsed[0]=181; return self.opener,{}
        self.session.side_effect=slow_auth
        result=self.run_caller()
        self.assertEqual((result['status'],result['reads_used']),('TIME_LIMIT_REACHED',0))
        self.session.side_effect=None; self.elapsed[0]=0; self.folder=Path(self.folder_context.name)/'get-delay'
        self.opener.on_open=lambda count:self.elapsed.__setitem__(0,181)
        result=self.run_caller()
        self.assertEqual((result['status'],result['reads_used']),('TIME_LIMIT_REACHED',1))

    def test_budget_reservation_and_midnight_prevent_further_gets(self):
        self.opener.on_open=lambda count:self.elapsed.__setitem__(0,151)
        result=self.run_caller()
        self.assertEqual((result['status'],result['reads_used']),('TIME_LIMIT_REACHED',1))
        self.elapsed[0]=0; self.opener.on_open=lambda count:None; self.opener.calls=[]
        self.folder=Path(self.folder_context.name)/'midnight'
        with patch.object(self.c,'utc_now',return_value=self.now.replace(day=16)):
            result=self.run_caller()
        self.assertEqual((result['status'],result['reads_used']),('STOPPED',0))

    def test_output_directory_and_every_payload_are_exclusive(self):
        self.folder.mkdir(); (self.folder/'manifest.json').write_bytes(b'user-owned')
        with self.assertRaises((ValueError,FileExistsError)): self.run_caller()
        self.assertEqual((self.folder/'manifest.json').read_bytes(),b'user-owned')
        self.session.assert_not_called()
        path=Path(self.folder_context.name)
        self.c.write_checked(path,'program.json',{'a':1})
        with self.assertRaises(FileExistsError): self.c.write_checked(path,'program.json',{})
        for name,value in [('raw.html',{}),('evaluation.json',{'x':'x'*256000})]:
            with self.assertRaises(ValueError): self.c.write_checked(path,name,value)

    def test_partial_write_residual_is_inventoried_without_normalization(self):
        original=self.c.write_checked
        def partial(folder,name,value):
            if name=='forecast.json':
                (folder/name).write_bytes(b'{"truncated":')
                raise OSError('credential-detail')
            return original(folder,name,value)
        with patch.object(self.c,'write_checked',side_effect=partial): result=self.run_caller()
        self.assertEqual(result['status'],'STOPPED')
        raw=(self.folder/'forecast.json').read_bytes()
        self.assertEqual(result['backups']['forecast.json'],dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        self.c.verify_backups(self.folder,result)

    def test_manifest_literal_types_coverage_and_complete_replay(self):
        manifest=self.run_caller()
        for field,value in [('schema_version',True),('reads_used',True),('max_seconds',180.0),('posts_attempted',False),
                ('official_source_requests',False),('commit_sha','A'*40),('extra',1),('backups',{})]:
            with self.subTest(field=field),self.assertRaises(ValueError): self.c.verify_backups(self.folder,dict(manifest,**{field:value}))
        report=copy.deepcopy(self.report); report['models'][0]['log_loss']+=1
        raw=canonical(report); (self.folder/'evaluation.json').write_bytes(raw)
        manifest['backups']['evaluation.json']=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        (self.folder/'manifest.json').write_bytes(canonical(manifest))
        with self.assertRaises(ValueError): self.c.verify_backups(self.folder,manifest)
        (self.folder/'raw.html').write_bytes(b'raw')
        with self.assertRaises(ValueError): self.c.verify_backups(self.folder,manifest)

    def test_completed_backups_require_all_five_files_and_canonical_manifest_readback(self):
        manifest=self.run_caller()
        path=self.folder/'manifest.json'; path.unlink()
        with self.assertRaises(ValueError): self.c.verify_backups(self.folder,manifest)
        path.write_bytes(canonical(manifest)+b'\n')
        with self.assertRaises(ValueError): self.c.verify_backups(self.folder,manifest)
        path.write_bytes(canonical(manifest)); self.c.verify_backups(self.folder,manifest)
        (self.folder/'program.json').unlink()
        with self.assertRaises(ValueError): self.c.verify_backups(self.folder,manifest)

    def test_late_manifest_readback_cannot_retain_completed(self):
        original_open=Path.open
        elapsed=self.elapsed
        class LateHandle:
            def __init__(self,handle): self.handle=handle
            def __enter__(self): return self
            def __exit__(self,*args): return self.handle.__exit__(*args)
            def __getattr__(self,name): return getattr(self.handle,name)
            def read(self,*args):
                raw=self.handle.read(*args)
                if b'"status":"COMPLETED"' in raw: elapsed[0]=181
                return raw
        def delayed(path,*args,**kwargs):
            handle=original_open(path,*args,**kwargs)
            return LateHandle(handle) if path.name=='manifest.json' and args and args[0]=='x+b' else handle
        with patch.object(Path,'open',delayed): result=self.run_caller()
        self.assertEqual(result['status'],'TIME_LIMIT_REACHED')
        self.assertEqual(result,self.retained())

    def test_final_verification_failure_and_failed_inventory_persist_stopped_first(self):
        original=self.c.verify_backups
        def fail(folder,manifest):
            if manifest['status']=='COMPLETED':
                (folder/'forecast.json').write_bytes(b'x'*256001)
                raise ValueError('oversize residual')
            return original(folder,manifest)
        with patch.object(self.c,'verify_backups',side_effect=fail):
            with self.assertRaises(ValueError): self.run_caller()
        self.assertEqual(self.retained()['status'],'STOPPED')
        self.assertEqual(self.retained()['failure_reason'],'NAME_BOUND_EVALUATION_STOPPED')

    def test_workflow_manual_guard_and_full_restore_block_execute(self):
        workflow=Path('.github/workflows/boat-blob-e2e.yml').read_text()
        tail=workflow[workflow.index('      - name: Verify frozen name-bound evaluation'):]
        condition=re.search(r'^        if: (.+)$',tail,re.M).group(1)
        for event,mode,want in [('push','name-bound-evaluation',False),('workflow_dispatch','name-bound-evaluation',True),('workflow_dispatch','result',False)]:
            expression=condition.replace('github.event_name',repr(event)).replace('inputs.collection',repr(mode)).replace('&&','and')
            self.assertEqual(eval(expression,{'__builtins__':{}},{}),want)
        self.assertNotIn('--race-id ${{',tail)
        self.assertIn('--forecast-request-id "$RACE_AI_NAME_BOUND_FORECAST_REQUEST_ID"',tail)
        self.assertIn('retention-days: 14',tail)
        self.assertIn("name_bound_forecast_request_id:\n",workflow)
        for block in re.findall(r"python - <<'PY'\n(.*?)^          PY",workflow,re.M|re.S):
            compile(textwrap.dedent(block),'<workflow>','exec')
        block=textwrap.dedent(tail.split("python - <<'PY'\n",1)[1].split('          PY',1)[0])
        manifest=self.run_caller()
        root=Path(self.folder_context.name)
        original=root/'race-ai-name-bound-evaluation'; restored=root/'race-ai-name-bound-evaluation-restored'
        shutil.copytree(self.folder,original); shutil.copytree(self.folder,restored)
        with patch.dict(self.c.os.environ,{'RUNNER_TEMP':str(root)}),redirect_stdout(StringIO()): exec(compile(block,'<workflow>','exec'),{})
        (restored/'evaluation.json').write_bytes(b'changed')
        with patch.dict(self.c.os.environ,{'RUNNER_TEMP':str(root)}),self.assertRaises(SystemExit): exec(compile(block,'<workflow>','exec'),{})


if __name__=='__main__': unittest.main()
