"""Invented full browser wire; no provider, owner key, Git or real originals."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts import all_existing_model_official_result_collect as collector

START=datetime(2030,1,15,3,tzinfo=timezone.utc)
RACE='autorace:2030-01-15:isesaki:1'
CSV='https://autorace.jp/data/refund/20300115-isesaki-01R-refund.csv'

class BrowserRefund404Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700);self.finish=START+timedelta(seconds=10)
        self.planned=[dict(sport='autorace',race_id=RACE)]
        self.index=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1',started_at=START.isoformat(),
            completed_at=self.finish.isoformat(),actual_request_count=3,normal_ui_only=True,manual_api_requests=0,
            stop_reason='FINISHED',stopped_host=False,responses=[],ledger=[],cases=[])
        request=b'{"placeCode":3,"raceDate":"2030-01-15","raceNo":"1"}'
        for seq,(url,status,raw) in enumerate([('https://autorace.jp/race_info/OtherRaceInfo',200,b'{"invented":"identity"}'),
                ('https://autorace.jp/race_info/RaceResult',200,b'{"invented":"result"}'),(CSV,404,b'<html>invented not found</html>')],1):
            method='GET' if seq==3 else 'POST';mime='text/html' if seq==3 else 'application/json'
            began=START+timedelta(seconds=seq*2);ended=began+timedelta(milliseconds=200)
            meta=dict(source_url=url,final_url=url,status=status,byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),
                method=method,http_method=method,resource_type='xhr',fetched_at=began.isoformat(),
                response_received_at=ended.isoformat(),headers={'content-type':mime},ui_capture_kind='NORMAL_BROWSER_UI')
            entry=dict(sequence=seq,url=url,status=status,method=method,resource_type='xhr',request_started_at=began.isoformat(),
                headers_received_at=(began+timedelta(milliseconds=100)).isoformat(),response_received_at=ended.isoformat(),
                body_captured_at=ended.isoformat(),byte_count=len(raw),source_sha256=meta['source_sha256'],content_type=mime,
                body_file=f'response-{seq}.body',metadata_file=f'response-{seq}.json')
            if method=='POST':
                entry.update(request_body_file=f'request-{seq}.body',request_body_sha256=sha256(request).hexdigest(),request_content_type='application/json')
                meta.update({k:entry[k] for k in ('request_body_file','request_body_sha256','request_content_type')})
                collector._write(self.root/entry['request_body_file'],request)
            collector._write(self.root/entry['body_file'],raw);collector._write(self.root/entry['metadata_file'],collector.future.wire(meta))
            self.index['responses'].append(entry);self.index['ledger'].append(deepcopy(entry))
        raw=b'<html>invented result DOM</html>';collector._write(self.root/'dom.html',raw)
        self.index['cases']=[dict(sport='autorace',race_id=RACE,state='CAPTURED',responses=[dict(role='identity',sequence=1),dict(role='result',sequence=2)],
            rendered_dom=dict(file='dom.html',source_url='https://autorace.jp/race_info/Live/isesaki',final_url='https://autorace.jp/race_info/Live/isesaki',
                captured_at=(START+timedelta(seconds=8)).isoformat(),byte_count=len(raw),source_sha256=sha256(raw).hexdigest()))]
    def mutate(self,seq=3,**changes):
        entry=self.index['responses'][seq-1];meta=json.loads((self.root/entry['metadata_file']).read_bytes())
        for key,value in changes.items():
            if key=='url':entry[key]=value;meta.update(source_url=value,final_url=value)
            elif key in ('status','method','resource_type'):entry[key]=value;meta[key]=value
            else:meta[key]=value
        if 'method'in changes:meta['http_method']=changes['method']
        (self.root/entry['metadata_file']).write_bytes(collector.future.wire(meta));self.index['ledger'][seq-1]=deepcopy(entry)
    def run_sources(self):
        return collector.browser_sources(self.index,self.root,self.planned,started=START,now=self.finish,remaining=16)
    def test_unselected_same_case_get_refund_404_is_retained_and_never_selected_as_feature(self):
        before=deepcopy(self.index);captures,states,originals=self.run_sources()
        self.assertEqual(self.index,before);self.assertEqual(len(captures),1);self.assertEqual(states[0]['state'],'CAPTURED')
        self.assertEqual(captures[0][2]['metadata']['status'],200)
        self.assertEqual(captures[0][2]['metadata']['auto_result_context']['race_info_capture']['metadata']['status'],200)
        self.assertEqual([o['metadata']['status'] for o in originals],[200,200,404])
        self.assertEqual(originals[-1]['metadata']['source_url'],CSV)
    def test_any_selected_role_must_still_be_http_200(self):
        for role in ('identity','result','program','result_companion'):
            with self.subTest(role=role):
                self.index['cases'][0]['responses']=[dict(role='identity',sequence=1),dict(role='result',sequence=2),dict(role=role,sequence=3)]
                with self.assertRaises(ValueError):self.run_sources()
    def test_other_status_method_host_or_case_never_receives_the_exception(self):
        base=deepcopy(self.index)
        for change in [dict(status=500),dict(status=204),dict(method='POST'),dict(url=CSV.replace('autorace.jp','foreign.invalid')),
                dict(url=CSV.replace('20300115','20300114')),dict(url=CSV.replace('isesaki','kawaguchi')),
                dict(url=CSV.replace('01R','02R')),dict(url=CSV+'?extra=1'),dict(url=CSV+'#fragment'),
                dict(url=CSV.replace('/data/refund/','/other/')),dict(final_url=CSV+'/redirect')]:
            self.index=deepcopy(base);self.mutate(**change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.run_sources()
    def test_all_access_denials_remain_host_stop_even_if_unselected(self):
        for status in (401,403,429):
            self.mutate(status=status)
            with self.subTest(status=status),self.assertRaises(ValueError):self.run_sources()
    def test_404_exception_requires_complete_exact_raw_metadata_ledger_and_clocks(self):
        for kind in ('body','metadata_hash','ledger_status','ledger_missing','entry_size','future_clock'):
            with self.subTest(kind=kind):
                fresh=BrowserRefund404Tests();fresh.setUp()
                try:
                    e=fresh.index['responses'][2]
                    if kind=='body':(fresh.root/e['body_file']).write_bytes(b'changed')
                    elif kind=='metadata_hash':fresh.mutate(source_sha256='f'*64)
                    elif kind=='ledger_status':fresh.index['ledger'][2]['status']=200
                    elif kind=='ledger_missing':fresh.index['ledger'].pop()
                    elif kind=='entry_size':e['byte_count']+=1;fresh.index['ledger'][2]=deepcopy(e)
                    else:fresh.mutate(response_received_at=(fresh.finish+timedelta(seconds=1)).isoformat())
                    with fresh.assertRaises(ValueError):fresh.run_sources()
                finally:fresh.doCleanups()
