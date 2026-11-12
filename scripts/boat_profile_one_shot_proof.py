"""One narrowly bounded official profile HTML proof, never a forecast backfill.

The source GET is disabled unless an authenticated saved-view candidate is
present AND an atomic one-time reservation is first committed. A network
failure consumes the one-time reservation; retrying must not silently add GETs.
Public logs reveal count-only statuses, never registration/name/URL/key.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import ssl
import sys
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from race_ai.boat_pdca_state import state_key
from race_ai import saved_view_feed as F
from race_ai.racer_profiles import parse_basic_profile
from scripts.boat_first_p0_reconcile import _bootstrap, _retained_names, _profile_index_diagnostic

REPOSITORY='haji84/RACE-AI'
DAY='2026-11-12'
REF='state/boat-private-originals'
PREFIX='state/boat-profile-original-proof/v1/'
PROFILE_SHA='e810da0da13c47ec3f26dc5a1df67c153ee5dc7363e678fa79b61eabd60bb811'
PROFILE_SIZE=2452782
MAX_HTML=500000
FORECAST_SHA='4169db99a1d99bbcf96c8fa1bfb076ed2d2fb1f434fc64cf7e43b38e55f5adda'
SCHEMA='RACE_AI_EXACT_OFFICIAL_PROFILE_ONCE_V1'

def _need(v,code):
    if not v:raise ValueError('BOAT_PROFILE_'+code)

def _wire(d):return json.dumps(d,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')

def _id(key,registration):
    _need(type(registration) is str and re.fullmatch(r'[0-9]{4}',registration),'ID_INVALID')
    return hmac.new(key,(SCHEMA+'\n'+DAY+'\n'+registration).encode(),hashlib.sha256).hexdigest()

def _derive(key):
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=REPOSITORY.encode(),
                info=b'BOAT_PROFILE_ORIGINAL_PROOF_AES_V1').derive(key)

def _pack(raw,key,tag,at):
    _need(type(raw) is bytes and 0<len(raw)<=MAX_HTML,'HTML_SIZE')
    header=dict(schema=SCHEMA,day=DAY,tag=tag,observed_at=at,
                source_bytes_sha256=hashlib.sha256(raw).hexdigest(),
                category='ENCRYPTED_OWNER_PROFILE_OBSERVATION')
    nonce=os.urandom(12)
    ciphertext=AESGCM(_derive(key)).encrypt(nonce,raw,_wire(header))
    return _wire(dict(header=header,nonce=base64.b64encode(nonce).decode(),
                      ciphertext=base64.b64encode(ciphertext).decode()))+b'\n'

def _unpack(encoded,key,tag):
    _need(type(encoded) is bytes and 0<len(encoded)<=800000,'ENVELOPE_SIZE')
    doc=json.loads(encoded)
    _need(type(doc) is dict and set(doc)=={'header','nonce','ciphertext'},'ENVELOPE_SCHEMA')
    hdr=doc['header']
    _need(type(hdr) is dict and hdr.get('schema')==SCHEMA and hdr.get('tag')==tag
          and hdr.get('day')==DAY,'ENVELOPE_IDENTITY')
    nonce=base64.b64decode(doc['nonce'],validate=True)
    body=base64.b64decode(doc['ciphertext'],validate=True)
    _need(len(nonce)==12 and len(body)<=MAX_HTML+16,'ENVELOPE_BOUND')
    try:raw=AESGCM(_derive(key)).decrypt(nonce,body,_wire(hdr))
    except Exception:raise ValueError('BOAT_PROFILE_ENVELOPE_AUTH') from None
    _need(len(raw)<=MAX_HTML and hashlib.sha256(raw).hexdigest()==hdr['source_bytes_sha256'],
          'ENVELOPE_HASH')
    return raw,hdr

def _select(repo,now,*,target_day=DAY):
    """Return candidate privately; no source request or saved-view mutation."""
    _need(target_day==DAY and now.tzinfo is not None and
          now.astimezone(timezone.utc).date().isoformat()>=DAY,
          'DAY_BOUND')
    bootstrap=_bootstrap(repo)
    git=F.FeedRepository(repo)
    _,_,generation,view=F.current_view(git,bootstrap,day=DAY)
    _need(generation>=128 and bootstrap['forecast_sha256']==FORECAST_SHA,
          'IMMUTABLE_FORECAST_OR_GENERATION')
    pending=[p['registration_no'] for row in view['records']
             if row.get('sport')=='boat' and row.get('event_date_jst')==DAY
             for p in row.get('participants',[]) if not p.get('name')]
    if not pending:return None
    _need(len(pending)==1,'MISSING_NAMES_NOT_SINGLE')
    names,proof=_retained_names(Path(repo),now)
    check=_profile_index_diagnostic(Path(repo),view,now=now,
                                     registry_sha=proof['display_name_registry_source_sha256'])
    _need(check['display_name_profile_index_candidates']==1
          and check['display_name_profile_index_unmatched']==0
          and check['display_name_profile_index_source_reparsed'] is False,
          'NO_PINNED_PROFILE_CANDIDATE')
    from race_ai.boat_pdca_recipient import _json as strict_json
    raw=(Path(repo)/'web/data/racer-profiles.json').read_bytes()
    _need(len(raw)==PROFILE_SIZE and hashlib.sha256(raw).hexdigest()==PROFILE_SHA,
          'PROFILE_INDEX_SHA')
    catalogue=strict_json(raw,PROFILE_SIZE)
    person=next((x for x in catalogue['people'] if x['registration']==pending[0]),None)
    _need(person and person.get('term') is None,'PROFILE_NOT_OFFICIAL_BASIC')
    basic=person['basic']
    sources=[s for s in catalogue['source']['basic_sources']
             if s['registration']==pending[0]]
    _need(len(sources)==1,'PROFILE_RECEIPT_MISSING')
    receipt=sources[0]
    _need(basic['name']==person['name'] and
          basic['source_url']==receipt['url'] and
          basic['source_sha256']==receipt['sha256'] and
          basic['captured_at']==receipt['captured_at'] and
          receipt['url']=='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban='+pending[0],
          'PROFILE_ORIGINAL_PROVENANCE_INVALID')
    return dict(registration=pending[0],name=person['name'],url=receipt['url'],
                historical_sha256=receipt['sha256'])

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def _official_get(url):
    _need(type(url) is str and
          re.fullmatch(r'https://www\.boatrace\.jp/owpc/pc/data/racersearch/profile\?toban=[0-9]{4}',url),
          'PROFILE_DOMAIN_OR_PATH')
    opener=build_opener(_NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(Request(url,headers={'User-Agent':'RACE-AI-OwnerOriginalProof/1.0',
              'Accept':'text/html','Accept-Encoding':'identity'}),timeout=18) as response:
            _need(response.status==200 and response.geturl()==url,'PROFILE_HTTP_STATUS')
            raw=response.read(MAX_HTML+1)
    except (HTTPError,URLError,TimeoutError) as e:
        raise ValueError('BOAT_PROFILE_OFFICIAL_HTTP_WAIT') from None
    _need(0<len(raw)<=MAX_HTML,'PROFILE_CONTENT_BOUND')
    return raw

def _github(path,*,body=None):
    """Authenticated GitHub Contents API; only static owner-private AES state."""
    token=os.environ.get('GH_TOKEN','')
    _need(len(token)>10,'GITHUB_TOKEN_REQUIRED')
    from urllib.request import urlopen
    api='https://api.github.com/repos/'+REPOSITORY+'/contents/'+path
    if body is None:
        api+='?ref='+REF.replace('/','%2F')
        request=Request(api,headers={'Authorization':'Bearer '+token,
          'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    else:
        body=dict(message='audit(boat): reserve or seal one official profile original',
                  branch=REF,content=base64.b64encode(body).decode())
        request=Request(api,data=_wire(body),method='PUT',headers={'Authorization':'Bearer '+token,
          'Content-Type':'application/json','Accept':'application/vnd.github+json',
          'X-GitHub-Api-Version':'2022-11-28'})
    try:
        with urlopen(request,timeout=25) as resp:
            _need(resp.status==(201 if body is not None else 200),'GITHUB_STATE_HTTP_STATUS')
            reply=resp.read(1_200_001)
            _need(0<len(reply)<=1_200_000,'GITHUB_RESPONSE_BOUND')
            document=json.loads(reply)
    except HTTPError:
        raise ValueError('BOAT_PROFILE_STATE_EXISTS_OR_UNAVAILABLE') from None
    return base64.b64decode(document['content'],validate=False) if body is None else document

def _proof(raw,item):
    """Exact historical source bytes, not a newer unrelated HTML observation."""
    _need(len(raw)<=MAX_HTML and
          hashlib.sha256(raw).hexdigest()==item['historical_sha256'],
          'HISTORICAL_HTML_SHA_MISMATCH')
    parsed=parse_basic_profile(raw,registration=item['registration'],expected_name=item['name'])
    _need(parsed['source_sha256']==item['historical_sha256'] and
          parsed['source_url']==item['url'],'OFFICIAL_HTML_IDENTITY')
    return True


def _check_observed_current_html(github, candidate, *, key, tag, base, now):
    """Verify an already captured official HTML as a fresh observation.

    Historical SHA mismatches are never upgraded into a historical source
    match. This only verifies the 200-response source that the immutable,
    once-reserved producer actually saved. No HTTP/provider GET here.
    """
    reservation=json.loads(github(base+'.reservation.json'))
    _need(type(reservation) is dict
          and set(reservation)=={'schema','day','tag','max_official_profile_gets',
                                'requested_source_kind','authorized_by','state'}
          and reservation['schema']==SCHEMA
          and reservation['day']==DAY and reservation['tag']==tag
          and reservation['max_official_profile_gets']==1
          and reservation['requested_source_kind']=='OFFICIAL_PROFILE'
          and reservation['authorized_by']=='OWNER_ONE_SHOT'
          and reservation['state']=='RESERVED',
          'CAPTURE_RESERVATION_NOT_VALID')
    raw,header=_unpack(github(base+'.enc'),key,tag)
    captured=datetime.fromisoformat(header['observed_at'].replace('Z','+00:00'))
    _need(captured.utcoffset() is not None and captured<=now
          and captured.date().isoformat()>=DAY,
          'CAPTURE_OBSERVATION_CLOCK')
    parsed=parse_basic_profile(raw,
        registration=candidate['registration'],expected_name=candidate['name'])
    _need(parsed['source_sha256']==header['source_bytes_sha256']
          and parsed['source_url']==candidate['url']
          and parsed['registration']==candidate['registration']
          and parsed['name'].replace(' ','')==candidate['name'].replace(' ',''),
          'FRESH_PROFILE_IDENTITY_INVALID')
    return dict(status='PROFILE_CURRENT_OFFICIAL_HTML_READBACK_VERIFIED',
                authenticated_current_profile=1,
                historical_source_sha_matched=(
                    header['source_bytes_sha256']==candidate['historical_sha256']),
                official_profile_gets=0,
                encrypted_source_retained=True,
                new_forecasts_created=0,
                display_name_auto_published=False,
                source_unmodified=True)

def execute(repo,*,readback=False,readback_current=False,
            get_source=_official_get,github=_github,now=None,key=None):
    now=now or datetime.now(timezone.utc)
    key=state_key('production',key)
    candidate=_select(Path(repo),now)
    if candidate is None:return dict(status='ALREADY_NAMED',display_name_newly_verified=0,
            new_forecasts_created=0,official_profile_gets=0)
    tag=_id(key,candidate['registration'])
    base=PREFIX+DAY+'/'+tag
    _need(not (readback and readback_current), 'READBACK_MODE_CONFLICT')
    if readback_current:
        return _check_observed_current_html(github,candidate,key=key,
                                            tag=tag,base=base,now=now)
    if readback:
        blob=github(base+'.enc')
        raw,header=_unpack(blob,key,tag)
        _proof(raw,candidate)
        return dict(status='PROFILE_ORIGINAL_INDEPENDENT_READBACK_VERIFIED',
            verified_original_bytes=1,official_profile_gets=0,
            encrypted_source_retained=True,new_forecasts_created=0,
            display_name_auto_published=False)
    # Create-only reservation is the one-GET durable budget. Even an error
    # or a dropped job cannot consume another GET through the same entry.
    reservation=_wire(dict(schema=SCHEMA,day=DAY,tag=tag,
                           max_official_profile_gets=1,requested_source_kind='OFFICIAL_PROFILE',
                           authorized_by='OWNER_ONE_SHOT',state='RESERVED'))+b'\n'
    github(base+'.reservation.json',body=reservation)
    raw=get_source(candidate['url'])    # One bounded GET ONLY after reservation.
    # Seal the observed bytes even if today's official page has changed
    # since the historical source SHA. This preserves nonmatching evidence
    # for later review with no retry or plaintext publication.
    github(base+'.enc',body=_pack(raw,key,tag,now.isoformat()))
    _proof(raw,candidate)
    return dict(status='PROFILE_ORIGINAL_RAW_HASH_VERIFIED',
         verified_original_bytes=1,official_profile_gets=1,
         encrypted_source_retained=True,new_forecasts_created=0,
         display_name_auto_published=False)

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--repo-root',default=str(ROOT))
    p.add_argument('--readback',action='store_true')
    p.add_argument('--readback-current',action='store_true',
                   help='Verify a previously encrypted current official profile; zero source GET')
    args=p.parse_args(argv)
    try:
        result=execute(args.repo_root,readback=args.readback,
                       readback_current=args.readback_current)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as e:
        # Fixed reason codes only; never print private strings or tracebacks.
        code=str(e)
        allowed=('BOAT_PROFILE_HISTORICAL_HTML_SHA_MISMATCH','BOAT_PROFILE_OFFICIAL_HTTP_WAIT',
                 'BOAT_PROFILE_STATE_EXISTS_OR_UNAVAILABLE')
        print(json.dumps(dict(status='PROFILE_ORIGINAL_HOLD',
              reason=code if code in allowed else 'SOURCE_PROOF_UNAVAILABLE',
              original_verified=False,new_forecasts_created=0),sort_keys=True))
        return 2

if __name__=='__main__':raise SystemExit(main())
