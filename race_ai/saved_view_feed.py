"""Display-only encrypted Git feed. No source HTTP, forecasts or root-state writes."""
import base64
from copy import deepcopy
import os
from pathlib import Path
import re
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from .actions_contract import digest
from .boat_history_store import wire,instant
from .boat_pdca_state import need,sha
from .boat_pdca_recipient import _private,_receiver,_json,_decode,REPO_ID
from .boat_pdca_github_handoff import GitStateRepository
from .saved_pages import MAX_VIEW,MAX_WIRE,_hex,_envelope
from .saved_result_sync import _merge,parse_capture,project_observation
from scripts.boat_history_collect import private_root,save

BOOT='RACE_AI_SAVED_VIEW_BOOTSTRAP_V1'
FEED='RACE_AI_SAVED_WEB_VIEW_V3'
REF='state/boat-saved-view'
DOMAIN=b'RACE_AI_SAVED_VIEW_BOOTSTRAP_V1'
MUTABLE={'result','result_revisions','result_observations','result_observation_rejections','missing_reasons'}

def originals_sha(view):
    need(type(view) is dict and view.get('schema')=='RACE_AI_PRIVATE_CYCLE_VIEW_V1'
         and type(view.get('records')) is list and 0<len(view['records'])<=5000,'FEED_VIEW_REQUIRED')
    records=[{k:v for k,v in r.items() if k not in MUTABLE} for r in view['records']]
    need(len({r['race_id'] for r in records})==len(records),'FEED_DUPLICATE_RACE')
    return digest(records)

def _session(shared,header):
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=REPO_ID.encode(),
                info=DOMAIN+wire(header).encode()).derive(shared)

def seal_bootstrap(key,view_id,cipher_sha,pages_commit,forecast_sha,receiver):
    need(type(key) is bytes and len(key)==32,'FEED_DISPLAY_KEY_REQUIRED')
    for value in (view_id,cipher_sha,forecast_sha):_hex(value)
    need(re.fullmatch('[a-f0-9]{40}',pages_commit) is not None,'FEED_SEED_COMMIT')
    public=_receiver(receiver);private=X25519PrivateKey.generate()
    header=dict(schema=BOOT,repository_id=REPO_ID,recipient_key_id=sha(public),
                ephemeral_public_key=base64.b64encode(private.public_key().public_bytes_raw()).decode(),
                view_id=view_id,cipher_sha256=cipher_sha,pages_commit=pages_commit,forecast_sha256=forecast_sha)
    nonce=os.urandom(12)
    cipher=AESGCM(_session(private.exchange(X25519PublicKey.from_public_bytes(public)),header)).encrypt(nonce,key,wire(header).encode())
    return (wire(dict(header=header,nonce=base64.b64encode(nonce).decode(),ciphertext=base64.b64encode(cipher).decode()))+'\n').encode()

def open_bootstrap(raw,*,key=None):
    doc=_json(raw,4096);need(type(doc) is dict and set(doc)=={'header','nonce','ciphertext'},'FEED_BOOTSTRAP_INVALID')
    h=doc['header'];fields={'schema','repository_id','recipient_key_id','ephemeral_public_key','view_id','cipher_sha256','pages_commit','forecast_sha256'}
    need(type(h) is dict and set(h)==fields and h['schema']==BOOT and h['repository_id']==REPO_ID,'FEED_BOOTSTRAP_SCOPE')
    for field in ('recipient_key_id','view_id','cipher_sha256','forecast_sha256'):_hex(h[field])
    need(re.fullmatch('[a-f0-9]{40}',h['pages_commit']) is not None,'FEED_SEED_COMMIT')
    private=_private(key);need(sha(private.public_key().public_bytes_raw())==h['recipient_key_id'],'FEED_RECIPIENT_MISMATCH')
    pub=_decode(h['ephemeral_public_key'],32);nonce=_decode(doc['nonce'],12);cipher=_decode(doc['ciphertext'],48)
    need(len(pub)==32 and len(nonce)==12 and len(cipher)==48,'FEED_BOOTSTRAP_INVALID')
    try:display=AESGCM(_session(private.exchange(X25519PublicKey.from_public_bytes(pub)),h)).decrypt(nonce,cipher,wire(h).encode())
    except Exception:raise ValueError('FEED_BOOTSTRAP_AUTH_FAILED') from None
    return dict(h,key=display)

def _header(h):
    need(type(h) is dict and set(h)=={'schema','source_content_sha256','view_id','forecast_sha256','generation','previous_cipher_sha256'}
         and h['schema']==FEED and type(h['generation']) is int and 1<=h['generation']<=999999,'FEED_HEADER_INVALID')
    for f in ('source_content_sha256','view_id','forecast_sha256','previous_cipher_sha256'):_hex(h[f])
    return h

