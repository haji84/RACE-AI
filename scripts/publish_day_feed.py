"""Publish one approved automatic feed with short-lived GitHub OIDC, then verify API SHA.

Run only from the dedicated trusted workflow. No Blob credential leaves Vercel.
All HTTP calls forbid redirects and sanitize transport errors.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None


def validate_target(url):
    try:
        parsed=urlsplit(url)
        if (parsed.scheme!='https' or not re.fullmatch(r'race-ai-preview-[a-z0-9-]+-qq1130034-1738\.vercel\.app',parsed.hostname or '')
                or parsed.path!='/api/publish-day' or parsed.query or parsed.fragment
                or parsed.username or parsed.password or parsed.port not in (None,443)):
            raise ValueError
    except ValueError:
        raise ValueError('PUBLISH_TARGET_INVALID') from None
    return url


def canonical_sha(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def verify_day_response(expected, actual, digest):
    if (not isinstance(actual,dict) or actual.get('date_jst')!=expected['date_jst']
            or canonical_sha(actual)!=digest or canonical_sha(expected)!=digest):
        raise ValueError('DAY_API_READBACK_MISMATCH')
    return digest


def get_json(opener, request, *, limit):
    try:
        with opener.open(request,timeout=30) as response:
            raw=response.read(limit+1)
            if response.status!=200 or response.geturl()!=request.full_url or len(raw)>limit or 'application/json' not in response.headers.get('Content-Type','').lower():
                raise ValueError('HTTP_RESPONSE_INVALID')
            return json.loads(raw.decode('utf-8'))
    except urllib.error.HTTPError as error:
        # Never emit redirects, token query URLs, provider bodies or request headers.
        raise RuntimeError('DAY_PUBLISH_HTTP_'+str(error.code)) from None
    except (OSError,http.client.HTTPException,ValueError):
        raise RuntimeError('DAY_PUBLISH_TRANSPORT_OR_JSON_FAILED') from None


def run(feed):
    url=validate_target(os.environ.get('RACE_AI_DAY_PUBLISH_URL',''))
    commit=os.environ.get('RACE_AI_DAY_COMMIT_SHA','')
    issuer_url=os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL','')
    issuer_token=os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN','')
    try:
        issuer=urlsplit(issuer_url)
        valid=(issuer.scheme=='https' and (issuer.hostname or '').endswith('.actions.githubusercontent.com')
               and not issuer.username and not issuer.password and not issuer.fragment
               and not any(ord(c)<=32 or ord(c)>126 for c in issuer_url))
    except ValueError:
        valid=False
    if not valid or not re.fullmatch(r'[0-9a-f]{40}',commit) or not re.fullmatch(r'[A-Za-z0-9_.-]+',issuer_token):
        raise ValueError('DAY_PUBLISH_CONFIG_INVALID')
    raw=Path(feed).read_bytes()
    if not 0<len(raw)<=6_000_000:
        raise ValueError('DAY_FEED_SIZE_INVALID')
    data=json.loads(raw.decode('utf-8'))
    if data.get('publication_review')!='user-confirmation-2026-10-15-official-facts' or data.get('redistribution_authorized') is not True:
        raise ValueError('DAY_FEED_NOT_APPROVED')
    opener=urllib.request.build_opener(NoRedirect())
    separator='&' if '?' in issuer_url else '?'
    token_response=get_json(opener,urllib.request.Request(issuer_url+separator+'audience=race-ai-preview-blob-probe',headers={'Authorization':'Bearer '+issuer_token}),limit=16384)
    token=token_response.get('value')
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,8192}',token):
        raise ValueError('OIDC_TOKEN_INVALID')
    headers={'Authorization':'Bearer '+token,'x-vercel-trusted-oidc-idp-token':token,'X-Race-AI-Commit':commit,'Content-Type':'application/json'}
    result=get_json(opener,urllib.request.Request(url,data=raw,method='POST',headers=headers),limit=16384)
    digest=canonical_sha(data)
    if (not isinstance(result,dict) or result.get('status')!='verified' or result.get('sha256')!=digest
            or result.get('commit_sha')!=commit or result.get('date_jst')!=data['date_jst']):
        raise ValueError('DAY_PUBLICATION_RESULT_INVALID')
    today_url=url.rsplit('/',1)[0]+'/today'
    served=get_json(opener,urllib.request.Request(today_url,headers=headers),limit=6_000_000)
    verify_day_response(data,served,digest)
    print(json.dumps({'result':'OFFICIAL_DAY_API_VERIFIED','date_jst':data['date_jst'],
                     'races':served['races'],'boats':sum(len(r['boats']) for v in served['venues'] for r in v['races']),
                     'venue_states':len(served['venues']),'sha256':digest,'commit_sha':commit,
                     'version_pathname':result['version_pathname']},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed',required=True,type=Path)
    args=parser.parse_args()
    try:
        run(args.feed)
    except (ValueError,RuntimeError,OSError):
        # Preserve safe stage codes only. No credentialed URL can appear in a traceback.
        print('SAFE_STOP: automatic day-feed publication failed',flush=True)
        raise SystemExit(2)
