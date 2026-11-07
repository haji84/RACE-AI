"""Invented COMPLETE/HOLD wire, public static bytes, and no source or key I/O."""
import base64
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from scripts import all_existing_model_official_result_collect as collector

NOW=datetime(2030,1,15,5,tzinfo=timezone.utc)
b64=lambda raw:base64.b64encode(raw).decode()


def module(test):
    spec=importlib.util.find_spec('race_ai.all_existing_model_prior_static_cache')
    test.assertIsNotNone(spec,'authenticated prior static cache helper is missing')
    return importlib.import_module('race_ai.all_existing_model_prior_static_cache')


def asset(url='https://autorace.jp/js/authored.js',raw=b'throw Error("DO_NOT_EXECUTE_STATIC");',kind='script'):
    return dict(raw_base64=b64(raw),metadata=dict(source_url=url,final_url=url,status=200,http_method='GET',method='GET',
        resource_type=kind,source_sha256=sha256(raw).hexdigest(),byte_count=len(raw),
        headers={'content-type':'text/css' if kind=='stylesheet' else 'text/javascript'},
        fetched_at=(NOW-timedelta(minutes=20)).isoformat(),response_received_at=(NOW-timedelta(minutes=19)).isoformat()))


def update_file(journal,name,raw):
    quarantine=journal['browser_quarantine']
    file=next(file for file in quarantine['files'] if file['file']==name)
    file.update(raw_base64=b64(raw),byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
    item=next(item for item in quarantine['inventory'] if item['file']==name)
    item.update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
    quarantine['inventory_sha256']=digest(quarantine['inventory'])
    quarantine['retained_raw_bytes']=sum(file['byte_count'] for file in quarantine['files'])


def fixture():
    epoch=NOW-timedelta(hours=2);start=epoch+timedelta(seconds=1);finish=start+timedelta(seconds=10)
    case=dict(sport='autorace',race_id='autorace:2030-01-15:isesaki:1',state='HOLD_RESULT_SOURCE_UNAVAILABLE',responses=[])
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);root.chmod(0o700);responses=[]
        values=[asset(),asset('https://autorace.jp/css/authored.css',b'body{color:black}','stylesheet')]
        document=asset('https://autorace.jp/race_info/Live/isesaki',b'<html>no result yet</html>','document')
        document['metadata']['headers']={'content-type':'text/html'};values.append(document)
        for number,item in enumerate(values,1):
            raw=base64.b64decode(item['raw_base64']);meta=item['metadata']
            fetched=start+timedelta(seconds=number*2);completed=fetched+timedelta(seconds=1)
            meta.update(fetched_at=fetched.isoformat(),response_received_at=completed.isoformat())
            entry=dict(sequence=number,url=meta['source_url'],method='GET',resource_type=meta['resource_type'],status=200,
                request_started_at=fetched.isoformat(),headers_received_at=(fetched+timedelta(milliseconds=100)).isoformat(),
                response_received_at=completed.isoformat(),body_captured_at=completed.isoformat(),byte_count=len(raw),
                source_sha256=sha256(raw).hexdigest(),content_type=meta['headers']['content-type'],
                body_file=f'response-{number}.body',metadata_file=f'response-{number}.json')
            collector._write(root/entry['body_file'],raw);collector._write(root/entry['metadata_file'],collector.future.wire(meta))
            responses.append(entry)
        (root/'case-01').mkdir(mode=0o700);dom=b'<html>authored HOLD DOM</html>'
        collector._write(root/'case-01/rendered-dom.html',dom)
        case['rendered_dom']=dict(file='case-01/rendered-dom.html',source_url=document['metadata']['source_url'],
            final_url=document['metadata']['source_url'],captured_at=finish.isoformat(),byte_count=len(dom),source_sha256=sha256(dom).hexdigest())
        index=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1',started_at=start.isoformat(),completed_at=finish.isoformat(),
            actual_request_count=3,normal_ui_only=True,manual_api_requests=0,stop_reason='FINISHED',stopped_host=False,
            responses=deepcopy(responses),cases=[case],ledger=deepcopy(responses)+[dict(event='STATIC_CACHE_REPLAY',
                url='https://autorace.jp/js/not-originally-fetched.js',method='GET',resource_type='script',source_sha256='f'*64,
                original_captured_at=epoch.isoformat(),at=finish.isoformat())])
        collector._write(root/'capture-index.json',json.dumps(index,indent=2).encode())
        planned=[dict(sport=case['sport'],race_id=case['race_id'])]
        captures,states,originals=collector.browser_sources(index,root,planned,started=start,now=finish,remaining=8)
        journal=dict(epoch_started_at=epoch.isoformat(),maximum_requests=8,attempts=[],captures=[row[2] for row in captures],cases=states,
            browser_attempt=dict(state='COMPLETE',actual_request_count=3,started_at=start.isoformat(),completed_at=finish.isoformat()),
            browser_index=collector._index_diagnostic(index,planned),browser_captures=originals,
            browser_quarantine=collector._browser_quarantine(index,root,maximum_json=12*1024*1024))
        return journal,dict(created_at=(finish+timedelta(seconds=1)).isoformat()),values[:2]


