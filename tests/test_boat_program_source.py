"""Official program capture uses invented B bytes and local encrypted Git only."""
from copy import deepcopy
from datetime import date,datetime,timezone,timedelta
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from contextlib import redirect_stdout
import io

from scripts import existing_day_program as collector
from tests import test_boat_private_original_vault as vault_fixtures
from tests.test_boat_seller_official_source import fixture,DAY,AT,CAPTURE,HEAD,URL,reseal
from race_ai import boat_private_original_vault as V

try:
    program=importlib.import_module('race_ai.boat_program_source')
except ModuleNotFoundError:
    program=None

KEY=vault_fixtures.KEY


def collector_archive():
    from tests.test_boat_entry_observations import uncompressed_lzh
    lines=['STARTB','17BBGN','2030年1月15日']
    for number in range(1,13):
        lines.append(f' {number}R TEST H1800m 電話投票締切予定 10:{number:02d}')
        for lane in range(1,7):
            rating=6.5 if lane==1 else 5.8-.35*(lane-2)
            grade='A1' if lane==1 else 'B1'
            lines.append(f' {lane} {4000+lane}TEST 30東京52{grade} {rating:.2f} 45.00 5.50 30.00 '
                         f'{54+lane:02d} 35.00 {32+lane:02d} 30.00')
    lines.append('17BEND')
    return uncompressed_lzh('\n'.join(lines).encode('cp932'),'B300115.TXT')


class Response:
    status=200
    def __init__(self,raw):self.raw=raw
    def geturl(self):return URL
    def read(self,limit):return self.raw[:limit]
    def __enter__(self):return self
    def __exit__(self,*_):return False


class Opener:
    def __init__(self,raw,error=None):self.raw=raw;self.error=error;self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request.full_url)
        if self.error:raise self.error
        return Response(self.raw)


class ProgramSourceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(program,'durable official B program source is absent')
        self.f=vault_fixtures.VaultTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.raw,self.document,self.receipt=fixture()
        self.capture_receipt=dict(source_url=URL,captured_at=CAPTURE,http_status=200,source_sha256=sha256(self.raw).hexdigest())
        import base64
        self.env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_RUN_ID='42',GITHUB_SHA=HEAD,
            RUNNER_TEMP=str(self.f.root),RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),GH_TOKEN='fixture-token-only-not-a-credential')

    def capture(self,raw=None,receipt=None):
        with patch.dict(os.environ,self.env,clear=True):
            return program.capture_program(self.raw if raw is None else raw,
                                           self.capture_receipt if receipt is None else receipt)

    def retain(self,**kwargs):
        return program.retain_program_source(DAY,self.document,self.receipt,self.f.writer.repo,
            expected_parent=kwargs.pop('expected_parent',self.f.parent),capture_dir=self.f.root/'boat-program-source',
            key=KEY,transport=self.f.writer,readback_transport=self.f.reader,
            now=datetime.fromisoformat(AT),**kwargs)

    def test_capture_retention_and_new_worker_restore_preserve_exact_program_and_clock(self):
        capture=self.capture();first=self.retain()
        folder=Path(capture['capture_dir'])
        self.assertEqual((folder/'program.lzh').read_bytes(),self.raw)
        self.assertEqual((folder/'program.lzh').stat().st_mode&0o777,0o600)
        self.assertEqual(folder.stat().st_mode&0o777,0o700)
        shutil.rmtree(self.f.root/'boat-program-source')
        with patch('urllib.request.urlopen',side_effect=AssertionError('extra official GET')):
            restored=program.load_program_source(DAY,self.document,self.receipt,self.f.reader.repo,
                                                key=KEY,transport=self.f.reader)
        self.assertEqual(restored['raw'],self.raw)
        self.assertEqual(restored['source_evidence'][0]['captured_at'],CAPTURE)
        self.assertEqual(restored['source_evidence'][0]['original_receipt'],self.receipt)
        self.assertEqual(len(restored['cards']),8)
        self.assertEqual(self.retain(expected_parent=first['source_commit'])['source_commit'],first['source_commit'])
        self.assertIsNone(program.load_program_source('2030-01-16',self.document,self.receipt,
            self.f.reader.repo,key=KEY,transport=self.f.reader))

    def test_optional_collector_capture_keeps_output_exact_and_uses_one_existing_get(self):
        def collect(flag):
            env=dict(self.env)
            if flag:env['RACE_AI_SAVED_PROGRAM_CAPTURE']='true'
            opener=Opener(collector_archive())
            with patch.dict(os.environ,env,clear=True),patch.object(collector.request,'build_opener',return_value=opener):
                result=collector.collect(clock=lambda:datetime.fromisoformat(CAPTURE))
            self.assertEqual(opener.requests,[URL])
            return result
        plain=collect(False)
        self.assertFalse((self.f.root/'boat-program-source').exists())
        captured=collect(True)
        self.assertEqual(V._wire(captured),V._wire(plain))
        self.assertGreater(captured['race_count'],0)
        self.assertTrue((self.f.root/'boat-program-source'/DAY).is_dir())

    def test_denied_get_does_not_capture_or_make_another_request(self):
        opener=Opener(self.raw,HTTPError(URL,403,'denied',{},None))
        env=dict(self.env,RACE_AI_SAVED_PROGRAM_CAPTURE='true')
        with patch.dict(os.environ,env,clear=True),patch.object(collector.request,'build_opener',return_value=opener):
            result=collector.collect(clock=lambda:datetime.fromisoformat(CAPTURE))
        self.assertEqual(result['http_status'],403)
        self.assertEqual(opener.requests,[URL])
        self.assertFalse((self.f.root/'boat-program-source').exists())

    def test_capture_rejects_wrong_hash_foreign_source_non_actions_or_repository_paths(self):
        wrong=dict(self.capture_receipt,source_sha256='f'*64)
        with self.assertRaises(ValueError):self.capture(receipt=wrong)
        wrong=dict(self.capture_receipt,source_url=URL.replace('/B/','/K/'))
        with self.assertRaises(ValueError):self.capture(receipt=wrong)
        with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):
            program.capture_program(self.raw,self.capture_receipt)
        env=dict(self.env,RUNNER_TEMP=str(self.f.writer.repo))
        with patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):
            program.capture_program(self.raw,self.capture_receipt)

    def test_wrong_key_roster_and_conflicting_day_source_do_not_fall_back(self):
        self.capture();first=self.retain()
        with self.assertRaises(ValueError):
            program.load_program_source(DAY,self.document,self.receipt,self.f.reader.repo,key=b'x'*32,transport=self.f.reader)
        document,receipt=deepcopy(self.document),deepcopy(self.receipt)
        document['predictions'][0]['observations'][0]['registration_no']='4999';reseal(document,receipt)
        with self.assertRaises(ValueError):
            program.load_program_source(DAY,document,receipt,self.f.reader.repo,key=KEY,transport=self.f.reader)
        receipt=deepcopy(self.receipt);receipt['artifact_id']+=1
        with self.assertRaises(ValueError):
            program.retain_program_source(DAY,self.document,receipt,self.f.writer.repo,
                expected_parent=first['source_commit'],key=KEY,transport=self.f.writer,
                readback_transport=self.f.reader,now=datetime.fromisoformat(AT))
        self.assertEqual(self.f.writer.head(),first['source_commit'])

    def test_authenticated_catalog_and_capture_tampering_stop_recovery(self):
        self.capture();first=self.retain()
        bad=self.f.writer.commit({first['catalog_path']:b'{"state":{},"mac":"'+b'0'*64+b'"}'},first['source_commit'])
        self.f.writer.push(bad,first['source_commit'])
        with self.assertRaises(ValueError):
            program.load_program_source(DAY,self.document,self.receipt,self.f.reader.repo,key=KEY,transport=self.f.reader)

    def test_vault_allows_only_exact_date_validated_official_b_archive_urls(self):
        self.assertTrue(V._capture_url(URL))
        for bad in (URL.replace('b300115','b300116'),URL.replace('203001','203002'),URL+'?retry=1',
                    URL.replace('/B/','/K/'),'https://example.test/program.lzh',
                    'https://www1.mbrace.or.jp/od2/B/203002/b300231.lzh'):
            if bad==URL.replace('b300115','b300116'):continue # a different valid day is allowed
            with self.subTest(url=bad):self.assertFalse(V._capture_url(bad))

    def test_new_day_retention_preserves_previous_day_for_another_worker(self):
        self.capture();first=self.retain()
        from tests.test_boat_entry_observations import uncompressed_lzh
        text=collector.extract_daily_lzh(self.raw,'B300115.TXT').decode('cp932').replace('2030年1月15日','2030年1月16日')
        raw=uncompressed_lzh(text.encode('cp932'),'B300116.TXT')
        document=json.loads(json.dumps(self.document,ensure_ascii=False).replace('2030-01-15','2030-01-16')
            .replace('20300115','20300116').replace('b300115','b300116'))
        receipt=json.loads(json.dumps(self.receipt).replace('2030-01-15','2030-01-16'))
        document['source_sha256']=sha256(raw).hexdigest()
        document['extracted_text_sha256']=sha256(text.encode('cp932')).hexdigest()
        for prediction in document['predictions']:
            prediction['source_evidence'][0]['source_sha256']=document['source_sha256']
        receipt['artifact_id']=101;receipt['run_id']='43';reseal(document,receipt)
        self.capture(raw,dict(source_url=document['source_url'],captured_at=document['captured_at'],
                              source_sha256=document['source_sha256'],http_status=200))
        second=program.retain_program_source('2030-01-16',document,receipt,self.f.writer.repo,
            expected_parent=first['source_commit'],capture_dir=self.f.root/'boat-program-source',key=KEY,
            transport=self.f.writer,readback_transport=self.f.reader,
            now=datetime.fromisoformat(AT)+timedelta(days=1))
        self.assertNotEqual(first['source_commit'],second['source_commit'])
        worker=self.f.git('another-day-worker')
        self.assertEqual(program.load_program_source(DAY,self.document,self.receipt,worker.repo,key=KEY,
            transport=worker)['raw'],self.raw)
        self.assertEqual(program.load_program_source('2030-01-16',document,receipt,worker.repo,key=KEY,
            transport=worker)['raw'],raw)

    def test_missing_encrypted_program_does_not_fall_back_to_healthy_local_capture(self):
        self.capture();first=self.retain();git=self.f.writer
        state=V._unsigned(git.read(first['source_commit'],first['catalog_path'],16384),program._key(KEY))
        state['capture_locator']['entry_sha256']='f'*64
        bad=git.commit({first['catalog_path']:V._signed(state,program._key(KEY))},first['source_commit'])
        git.push(bad,first['source_commit'])
        self.assertTrue((self.f.root/'boat-program-source'/DAY).is_dir())
        with self.assertRaises(ValueError):
            program.load_program_source(DAY,self.document,self.receipt,self.f.reader.repo,key=KEY,transport=self.f.reader)

    def test_cli_authenticates_local_first_p0_against_vault_without_source_get(self):
        try:cli=importlib.import_module('scripts.boat_program_source')
        except ModuleNotFoundError:cli=None
        self.assertIsNotNone(cli,'Actions program-source retain CLI is absent')
        raw=collector_archive();env=dict(self.env,RACE_AI_SAVED_PROGRAM_CAPTURE='true')
        with patch.dict(os.environ,env,clear=True),patch.object(collector.request,'build_opener',return_value=Opener(raw)):
            document=collector.collect(clock=lambda:datetime.fromisoformat(CAPTURE))
        body=V._wire(document)
        original=vault_fixtures.packed({'forecasts.json':body})
        metadata=dict(id=100,name='boat-p0-existing-42',expired=False,created_at=self.receipt['created_at'],
            expires_at='2030-01-22T05:01:00+09:00',digest='sha256:'+V._sha(original),size_in_bytes=len(original),
            workflow_run=dict(id=42,repository_id=1416489937,head_repository_id=1416489937,head_sha=HEAD))
        V.retain_original(original,V._wire(metadata),self.f.writer.repo,expected_parent=self.f.parent,key=KEY,
            transport=self.f.writer,readback_transport=self.f.reader,now=datetime.fromisoformat(AT))
        folder=self.f.writer.repo/'boat_all_day_output';folder.mkdir()
        (folder/'forecasts.json').write_bytes(body);(folder/'first-receipt.json').write_bytes(V._wire(metadata))
        output=io.StringIO()
        with patch.dict(os.environ,self.env,clear=True),redirect_stdout(output),patch('urllib.request.urlopen',side_effect=AssertionError('source GET')):
            result=cli.main(['retain','--day',DAY,'--repo-root',str(self.f.writer.repo),
                '--output',str(self.f.root/'program-report.json')],transport=self.f.writer,
                readback_transport=self.f.reader,now=datetime.fromisoformat(AT))
        self.assertEqual(result,0,output.getvalue())
        report=json.loads(output.getvalue())
        self.assertEqual(report['day_jst'],DAY);self.assertEqual(report['source_requests'],0)
        self.assertNotIn('cards',report)


if __name__=='__main__':unittest.main()
