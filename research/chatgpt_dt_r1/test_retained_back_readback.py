"""Read-only B ciphertext readback: pinned I/O and real synthetic envelopes."""
import copy
from datetime import datetime, timezone
from email.message import Message
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO, StringIO
import importlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from urllib.error import HTTPError
from urllib.request import build_opener

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from research.chatgpt_dt_r1 import back_candidate
from research.chatgpt_dt_r1.model import digest
from research.chatgpt_dt_r1.runtime import _canonical


class Response(BytesIO):
    def __init__(self,raw,url,status=200,headers=None):
        super().__init__(raw);self.url=url;self.status=status;self.headers=Message()
        for key,value in (headers or {}).items():self.headers[key]=str(value)

    def geturl(self):return self.url


class RetainedBackReadbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai import keirin_official_run_history as codec
        cls.codec=codec
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.owner_pin=sha256(key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('research.chatgpt_dt_r1.retained_back_readback'),
                             'An independent ciphertext readback entry is required')
        self.api=importlib.import_module('research.chatgpt_dt_r1.retained_back_readback')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        owner=patch.object(self.codec.storage,'PINNED_OWNER_SPKI_SHA256',self.owner_pin)
        owner.start();self.addCleanup(owner.stop)
        files=[{'file':name,'bytes':len(raw),'sha256':sha256(raw).hexdigest()} for name,raw in (
            ('back_candidate.json',b'PRIVATE_CANDIDATE_FIXTURE'),('aggregate.json',b'PRIVATE_AGGREGATE_FIXTURE'))]
        identity=digest({'artifact_sha256':'d'*64,'files':files})
        payload={'schema':back_candidate.BUNDLE_SCHEMA,'day_jst':'2026-11-27','bundle_id':identity,
                 'private_fixture':'PRIVATE_CIPHERTEXT_CONTENT',
                 'safe_report':{'day_jst':'2026-11-27','scope':'synthetic'}}
        sealed=self.codec.seal_evidence(payload,self.public,'2026-11-27','2026-11-27T12:00:00Z')
        cipher={'file':'candidate.sealed.json','bytes':len(sealed),'sha256':sha256(sealed).hexdigest()}
        manifest={'schema':back_candidate.BUNDLE_SCHEMA,'bundle_id':identity,'created_at':'2026-11-27T12:00:00Z',
            'day':'2026-11-27','owner_spki_sha256':self.owner_pin,'artifact_sha256':'d'*64,'dataset_sha256':'c'*64,
            'files':files,'cipher':cipher,'production_promoted':False,'owner_decryption_verified':False}
        raw=_canonical(manifest);manifest_sha=sha256(raw).hexdigest()
        self.receipt={'schema':'DT_R1_RETAINED_BACK_RECEIPT_V1','repository':'haji84/RACE-AI',
            'archive_commit':'b'*40,'path':'research/chatgpt-dt-r1/20261128-back/'+manifest_sha,
            'source_code_commit':'a'*40,'source_code_sha256':back_candidate._source_pins(),
            'manifest':{'file':'manifest.json','bytes':len(raw),'sha256':manifest_sha},'cipher':cipher,
            'candidate_bytes_sha256':files[0]['sha256'],'artifact_sha256':'d'*64,'dataset_sha256':'c'*64}
        self.raw={'manifest.json':raw,'candidate.sealed.json':sealed}
        self.receipt_path=self.root/'receipt.json';self.save_receipt()
        self.requests=[]

    def save_receipt(self,value=None):
        self.receipt_path.write_text(json.dumps(self.receipt if value is None else value,sort_keys=True,indent=2))

    def open(self,request,timeout):
        self.requests.append(request.full_url)
        name=request.full_url.rsplit('/',1)[-1]
        expected=('https://raw.githubusercontent.com/haji84/RACE-AI/'+self.receipt['archive_commit']+
                  '/'+self.receipt['path']+'/'+name)
        self.assertEqual(request.full_url,expected)
        self.assertNotIn('Authorization',dict(request.header_items()))
        return Response(self.raw[name],request.full_url,headers={'Content-Length':len(self.raw[name])})

    def test_exact_bundle_is_read_back_without_keys_or_matching_reader_commit(self):
        with patch.object(self.api._OPENER,'open',side_effect=self.open),patch.dict(os.environ,
                {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'haji84/RACE-AI',
                 'GITHUB_RUN_ID':'12345','GITHUB_SHA':'e'*40}):
            result=self.api.readback(self.receipt_path)
        self.assertEqual(len(self.requests),2)
        self.assertEqual(result['files_verified'],2)
        self.assertEqual(result['artifact_sha256'],'d'*64)
        self.assertEqual(result['source_code_commit'],'a'*40)
        self.assertEqual(result['reader_code_commit'],'e'*40)
        self.assertEqual(result['receipt_file_sha256'],sha256(self.receipt_path.read_bytes()).hexdigest())
        for key in ('owner_decryption_verified','candidate_plaintext_verified','source_authenticated',
                    'production_promoted','private_key_used','independent_run_verified'):
            self.assertIs(result[key],False)
        self.assertEqual(result['state_writes'],0)
        self.assertEqual(result['provider_source_requests'],0)
        self.assertNotIn('PRIVATE_',json.dumps(result))

    def test_verified_bundle_context_exposes_only_verified_temporary_ciphertext(self):
        with patch.object(self.api._OPENER,'open',side_effect=self.open):
            with self.api.verified_bundle(self.receipt_path) as verified:
                folder=verified['directory']
                self.assertEqual({p.name for p in folder.iterdir()},{'manifest.json','candidate.sealed.json'})
                self.assertEqual(verified['manifest']['artifact_sha256'],'d'*64)
                self.assertEqual(verified['receipt'],self.receipt)
                self.assertEqual((folder/'candidate.sealed.json').read_bytes(),self.raw['candidate.sealed.json'])
        self.assertFalse(folder.exists())

    def test_receipt_rejects_ambiguous_refs_paths_files_repositories_and_sizes_before_network(self):
        changes=[
            lambda x:x.update(repository='other/RACE-AI'),
            lambda x:x.update(archive_commit='main'),
            lambda x:x.update(archive_commit='B'*40),
            lambda x:x.update(source_code_commit='a'*39),
            lambda x:x.update(path=x['path']+'/..'),
            lambda x:x.update(path=x['path'].replace('/20261128-back/','//20261128-back/')),
            lambda x:x.update(path=x['path'].replace('20261128-back','%2e%2e')),
            lambda x:x.update(path=x['path'].replace('20261128-back','../elsewhere')),
            lambda x:x.update(path=x['path']+'?raw=1'),
            lambda x:x['cipher'].update(file='../candidate.sealed.json'),
            lambda x:x['manifest'].update(bytes=True),
            lambda x:x['manifest'].update(bytes=65537),
            lambda x:x['cipher'].update(bytes=self.codec.MAX_CIPHER_BYTES+1),
            lambda x:x['source_code_sha256'].update({'back_phase_study.py':'0'*64}),
            lambda x:x.update(extra_field='unexpected'),
        ]
        for change in changes:
            changed=copy.deepcopy(self.receipt);change(changed);self.save_receipt(changed)
            with self.subTest(receipt=changed),patch.object(self.api._OPENER,'open',side_effect=self.open):
                with self.assertRaises(ValueError):self.api.readback(self.receipt_path)
        self.assertEqual(self.requests,[])

    def test_duplicate_receipt_keys_and_oversized_receipt_stop_before_network(self):
        original=self.receipt_path.read_text()
        for raw in ('{"repository":"haji84/RACE-AI",'+original[1:],original+' '*(64*1024)):
            self.receipt_path.write_text(raw)
            with patch.object(self.api._OPENER,'open',side_effect=self.open):
                with self.assertRaises(ValueError):self.api.readback(self.receipt_path)
        self.assertEqual(self.requests,[])

    def test_truncated_oversized_and_tampered_ciphertext_is_never_accepted(self):
        original=self.raw['candidate.sealed.json']
        for changed in (original[:-1],original+b'x',b'x'+original[1:]):
            self.raw['candidate.sealed.json']=changed
            with self.subTest(size=len(changed)),patch.object(self.api._OPENER,'open',side_effect=self.open):
                with self.assertRaisesRegex(ValueError,'SIZE|INTEGRITY'):
                    self.api.readback(self.receipt_path)

    def test_response_redirect_changed_url_and_content_encoding_are_refused(self):
        for status,url,headers,reason in (
            (302,None,{},'REDIRECT'),
            (200,'https://example.test/elsewhere',{},'URL_CHANGED'),
            (200,None,{'Content-Encoding':'gzip'},'ENCODING'),
            (200,None,{'Content-Length':'1, 2'},'SIZE'),
        ):
            def opened(request,timeout):
                return Response(self.raw['manifest.json'],url or request.full_url,status,headers)
            with self.subTest(reason=reason),patch.object(self.api._OPENER,'open',side_effect=opened):
                with self.assertRaisesRegex(ValueError,reason):self.api.readback(self.receipt_path)

    def test_redirect_handler_does_not_send_the_second_request(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(302);self.send_header('Location','/must-not-fetch');self.end_headers()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            opener=build_opener(self.api.NoRedirect())
            with self.assertRaisesRegex(ValueError,'REDIRECT'):
                opener.open('http://127.0.0.1:'+str(server.server_port)+'/start',timeout=3)
            self.assertEqual(seen,['/start'])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)

    def test_external_candidate_model_dataset_pins_must_match_verified_manifest(self):
        for key in ('candidate_bytes_sha256','artifact_sha256','dataset_sha256'):
            changed=copy.deepcopy(self.receipt);changed[key]='0'*64;self.save_receipt(changed)
            with self.subTest(key=key),patch.object(self.api._OPENER,'open',side_effect=self.open):
                with self.assertRaisesRegex(ValueError,'RECEIPT_BINDING'):
                    self.api.readback(self.receipt_path)

    def test_cli_outputs_only_public_receipt(self):
        output=StringIO()
        with patch.object(self.api._OPENER,'open',side_effect=self.open),redirect_stdout(output):
            self.api.main(['--receipt',str(self.receipt_path)])
        line=output.getvalue().strip()
        self.assertTrue(line.startswith('DT_R1_RETAINED_BACK_READBACK '))
        report=json.loads(line.split(' ',1)[1])
        self.assertEqual(report['files_verified'],2)
        self.assertNotIn('PRIVATE_',line)


if __name__=='__main__':unittest.main()