def captured_fixture():
    """Transport captured data whose downstream result parser may still HOLD."""
    journal,metadata,expected=fixture();q=journal['browser_quarantine']
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);root.chmod(0o700)
        for item in q['files']:
            path=root/item['file'];path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            collector._write(path,base64.b64decode(item['raw_base64']))
        index=json.loads((root/'capture-index.json').read_bytes());entry=index['responses'][2]
        request=b'{"authored":"normal UI original"}';entry.update(method='POST',request_body_file='request-3.body',
            request_body_sha256=sha256(request).hexdigest(),request_content_type='application/json')
        source=json.loads((root/entry['metadata_file']).read_bytes())
        source.update(method='POST',http_method='POST',**{key:entry[key] for key in
            ('request_body_file','request_body_sha256','request_content_type')})
        (root/entry['metadata_file']).unlink()
        collector._write(root/entry['metadata_file'],collector.future.wire(source));collector._write(root/'request-3.body',request)
        index['ledger'][2]=deepcopy(entry);case=index['cases'][0];case.update(state='CAPTURED',
            responses=[dict(sequence=3,role='identity'),dict(sequence=3,role='result')])
        (root/'capture-index.json').unlink();collector._write(root/'capture-index.json',json.dumps(index,indent=2).encode())
        planned=[dict(sport=case['sport'],race_id=case['race_id'])]
        captures,states,originals=collector.browser_sources(index,root,planned,
            started=collector.stamp(index['started_at']),now=collector.stamp(index['completed_at']),remaining=8)
        journal.update(browser_captures=originals,captures=[dict(raw_base64=b64(b'horse retained separately'),
            metadata=dict(source_url='https://www.jra.go.jp/authored'))]+[row[2] for row in captures],
            cases=states,browser_index=collector._index_diagnostic(index,planned),
            browser_quarantine=collector._browser_quarantine(index,root,maximum_json=12*1024*1024))
        return journal,metadata,expected


