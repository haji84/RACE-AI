import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from scripts import publish_name_bound_exhibition as caller

class CallerTests(unittest.TestCase):
    def test_dry_run_no_io(self):
        self.assertIsNone(caller.run('missing','missing','missing',race_id='bad',name_binding_request_id='bad'))
    def test_budget_is_runtime_error(self):
        self.assertTrue(issubclass(caller.BudgetExhausted, RuntimeError))
    def test_exclusive_bounded_write(self):
        with TemporaryDirectory() as d:
            p=Path(d)
            meta=caller.write_checked(p,'inputs.json',{'a':1})
            self.assertEqual(meta['bytes'],7)
            with self.assertRaises(FileExistsError):caller.write_checked(p,'inputs.json',{})
            with self.assertRaises(ValueError):caller.write_checked(p,'raw.html',{})
    def test_forensic_inventory_replaces_stale_digest(self):
        with TemporaryDirectory() as d:
            p=Path(d);(p/'inputs.json').write_bytes(b'corrupt')
            self.assertEqual(caller.inventory(p)['inputs.json']['bytes'],7)
    def test_bad_nonce_stops_without_transport(self):
        from unittest.mock import patch
        with TemporaryDirectory() as d, patch.object(caller,'workflow_session') as session:
            result=caller.run('missing','missing',Path(d)/'out',race_id='bad',name_binding_request_id='bad',execute=True)
            session.assert_not_called()
            self.assertEqual(result['status'],'STOPPED')
            self.assertEqual(result['official_source_requests'],0)

class FinalManifestTests(unittest.TestCase):
    def check_failure(self,error,status):
        import json
        from unittest.mock import patch
        with TemporaryDirectory() as d:
            folder=Path(d)
            manifest=caller.run('missing','missing',folder/'other',race_id='bad',name_binding_request_id='bad',execute=True)
            folder=folder/'final';folder.mkdir()
            manifest.update(status='COMPLETED',failure_reason=None)
            checked=[]
            def guard():
                checked.append(True)
                raise error
            with patch.object(caller,'verify_backups'):
                result=caller.finalize_manifest(folder,manifest,guard)
            self.assertEqual(result['status'],status)
            retained=json.loads((folder/'manifest.json').read_bytes())
            self.assertEqual(retained,result)
            self.assertNotEqual(retained['status'],'COMPLETED')
            self.assertTrue(checked)
            with self.assertRaises(FileExistsError):caller.finalize_manifest(folder,manifest,lambda:None)
    def test_final_readback_crosses_deadline(self):
        self.check_failure(caller.BudgetExhausted(),'TIME_LIMIT_REACHED')
    def test_final_clock_failure_truthful_manifest(self):
        self.check_failure(ValueError('clock'),'STOPPED')

    def test_cli_failure_exit_two(self):
        import subprocess,sys,os
        with TemporaryDirectory() as d:
            env=dict(os.environ);env.pop('RACE_AI_NAME_BOUND_PUBLISH_URL',None)
            result=subprocess.run([sys.executable,'scripts/publish_name_bound_exhibition.py','--facts-review','missing','--media-review','missing','--output-dir',str(Path(d)/'out'),'--race-id','bad','--name-binding-request-id','bad','--execute'],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,2)
            self.assertIn('"status": "STOPPED"',result.stdout)

