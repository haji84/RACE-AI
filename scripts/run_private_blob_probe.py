"""Scoped GitHub OIDC caller; no redirects, secrets in URLs, or live day writes."""
from __future__ import annotations
import json
import http.client
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

PREVIEW_URL = 'https://race-ai-preview-git-feat-boat-oidc-probe-auth-qq1130034-1738.vercel.app/api/blob-probe'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def run():
    oidc_url = os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL', '')
    oidc_auth = os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN', '')
    try:
        configured=urlsplit(os.environ.get('RACE_AI_PROBE_URL',''))
        issuer_request=urlsplit(oidc_url)
    except ValueError:
        raise RuntimeError('PROBE_CONFIG_INVALID') from None
    commit = os.environ.get('GITHUB_SHA', '')
    if (configured.scheme != 'https' or not configured.hostname or
        not configured.hostname.endswith('.vercel.app') or configured.path != '/api/blob-probe' or
        configured.username or configured.password or configured.query or configured.fragment or
        issuer_request.scheme!='https' or not issuer_request.hostname or
        not issuer_request.hostname.endswith('.actions.githubusercontent.com') or
        issuer_request.username or issuer_request.password or issuer_request.fragment or
        any(ord(c)<=32 or ord(c)>126 for c in oidc_url) or
        not re.fullmatch('[A-Za-z0-9_.-]+',oidc_auth) or not re.fullmatch('[0-9a-f]{40}', commit)):
        raise RuntimeError('PROBE_CONFIG_INVALID')
    # Existing workflow's old immutable URL is a config presence guard only.
    # The branch alias is scoped and its response must match this exact commit.
    url = PREVIEW_URL
    opener = urllib.request.build_opener(NoRedirect())
    separator = '&' if '?' in oidc_url else '?'
    token_request = urllib.request.Request(oidc_url + separator + 'audience=race-ai-preview-blob-probe',
        headers={'Authorization': 'Bearer ' + oidc_auth})
    try:
        with opener.open(token_request, timeout=15) as response:
            raw = response.read(16385)
            if len(raw)>16384: raise ValueError('oversized token response')
            oidc = json.loads(raw)['value']
            if not isinstance(oidc,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,8192}',oidc): raise ValueError('invalid token')
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'OIDC_ISSUE_FAILED: HTTP {exc.code}') from None
    except (OSError,http.client.HTTPException,KeyError,ValueError,TypeError):
        raise RuntimeError('OIDC_ISSUE_FAILED') from None
    print('OIDC_TOKEN_ISSUED')
    req = urllib.request.Request(url, data=b'', method='POST', headers={
        'Authorization': 'Bearer ' + oidc,
        'x-vercel-trusted-oidc-idp-token': oidc,
        'X-Race-AI-Commit': commit,
        'Content-Type': 'application/octet-stream'})
    # Retry only stale deployment, not authorization or Blob failures.
    for attempt in range(5):
        try:
            with opener.open(req, timeout=25) as response:
                body = response.read(8193)
                status = response.status
                response_type = response.headers.get('Content-Type','')
                if response.geturl()!=url: raise RuntimeError('PREVIEW_PROBE_REDIRECTED')
            break
        except urllib.error.HTTPError as exc:
            if exc.code==409 and attempt<4:
                print('PREVIEW_DEPLOYMENT_NOT_CURRENT')
                time.sleep(10)
                continue
            raise RuntimeError(f'PREVIEW_PROBE_REJECTED: HTTP {exc.code}') from None
        except (OSError,http.client.HTTPException,ValueError):
            raise RuntimeError('PREVIEW_PROBE_TRANSPORT_FAILED') from None
    if len(body)>8192 or status!=200 or 'application/json' not in response_type.lower():
        raise RuntimeError('PREVIEW_PROBE_RESPONSE_INVALID')
    try:
        result = json.loads(body)
    except ValueError:
        raise RuntimeError('PREVIEW_PROBE_MALFORMED_JSON') from None
    if (not isinstance(result,dict) or result.get('status')!='verified' or
        not isinstance(result.get('pathname'),str) or not isinstance(result.get('sha256'),str) or
        not re.fullmatch(r'race-ai/probe/[0-9a-f]{32}\.json',result.get('pathname','')) or
        not re.fullmatch('[0-9a-f]{64}',result.get('sha256','')) or
        result.get('cleanup')!='deleted' or result.get('commit_sha')!=commit or
        type(result.get('bytes')) is not int or not 0<result['bytes']<=8192):
        raise RuntimeError('PREVIEW_PROBE_RESULT_INVALID')
    print(json.dumps({'result':'BLOB_PROBE_VERIFIED','bytes':result['bytes'],
                     'sha256':result['sha256'],'cleanup':'deleted','commit_sha':commit},sort_keys=True))

if __name__=='__main__': run()