class PriorStaticCacheTests(unittest.TestCase):
    def setUp(self):
        self.journal,self.metadata,self.expected=fixture()
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('provider access forbidden'))
        network.start();self.addCleanup(network.stop)
    def test_complete_hold_returns_only_genuine_js_css_with_original_metadata_without_result_grant(self):
        api=module(self);before=deepcopy(self.journal)
        self.assertEqual(api.extract_static_cache(self.journal,self.metadata,now=NOW),self.expected)
        self.assertEqual(self.journal,before);self.assertEqual(self.journal['captures'],[])
        self.assertNotIn('not-originally-fetched',json.dumps(self.expected))
    def test_captured_wire_allows_parsed_label_or_parse_hold_and_separate_horse_capture(self):
        api=module(self);journal,metadata,expected=captured_fixture()
        for state in ('settled','rank_confirmed','special','HOLD_RESULT_PARSE'):
            journal['cases'][0]['state']=state
            with self.subTest(state=state):self.assertEqual(api.extract_static_cache(journal,metadata,now=NOW),expected)
        journal['captures'][-1]['metadata']['source_sha256']='f'*64
        with self.assertRaises(ValueError):api.extract_static_cache(journal,metadata,now=NOW)
    def test_unknown_interrupted_denied_or_incomplete_quarantine_never_extracts(self):
        api=module(self)
        for kind in ('unknown','interrupted','denied','manual','incomplete','inventory','capture_index'):
            journal=deepcopy(self.journal)
            if kind=='unknown':journal['browser_attempt']['actual_request_count']=None
            elif kind=='interrupted':journal['browser_attempt']['state']='INTERRUPTED'
            elif kind=='denied':journal['browser_index']['ledger'][0]['status']=403
            elif kind=='manual':journal['browser_index']['manual_api_requests']=1
            elif kind=='incomplete':journal['browser_quarantine']['complete']=False
            elif kind=='inventory':journal['browser_quarantine']['inventory_sha256']='f'*64
            else:journal['browser_quarantine']['files']=[f for f in journal['browser_quarantine']['files'] if f['file']!='capture-index.json']
            with self.subTest(kind=kind),self.assertRaises(ValueError):api.extract_static_cache(journal,self.metadata,now=NOW)
    def test_hidden_http_denial_and_rehashed_ledger_or_body_swap_fail_before_filtering(self):
        api=module(self)
        for kind in ('denial','body','ledger'):
            journal=deepcopy(self.journal)
            if kind=='denial':
                file=next(f for f in journal['browser_quarantine']['files'] if f['file']=='response-3.json')
                meta=json.loads(base64.b64decode(file['raw_base64']));meta['status']=429
                update_file(journal,'response-3.json',collector.future.wire(meta))
            elif kind=='body':update_file(journal,'response-1.body',b'changed-but-rehashed')
            else:
                file=next(f for f in journal['browser_quarantine']['files'] if f['kind']=='CANONICAL_RETURNED_OBJECT')
                index=json.loads(base64.b64decode(file['raw_base64']));index['responses'][0]['method']='POST'
                update_file(journal,file['file'],collector.future.wire(index));update_file(journal,'capture-index.json',collector.future.wire(index))
                journal['browser_quarantine']['returned_index_sha256']=digest(index)
                journal['browser_index']=collector._index_diagnostic(index,journal['cases'])
            with self.subTest(kind=kind),self.assertRaises(ValueError):api.extract_static_cache(journal,self.metadata,now=NOW)
    def test_complete_wire_still_requires_exact_metadata_urls_types_clocks_headers_and_safe_paths(self):
        api=module(self)
        for kind in ('url','type','clock','duplicate_mime','traversal'):
            journal=deepcopy(self.journal)
            if kind=='traversal':journal['browser_quarantine']['files'][0]['file']='../outside.json'
            else:
                file=next(f for f in journal['browser_quarantine']['files'] if f['file']=='response-3.json')
                meta=json.loads(base64.b64decode(file['raw_base64']))
                if kind=='url':meta['source_url']=meta['final_url']='https://autorace.jp/different'
                elif kind=='type':meta['resource_type']='script'
                elif kind=='clock':meta['response_received_at']=(NOW-timedelta(hours=1)).isoformat()
                else:meta['headers']['Content-Type']='text/html'
                update_file(journal,file['file'],collector.future.wire(meta))
            with self.subTest(kind=kind),self.assertRaises(ValueError):api.extract_static_cache(journal,self.metadata,now=NOW)
    def test_merge_preserves_first_original_metadata_filters_sports_and_rejects_conflicts(self):
        api=module(self);first=asset();later=deepcopy(first)
        later['metadata']['response_received_at']=(NOW-timedelta(minutes=1)).isoformat()
        other=asset('https://keirin.jp/pc/js/authored.js')
        before=deepcopy(first)
        self.assertEqual(api.merge_static_cache([first],[later,other],now=NOW,sports={'autorace'}),[first])
        self.assertEqual(first,before)
        with self.assertRaises(ValueError):api.merge_static_cache([first],[asset(raw=b'conflict')],now=NOW,sports={'autorace'})
        duplicated=[asset(f'https://autorace.jp/js/{i}.js') for i in range(128)]
        self.assertEqual(api.merge_static_cache(duplicated,deepcopy(duplicated),now=NOW,sports={'autorace'}),duplicated)
    def test_static_policy_rejects_data_credentials_danger_paths_duplicate_mime_and_precise_future_clock(self):
        api=module(self)
        for kind in ('data','credentials','danger','fragment','duplicate_mime','wrong_mime','future'):
            item=asset();meta=item['metadata']
            if kind=='data':meta['source_url']=meta['final_url']='https://autorace.jp/race_info/RaceResult'
            elif kind=='credentials':meta['source_url']=meta['final_url']='https://autorace.jp/js/app.js?token=forbidden'
            elif kind=='danger':meta['source_url']=meta['final_url']='https://autorace.jp/account/app.js'
            elif kind=='fragment':meta['source_url']=meta['final_url']='https://autorace.jp/js/app.js#fragment'
            elif kind=='duplicate_mime':meta['headers']['Content-Type']='text/javascript'
            elif kind=='wrong_mime':meta['headers']={'content-type':'application/json'}
            else:meta['response_received_at']=(NOW+timedelta(microseconds=1)).isoformat()
            with self.subTest(kind=kind),self.assertRaises(ValueError):api.merge_static_cache([],[item],now=NOW,sports={'autorace'})
    def test_merge_bounds_and_keyless_validator_child_environment(self):
        api=module(self)
        with self.assertRaises(ValueError):api.merge_static_cache([], [asset(f'https://autorace.jp/js/{i}.js') for i in range(129)],now=NOW,sports={'autorace'})
        with self.assertRaises(ValueError):api.merge_static_cache([], [asset(f'https://autorace.jp/js/{i}.js',b'x'*(2*1024*1024)) for i in range(9)],now=NOW,sports={'autorace'})
        original=subprocess.run;seen=[]
        def run(*args,**kwargs):seen.append(kwargs['env']);return original(*args,**kwargs)
        with patch.dict(os.environ,RACE_AI_STATE_KEY='never-forward',GH_TOKEN='never-forward',
                GIT_CONFIG_VALUE_0='never-forward',NODE_OPTIONS='--require=/must-not-load.js'),patch.object(api.subprocess,'run',side_effect=run):
            self.assertEqual(api.merge_static_cache([],[asset()],now=NOW,sports={'autorace'}),[asset()])
        self.assertTrue(seen);self.assertTrue(all(set(env)<= {'PATH','LANG','LC_ALL'} for env in seen))


if __name__=='__main__':unittest.main()