def encrypt_view(view,key,*,view_id,source_sha,generation,previous):
    h=_header(dict(schema=FEED,source_content_sha256=source_sha,view_id=view_id,
                   forecast_sha256=originals_sha(view),generation=generation,previous_cipher_sha256=previous))
    plain=wire(view).encode();need(0<len(plain)<=MAX_VIEW,'FEED_VIEW_BOUND');nonce=os.urandom(12)
    cipher=AESGCM(key).encrypt(nonce,plain,wire(h).encode())
    raw=(wire(dict(header=h,nonce=base64.b64encode(nonce).decode(),ciphertext=base64.b64encode(cipher).decode()))+'\n').encode()
    need(len(raw)<=MAX_WIRE,'FEED_CIPHER_BOUND');return raw

def decrypt_view(raw,key,*,view_id):
    doc=_json(raw,MAX_WIRE);need(type(doc) is dict and set(doc)=={'header','nonce','ciphertext'},'FEED_CIPHER_INVALID')
    h=doc['header']
    if h.get('schema')==FEED:_header(h)
    else:_envelope(raw)
    need((sha(raw)==view_id if h.get('schema')=='RACE_AI_SAVED_WEB_VIEW_V1' else h.get('view_id')==view_id),'FEED_VIEW_ID_MISMATCH')
    nonce=_decode(doc['nonce'],12);cipher=_decode(doc['ciphertext'],MAX_VIEW+16)
    need(len(nonce)==12 and 16<=len(cipher)<=MAX_VIEW+16,'FEED_CIPHER_INVALID')
    try:plain=AESGCM(key).decrypt(nonce,cipher,wire(h).encode())
    except Exception:raise ValueError('FEED_AUTH_FAILED') from None
    view=_json(plain,MAX_VIEW);forecast=originals_sha(view)
    if h.get('schema')==FEED:need(forecast==h['forecast_sha256'],'FEED_FORECAST_MISMATCH')
    return h,view

def update_view(view,observations,*,synced_at,captures=()):
    """Append observations; latest pending/rejected evidence never falls back."""
    instant(synced_at);pin=originals_sha(view);out=deepcopy(view)
    from datetime import date
    from .official_race_updates import endpoint
    rows={endpoint(date.fromisoformat(r['event_date_jst']),r['race_id'][9:11],int(r['race_id'][-2:]),'raceresult'):r for r in out['records']}
    parsed=[]
    for raw,receipt in captures:
        need(receipt.get('http_status')==200 and sha(raw)==receipt.get('source_sha256'),'FEED_CAPTURE_HASH')
        row=rows.get(receipt.get('source_url'))
        if row is None:continue
        instant(receipt['captured_at'])
        try:parsed.append(parse_capture(raw,receipt))
        except Exception:
            # Source layouts are isolated per race, just like the native audit.
            # Keep the newer rejection visible rather than reuse an old final.
            parsed.append(dict(race_id=row['race_id'],closed_at=row['cutoff_at'],captured_at=receipt['captured_at'],
                source_sha256=receipt['source_sha256'],source_url=receipt['source_url'],body_identity_verified=False,
                status='UNSUPPORTED',data=None,source_parse_rejected=True))
    raw_ids={digest(o) for o in parsed}
    by_capture={(o['race_id'],instant(o['captured_at'])):o for o in _merge(parsed)}
    observations=_merge(observations);native={(o['race_id'],instant(o['captured_at'])):o for o in observations}
    for identity,o in by_capture.items():
        if identity in native:
            need(native[identity].get('source_sha256')==o.get('source_sha256'),'RESULT_CAPTURE_CONFLICT')
        else:observations.append(o)
    by_race={}
    for o in _merge(observations):by_race.setdefault(o['race_id'],[]).append(o)
    for row in out['records']:
        incoming=by_race.get(row['race_id'],[])
        if not incoming:continue
        old=row['result_observations'];merged=_merge([*old,*incoming]);row['result_observations']=merged
        latest=max(merged,key=lambda o:instant(o['captured_at']))
        if old and digest(latest)==digest(max(old,key=lambda o:instant(o['captured_at']))):continue
        need(instant(latest['captured_at'])<=instant(synced_at),'FEED_FUTURE_OBSERVATION')
        row['result_observation_rejections']=[]
        row['missing_reasons']=[r for r in row['missing_reasons'] if r!='LATEST_RESULT_OBSERVATION_REJECTED']
        # Native observations keep their ST and other source fields. The raw
        # parser supplies this display projection only; next runners can replay
        # the exact native journal without needing the previous raw cache.
        selected=by_capture.get((latest['race_id'],instant(latest['captured_at'])),latest)
        try:row['result']=project_observation(selected,row,freeze_at=row['prediction']['persisted_at'],raw_bound=digest(selected) in raw_ids)
        except (KeyError,ValueError,TypeError) as error:
            reason=str(error) if re.fullmatch('[A-Z][A-Z0-9_]{1,199}',str(error)) else 'RESULT_OBSERVATION_INVALID'
            row['result']=dict(status='unsupported',winning_combinations=[],confirmed_at=None,observed_at=latest['captured_at'],official=False,source_sha256=latest.get('source_sha256'))
            row['result_observation_rejections']=[dict(captured_at=latest['captured_at'],source_sha256=latest.get('source_sha256'),reason=reason)]
            row['missing_reasons'].append('LATEST_RESULT_OBSERVATION_REJECTED')
    out['results_synced_at']=synced_at;need(originals_sha(out)==pin,'FEED_ORIGINAL_CHANGED');return out

