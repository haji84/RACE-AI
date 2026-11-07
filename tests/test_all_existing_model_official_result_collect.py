"""Invented collector epochs: no provider, real owner key, Git or Actions."""
import base64
from copy import deepcopy
from datetime import datetime,timedelta
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from contextlib import redirect_stdout
from race_ai import all_existing_model_official_results as results
from race_ai.boat_all_model_store import seal_forecasts,open_forecasts
from race_ai.manual_official_capture import TERMS_SCHEMA,official_rights_ref
from race_ai.jra_official_result_adapter import parse_result
from tests import test_jra_official_result_adapter as jra

KEY=bytes(range(32));HEAD='a'*40
b64=lambda raw:base64.b64encode(raw).decode()

class Clock:
    def __init__(self,now):self.value=now;self.sleeps=[]
    def now(self):return self.value
    def sleep(self,seconds):self.sleeps.append(seconds);self.value+=timedelta(seconds=seconds)
class Response(io.BytesIO):
    def __init__(self,raw,url,status=200):
        super().__init__(raw);self.url=url;self.status=status
        self.headers={'Content-Type':'text/html; charset=shift_jis','Content-Length':str(len(raw))}
    def geturl(self):return self.url

class OfficialResultCollectorTests(unittest.TestCase):
    def setUp(self):
        self.api=importlib.import_module('scripts.all_existing_model_official_result_collect')
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name);self.root.chmod(0o700)
        self.repo=self.root/'repo';self.repo.mkdir();self.clock=Clock(jra.NOW)
        owner=patch.dict(os.environ,RACE_AI_STATE_KEY=b64(KEY));owner.start();self.addCleanup(owner.stop)
        self.native=json.loads(json.dumps(jra.frozen()).replace('SYNTHETIC_PERSONAL_SOURCE',official_rights_ref('horse')))
        self.day='2026-11-07';self.card_url=self.native['source_evidence'][0]['source_ref']
        self.result_url=jra.URL.replace('pw01sde10','pw01sde01')
        self.card=jra.sparse_fixtures.card()+('<a href="'+self.result_url+'">結果</a>').encode('cp932')
        self.calls=[];self.bodies={self.card_url:self.card,self.result_url:jra.result_html()}
        self.env=dict(run_id=42,head_sha=HEAD,temp=self.root)
        self.native_pin=dict(id=700,digest='sha256:'+'b'*64,run_id=41,head_sha='c'*40)
        self.case=dict(sport='horse',race_id=self.native['snapshot']['race']['race_id'],route=dict(
            kind='JRA_CARD_PUBLISHED_GET',card_url=self.card_url,result_url=None,link_capture=None))
        self.plan=self.plan_for([self.case]);self.manifest=self.sealed(self.plan)
    def plan_for(self,cases,maximum_requests=32):
        urls=sorted({case['route']['card_url'] if case['sport']=='horse' else case['route']['ui_entry_url'] for case in cases})
        sports=sorted({case['sport'] for case in cases})
        terms=dict(schema=TERMS_SCHEMA,execution_day=self.day,purpose='PRIVATE_FACTUAL_ANALYSIS',public_redistribution=False,
            provider_model_training_permission_confirmed=False,owner_instruction_ref='OWNER_INSTRUCTION_20261107_ALL_MODELS',terms=[])
        for sport in sports:
            host={'horse':'www.jra.go.jp','autorace':'autorace.jp','keirin':'keirin.jp'}[sport]
            terms['terms'].append(dict(sport=sport,terms_url='https://'+host+'/fixture-policy',policy_sha256='d'*64,
                policy_captured_at=self.day+'T00:00:00+09:00',
                source_urls=[url for url in urls if host in url],uses=['private_retention','private_factual_analysis']))
        return dict(schema=self.api.PLAN,execution_day=self.day,cases=cases,terms_manifest=terms,
            maximum_requests=maximum_requests,result_wait_seconds=120)
    def sealed(self,plan):
        raw=seal_forecasts(plan,run_id='40',round_no=900006,key=KEY);hashed=sha256(raw).hexdigest()
        relative='audit/state/official-result-collection-plan-'+hashed+'.enc';path=self.repo/relative
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        return dict(schema=self.api.SCHEMA,execution_day=self.day,plan_path=relative,plan_sha256=hashed,
            native_artifacts=[self.native_pin],checkpoint_artifacts=[],allow_order_only=False)
    def opener(self,request,timeout):
        self.calls.append((request.full_url,timeout,self.clock.now()));return Response(self.bodies[request.full_url],request.full_url)
    def collect(self,manifest=None,root=None,opener=None):
        with patch.object(self.api,'ROOT',self.repo),patch.object(self.api.freeze,'frozen_inputs',return_value=[self.native]):
            return self.api.collect(self.root/'out' if root is None else root,self.env,self.manifest if manifest is None else manifest,
                clock=self.clock.now,sleeper=self.clock.sleep,opener=self.opener if opener is None else opener)
    def checkpoint(self,*,pending=False,expired=False,special=False):
        raw=jra.result_html(table=not pending,places=('1','1','3') if special else ('1','2','3'));metadata=jra.source_metadata(raw)
        observation=parse_result(raw,metadata,frozen_native_payload=self.native,now=jra.NOW,source_rights_ref=official_rights_ref('horse'))
        payload=results.build_result_payload([dict(raw_base64=b64(raw),metadata=metadata)],[observation],run_id=39,code_sha='e'*40,
            generated_at=jra.NOW,day_jst=self.day,frozen_native_payloads=[self.native])
        cipher=results.seal_results(payload,round_no=1,frozen_native_payloads=[self.native],key=KEY)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('results.enc',cipher)
        wire=stream.getvalue();pin=dict(id=800,digest='sha256:'+sha256(wire).hexdigest(),run_id=39,head_sha='e'*40)
        meta=dict(id=800,name='all-existing-official-results-39-1',expired=expired,digest=pin['digest'],size_in_bytes=len(wire),
            created_at=jra.NOW.isoformat(),expires_at=(jra.NOW+timedelta(days=7)).isoformat(),workflow_run=dict(
                id=39,head_sha='e'*40,repository_id=1416489937,head_repository_id=1416489937))
        return pin,meta,wire
    def test_due_case_follows_actual_published_href_and_seals_only_cipher(self):
        status=self.collect();self.assertTrue(status['ready']);self.assertEqual(status['source_requests'],2)
        self.assertEqual([u for u,_,_ in self.calls],[self.card_url,self.result_url])
        self.assertTrue(all(timeout==12 for _,timeout,_ in self.calls));self.assertGreaterEqual(sum(self.clock.sleeps),.825)
        output=self.root/'out';self.assertEqual({p.name for p in output.iterdir()},{'results.enc'})
        payload=open_forecasts((output/'results.enc').read_bytes(),key=KEY)
        self.assertEqual(payload['observations'][0]['source_ref'],self.result_url)
        self.assertEqual(payload['observations'][0]['status'],'settled')
        self.assertFalse(status['independent_result_artifact_receipt_verified'])
        journal=open_forecasts((self.root/'out.collection.enc').read_bytes(),key=KEY)
        self.assertEqual(len(journal['attempts']),2);self.assertEqual(len(journal['captures']),2)
        self.assertNotIn(self.result_url,json.dumps(status));self.assertNotIn('raw_base64',json.dumps(status))
    def test_future_and_wait_margin_cases_make_zero_source_requests(self):
        cutoff=datetime.fromisoformat(self.native['snapshot']['race']['sales_cutoff_at'])
        self.clock.value=cutoff+timedelta(seconds=119)
        status=self.collect();self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],0)
        self.assertEqual(self.calls,[])
    def test_confirmed_checkpoint_is_skipped_and_expired_checkpoint_holds_before_source(self):
        for expired in (False,True):
            pin,meta,wire=self.checkpoint(expired=expired);manifest=dict(self.manifest,checkpoint_artifacts=[pin])
            with patch.object(self.api.future,'metadata',return_value=meta),patch.object(self.api.future,'gh',return_value=wire):
                if expired:
                    with self.assertRaises(ValueError):self.collect(manifest,root=self.root/'expired')
                else:
                    status=self.collect(manifest,root=self.root/'confirmed');self.assertFalse(status['ready'])
                    self.assertEqual(status['confirmed_case_count'],1)
        self.assertEqual(self.calls,[])
    def test_pending_checkpoint_allows_later_real_result_and_request_limit_stops(self):
        pin,meta,wire=self.checkpoint(pending=True)
        with patch.object(self.api.future,'metadata',return_value=meta),patch.object(self.api.future,'gh',return_value=wire):
            status=self.collect(dict(self.manifest,checkpoint_artifacts=[pin]))
        self.assertTrue(status['ready']);self.assertEqual(len(self.calls),2)
        self.calls=[];manifest=self.sealed(self.plan_for([self.case],maximum_requests=1))
        status=self.collect(manifest,root=self.root/'bounded');self.assertFalse(status['ready'])
        self.assertEqual(status['source_requests'],1)

    def test_special_checkpoint_is_skipped_without_counting_as_an_eighth_normal_case(self):
        pin,meta,wire=self.checkpoint(special=True)
        with patch.object(self.api.future,'metadata',return_value=meta),patch.object(self.api.future,'gh',return_value=wire):
            status=self.collect(dict(self.manifest,checkpoint_artifacts=[pin]))
        self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],0)
        self.assertEqual(status['confirmed_case_count'],1)
        self.assertEqual(status['normal_confirmed_cases_by_sport'],{'horse':0})
        self.assertFalse(status['normal_eight_case_requirement_met']);self.assertEqual(self.calls,[])
    def test_absent_or_foreign_href_is_not_replaced_with_a_guessed_url(self):
        self.bodies[self.card_url]=jra.sparse_fixtures.card()+b'<a href="https://bad.invalid/result">wrong</a>'
        status=self.collect();self.assertFalse(status['ready']);self.assertEqual(len(self.calls),1)
        self.assertEqual(status['no_published_link_case_count'],1)
    def test_denial_and_corrupt_owner_plan_never_trigger_fallback_requests(self):
        def denied(request,timeout):self.calls.append(request.full_url);return Response(b'denied',request.full_url,403)
        status=self.collect(opener=denied);self.assertFalse(status['ready']);self.assertEqual(len(self.calls),1)
        self.assertEqual(status['denied_source_count'],1)
        bad=dict(self.manifest,plan_sha256='f'*64)
        with self.assertRaises(ValueError):self.collect(bad,root=self.root/'bad')
        self.assertEqual(len(self.calls),1)

    def test_actual_result_zip_readback_reuses_original_cipher_and_queries_no_provider(self):
        status=self.collect();output=self.root/'out'
        proof=dict(status,schema=self.api.STATUS,workflow_run_id=42,expected_head_sha=HEAD)
        self.api._write(output.with_name('out.generation.json'),self.api.future.wire(proof))
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('results.enc',(output/'results.enc').read_bytes())
        raw=stream.getvalue();saved=self.clock.now();self.clock.value+=timedelta(seconds=1)
        metadata=dict(id=900,name='all-existing-official-results-42-900005',expired=False,
            digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),created_at=saved.isoformat(),
            expires_at=(saved+timedelta(days=7)).isoformat(),workflow_run=dict(id=42,head_sha=HEAD,
                repository_id=1416489937,head_repository_id=1416489937))
        with patch.object(self.api,'ROOT',self.repo),patch.object(self.api.freeze,'frozen_inputs',return_value=[self.native]), \
                patch.object(self.api.future,'metadata',return_value=metadata),patch.object(self.api.future,'gh',return_value=raw):
            read=self.api.readback(900,output,self.env,self.manifest,clock=self.clock.now)
            self.assertTrue(read['independent_result_artifact_receipt_verified'])
            self.assertEqual(read['source_requests'],0);self.assertEqual(read['collection_source_requests'],2)
            journal=output.with_name('out.collection.enc');journal.write_bytes(journal.read_bytes()[:-1]+b'x')
            with self.assertRaises(Exception):self.api.readback(900,output,self.env,self.manifest,clock=self.clock.now)
        self.assertEqual(len(self.calls),2)

    def test_wrong_published_case_empty_response_and_existing_epoch_stay_unconfirmed(self):
        self.bodies[self.card_url]=self.card.replace(b'1120261107/AA',b'1020261107/AA')
        status=self.collect();self.assertFalse(status['ready']);self.assertEqual(len(self.calls),1)
        with self.assertRaisesRegex(ValueError,'UNCERTAIN_PRIOR_EPOCH'):
            self.collect()
        self.calls=[]
        status=self.collect(root=self.root/'empty',opener=lambda request,timeout:Response(b'',request.full_url))
        self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],1)

    def test_manifest_and_plan_authentication_happen_before_any_source_get(self):
        for change in ({'allow_order_only':1},{'execution_day':'2026-11-06'},
                       {'native_artifacts':[]},{'checkpoint_artifacts':[self.native_pin]}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.collect(dict(self.manifest,**change),root=self.root/'invalid')
        with patch.dict(os.environ,RACE_AI_STATE_KEY=''),self.assertRaises(ValueError):self.collect()
        self.assertEqual(self.calls,[])

    def test_clock_regression_before_first_request_cannot_access_a_future_case(self):
        cutoff=datetime.fromisoformat(self.native['snapshot']['race']['sales_cutoff_at'])
        times=iter([cutoff+timedelta(seconds=120)])
        def regressed():return next(times,cutoff-timedelta(seconds=1))
        with patch.object(self.api,'ROOT',self.repo),patch.object(self.api.freeze,'frozen_inputs',return_value=[self.native]):
            with self.assertRaises(ValueError):
                self.api.collect(self.root/'out',self.env,self.manifest,clock=regressed,sleeper=lambda _:None,opener=self.opener)
        self.assertEqual(self.calls,[])

    def test_literal_result_url_requires_the_original_published_href_body(self):
        metadata=jra.sparse_fixtures.metadata(self.card,self.card_url,
            completed=(self.clock.now()-timedelta(seconds=1)).isoformat())
        metadata['fetched_at']=(self.clock.now()-timedelta(seconds=2)).isoformat()
        case=deepcopy(self.case);case['route'].update(result_url=self.result_url,
            link_capture=dict(raw_base64=b64(self.card),metadata=metadata))
        manifest=self.sealed(self.plan_for([case],maximum_requests=1))
        status=self.collect(manifest);self.assertTrue(status['ready']);self.assertEqual(status['source_requests'],1)
        self.assertEqual([u for u,_,_ in self.calls],[self.result_url])
        case['route']['link_capture']['metadata']['source_sha256']='f'*64
        with self.assertRaises(ValueError):self.collect(self.sealed(self.plan_for([case])),root=self.root/'forged')
        self.assertEqual(len(self.calls),1)

    def test_static_cache_cannot_replay_data_or_forge_original_clocks(self):
        for kind in ('data','future','hash'):
            plan=deepcopy(self.plan);raw=b'const staticFixture=true;';url='https://autorace.jp/js/fixture.js'
            metadata=dict(source_url=url,final_url=url,status=200,http_method='GET',resource_type='script',
                source_sha256=sha256(raw).hexdigest(),byte_count=len(raw),headers={'content-type':'text/javascript'},
                fetched_at=(self.clock.now()-timedelta(seconds=2)).isoformat(),
                response_received_at=(self.clock.now()-timedelta(seconds=1)).isoformat())
            if kind=='data':metadata.update(source_url='https://autorace.jp/race_info/RaceResult',final_url='https://autorace.jp/race_info/RaceResult')
            elif kind=='future':metadata['response_received_at']=(self.clock.now()+timedelta(seconds=1)).isoformat()
            else:metadata['source_sha256']='f'*64
            plan['static_cache']=[dict(raw_base64=b64(raw),metadata=metadata)]
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.collect(self.sealed(plan),root=self.root/kind)
        self.assertEqual(self.calls,[])

    def test_cli_writes_generation_status_and_actions_outputs_without_raw_values(self):
        manifest_path=self.root/'input.json';manifest_path.write_text(json.dumps(self.manifest))
        github_output=self.root/'github-output';original=self.api.collect
        def run(*args,**kwargs):return original(*args,**kwargs,clock=self.clock.now,sleeper=self.clock.sleep,opener=self.opener)
        stdout=io.StringIO()
        with patch.object(self.api,'ROOT',self.repo),patch.object(self.api,'utc_now',side_effect=self.clock.now), \
                patch.object(self.api.future,'environment',return_value=self.env), \
                patch.object(self.api.future,'output_path',return_value=self.root/'out'), \
                patch.object(self.api.freeze,'frozen_inputs',return_value=[self.native]), \
                patch.object(self.api,'collect',side_effect=run),patch.dict(os.environ,GITHUB_OUTPUT=str(github_output)),redirect_stdout(stdout):
            self.assertEqual(self.api.main(['--input',str(manifest_path),'--out-dir',str(self.root/'out')]),0)
        status=json.loads(stdout.getvalue());self.assertTrue(status['ready'])
        self.assertEqual(status['source_requests'],2)
        self.assertTrue((self.root/'out.generation.json').exists());self.assertTrue((self.root/'out.status.json').exists())
        self.assertIn('ready=true\n',github_output.read_text())
        self.assertIn('artifact_name=all-existing-official-results-42-900005\n',github_output.read_text())
        self.assertNotIn(self.result_url,stdout.getvalue());self.assertNotIn('raw_base64',stdout.getvalue())


class BrowserCollectorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=OfficialResultCollectorTests(methodName='runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        from tests import test_autorace_official_result_adapter as auto
        self.auto=auto;self.data=auto.fixture();f=self.fixture
        f.native=self.data['frozen'];f.day='2030-01-15';f.clock=Clock(datetime.fromisoformat('2030-01-15T03:00:00+00:00'))
        f.case=dict(sport='autorace',race_id=f.native['snapshot']['race']['race_id'],route=dict(kind='NORMAL_UI',
            ui_entry_url='https://autorace.jp/race_info/Live/isesaki',ui_venue_name=None,place_code=3))
        f.manifest=f.sealed(f.plan_for([f.case]));f.manifest['allow_order_only']=True;self.seen=[]
    def browser(self,plan,directory):
        self.seen.append(deepcopy(plan));directory.mkdir(mode=0o700);start=self.fixture.clock.now();context=self.data['metadata']['auto_result_context']
        responses=[]
        for sequence,role,raw,original in ((1,'identity',base64.b64decode(context['race_info_capture']['raw_base64']),context['race_info_capture']['metadata']),
                (2,'result',self.auto.wire(self.data['result']),self.data['metadata'])):
            metadata=deepcopy(original);metadata.pop('auto_result_context',None);metadata.pop('auto_result_archive_context',None)
            metadata.update(method='POST',http_method='POST',resource_type='xhr',
                fetched_at=(start+timedelta(seconds=sequence-.2)).isoformat(),response_received_at=(start+timedelta(seconds=sequence)).isoformat())
            request=base64.b64decode(context['request_body_base64'])
            for name,body in ((f'r{sequence}.body',raw),(f'r{sequence}.json',json.dumps(metadata).encode()),(f'q{sequence}.body',request)):
                path=directory/name;path.write_bytes(body);path.chmod(0o600)
            responses.append(dict(sequence=sequence,body_file=f'r{sequence}.body',metadata_file=f'r{sequence}.json',request_body_file=f'q{sequence}.body'))
        body=base64.b64decode(context['rendered_dom_capture']['raw_base64']);path=directory/'dom.html';path.write_bytes(body);path.chmod(0o600)
        dom=dict(context['rendered_dom_capture']['metadata'],file='dom.html',captured_at=(start+timedelta(seconds=3)).isoformat())
        self.fixture.clock.value=start+timedelta(seconds=4)
        return dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1',started_at=start.isoformat(),completed_at=self.fixture.clock.now().isoformat(),
            actual_request_count=2,normal_ui_only=True,manual_api_requests=0,stop_reason='FINISHED',responses=responses,
            ledger=[dict(sequence=n,status=200,request_started_at=(start+timedelta(seconds=n-.2)).isoformat(),
                headers_received_at=(start+timedelta(seconds=n)).isoformat()) for n in (1,2)],cases=[dict(
                sport='autorace',race_id=plan['cases'][0]['race_id'],state='CAPTURED',responses=[dict(role='identity',sequence=1),dict(role='result',sequence=2)],
                rendered_dom=dom,browser_metadata={})])
    def run_collect(self,maximum=None):
        f=self.fixture
        if maximum is not None:f.manifest=f.sealed(f.plan_for([f.case],maximum_requests=maximum));f.manifest['allow_order_only']=True
        with patch.object(f.api,'ROOT',f.repo),patch.object(f.api.freeze,'frozen_inputs',return_value=[f.native]):
            return f.api.collect(f.root/'out',f.env,f.manifest,clock=f.clock.now,sleeper=f.clock.sleep,browser=self.browser)
    def test_actual_http_request_files_replay_to_typed_order_and_aes_result(self):
        status=self.run_collect();self.assertTrue(status['ready']);self.assertEqual(status['source_requests'],2)
        self.assertEqual(self.seen[0]['request_budget'],32)
        payload=open_forecasts((self.fixture.root/'out/results.enc').read_bytes(),key=KEY)
        self.assertEqual(payload['observations'][0]['status'],'rank_confirmed')
        self.assertIsNone(payload['observations'][0]['payout_per_100_yen'])
        self.assertEqual(payload['captures'][0]['metadata']['source_url'],'https://autorace.jp/race_info/RaceResult')
    def test_browser_cannot_exceed_remaining_budget_or_turn_unknown_attempts_into_zero(self):
        status=self.run_collect(maximum=1)
        self.assertFalse(status['ready']);self.assertIsNone(status['source_requests'])
        self.assertEqual(self.seen[0]['request_budget'],1);self.assertEqual(status['source_requests_upper_bound'],1)

    def test_node_inherits_transport_trust_but_not_owner_or_git_credentials(self):
        from types import SimpleNamespace
        f=self.fixture;directory=f.root/'fake-browser';directory.mkdir(mode=0o700)
        path=directory/'capture-index.json';path.write_text('{"schema":"fixture-index"}');path.chmod(0o600)
        values=dict(HTTPS_PROXY='http://fixture.proxy:80',http_proxy='http://fixture.proxy:80',NO_PROXY='localhost',
            SSL_CERT_FILE='/fixture/ca.pem',NODE_EXTRA_CA_CERTS='/fixture/ca.pem',REQUESTS_CA_BUNDLE='/fixture/ca.pem',
            GH_TOKEN='fixture-token',GITHUB_TOKEN='fixture-token',GIT_CONFIG_VALUE_0='fixture-git-secret')
        with patch.dict(os.environ,values),patch.object(f.api.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            actual=f.api.browser_capture({'schema':'fixture-plan'},directory)
        self.assertEqual(actual,{'schema':'fixture-index'});environment=run.call_args.kwargs['env']
        for name in ('RACE_AI_STATE_KEY','GH_TOKEN','GITHUB_TOKEN','GIT_CONFIG_VALUE_0'):self.assertNotIn(name,environment)
        for name in ('HTTPS_PROXY','http_proxy','NO_PROXY','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS','REQUESTS_CA_BUNDLE'):
            self.assertEqual(environment[name],values[name])

    def test_timeout_keeps_durable_started_attempt_count_and_never_resets_same_epoch(self):
        f=self.fixture
        def interrupted(plan,directory):
            directory.mkdir(mode=0o700);started=f.clock.now();f.clock.value+=timedelta(seconds=1)
            checkpoint=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_REQUEST_CHECKPOINT_V1',
                started_at=started.isoformat(),last_updated_at=f.clock.now().isoformat(),actual_request_count=5,
                maximum_requests=plan['request_budget'],ledger=[])
            path=directory/'request-ledger-005.json';path.write_text(json.dumps(checkpoint));path.chmod(0o600)
            with patch.object(f.api.subprocess,'run',side_effect=f.api.subprocess.TimeoutExpired('node',100)):
                return f.api.browser_capture(plan,directory)
        with patch.object(f.api,'ROOT',f.repo),patch.object(f.api.freeze,'frozen_inputs',return_value=[f.native]):
            status=f.api.collect(f.root/'out',f.env,f.manifest,clock=f.clock.now,sleeper=f.clock.sleep,browser=interrupted)
            self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],5)
            self.assertEqual(status['source_request_count_semantics'],'STARTED_OR_DURABLY_RESERVED_ATTEMPTS')
            with self.assertRaisesRegex(ValueError,'UNCERTAIN_PRIOR_EPOCH'):
                f.api.collect(f.root/'out',f.env,f.manifest,clock=f.clock.now,sleeper=f.clock.sleep,browser=interrupted)

    def test_changed_result_schema_is_quarantined_with_original_response_bytes(self):
        self.data['result']['body'].pop('refundInfo');self.auto.reseal_result(self.data)
        status=self.run_collect();self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],2)
        journal=open_forecasts((self.fixture.root/'out.collection.enc').read_bytes(),key=KEY)
        self.assertEqual(journal['cases'][0]['state'],'HOLD_RESULT_PARSE')
        self.assertEqual(len(journal['browser_captures']),2)
        main=next(x for x in journal['browser_captures'] if x['metadata']['source_url'].endswith('/RaceResult'))
        self.assertEqual(base64.b64decode(main['raw_base64']),self.auto.wire(self.data['result']))
        self.assertEqual(main['metadata']['source_sha256'],sha256(base64.b64decode(main['raw_base64'])).hexdigest())

    def test_rejected_response_roles_keep_bounded_count_and_encrypted_failure_detail(self):
        original=self.browser
        def repeated(plan,directory):
            index=original(plan,directory)
            index['cases'][0]['responses'].append(dict(role='identity',sequence=1))
            return index
        self.browser=repeated;status=self.run_collect();self.assertFalse(status['ready'])
        self.assertEqual(status['source_requests'],2)
        journal=open_forecasts((self.fixture.root/'out.collection.enc').read_bytes(),key=KEY)
        self.assertEqual(journal['browser_attempt']['state'],'REJECTED')
        self.assertEqual(journal['browser_attempt']['actual_request_count'],2)
        self.assertEqual(journal['browser_failure']['stage'],'SOURCE_VALIDATION')
        self.assertEqual(journal['browser_failure']['error_code'],'ALL_MODEL_OFFICIAL_COLLECT_BROWSER_CASE_RESPONSES')
        self.assertIn('browser_quarantine',journal)
        self.assertTrue(journal['browser_quarantine']['complete'])
        preserved={f['file']:base64.b64decode(f['raw_base64']) for f in journal['browser_quarantine']['files']}
        self.assertEqual(preserved['r2.body'],self.auto.wire(self.data['result']))
        self.assertEqual(preserved['q2.body'],base64.b64decode(self.data['metadata']['auto_result_context']['request_body_base64']))
        self.assertTrue(journal['browser_index']['diagnostic_projection_only'])
        self.assertEqual([r['role'] for r in journal['browser_index']['cases'][0]['responses']],['identity','result','identity'])
        self.assertNotIn('browser_failure',json.dumps(status))

    def test_contradictory_index_zero_with_real_response_references_stays_unknown(self):
        original=self.browser
        def contradictory(plan,directory):
            index=original(plan,directory);index['actual_request_count']=0
            index['cases'][0]['responses'].append(dict(role='identity',sequence=1));return index
        self.browser=contradictory;status=self.run_collect();self.assertIsNone(status['source_requests'])
        journal=open_forecasts((self.fixture.root/'out.collection.enc').read_bytes(),key=KEY)
        self.assertEqual(journal['browser_attempt']['state'],'RESERVED')
        self.assertEqual(journal['browser_failure']['stage'],'INDEX_VALIDATION')

    def test_oversized_quarantine_retains_inventory_but_never_grants_result_authority(self):
        original=self.browser
        def oversized(plan,directory):
            index=original(plan,directory);path=directory/'r1.body'
            path.write_bytes(b'x'*(2*1024*1024+1));return index
        self.browser=oversized;status=self.run_collect();self.assertFalse(status['ready'])
        journal=open_forecasts((self.fixture.root/'out.collection.enc').read_bytes(),key=KEY)
        self.assertIn('browser_quarantine',journal);quarantine=journal['browser_quarantine']
        self.assertFalse(quarantine['complete']);self.assertEqual(len(quarantine['inventory_sha256']),64)
        self.assertEqual(journal['browser_attempt']['state'],'REJECTED')
        self.assertEqual(journal['browser_failure']['stage'],'QUARANTINE')
        self.assertLess(len(json.dumps(journal)),12*1024*1024)
        self.assertFalse((self.fixture.root/'out/results.enc').exists())

    def test_process_failure_never_trusts_stdout_zero_or_persists_secret_stderr(self):
        from types import SimpleNamespace
        f=self.fixture;secret=b'https://fixture.invalid?sig=PRIVATE_SAS_AND_KEY'
        def failed(plan,directory):
            process=SimpleNamespace(returncode=1,stdout=b'{"state":"HOLD","actual_request_count":0}\n',stderr=secret)
            with patch.object(f.api.subprocess,'run',return_value=process):
                return f.api.browser_capture(plan,directory)
        self.browser=failed;status=self.run_collect();self.assertFalse(status['ready']);self.assertIsNone(status['source_requests'])
        journal=open_forecasts((f.root/'out.collection.enc').read_bytes(),key=KEY)
        self.assertEqual(journal['browser_attempt']['state'],'RESERVED')
        self.assertIn('browser_process_diagnostic',journal)
        process=journal['browser_process_diagnostic']
        self.assertEqual(process['returncode'],1);self.assertEqual(process['stdout_reported_actual_request_count'],0)
        self.assertFalse(process['stdout_request_count_authoritative'])
        self.assertEqual(process['stderr_sha256'],sha256(secret).hexdigest())
        self.assertNotIn('PRIVATE_SAS_AND_KEY',json.dumps(journal));self.assertNotIn('fixture.invalid',json.dumps(journal))
        self.assertNotIn('browser_process_diagnostic',json.dumps(status))

