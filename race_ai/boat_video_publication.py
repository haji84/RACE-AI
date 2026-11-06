"""Opt-in encrypted context handoff through the EXISTING viewer workflow.

No key creation, source capture, source certification, main changes or automatic
dispatch. Public-repository artifacts retain ciphertext; an owner-key reader
must authenticate the actual GitHub artifact/run/ZIP before decrypting it.
Default-branch activation, owner key and qualified real inputs are separate
gates. Successful dispatch alone is not an independently saved receipt.
"""
import argparse
import base64
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from .boat_video_connection import connect_report
from .boat_video_evaluation import _decode,_local_digest,_read
from .boat_video_model_context import validate_video_context
from .frozen_day_cycle import check_clock,ts
from .private_cycle_capture import _parent_handle,_write_at


WORKFLOW_ID=392270247
REPOSITORY_ID=1416489937
REPOSITORY='haji84/RACE-AI'
BRANCH='feat/four-sport-forecast-audit-view-20261022'
WORKFLOW_PATH='.github/workflows/forecast-audit-ui.yml'
ARCHIVE_SCHEMA='RACE_AI_BOAT_VIDEO_CONTEXT_ARCHIVE_V1'
PUBLICATION_SCHEMA='RACE_AI_BOAT_VIDEO_PUBLICATION_V1'
CIPHER_SCHEMA='RACE_AI_BOAT_VIDEO_CONTEXT_ENCRYPTED_V1'
CIPHER_MEMBER='video-context.enc'
INPUT_NAME='video_context_cipher'
MAX_DISPATCH_BYTES=65535
MAX_PLAIN_BYTES=32*1024*1024
_ERROR='BOAT_VIDEO_PUBLICATION_REJECTED'
_HEAD=re.compile(r'[a-f0-9]{40}\Z')


class _TooLarge(ValueError):pass


def _need(ok):
    if not ok:raise ValueError(_ERROR)


def _now(clock=None):
    value=datetime.now(timezone.utc) if clock is None else clock()
    _need(type(value) is datetime and value.utcoffset() is not None)
    return value


