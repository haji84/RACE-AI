"""Injected source transport, real parser/AES/Git fixtures; not live receipts.

The thirty-cell admission boundary is tested separately with real full ZIPs.
Here an authored admitted context isolates capture, failure and readback wiring.
"""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from contextlib import redirect_stdout

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import open_forecasts
from tests.test_official_future_horse_result import fixture as horse_fixture
from tests.test_jra_official_result_adapter import NOW
from tests.test_all_existing_model_official_result_collect import Clock,Response
from tests.test_official_issue_transport import FakeGitHub,PARENT
from tests.test_all_existing_model_future_source_history import _metadata
from tests.test_all_existing_model_future_result_capture import KEY


def fixture():
    from race_ai import all_existing_model_future_result_capture as core
    case,native,card,result=horse_fixture();day='2026-11-07'
    cases=[dict(sport='autorace',race_id='autorace:'+day+':isesaki:1',route=dict(kind='NORMAL_UI',
        ui_entry_url='https://autorace.jp/race_info/Live/isesaki',ui_venue_name=None,place_code=3)),
        dict(sport='keirin',race_id='keirin:'+day+':keirin-jyo-48:1',route=dict(kind='NORMAL_UI',
        ui_entry_url='https://keirin.jp/pc/top',ui_venue_name=None)),case]
    pin=lambda n:dict(id=n,digest='sha256:'+str(n)*64,run_id=10,head_sha='b'*40)
    terms=dict(schema='RACE_AI_MANUAL_OFFICIAL_TERMS_V1',execution_day=day,purpose='PRIVATE_FACTUAL_ANALYSIS',
        public_redistribution=False,provider_model_training_permission_confirmed=False,
        owner_instruction_ref='AUTHORED_TEST_ONLY',terms=[dict(sport=c['sport'],terms_url={
            'horse':'https://www.jra.go.jp/use/','autorace':'https://autorace.jp/policy/','keirin':'https://keirin.jp/pc/dfw/portal/guest/policy/index.html'}[c['sport']],
            policy_sha256='c'*64,policy_captured_at='2026-11-06T00:00:00Z',
            source_urls=[c['route'].get('card_url',c['route'].get('ui_entry_url'))],uses=['private_retention','private_factual_analysis']) for c in cases])
    manifest=dict(schema=core.SCHEMA,execution_day=day,target_event_day=day,forecast_artifact=pin(1),origin_artifact=pin(2),
        cases=cases,terms_manifest=terms,prior_journal_artifacts=[pin(3)],maximum_requests=32,allow_order_only=True)
    info=dict(race_cutoff_at=native['snapshot']['race']['sales_cutoff_at'])
    admitted=dict(records=[dict(training=dict(scope='OPERATOR_SUPPLIED_RESEARCH'))],natives=[native],
        cases=[dict(case=c,native_payload=native,identity=dict(info,race_id=c['race_id'])) for c in cases],
        forecast_identity=dict(authored_test_context=True))
    history=dict(bodies={},receipts={},runs=[],old_source_requests_actual=None,old_source_requests_upper_bound=32,
        old_browser_outcome='UNKNOWN')
    return manifest,admitted,history,card,result


def zipped(root):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.iterdir()):archive.writestr(path.name,path.read_bytes())
    return stream.getvalue()