class ReplayTests(unittest.TestCase):
    def setUp(self):
        from tests.test_name_bound_store import StoreTests
        self.store=StoreTests();self.store.setUp();self.store.publish()
        self.envelope=self.store.read()
        self.request=self.store.request
    def test_exact_replay_and_metadata_tamper(self):
        from tests.test_name_bound_prediction import NOW
        from copy import deepcopy
        report=dict(self.store.s.metadata(self.envelope,self.store.race),commit_sha='a'*40)
        args=(report,self.envelope,self.request,self.store.race,self.store.base,self.store.binding,'a'*40,NOW)
        caller.verify_response(*args)
        changed=deepcopy(report);changed['research_only']=1
        with self.assertRaises(ValueError):caller.verify_response(changed,*args[1:])
        changed=deepcopy(report);changed['extra']=1
        with self.assertRaises(ValueError):caller.verify_response(changed,*args[1:])
        changed=deepcopy(self.request);changed['request_id']='999-1'
        with self.assertRaises(ValueError):caller.verify_response(report,self.envelope,changed,*args[3:])
    def test_completed_artifacts_full_replay(self):
        with TemporaryDirectory() as d:
            p=Path(d)
            values={'baseline.json':self.store.base,'name-binding.json':self.store.binding,'inputs.json':self.store.inputs,'request.json':self.request,'receipt.json':self.envelope}
            for n,v in values.items():caller.write_checked(p,n,v)
            manifest=dict(schema_version=1,status='COMPLETED',failure_reason=None,race_id=self.store.race['race_id'],request_id=self.request['request_id'],name_binding_request_id=self.request['name_binding_request_id'],commit_sha='a'*40,backups=caller.inventory(p),reads_used=4,posts_attempted=1,official_source_requests=3,max_seconds=240,validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
            caller.verify_backups(p,manifest)
            manifest['reads_used']=True
            with self.assertRaises(ValueError):caller.verify_backups(p,manifest)
    def invoke(self,mode):
        from unittest.mock import patch
        from contextlib import ExitStack
        from tests.test_name_bound_prediction import NOW
        with TemporaryDirectory() as d, ExitStack() as stack:
            folder=Path(d);review=folder/'review.json';review.write_text('{}')
            stack.enter_context(patch.dict(caller.os.environ,{'RACE_AI_NAME_BOUND_PUBLISH_URL':'https://example.vercel.app/api/publish-name-bound-exhibition','RACE_AI_NAME_BOUND_COMMIT_SHA':'a'*40,'GITHUB_RUN_ID':'123499','GITHUB_RUN_ATTEMPT':'1'}))
            stack.enter_context(patch.object(caller,'validate_target'))
            stack.enter_context(patch.object(caller,'utc_now',return_value=NOW))
            stack.enter_context(patch.object(caller,'workflow_session',return_value=(None,{})))
            stack.enter_context(patch.object(caller,'select_race',return_value=(self.store.race,None)))
            calls=[]
            def get(opener,request,**kwargs):
                calls.append(request.full_url)
                if len(calls)==1:return {}
                if len(calls)==2:return self.store.binding
                if len(calls)==3:
                    if mode=='missing':raise RuntimeError('missing')
                    return self.store.base
                raise AssertionError('unexpected network')
            stack.enter_context(patch.object(caller,'get_json',side_effect=get))
            def collect(*args,**kwargs):
                if mode=='budget':raise caller.BudgetExhausted()
                return {'status':'DISPLAY_PENDING'}
            source=stack.enter_context(patch.object(caller,'collect_name_bound_inputs',side_effect=collect))
            result=caller.run(review,review,folder/'out',race_id=self.store.race['race_id'],name_binding_request_id=self.request['name_binding_request_id'],execute=True)
            if mode=='missing':source.assert_not_called()
            self.assertIn('&request_id='+self.request['baseline_request_id'],calls[2])
            self.assertEqual(result['reads_used'],3)
            self.assertEqual(result['posts_attempted'],0)
            return result
    def test_missing_parent_stops_before_source(self):
        self.assertEqual(self.invoke('missing')['status'],'STOPPED')
    def test_budget_exhaustion_keeps_distinct_status(self):
        self.assertEqual(self.invoke('budget')['status'],'TIME_LIMIT_REACHED')
    def test_source_partial_stops_without_post(self):
        self.assertEqual(self.invoke('partial')['status'],'STOPPED')

    def test_workflow_python_compiles_and_mode_is_manual(self):
        import textwrap
        workflow=Path('.github/workflows/boat-blob-e2e.yml').read_text()
        tail=workflow[workflow.index('      - name: Publish bounded name-bound'):]
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.collection == 'name-bound-exhibition'",tail)
        self.assertNotIn('--race-id ${{',tail)
        self.assertIn('retention-days: 14',tail)
        block=tail.split("python - <<'PY'\n",1)[1].split('          PY',1)[0]
        compile(textwrap.dedent(block),'<workflow>','exec')

if __name__=='__main__':unittest.main()