def _wire(value,limit=MAX_PLAIN_BYTES):
    chunks=[];size=0
    encoder=json.JSONEncoder(ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    for chunk in encoder.iterencode(value):
        raw=chunk.encode();size+=len(raw)
        if size>limit:raise _TooLarge(_ERROR)
        chunks.append(raw)
    return b''.join(chunks)


def _json(raw,limit):
    _need(type(raw) is bytes and 0<len(raw)<=limit)
    def unique(pairs):
        out={}
        for key,value in pairs:
            _need(key not in out);out[key]=value
        return out
    def invalid(_):raise ValueError(_ERROR)
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def _owner_key(key):
    # Reuse the existing production key validator; no public/synthetic key or
    # automatic fallback may become an owner secret.
    from .boat_pdca_state import state_key
    return hmac.digest(state_key('production',key),
        b'RACE_AI_BOAT_VIDEO_CONTEXT_ENCRYPTION_KEY_V1','sha256')


def _aad(head):
    _need(type(head) is str and _HEAD.fullmatch(head))
    return _wire(dict(schema=CIPHER_SCHEMA,repository_id=REPOSITORY_ID,
        workflow_id=WORKFLOW_ID,branch=BRANCH,head_sha=head))


def _summary(status,**fields):
    return dict(status=status,ready=status.startswith('READY_'),context_count=0,
        plaintext_published=False,artifact_receipt_verified=False,**fields)


def _context(context):
    return validate_video_context(context,race_id=context['race_id'],cutoff_at=context['cutoff_at'],
        as_of=context['as_of'],roster=[dict(lane=p['lane'],registration_number=p['registration_number'])
                                      for p in context['participants']])


def _original_context(item,now):
    required={'report_path','media_path','identity_evidence','video_context'}
    _need(type(item) is dict and required<=item.keys() and
          item.keys()<=required|{'calibration_manifest'})
    report_path=Path(item['report_path']).absolute()
    _need(report_path.suffix=='.json' and re.fullmatch('[a-f0-9]{64}',report_path.stem))
    with _parent_handle(report_path.parent) as parent:
        report=_decode(_read(parent,report_path.name),report_path.stem)
    media_path=Path(item['media_path']).absolute()
    # The protected original must still exist outside Git; a hash declaration
    # or a re-sealed context alone is not an exportable original.
    with _parent_handle(media_path.parent):
        _need(_local_digest(media_path)==report['source']['media_sha256'])
    context=_context(item['video_context'])
    supplied={'video_context':context}
    if 'calibration_manifest' in item:supplied['calibration_manifest']=deepcopy(item['calibration_manifest'])
    rebuilt=connect_report(report,identity_evidence=item['identity_evidence'],
        model_inputs=supplied,clock=lambda:now)
    _need(rebuilt['video_context']==context and context['eligible_for_research'] is True and
          rebuilt['status']=='WAITING_FROZEN_TRAINING_AND_INPUTS' and not rebuilt['shadows'] and
          rebuilt['missing_reasons']==['WAITING_FROZEN_TRAINING_AND_INPUTS'])
    return context


def prepare_publication(items,*,expected_head_sha,key=None,clock=None):
    """Replay private originals, encrypt contexts and prepare a bounded request.

    Returns ``(safe_summary, request_or_None)``. The request contains ciphertext
    only; it is not sent here. Missing key is checked before any source read.
    Source paths are trusted local arguments, never workflow dispatch inputs.
    """
    try:derived=_owner_key(key)
    except Exception:return _summary('HOLD_OWNER_STATE_KEY_REQUIRED'),None
    try:
        now=_now(clock);aad=_aad(expected_head_sha)
        _need(type(items) in (tuple,list) and 0<len(items)<=2048)
        contexts=[];seen=set()
        for item in items:
            if now>=ts(item['video_context']['cutoff_at']):
                return _summary('HOLD_VIDEO_PUBLICATION_DEADLINE'),None
            context=_original_context(item,now)
            _need(context['context_sha256'] not in seen)
            seen.add(context['context_sha256']);contexts.append(context)
        expires=min((c['cutoff_at'] for c in contexts),key=ts)
        plain=_wire(dict(schema=PUBLICATION_SCHEMA,sealed_at=now.isoformat(),
                         expires_at=expires,contexts=contexts))
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce=os.urandom(12);_need(len(nonce)==12)
        encrypted=AESGCM(derived).encrypt(nonce,gzip.compress(plain,compresslevel=3,mtime=0),aad)
        raw=_wire(dict(schema=CIPHER_SCHEMA,nonce=base64.b64encode(nonce).decode(),
                       ciphertext=base64.b64encode(encrypted).decode()))
        request=dict(ref=BRANCH,inputs={INPUT_NAME:raw.decode('ascii')})
        packed=_wire(request,MAX_DISPATCH_BYTES)
        summary=_summary('READY_ENCRYPTED_CONTEXT_PUBLICATION',expected_head_sha=expected_head_sha,
            cipher_sha256=hashlib.sha256(raw).hexdigest(),dispatch_sha256=hashlib.sha256(packed).hexdigest(),
            payload_bytes=len(packed))
        summary['context_count']=len(contexts)
        return summary,request
    except _TooLarge:return _summary('HOLD_DISPATCH_PAYLOAD_TOO_LARGE'),None
    except Exception:return _summary('HOLD_ORIGINALS_OR_CONTEXT_UNAVAILABLE'),None


def decrypt_publication(raw,*,expected_head_sha,key=None,available_at):
    """Authenticate ciphertext at an actual receive or saved-receipt time.

    A later reader passes the independent artifact creation time, so historical
    replay after cutoff remains possible without pretending the artifact was
    saved earlier. No human/field verification flag is changed.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        document=_json(raw,MAX_DISPATCH_BYTES)
        _need(type(document) is dict and set(document)=={'schema','nonce','ciphertext'} and
              document['schema']==CIPHER_SCHEMA and _wire(document)==raw)
        nonce=base64.b64decode(document['nonce'],validate=True)
        cipher=base64.b64decode(document['ciphertext'],validate=True)
        _need(len(nonce)==12 and len(cipher)>=16 and
              base64.b64encode(nonce).decode()==document['nonce'] and
              base64.b64encode(cipher).decode()==document['ciphertext'])
        compressed=AESGCM(_owner_key(key)).decrypt(nonce,cipher,_aad(expected_head_sha))
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:plain=stream.read(MAX_PLAIN_BYTES+1)
        body=_json(plain,MAX_PLAIN_BYTES)
        _need(type(body) is dict and set(body)=={'schema','sealed_at','expires_at','contexts'} and
              body['schema']==PUBLICATION_SCHEMA and type(body['contexts']) is list and
              0<len(body['contexts'])<=2048)
        contexts=[];seen=set()
        for candidate in body['contexts']:
            context=_context(candidate)
            _need(context['eligible_for_research'] is True and context['context_sha256'] not in seen and
                  ts(context['as_of'])<=ts(body['sealed_at']))
            seen.add(context['context_sha256']);contexts.append(context)
        expires=min((c['cutoff_at'] for c in contexts),key=ts)
        _need(body['expires_at']==expires)
        at=available_at.isoformat() if type(available_at) is datetime else available_at
        check_clock(body['sealed_at'],expires,at)
        return dict(schema=ARCHIVE_SCHEMA,contexts=contexts),dict(
            sealed_at=body['sealed_at'],expires_at=expires,cipher_sha256=hashlib.sha256(raw).hexdigest())
    except Exception:raise ValueError(_ERROR) from None


def _request_bytes(request):
    _need(type(request) is dict and set(request)=={'ref','inputs'} and request['ref']==BRANCH and
          type(request['inputs']) is dict and set(request['inputs'])=={INPUT_NAME} and
          type(request['inputs'][INPUT_NAME]) is str)
    if len(request['inputs'][INPUT_NAME])>MAX_DISPATCH_BYTES:raise _TooLarge(_ERROR)
    return _wire(request,MAX_DISPATCH_BYTES)


def _gh_send(raw):
    result=subprocess.run(['gh','api',f'repos/{REPOSITORY}/actions/workflows/{WORKFLOW_ID}/dispatches',
        '--method','POST','--input','-'],input=raw,capture_output=True,timeout=50)
    _need(result.returncode==0)


def dispatch_publication(summary,request,*,key=None,clock=None,platform_ready=False,send=None):
    """Explicit trusted caller action; default platform gate performs no API call.

    This API is never invoked by module CLI. Tests inject ``send``; actual gh
    transport passes complete structured JSON on stdin, never keys/ciphertext
    in command arguments. Acceptance is not an artifact timestamp receipt.
    """
    try:_owner_key(key)
    except Exception:return _summary('HOLD_OWNER_STATE_KEY_REQUIRED')
    try:
        raw=_request_bytes(request)
        _need(type(summary) is dict and summary.get('status')=='READY_ENCRYPTED_CONTEXT_PUBLICATION')
        if not platform_ready:return _summary('HOLD_PLATFORM_ACTIVATION_UNVERIFIED')
        _need(platform_ready is True and hashlib.sha256(raw).hexdigest()==summary['dispatch_sha256'])
        cipher=request['inputs'][INPUT_NAME].encode('ascii')
        _need(hashlib.sha256(cipher).hexdigest()==summary['cipher_sha256'])
        document,_=decrypt_publication(cipher,expected_head_sha=summary['expected_head_sha'],
            key=key,available_at=_now(clock))
        sender=_gh_send if send is None else send
        _need(callable(sender))
        sender(raw)
        out=_summary('DISPATCH_REQUEST_ACCEPTED_NOT_ARTIFACT_RECEIPT',
            cipher_sha256=summary['cipher_sha256'],dispatch_sha256=summary['dispatch_sha256'])
        out['context_count']=len(document['contexts']);return out
    except _TooLarge:return _summary('HOLD_DISPATCH_PAYLOAD_TOO_LARGE')
    except Exception:return _summary('HOLD_PUBLICATION_INPUT_OR_DISPATCH_REJECTED')


def receive_publication(event,*,identity,key=None,clock=None):
    """Validate actual job identity and return only ciphertext for its upload."""
    try:_owner_key(key)
    except Exception:return _summary('HOLD_OWNER_STATE_KEY_REQUIRED'),None
    try:
        _need(type(identity) is dict and identity.get('event_name')=='workflow_dispatch' and
            identity.get('repository')==REPOSITORY and identity.get('repository_id')==REPOSITORY_ID and
            identity.get('workflow_id')==WORKFLOW_ID and identity.get('head_branch')==BRANCH and
            type(identity.get('run_id')) is int and identity['run_id']>0)
        _aad(identity['head_sha'])
        _need(type(event) is dict and event.get('repository',{}).get('id')==REPOSITORY_ID and
              event['repository'].get('full_name')==REPOSITORY and event.get('ref') in (BRANCH,'refs/heads/'+BRANCH))
        request=dict(ref=BRANCH,inputs=event.get('inputs'))
        _request_bytes(request)
        cipher=request['inputs'][INPUT_NAME].encode('ascii')
        document,meta=decrypt_publication(cipher,expected_head_sha=identity['head_sha'],key=key,
                                          available_at=_now(clock))
        summary=_summary('READY_ENCRYPTED_CONTEXT_ARTIFACT',cipher_sha256=meta['cipher_sha256'])
        summary['context_count']=len(document['contexts'])
        return summary,cipher
    except _TooLarge:return _summary('HOLD_DISPATCH_PAYLOAD_TOO_LARGE'),None
    except Exception:return _summary('HOLD_PUBLICATION_INPUT_REJECTED'),None


def _event_file(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno());_need(stat.S_ISREG(info.st_mode) and 0<info.st_size<=256*1024)
        return _json(stream.read(256*1024+1),256*1024)


def _job_identity():
    _need(os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH and
          os.environ.get('GITHUB_WORKFLOW_REF')==REPOSITORY+'/'+WORKFLOW_PATH+'@refs/heads/'+BRANCH)
    return dict(event_name=os.environ.get('GITHUB_EVENT_NAME'),repository=os.environ.get('GITHUB_REPOSITORY'),
        repository_id=int(os.environ.get('GITHUB_REPOSITORY_ID','0')),workflow_id=WORKFLOW_ID,
        head_branch=BRANCH,head_sha=os.environ.get('GITHUB_SHA'),run_id=int(os.environ.get('GITHUB_RUN_ID','0')))


def _write_cipher(out,raw):
    out=Path(out).absolute()
    with _parent_handle(out.parent) as parent:
        os.mkdir(out.name,0o700,dir_fd=parent)
        fd=os.open(out.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        try:_write_at(fd,CIPHER_MEMBER,raw)
        finally:os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['receive'])
    parser.add_argument('--event-file',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        identity=_job_identity()
        summary,cipher=receive_publication(_event_file(args.event_file),identity=identity)
        if cipher is not None:
            # Recheck immediately before the create-only ciphertext export.
            decrypt_publication(cipher,expected_head_sha=identity['head_sha'],available_at=_now())
            _write_cipher(args.out,cipher)
    except Exception:summary=_summary('HOLD_PUBLICATION_INPUT_REJECTED')
    try:
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                output.write('ready='+('true' if summary['ready'] else 'false')+'\n')
                output.write('status='+summary['status']+'\n')
                output.write('context_count='+str(summary['context_count'])+'\n')
                output.write('cipher_sha256='+summary.get('cipher_sha256','')+'\n')
    except Exception:
        summary=_summary('HOLD_PUBLICATION_OUTPUT_REJECTED')
    print(json.dumps(summary,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