class FutureResultCaptureCliTests(unittest.TestCase):
    def setUp(self):
        from scripts import all_existing_model_future_result_capture as api
        self.api=api;temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)/'capture'
        self.manifest,self.admitted,self.history,self.card,self.result=fixture();self.clock=Clock(NOW)
        self.env=dict(run_id=42,head_sha='a'*40,run_attempt=1,temp=self.root.parent);self.server=FakeGitHub();self.transport=api.core.MarkerTransport(self.server)
        self.calls=[]
        values={k:v for k,v in os.environ.items() if k!='NODE_PATH'};values['RACE_AI_STATE_KEY']=base64.b64encode(KEY).decode()
        environment=patch.dict(os.environ,values,clear=True);environment.start();self.addCleanup(environment.stop)
        for name,value in (('_admit',(self.admitted,dict(source_input_receipts_verified=True))),):
            active=patch.object(api,name,return_value=value);active.start();self.addCleanup(active.stop)
        for name,value in (('history',self.history),('static_cache',[])):
            active=patch.object(api.common,name,return_value=value);active.start();self.addCleanup(active.stop)
        active=patch.object(api.core,'bind_source_history',return_value=dict(authored_test_source_history_join=True))
        active.start();self.addCleanup(active.stop)
    def browser(self,plan,directory,**_):
        directory.mkdir(mode=0o700);now=self.clock.now().isoformat()
        index=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1',started_at=now,completed_at=now,
            actual_request_count=0,normal_ui_only=True,manual_api_requests=0,responses=[],ledger=[],cases=[],stop_reason='FINISHED')
        path=directory/'capture-index.json';path.write_text(json.dumps(index));path.chmod(0o600);return index
    def opener(self,request,timeout):
        self.calls.append(request.full_url);capture=self.card if request.full_url==self.card['metadata']['source_url'] else self.result
        return Response(base64.b64decode(capture['raw_base64']),request.full_url)
    def generate(self,**kw):
        return self.api.generate(self.manifest,self.root,self.env,marker_transport=self.transport,clock=self.clock.now,
            browser=kw.pop('browser',self.browser),opener=kw.pop('opener',self.opener),sleeper=self.clock.sleep,**kw)
    def test_existing_result_purpose_blocks_before_forecast_or_source_and_never_resets(self):
        self.server.snapshots[PARENT][self.api.core.PATH]=b'old-unknown';self.server._commit(PARENT,self.server.snapshots[PARENT])
        with self.assertRaisesRegex(ValueError,'ALREADY_CONSUMED'):self.generate()
        self.api._admit.assert_not_called();self.assertFalse(self.root.exists());self.assertEqual(self.calls,[])
    def test_missing_actual_forecast_holds_before_consumption_or_browser(self):
        self.api._admit.side_effect=ValueError('NO_ACTUAL_THIRTY_FORECAST')
        with self.assertRaisesRegex(ValueError,'NO_ACTUAL'):self.generate()
        self.assertFalse(self.root.exists());self.assertEqual(self.calls,[])
        self.assertNotIn(self.api.core.PATH,self.server.snapshots[self.transport.head()])
    def test_injected_empty_ui_and_real_horse_parser_seal_and_dual_actual_zip_readback(self):
        status=self.generate();self.assertTrue(status['ready']);self.assertEqual(status['source_requests'],2)
        self.assertEqual(len(self.calls),2);self.assertEqual(status['result_observation_count'],1)
        source_raw=zipped(self.root/'source');result_raw=zipped(self.root/'result');saved=self.clock.now()+timedelta(seconds=2)
        sm=_metadata(source_raw,500,'official-future-result-capture-42',self.env,saved)
        rm=_metadata(result_raw,501,'all-existing-official-results-42-900030',self.env,saved)
        mapping={500:(source_raw,sm),501:(result_raw,rm)};self.clock.value=saved+timedelta(hours=6)
        with patch.object(self.api.future,'metadata',side_effect=lambda n:mapping[n][1]),\
             patch.object(self.api.future,'gh',side_effect=lambda p:mapping[int(p.split('/')[-2])][0]):
            source_status=self.api.readback_source(500,self.root,self.env,self.manifest,marker_transport=self.transport,clock=self.clock.now)
            final=self.api.readback(501,500,self.root,self.env,self.manifest,marker_transport=self.transport,clock=self.clock.now)
        self.assertTrue(source_status['independent_source_capture_receipt_verified']);self.assertTrue(final['ready'])
        self.assertEqual(final['source_requests'],2);self.assertEqual(len(self.calls),2)
        self.assertTrue(all(p.suffix=='.enc' for folder in ('source','result') for p in (self.root/folder).iterdir()))
        journal=open_forecasts((self.root/'source/collection.enc').read_bytes(),key=KEY)
        self.assertEqual(journal['observations'][0]['status'],'settled');self.assertIsNone(journal['observations'][0]['published_at'])
    def test_no_directory_failure_and_written_reserved_checkpoint_remain_unknown_but_readable(self):
        for written in (False,True):
            if written:
                self.root=self.root.with_name('capture-written');self.server=FakeGitHub();self.transport=self.api.core.MarkerTransport(self.server)
            def interrupted(plan,directory,**_):
                if written:
                    directory.mkdir(mode=0o700);(directory/'request-ledger-001.json').write_text('{"state":"RESERVED"}')
                raise TimeoutError('PRIVATE_ERROR_TOKEN_NEVER_PUBLIC')
            status=self.generate(browser=interrupted);self.assertFalse(status['ready']);self.assertIsNone(status['source_requests'])
            raw=zipped(self.root/'source');actual=_metadata(raw,500,'official-future-result-capture-42',self.env,self.clock.now()+timedelta(seconds=1))
            journal,_,_=self.api.source_archive(raw,actual,self.env,now=self.clock.now()+timedelta(seconds=2),key=KEY)
            self.assertIsNone(journal['source_requests_actual']);self.assertEqual(self.calls,[])
            self.assertNotIn('PRIVATE_ERROR_TOKEN',json.dumps(status));self.assertNotIn('PRIVATE_ERROR_TOKEN',json.dumps(journal))
    def test_denial_stops_horse_and_retains_original_denial_body(self):
        def denied(request,timeout):self.calls.append(request.full_url);return Response(b'private denial body',request.full_url,403)
        status=self.generate(opener=denied);self.assertFalse(status['ready']);self.assertEqual(len(self.calls),1)
        raw=zipped(self.root/'source');actual=_metadata(raw,500,'official-future-result-capture-42',self.env,self.clock.now()+timedelta(seconds=1))
        journal,_,files=self.api.source_archive(raw,actual,self.env,now=self.clock.now()+timedelta(seconds=2),key=KEY)
        self.assertEqual(journal['attempts'][0]['state'],'DENIED');self.assertIn(b'private denial body',files.values())
        self.assertEqual(journal['source_requests_actual'],1)
    def test_expiry_during_spacing_stops_before_any_provider_request(self):
        original=self.clock.sleep
        def sleep(seconds):
            original(seconds);self.clock.value+=timedelta(hours=2)
        self.clock.sleep=sleep
        status=self.generate();self.assertFalse(status['ready']);self.assertEqual(len(self.calls),0)
        journal=open_forecasts((self.root/'source/collection.enc').read_bytes(),key=KEY)
        self.assertIsNone(journal['source_requests_actual'])
        self.assertEqual(journal['attempts'][-1]['http_status'],None)
    def test_unbound_horse_card_fails_before_consumption_and_any_source(self):
        self.admitted['cases'][-1]['native_payload']=json.loads(json.dumps(self.admitted['cases'][-1]['native_payload']).replace(
            self.card['metadata']['source_url'],'https://www.jra.go.jp/other-source'))
        with self.assertRaisesRegex(ValueError,'FROZEN_CARD_SOURCE_BINDING'):self.generate()
        self.assertEqual(self.calls,[]);self.assertFalse(self.root.exists())
    def test_opened_response_body_timeout_is_unknown_and_never_full_raw_retention(self):
        class TimeoutBody(Response):
            def read(self,*_):raise TimeoutError('authored body timeout')
        def timeout(request,timeout):self.calls.append(request.full_url);return TimeoutBody(b'',request.full_url)
        status=self.generate(opener=timeout)
        self.assertFalse(status['ready']);self.assertIsNone(status['source_requests']);self.assertFalse(status['raw_retention_complete'])
        self.assertEqual(len(self.calls),1)
    def test_attempt_url_and_clock_must_join_retained_original_direct_wire(self):
        self.assertTrue(self.generate()['ready'])
        path=self.root/'source/collection.enc';journal=open_forecasts(path.read_bytes(),key=KEY)
        for field,value in (('url','https://www.jra.go.jp/unrelated'),('started_at',(self.clock.now()+timedelta(days=1)).isoformat())):
            tampered=deepcopy(journal);tampered['attempts'][0][field]=value
            path.write_bytes(self.api._seal(tampered,self.env,KEY));path.chmod(0o600)
            raw=zipped(self.root/'source');actual=_metadata(raw,500,'official-future-result-capture-42',self.env,self.clock.now()+timedelta(seconds=1))
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.api.source_archive(raw,actual,self.env,now=self.clock.now()+timedelta(seconds=2),key=KEY)
        path.write_bytes(self.api._seal(journal,self.env,KEY))
    def test_browser_to_horse_boundary_observes_global_spacing(self):
        seen=[]
        def get(request,timeout):seen.append(self.clock.now());return self.opener(request,timeout)
        before=self.clock.now();self.assertTrue(self.generate(opener=get)['ready'])
        self.assertGreaterEqual((seen[0]-before).total_seconds(),self.api.C.INTERVAL)
        self.assertGreaterEqual((seen[1]-seen[0]).total_seconds(),self.api.C.INTERVAL)
    def test_output_outside_actual_runner_temp_is_rejected_before_consumption(self):
        self.env['temp']=self.root.parent/'unrelated'
        with self.assertRaisesRegex(ValueError,'PRIVATE_OUTPUT_REQUIRED'):self.generate()
        self.api._admit.assert_not_called();self.assertEqual(self.calls,[]);self.assertFalse(self.root.exists())
    def test_cli_archival_readback_uses_authenticated_original_day_not_current_capture_validation(self):
        path=self.root.parent/'input.json';path.write_text(json.dumps(self.manifest));path.chmod(0o600)
        status=dict(ready=False,source_artifact_name='official-future-result-capture-42',state='AUTHORED_READBACK')
        with patch.object(self.api.common,'environment',return_value=self.env),\
             patch.object(self.api,'utc_now',return_value=NOW+timedelta(days=1)),\
             patch.object(self.api,'readback_source',return_value=status) as readback,redirect_stdout(io.StringIO()):
            self.assertEqual(self.api.main(['--input',str(path),'--out-dir',str(self.root),'--readback-source','500']),0)
        self.assertEqual(readback.call_args.args[:4],(500,self.root,self.env,self.manifest));self.assertEqual(self.calls,[])
        proof=self.root.with_name(self.root.name+'.status.json')
        self.assertEqual(json.loads(proof.read_text()),status);self.assertEqual(proof.stat().st_mode&0o777,0o600)
    def test_retained_denial_cannot_be_overridden_by_unchanged_successful_capture(self):
        self.assertTrue(self.generate()['ready'])
        path=self.root/'source/collection.enc';journal=open_forecasts(path.read_bytes(),key=KEY)
        journal['attempts'][0]['http_status']=403;journal['direct_wire_retention'][0]['status']=403
        row=journal['direct_wire_retention'][0];raw_row=self.api.future.wire(row);h=sha256(raw_row).hexdigest()
        item=next(i for i in journal['capture_inventory'] if i['file']==row['metadata_file'])
        old=self.root/'source'/item['cipher_file'];value=open_forecasts(old.read_bytes(),key=KEY)
        value.update(source_sha256=h,raw_base64=base64.b64encode(raw_row).decode());name=item['cipher_file'][:8]+h+'.enc'
        self.api.common._seal(self.root/'source'/name,value,self.env,KEY);old.unlink()
        item.update(byte_count=len(raw_row),source_sha256=h,cipher_file=name)
        path.write_bytes(self.api._seal(journal,self.env,KEY));path.chmod(0o600)
        raw=zipped(self.root/'source');actual=_metadata(raw,500,'official-future-result-capture-42',self.env,self.clock.now()+timedelta(seconds=1))
        with self.assertRaises(ValueError):self.api.source_archive(raw,actual,self.env,now=self.clock.now()+timedelta(seconds=2),key=KEY)
    def test_invalid_readback_ids_do_not_fall_through_to_live_generate(self):
        with patch.object(self.api.common,'environment',side_effect=AssertionError('NO_ENV_OR_KEY_OR_SOURCE')):
            for flag,value in (('--readback-source','0'),('--readback-source','-1'),('--readback-result','0'),('--readback-result','2')):
                with self.subTest(flag=flag,value=value),self.assertRaisesRegex(ValueError,'READBACK_IDS'):
                    self.api.main(['--input','unused','--out-dir',str(self.root),flag,value])
    def test_expiry_during_durable_checkpoint_stops_before_opener(self):
        original=self.api._seal;advanced=False
        def delayed(value,*args):
            nonlocal advanced
            raw=original(value,*args)
            if not advanced and value.get('direct_wire_retention') and value['direct_wire_retention'][-1]['state']=='RESERVED':
                advanced=True;self.clock.value+=timedelta(hours=2)
            return raw
        with patch.object(self.api,'_seal',side_effect=delayed):status=self.generate()
        self.assertFalse(status['ready']);self.assertEqual(self.calls,[]);self.assertIsNone(status['source_requests'])
    def test_direct_metadata_preserves_actual_send_and_body_completion_after_slow_fsync(self):
        original=self.api._seal;advanced=False;sent=[]
        def delayed(value,*args):
            nonlocal advanced
            raw=original(value,*args)
            if not advanced and value.get('direct_wire_retention') and value['direct_wire_retention'][-1]['state']=='RESERVED':
                advanced=True;self.clock.value+=timedelta(seconds=2)
            return raw
        def opener(request,timeout):sent.append(self.clock.now());return self.opener(request,timeout)
        with patch.object(self.api,'_seal',side_effect=delayed):self.assertTrue(self.generate(opener=opener)['ready'])
        journal=open_forecasts((self.root/'source/collection.enc').read_bytes(),key=KEY)
        row=journal['direct_wire_retention'][0];capture=journal['direct_captures'][0]['metadata']
        self.assertEqual(row['request_started_at'],sent[0].isoformat())
        self.assertEqual(capture['fetched_at'],row['request_started_at'])
        self.assertEqual(capture['response_received_at'],row['response_received_at'])
        self.assertLess(journal['attempts'][0]['started_at'],row['request_started_at'])


if __name__=='__main__':unittest.main()