class FeedRepository(GitStateRepository):
    """Fixed display-only ref; original checkpoint authority is unchanged."""
    def __init__(self,repo):
        super().__init__(repo);self.ref=REF

    def validate_tree(self,commit):
        rows=self._run(['ls-tree','-r','--format=%(objectmode)\t%(path)',commit]).decode().splitlines()
        need(0<len(rows)<=10000,'FEED_TREE_BOUND')
        for row in rows:
            mode,tab,path=row.partition('\t')
            need(mode=='100644' and tab and (path=='latest.json' or re.fullmatch('views/[a-f0-9]{64}\\.json',path)),'FEED_TREE_REJECTED')
            if path!='latest.json':
                raw=self.read(commit,path,MAX_WIRE);need(sha(raw)==Path(path).stem,'FEED_HISTORY_HASH')
                _header(_json(raw,MAX_WIRE)['header'])

def current_view(git,bootstrap):
    parent=git.head()
    if parent is None:
        commit=bootstrap['pages_commit'];git.fetch(commit);ident=bootstrap['cipher_sha256']
        raw=git.read(commit,'views/'+ident+'.json',MAX_WIRE)
        need(sha(raw)==ident,'FEED_SEED_HASH')
        h,view=decrypt_view(raw,bootstrap['key'],view_id=bootstrap['view_id']);generation=0
    else:
        git.fetch(parent);git.validate_tree(parent)
        latest=_json(git.read(parent,'latest.json',4096),4096)
        need(type(latest) is dict and set(latest)=={'header','cipher_sha256'},'FEED_MANIFEST_INVALID')
        h=_header(latest['header']);ident=_hex(latest['cipher_sha256'])
        raw=git.read(parent,'views/'+ident+'.json',MAX_WIRE);need(sha(raw)==ident,'FEED_CIPHER_HASH')
        header,view=decrypt_view(raw,bootstrap['key'],view_id=bootstrap['view_id'])
        need(header==h,'FEED_MANIFEST_MISMATCH');generation=h['generation']
    need(originals_sha(view)==bootstrap['forecast_sha256'],'FEED_ORIGINAL_CHANGED')
    return parent,ident,generation,view

def publish_view(git,bootstrap,view,*,parent,previous,generation):
    need(git.ref==REF and git.head()==parent,'FEED_CONCURRENT_UPDATE')
    need(originals_sha(view)==bootstrap['forecast_sha256'],'FEED_ORIGINAL_CHANGED')
    raw=encrypt_view(view,bootstrap['key'],view_id=bootstrap['view_id'],source_sha=bootstrap['cipher_sha256'],generation=generation+1,previous=previous)
    h=_json(raw,MAX_WIRE)['header'];ident=sha(raw)
    files={'views/'+ident+'.json':raw,'latest.json':(wire(dict(header=h,cipher_sha256=ident))+'\n').encode()}
    commit=git.commit(files,parent);git.validate_tree(commit);git.push(commit,parent)
    for path,body in files.items():need(git.read(commit,path,MAX_WIRE)==body,'FEED_READBACK_MISMATCH')
    return dict(status='ENCRYPTED_VIEW_PUBLISHED',generation=generation+1,commit=commit,cipher_sha256=ident)

def retain_capture(folder,raw,receipt):
    root=private_root(folder);need(sha(raw)==receipt['source_sha256'],'FEED_CAPTURE_HASH')
    need(0<len(raw)<=4*1024*1024,'FEED_CAPTURE_BOUND')
    save(root/(sha(raw)+'.html'),raw)
    save(root/(digest(receipt)+'.json'),(wire(receipt)+'\n').encode())

def load_captures(folder):
    folder=Path(folder)
    if not folder.exists():return []
    root=private_root(folder);receipts=sorted(root.glob('*.json'));need(len(receipts)<=240,'FEED_CAPTURE_COUNT')
    out=[]
    from .saved_pages import _read
    for path in receipts:
        receipt=_json(_read(path,4096),4096);need(digest(receipt)==path.stem,'FEED_CAPTURE_RECEIPT_HASH')
        raw=_read(root/(_hex(receipt['source_sha256'])+'.html'),4*1024*1024)
        need(sha(raw)==receipt['source_sha256'],'FEED_CAPTURE_HASH');out.append((raw,receipt))
    return out