class JournalResumeCollectorTests(OfficialResultCollectorTests):
    def v2(self,prior=()):
        return dict(self.manifest,schema=self.api.SCHEMA_V2,prior_journal_artifacts=list(prior))
    def journal_archive(self,journal=None,*,expired=False):
        path=self.root/'out.collection.enc'
        cipher=path.read_bytes() if journal is None else seal_forecasts(journal,run_id='42',round_no=900006,key=KEY)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('out.collection.enc',cipher)
        raw=stream.getvalue();pin=dict(id=990,digest='sha256:'+sha256(raw).hexdigest(),run_id=42,head_sha=HEAD)
        meta=dict(id=990,name='official-result-collection-journal-42',expired=expired,digest=pin['digest'],size_in_bytes=len(raw),
            created_at=self.clock.now().isoformat(),expires_at=(self.clock.now()+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=42,head_sha=HEAD,repository_id=1416489937,head_repository_id=1416489937))
        return pin,meta,raw
    def test_v2_first_epoch_binds_original_manifest_and_local_journal_origin(self):
        manifest=self.v2();status=self.collect(manifest);self.assertTrue(status['ready'])
        journal=open_forecasts((self.root/'out.collection.enc').read_bytes(),key=KEY)
        self.assertEqual(journal['schema'],self.api.JOURNAL_V2)
        self.assertEqual(journal['manifest'],manifest);self.assertEqual(journal['manifest_sha256'],self.api.digest(manifest))
        self.assertEqual(journal['workflow_run_id'],42);self.assertEqual(journal['code_sha'],HEAD)
        self.assertEqual(status['prior_journal_artifact_count'],0)
    def test_recent_epoch_holds_before_new_source_and_normal_old_epoch_can_resume(self):
        manifest=self.v2();self.collect(manifest);pin,meta,raw=self.journal_archive();self.calls=[]
        next_manifest=self.v2([pin]);self.clock.value+=timedelta(seconds=1)
        with patch.object(self.api.future,'metadata',return_value=meta),patch.object(self.api.future,'gh',return_value=raw):
            with self.assertRaisesRegex(ValueError,'PRIOR_EPOCH_TOO_RECENT'):
                self.collect(next_manifest,root=self.root/'next')
            self.clock.value+=timedelta(seconds=3600)
            summary=self.api.prior_journals(next_manifest,now=self.clock.now(),key=KEY)
        self.assertEqual(self.calls,[]);self.assertEqual(summary['prior_journal_artifact_count'],1)
    def test_denied_or_uncertain_journal_never_restarts_after_an_hour(self):
        self.collect(self.v2());base=open_forecasts((self.root/'out.collection.enc').read_bytes(),key=KEY)
        for kind in ('denied','reserved','browser_interrupted'):
            journal=deepcopy(base)
            if kind=='denied':journal['attempts'][0].update(state='DENIED',http_status=429)
            elif kind=='reserved':journal['attempts'][0].update(state='RESERVED')
            else:journal['browser_attempt']=dict(state='INTERRUPTED',reserved_request_limit=30,actual_request_count=5)
            pin,meta,raw=self.journal_archive(journal);self.calls=[];self.clock.value+=timedelta(seconds=3601)
            with patch.object(self.api.future,'metadata',return_value=meta),patch.object(self.api.future,'gh',return_value=raw):
                with self.subTest(kind=kind),self.assertRaises(ValueError):
                    self.api.prior_journals(self.v2([pin]),now=self.clock.now(),key=KEY)
            self.assertEqual(self.calls,[])
    def test_complete_browser_requires_known_wire_outcomes_and_matching_count(self):
        self.collect(self.v2());base=open_forecasts((self.root/'out.collection.enc').read_bytes(),key=KEY)
        at=self.clock.now().isoformat()
        base['browser_attempt']=dict(state='COMPLETE',actual_request_count=1,reserved_request_limit=30,
            started_at=at,completed_at=at,stop_reason='FINISHED')
        base['browser_index']=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1',started_at=at,completed_at=at,
            actual_request_count=1,stop_reason='FINISHED',stopped_host=False,normal_ui_only=True,manual_api_requests=0,
            ledger=[dict(sequence=1,status=200,request_started_at=at,headers_received_at=at)])
        self.clock.value+=timedelta(seconds=3601)
        for change in ('valid','missing_status','count_conflict','denied_stop','late_index_clock'):
            body=deepcopy(base)
            if change=='missing_status':body['browser_index']['ledger'][0].pop('status')
            elif change=='count_conflict':body['browser_index']['actual_request_count']=2
            elif change=='denied_stop':body['browser_index']['stop_reason']='HTTP_ACCESS_DENIED'
            elif change=='late_index_clock':body['browser_index']['completed_at']=(self.clock.now()+timedelta(seconds=1)).isoformat()
            pin,meta,raw=self.journal_archive(body)
            with patch.object(self.api.future,'metadata',return_value=meta),patch.object(self.api.future,'gh',return_value=raw):
                if change=='valid':self.api.prior_journals(self.v2([pin]),now=self.clock.now(),key=KEY)
                else:
                    with self.subTest(change=change),self.assertRaises(ValueError):
                        self.api.prior_journals(self.v2([pin]),now=self.clock.now(),key=KEY)
    def test_journal_original_manifest_hash_run_head_and_cipher_header_cannot_be_rebound(self):
        self.collect(self.v2());base=open_forecasts((self.root/'out.collection.enc').read_bytes(),key=KEY)
        self.calls=[];self.clock.value+=timedelta(seconds=3601)
        for change in ('run','head','manifest','plan','future_epoch','header_run','header_round','legacy_origin'):
            journal=deepcopy(base);run='42';round_no=900006
            if change=='run':journal['workflow_run_id']=43
            elif change=='head':journal['code_sha']='f'*40
            elif change=='manifest':journal['manifest_sha256']='f'*64
            elif change=='plan':journal['collection_plan_sha256']='f'*64
            elif change=='future_epoch':journal['epoch_started_at']=(self.clock.now()+timedelta(seconds=1)).isoformat()
            elif change=='header_run':run='43'
            elif change=='header_round':round_no=900005
            elif change=='legacy_origin':journal['schema']=self.api.JOURNAL
            cipher=seal_forecasts(journal,run_id=run,round_no=round_no,key=KEY)
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('collection.enc',cipher)
            raw=stream.getvalue();pin,meta,_=self.journal_archive(journal)
            pin['digest']='sha256:'+sha256(raw).hexdigest();meta.update(digest=pin['digest'],size_in_bytes=len(raw))
            with patch.object(self.api.future,'metadata',return_value=meta),patch.object(self.api.future,'gh',return_value=raw):
                with self.subTest(change=change),self.assertRaises(ValueError):
                    self.api.prior_journals(self.v2([pin]),now=self.clock.now(),key=KEY)
        self.assertEqual(self.calls,[])
    def test_journal_actual_metadata_origin_expiry_and_cipher_are_required(self):
        self.collect(self.v2());pin,meta,raw=self.journal_archive();self.clock.value+=timedelta(seconds=3601)
        for change in ({'name':'official-result-collection-journal-43'},{'expired':True},{'digest':'sha256:'+'f'*64},
                {'workflow_run':dict(meta['workflow_run'],repository_id=1)}):
            with patch.object(self.api.future,'metadata',return_value=dict(meta,**change)),patch.object(self.api.future,'gh',return_value=raw):
                with self.subTest(change=change),self.assertRaises(ValueError):
                    self.api.prior_journals(self.v2([pin]),now=self.clock.now(),key=KEY)
    def test_v2_journal_upload_name_survives_collection_failure_for_always_upload(self):
        manifest=self.v2();path=self.root/'v2.json';path.write_text(json.dumps(manifest));github=self.root/'outputs'
        with patch.object(self.api,'ROOT',self.repo),patch.object(self.api,'utc_now',side_effect=self.clock.now), \
                patch.object(self.api.future,'environment',return_value=self.env), \
                patch.object(self.api.future,'output_path',return_value=self.root/'out'), \
                patch.object(self.api,'collect',side_effect=ValueError('ALL_MODEL_OFFICIAL_COLLECT_SOURCE_CLOCK')), \
                patch.dict(os.environ,GITHUB_OUTPUT=str(github)),redirect_stdout(io.StringIO()):
            self.api.main(['--input',str(path),'--out-dir',str(self.root/'out')])
        self.assertIn('journal_artifact_name=official-result-collection-journal-42',github.read_text())
        self.assertIn('ready=false',github.read_text());self.assertEqual(self.calls,[])
    def test_cli_denied_epoch_journal_upload_and_readback_keep_results_unready(self):
        manifest=self.v2();path=self.root/'v2.json';path.write_text(json.dumps(manifest));github=self.root/'outputs'
        original=self.api.collect
        def denied(request,timeout):return Response(b'denied',request.full_url,403)
        def run(*args,**kwargs):return original(*args,**kwargs,clock=self.clock.now,sleeper=self.clock.sleep,opener=denied)
        with patch.object(self.api,'ROOT',self.repo),patch.object(self.api,'utc_now',side_effect=self.clock.now), \
                patch.object(self.api.future,'environment',return_value=self.env), \
                patch.object(self.api.future,'output_path',return_value=self.root/'out'), \
                patch.object(self.api.freeze,'frozen_inputs',return_value=[self.native]), \
                patch.object(self.api,'collect',side_effect=run),patch.dict(os.environ,GITHUB_OUTPUT=str(github)),redirect_stdout(io.StringIO()):
            self.api.main(['--input',str(path),'--out-dir',str(self.root/'out')])
            pin,meta,raw=self.journal_archive();self.clock.value+=timedelta(seconds=1)
            with patch.object(self.api.future,'metadata',return_value=meta),patch.object(self.api.future,'gh',return_value=raw):
                self.api.main(['--input',str(path),'--out-dir',str(self.root/'out'),'--readback-journal-artifact','990'])
        status=json.loads((self.root/'out.status.json').read_text())
        self.assertFalse(status['ready']);self.assertFalse(status['independent_result_artifact_receipt_verified'])
        self.assertTrue(status['independent_journal_artifact_receipt_verified']);self.assertEqual(status['source_requests'],0)
        self.assertEqual(status['journal_artifact_name'],'official-result-collection-journal-42')
        self.assertIn('journal_artifact_name=official-result-collection-journal-42',github.read_text())
        self.assertFalse((self.root/'out.generation.json').exists())
        self.assertFalse((self.root/'out/results.enc').exists());self.assertEqual(self.calls,[])
    def test_journal_artifact_readback_works_for_denied_epoch_with_no_result_cipher(self):
        def denied(request,timeout):return Response(b'denied',request.full_url,403)
        manifest=self.v2();status=self.collect(manifest,opener=denied);self.assertFalse(status['ready'])
        pin,meta,raw=self.journal_archive();self.clock.value+=timedelta(seconds=1)
        with patch.object(self.api,'ROOT',self.repo),patch.object(self.api.future,'metadata',return_value=meta), \
                patch.object(self.api.future,'gh',return_value=raw):
            verified=self.api.readback_journal(990,self.root/'out',self.env,manifest,clock=self.clock.now)
        self.assertTrue(verified['independent_journal_artifact_receipt_verified'])
        self.assertEqual(verified['source_requests'],0);self.assertEqual(verified['journal_artifact_id'],990)

if __name__=='__main__':unittest.main()
