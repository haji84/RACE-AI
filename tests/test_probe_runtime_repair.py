import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(ROOT / 'web/api')] + sys.path):
        spec.loader.exec_module(result)
    return result

class Response(io.BytesIO):
    def __init__(self, value, url):
        super().__init__(json.dumps(value).encode())
        self.status = 200
        self.headers = {'Content-Type': 'application/json'}
        self.url = url
    def geturl(self): return self.url

class ProbeRepairTests(unittest.TestCase):
    def test_auth_failure_reports_only_stage_not_secret_exception(self):
        probe = module('web/api/blob-probe.py', 'probe_auth_diagnostic')
        out = io.StringIO()
        with patch.dict(os.environ, {'VERCEL_ENV':'preview'}, clear=True), patch.object(probe, 'verify_github_oidc', side_effect=ValueError('PRIVATE_TOKEN')), patch('sys.stdout', out):
            self.assertFalse(probe.authorized({'Authorization':'Bearer PRIVATE_TOKEN'}))
        self.assertIn('PROBE_AUTH_REJECTED', out.getvalue())
        self.assertNotIn('PRIVATE_TOKEN', out.getvalue())

    def test_secret_in_invalid_oidc_url_is_not_exposed(self):
        caller=module('scripts/run_private_blob_probe.py','caller_url')
        env={'RACE_AI_PROBE_URL':caller.PREVIEW_URL,'GITHUB_SHA':'b'*40,
             'ACTIONS_ID_TOKEN_REQUEST_URL':'https://token.actions.githubusercontent.com/token?secret=PRIVATE SECRET',
             'ACTIONS_ID_TOKEN_REQUEST_TOKEN':'runtime-token'}
        with patch.dict(os.environ,env,clear=True):
            with self.assertRaisesRegex(RuntimeError,'^PROBE_CONFIG_INVALID$'):caller.run()

    def test_invalid_ipv6_url_is_sanitized(self):
        caller=module('scripts/run_private_blob_probe.py','caller_ipv6')
        env={'RACE_AI_PROBE_URL':caller.PREVIEW_URL,'GITHUB_SHA':'b'*40,
             'ACTIONS_ID_TOKEN_REQUEST_URL':'https://[PRIVATE_RUNTIME_SECRET]/token',
             'ACTIONS_ID_TOKEN_REQUEST_TOKEN':'runtime-token'}
        with patch.dict(os.environ,env,clear=True):
            with self.assertRaisesRegex(RuntimeError,'^PROBE_CONFIG_INVALID$'):caller.run()
    def test_real_sdk_content_shape(self):
        probe = module('web/api/blob-probe.py', 'probe_content')
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def put(self,key,raw,**kwargs): self.raw=raw; return types.SimpleNamespace(pathname=key)
            async def get(self,*args,**kwargs): return types.SimpleNamespace(status_code=200, content=self.raw)
            async def delete(self,key): pass
        sdk=types.ModuleType('vercel.blob'); sdk.AsyncBlobClient=lambda:Client()
        with patch.dict(sys.modules, {'vercel.blob':sdk}):
            self.assertEqual(asyncio.run(probe.roundtrip())['status'], 'verified')

    def test_control_character_token_is_sanitized_before_post(self):
        caller=module('scripts/run_private_blob_probe.py','caller_controls')
        env={'RACE_AI_PROBE_URL':caller.PREVIEW_URL,'GITHUB_SHA':'b'*40,
             'ACTIONS_ID_TOKEN_REQUEST_URL':'https://token.actions.githubusercontent.com/token',
             'ACTIONS_ID_TOKEN_REQUEST_TOKEN':'runtime-token'}
        with patch.dict(os.environ,env,clear=True), patch.object(caller.urllib.request,'build_opener') as build:
            build.return_value.open.return_value=Response({'value':'secret\r\nleak'},caller.PREVIEW_URL)
            with self.assertRaisesRegex(RuntimeError,'^OIDC_ISSUE_FAILED$'):
                caller.run()
            self.assertEqual(build.return_value.open.call_count,1)

    def test_import_under_vercel_root_without_api_sys_path(self):
        code = "import importlib.util; s=importlib.util.spec_from_file_location('probe','api/blob-probe.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)"
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT / 'web', capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_trusted_source_header_and_no_redirects(self):
        caller = module('scripts/run_private_blob_probe.py', 'probe_caller')
        requests = []
        def open_request(request, **kwargs):
            requests.append(request)
            if len(requests) == 1:
                return Response({'value': 'private-token'}, request.full_url)
            return Response({'status':'verified','pathname':'race-ai/probe/'+'a'*32+'.json',
                             'sha256':'a'*64,'bytes':10,'cleanup':'deleted','commit_sha':'b'*40}, request.full_url)
        env = {'RACE_AI_PROBE_URL': 'https://race-ai-preview-35zjg8yzl-qq1130034-1738.vercel.app/api/blob-probe',
               'ACTIONS_ID_TOKEN_REQUEST_URL':'https://token.actions.githubusercontent.com/token',
               'ACTIONS_ID_TOKEN_REQUEST_TOKEN':'runtime-token','GITHUB_SHA':'b'*40}
        with patch.dict(os.environ, env, clear=True), patch.object(caller.urllib.request, 'urlopen', side_effect=open_request), patch.object(caller.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect=open_request
            caller.run()
        self.assertEqual(requests[-1].get_header('X-vercel-trusted-oidc-idp-token'), 'private-token')
        self.assertTrue(build.called, 'credentialed POST must use no-redirect opener')

    def test_roundtrip_deletes_and_reports_sha(self):
        probe = module('web/api/blob-probe.py', 'probe_roundtrip')
        class Client:
            def __init__(self): self.deleted=[]; self.closed=False
            async def __aenter__(self): return self
            async def __aexit__(self, *args): self.closed=True
            async def put(self, key, raw, **kwargs):
                self.key=key; self.raw=raw
                return types.SimpleNamespace(pathname=key)
            async def get(self, key, **kwargs):
                async def stream(): yield self.raw
                return types.SimpleNamespace(status_code=200, stream=stream())
            async def delete(self, key): self.deleted.append(key)
        client=Client()
        sdk=types.ModuleType('vercel.blob'); sdk.AsyncBlobClient=lambda:client
        with patch.dict(sys.modules, {'vercel.blob': sdk}), patch.dict(os.environ, {'VERCEL_GIT_COMMIT_SHA':'b'*40}):
            result=asyncio.run(probe.roundtrip())
        self.assertEqual(client.deleted, [client.key])
        self.assertTrue(client.closed)
        self.assertEqual(result['cleanup'], 'deleted')
        self.assertEqual(len(result['sha256']), 64)

    def test_cleanup_after_readback_failure(self):
        probe = module('web/api/blob-probe.py', 'probe_failure')
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def put(self,key,raw,**kwargs): self.key=key; return types.SimpleNamespace(pathname=key)
            async def get(self,*args,**kwargs): raise ValueError('failed')
            async def delete(self,key): self.deleted=key
        client=Client(); sdk=types.ModuleType('vercel.blob'); sdk.AsyncBlobClient=lambda:client
        with patch.dict(sys.modules, {'vercel.blob':sdk}):
            with self.assertRaises(ValueError): asyncio.run(probe.roundtrip())
        self.assertEqual(client.deleted, client.key)
