"""Deliver private state to the existing Actions owner's public recipient.

The root RACE_AI_STATE_KEY never leaves Actions. Canonical storage still uses
the existing production AES-GCM checkpoint, not the transport session key.
Caller pins receiver bytes/run/reviewed head from independently read GitHub
artifact metadata before encrypting any actual data.
"""
import base64
from datetime import datetime,timezone
import gzip
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .boat_history_store import wire
from .boat_pdca_state import PdcaState,sha,need,state_key,sqlite_snapshot,inflate,restore_state,scope_for
from .boat_pdca_github_handoff import (_audit,_no_regression,_scope,_cipher_path,_fetch_cipher,readback,
    REPO,INPUT_SCHEMA,GitStateRepository,TRANSFER_REF,STATE_REF,HEAD_PATH)
from scripts.boat_history_collect import private_root,save

REPO_ID='1416489937'
RECEIVER_SCHEMA='RACE_AI_BOAT_OWNER_RECIPIENT_V1'
INPUT='RACE_AI_BOAT_TRANSFER_INPUT_V1'
ENVELOPE='RACE_AI_BOAT_OWNER_TRANSFER_V2'
HANDOFF='RACE_AI_BOAT_OWNER_TRANSFER_PROOF_V2'
DOMAIN=b'RACE_AI_BOAT_PDCA_OWNER_RECIPIENT_V1'
MAX_TRANSFER=96*1024*1024
HEAD=re.compile(r'[a-f0-9]{40}\Z')
SHA=re.compile(r'[a-f0-9]{64}\Z')


def _hex(value,pattern=SHA):
    need(type(value) is str and pattern.fullmatch(value),'RECIPIENT_IDENTITY_INVALID');return value


def _run(value):
    need(type(value) is str and re.fullmatch(r'[1-9][0-9]{0,19}',value),'RECIPIENT_RUN_INVALID');return value


def _decode(value,size):
    need(type(value) is str and len(value)<=4*((size+2)//3),'RECIPIENT_BASE64_INVALID')
    try:raw=base64.b64decode(value,validate=True)
    except ValueError:raise ValueError('RECIPIENT_BASE64_INVALID') from None
    need(len(raw)<=size and base64.b64encode(raw).decode()==value,'RECIPIENT_BASE64_INVALID');return raw


def _json(raw,limit):
    need(type(raw) is bytes and 0<len(raw)<=limit,'RECIPIENT_JSON_BOUND_INVALID')
    def unique(items):
        out={}
        for k,v in items:
            need(k not in out,'RECIPIENT_DUPLICATE_JSON_KEY');out[k]=v
        return out
    try:
        return json.loads(raw,object_pairs_hook=unique,
            parse_constant=lambda _:(_ for _ in ()).throw(ValueError('RECIPIENT_JSON_INVALID')))
    except (UnicodeError,json.JSONDecodeError,RecursionError):raise ValueError('RECIPIENT_JSON_INVALID') from None


def _file(path,limit):
    path=Path(path)
    need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=limit,'RECIPIENT_FILE_BOUND_INVALID')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:raw=stream.read(limit+1)
    need(0<len(raw)<=limit,'RECIPIENT_FILE_BOUND_INVALID');return raw


def _private(key):
    key=state_key('production',key)
    return X25519PrivateKey.from_private_bytes(HKDF(algorithm=hashes.SHA256(),length=32,
        salt=REPO_ID.encode(),info=DOMAIN+b'/owner-private').derive(key))


def receiver_document(*,key=None,run_id,source_head):
    public=_private(key).public_key().public_bytes_raw()
    return dict(schema=RECEIVER_SCHEMA,repository_id=REPO_ID,mode='production',
        public_key=base64.b64encode(public).decode(),key_id=sha(public),
        run_id=_run(run_id),source_head=_hex(source_head,HEAD))


def _receiver(value):
    need(type(value) is dict and set(value)=={'schema','repository_id','mode','public_key','key_id','run_id','source_head'}
         and value['schema']==RECEIVER_SCHEMA and value['repository_id']==REPO_ID and value['mode']=='production',
         'RECIPIENT_DOCUMENT_INVALID')
    raw=_decode(value['public_key'],32);need(len(raw)==32 and sha(raw)==value['key_id'],'RECIPIENT_PUBLIC_KEY_INVALID')
    _run(value['run_id']);_hex(value['source_head'],HEAD);return raw


def _previous(value):
    need(type(value) is dict and set(value)=={'schema','status','repository_id','source_commit','cipher_path','cipher_sha256','scope'}
         and value['schema']==INPUT_SCHEMA and value['status']=='READY' and value['repository_id']==REPO_ID,
         'RECIPIENT_PREVIOUS_INPUT_REQUIRED')
    scope=_scope(value['scope']);_hex(value['source_commit'],HEAD);_hex(value['cipher_sha256'])
    need(value['cipher_path']==_cipher_path(scope),'RECIPIENT_PREVIOUS_PATH_INVALID');return scope


def _header(value):
    fields={'schema','repository_id','mode','generation','previous_cipher_sha256','previous_source_commit',
            'recipient_key_id','source_state_sha256','source_content_sha256','receiver_document_sha256','receiver_run_id','receiver_source_head'}
    need(type(value) is dict and set(value)==fields and value['schema']==ENVELOPE and value['repository_id']==REPO_ID
         and value['mode']=='production','RECIPIENT_SCOPE_INVALID')
    scope_for('production',value['generation'],value['previous_cipher_sha256'])
    need(value['generation']<=999999,'RECIPIENT_GENERATION_BOUND')
    if value['generation']==1:need(value['previous_source_commit'] is None,'RECIPIENT_PREVIOUS_COMMIT_INVALID')
    else:_hex(value['previous_source_commit'],HEAD)
    for field in ('recipient_key_id','source_state_sha256','source_content_sha256','receiver_document_sha256'):_hex(value[field])
    _run(value['receiver_run_id']);_hex(value['receiver_source_head'],HEAD);return value


def _session(shared,header,ephemeral,recipient):
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=recipient,
        info=DOMAIN+b'/transport/'+ephemeral+wire(header).encode()).derive(shared)


def encrypt_transfer(state_path,receiver,*,expected_receiver_sha,expected_run_id,expected_source_head,
                     output,previous_pointer=None,now=None):
    public=_receiver(receiver)
    need(sha((wire(receiver)+'\n').encode())==_hex(expected_receiver_sha) and
         receiver['run_id']==_run(expected_run_id) and receiver['source_head']==_hex(expected_source_head,HEAD),
         'RECIPIENT_INDEPENDENT_PIN_REQUIRED')
    ephemeral=X25519PrivateKey.generate();epub=ephemeral.public_key().public_bytes_raw()
    try:shared=ephemeral.exchange(X25519PublicKey.from_public_bytes(public))
    except ValueError:raise ValueError('RECIPIENT_PUBLIC_KEY_INVALID') from None
    previous=_previous(previous_pointer) if previous_pointer is not None else None
    state=PdcaState(state_path)
    try:
        need(state.mode=='production','RECIPIENT_PRODUCTION_STATE_REQUIRED')
        raw=sqlite_snapshot(state_path)
    finally:state.close()
    root=private_root(output);save(root/'source.sqlite',raw);snapshot=PdcaState(root/'source.sqlite')
    try:
        audited=_audit(snapshot,private_root(root/'verification'),now or datetime.now(timezone.utc))
        content_id=audited['state_content_sha256']
    finally:snapshot.close()
    header=_header(dict(schema=ENVELOPE,repository_id=REPO_ID,mode='production',generation=previous['generation']+1 if previous else 1,
        previous_cipher_sha256=previous_pointer['cipher_sha256'] if previous else None,
        previous_source_commit=previous_pointer['source_commit'] if previous else None,
        recipient_key_id=receiver['key_id'],source_state_sha256=sha(raw),source_content_sha256=content_id,
        receiver_document_sha256=expected_receiver_sha,
        receiver_run_id=expected_run_id,receiver_source_head=expected_source_head))
    nonce=os.urandom(12);cipher=AESGCM(_session(shared,header,epub,public)).encrypt(nonce,
        gzip.compress(raw,compresslevel=3,mtime=0),wire(header).encode())
    envelope=(wire(dict(header=header,ephemeral_public_key=base64.b64encode(epub).decode(),
        nonce=base64.b64encode(nonce).decode(),ciphertext=base64.b64encode(cipher).decode()))+'\n').encode()
    need(len(envelope)<=MAX_TRANSFER,'RECIPIENT_CIPHERTEXT_BOUND')
    save(root/'transfer.enc',envelope)
    report=dict(schema=INPUT,status='ENCRYPTED_LOCAL_TRANSFER',repository_id=REPO_ID,cipher_sha256=sha(envelope),scope=header)
    save(root/'transfer-metadata.json',(wire(report)+'\n').encode());return report


def _pointer(value):
    need(type(value) is dict and set(value)=={'schema','status','repository_id','cipher_sha256','scope','source_commit','cipher_path'}
         and value['schema']==INPUT and value['status']=='READY' and value['repository_id']==REPO_ID,'RECIPIENT_POINTER_INVALID')
    _header(value['scope']);_hex(value['source_commit'],HEAD);_hex(value['cipher_sha256'])
    need(value['cipher_path']=='state/boat-pdca-incoming/v1/'+value['cipher_sha256']+'.enc','RECIPIENT_PATH_INVALID')
    return value


def _already_covered(pointer,plain,current_pointer,root,*,key,fetch,clock):
    """A stale offer is a no-op only after both states are restored and audited.

    Comparison copies never become another canonical checkpoint. In particular,
    generation numbers, inventory counts or transfer headers alone cannot prove
    that the current state preserves every immutable incoming original.
    """
    root=private_root(root)
    with TemporaryDirectory(dir=root,prefix='.covered-state-check-') as folder:
        scratch=Path(folder);save(scratch/'incoming.sqlite',plain)
        incoming=PdcaState(scratch/'incoming.sqlite')
        try:
            need(incoming.mode=='production','RECIPIENT_PRODUCTION_STATE_REQUIRED')
            _audit(incoming,private_root(scratch/'incoming-verification'),clock)
            need(incoming.content_sha256()==pointer['scope']['source_content_sha256'],'RECIPIENT_SOURCE_CONTENT_MISMATCH')
            current_root=private_root(scratch/'current')
            report=readback(current_pointer,current_root,key=key,fetch=fetch,now=clock)
            need(report.get('production_schema_readback_verified') is True,'RECIPIENT_PREVIOUS_RESTORE_REQUIRED')
            current=PdcaState(current_root/'state.sqlite')
            try:
                content_id=pointer['scope']['source_content_sha256']
                manifest='source-states/v1/'+content_id+'/manifest.json'
                if current.db.execute('SELECT 1 FROM heads WHERE name=?',(manifest,)).fetchone():
                    current.verify_contribution(content_id)
                else:_no_regression(incoming,current)
            finally:current.close()
        finally:incoming.close()
    return dict(report,status='OWNER_PDCA_TRANSFER_ALREADY_COVERED',encrypted_checkpoint_created=False,
        incoming_originals_covered=True,cipher_sha256=current_pointer['cipher_sha256'],
        incoming_content_sha256=pointer['scope']['source_content_sha256'],
        scope=current_pointer['scope'],transfer_sha256=pointer['cipher_sha256'],source_gets=2)


def receive_transfer(pointer,root,*,key=None,fetch=None,run_id,source_head,previous_pointer=None,now=None):
    try:key=state_key('production',key)
    except ValueError:return dict(status='HOLD_OWNER_STATE_KEY_MISSING',source_gets=0,encrypted_checkpoint_created=False)
    if type(pointer) is dict and pointer.get('schema')==INPUT and pointer.get('repository_id')==REPO_ID and pointer.get('status')=='WAITING_TRANSFER':
        return dict(status='HOLD_TRANSFER_INPUT_REQUIRED',source_gets=0,encrypted_checkpoint_created=False)
    pointer=_pointer(pointer);header=pointer['scope'];_run(run_id);_hex(source_head,HEAD)
    owner=_private(key);public=owner.public_key().public_bytes_raw()
    need(sha(public)==header['recipient_key_id'],'RECIPIENT_OWNER_KEY_MISMATCH')
    current_scope=_previous(previous_pointer) if previous_pointer is not None else None
    covered_candidate=current_scope is not None and header['generation']<=current_scope['generation']
    if not covered_candidate and header['generation']==1:
        need(previous_pointer is None,'RECIPIENT_UNEXPECTED_PREVIOUS_STATE')
    elif not covered_candidate:
        old=current_scope if current_scope is not None else _previous(previous_pointer)
        need(old['generation']+1==header['generation'] and previous_pointer['cipher_sha256']==header['previous_cipher_sha256']
             and previous_pointer['source_commit']==header['previous_source_commit'],'RECIPIENT_PREVIOUS_STATE_MISMATCH')
    url='https://raw.githubusercontent.com/'+REPO+'/'+pointer['source_commit']+'/'+pointer['cipher_path']
    raw=(fetch or _fetch_cipher)(url)
    need(type(raw) is bytes and len(raw)<=MAX_TRANSFER and sha(raw)==pointer['cipher_sha256'],'RECIPIENT_CIPHER_HASH_MISMATCH')
    envelope=_json(raw,MAX_TRANSFER)
    need(type(envelope) is dict and set(envelope)=={'header','ephemeral_public_key','nonce','ciphertext'}
         and envelope['header']==header,'RECIPIENT_ENVELOPE_INVALID')
    epub=_decode(envelope['ephemeral_public_key'],32);nonce=_decode(envelope['nonce'],12)
    need(len(epub)==32 and len(nonce)==12,'RECIPIENT_AEAD_PARAMETERS_INVALID')
    ciphertext=_decode(envelope['ciphertext'],MAX_TRANSFER)
    try:
        shared=owner.exchange(X25519PublicKey.from_public_bytes(epub))
        compressed=AESGCM(_session(shared,header,epub,public)).decrypt(nonce,ciphertext,wire(header).encode())
    except Exception:raise ValueError('RECIPIENT_TRANSFER_AUTHENTICATION_FAILED') from None
    plain=inflate(compressed);need(sha(plain)==header['source_state_sha256'],'RECIPIENT_PLAINTEXT_HASH_MISMATCH')
    if covered_candidate:
        return _already_covered(pointer,plain,previous_pointer,root,key=key,fetch=fetch,
            clock=now or datetime.now(timezone.utc))
    root=private_root(root);save(root/'incoming.sqlite',plain);incoming=PdcaState(root/'incoming.sqlite')
    state=None;oldstate=None
    try:
        need(incoming.mode=='production','RECIPIENT_PRODUCTION_STATE_REQUIRED')
        clock=now or datetime.now(timezone.utc)
        _audit(incoming,private_root(root/'incoming-check'),clock)
        need(incoming.content_sha256()==header['source_content_sha256'],'RECIPIENT_SOURCE_CONTENT_MISMATCH')
        state=PdcaState.create(root/'canonical.sqlite',mode='production')
        if previous_pointer is not None:
            oldroot=private_root(root/'previous')
            previous_report=readback(previous_pointer,oldroot,key=key,fetch=fetch,now=clock)
            need(previous_report.get('production_schema_readback_verified') is True,'RECIPIENT_PREVIOUS_RESTORE_REQUIRED')
            oldstate=PdcaState(oldroot/'state.sqlite');oldstate.db.backup(state.db)
        contribution=state.merge_from(incoming)
        need(contribution==header['source_content_sha256'],'RECIPIENT_SOURCE_CONTENT_MISMATCH')
        before_scores=state.inventory()['scorings']
        # Independent sources can retain different revisions for one race.
        # Append derived comparisons; original pairs, results and scores stay.
        for pair_sha,json_sha in state.db.execute('SELECT sha,json_sha FROM pairs').fetchall():
            pair=json.loads(state._get(json_sha))
            latest=state.db.execute('SELECT body FROM results WHERE race_id=? ORDER BY captured_at DESC LIMIT 1',
                                    (pair['race_id'],)).fetchone()
            if latest is not None:state.score(pair_sha,json.loads(latest[0]),clock)
        added_scores=state.inventory()['scorings']-before_scores
        if oldstate is not None:_no_regression(oldstate,state)
        report=_audit(state,private_root(root/'incoming-verification'),clock)
        inventory=state.inventory();sealed=private_root(root/'sealed')
        proof=state.checkpoint(sealed,generation=header['generation'],previous_cipher_sha256=header['previous_cipher_sha256'],key=key)
    finally:
        incoming.close()
        if state is not None:state.close()
        if oldstate is not None:oldstate.close()
    handoff=dict(schema=HANDOFF,producer_run_id=run_id,source_head=source_head,transfer_sha256=pointer['cipher_sha256'],
        recipient_key_id=header['recipient_key_id'],source_state_sha256=header['source_state_sha256'],
        cipher_sha256=proof['cipher_sha256'],scope=proof['scope'],source_inventory=inventory,
        incoming_content_sha256=header['source_content_sha256'])
    save(sealed/'handoff-proof.json',(wire(handoff)+'\n').encode())
    return dict(report,status='OWNER_PDCA_TRANSFER_SEALED',encrypted_checkpoint_created=True,
        cipher_sha256=proof['cipher_sha256'],scope=proof['scope'],source_gets=1+(previous_pointer is not None),
        union_derived_scorings_added=added_scores,
        incoming_content_sha256=header['source_content_sha256'],incoming_originals_verified=True)


def verify_received_checkpoint(folder,root,*,key=None,expected_run_id,expected_source_head,expected_transfer_sha,
                               expected_incoming_content_sha256=None,now=None):
    key=state_key('production',key);folder=Path(folder)
    handoff=_json(_file(folder/'handoff-proof.json',16384),16384)
    fields={'schema','producer_run_id','source_head','transfer_sha256','recipient_key_id','source_state_sha256',
            'cipher_sha256','scope','source_inventory','incoming_content_sha256'}
    need(type(handoff) is dict and set(handoff)==fields and handoff['schema']==HANDOFF and
         handoff['producer_run_id']==_run(expected_run_id) and handoff['source_head']==_hex(expected_source_head,HEAD)
         and handoff['transfer_sha256']==_hex(expected_transfer_sha),'RECIPIENT_PRODUCER_IDENTITY_INVALID')
    need(handoff['recipient_key_id']==sha(_private(key).public_key().public_bytes_raw()),'RECIPIENT_OWNER_KEY_MISMATCH')
    _hex(handoff['source_state_sha256']);_hex(handoff['cipher_sha256']);scope=_scope(handoff['scope'])
    contribution=_hex(handoff['incoming_content_sha256'])
    if expected_incoming_content_sha256 is not None:
        need(contribution==_hex(expected_incoming_content_sha256),'RECIPIENT_SOURCE_CONTENT_MISMATCH')
    proof=_json(_file(folder/'proof.json',8192),8192)
    need(proof==dict(scope=scope,cipher_sha256=handoff['cipher_sha256'],synthetic_only=False,plaintext_published=False),
         'RECIPIENT_CHECKPOINT_PROOF_MISMATCH')
    root=private_root(root)
    state=restore_state(folder/'state.enc',root/'state.sqlite',expected_sha256=handoff['cipher_sha256'],expected_scope=scope,key=key)
    try:
        need(state.inventory()==handoff['source_inventory'],'RECIPIENT_INVENTORY_CHANGED')
        state.verify_contribution(contribution)
        report=_audit(state,root,now or datetime.now(timezone.utc))
    finally:state.close()
    return dict(report,status='OWNER_PDCA_TRANSFER_READBACK_VERIFIED',production_schema_readback_verified=True,
        cipher_sha256=handoff['cipher_sha256'],scope=scope,producer_run_id=expected_run_id,
        source_head=expected_source_head,transfer_sha256=expected_transfer_sha,
        recipient_key_id=handoff['recipient_key_id'],incoming_content_sha256=contribution,
        incoming_originals_verified=True,plaintext_published=False)


def publish_incoming(repo,folder,*,transport=None):
    folder=private_root(folder);meta=_json(_file(folder/'transfer-metadata.json',16384),16384)
    need(type(meta) is dict and set(meta)=={'schema','status','repository_id','cipher_sha256','scope'}
         and meta['schema']==INPUT and meta['status']=='ENCRYPTED_LOCAL_TRANSFER' and meta['repository_id']==REPO_ID,
         'RECIPIENT_LOCAL_TRANSFER_INVALID')
    _header(meta['scope']);_hex(meta['cipher_sha256'])
    raw=_file(folder/'transfer.enc',MAX_TRANSFER);need(sha(raw)==meta['cipher_sha256'],'RECIPIENT_CIPHER_HASH_MISMATCH')
    body=_json(raw,MAX_TRANSFER)
    need(type(body) is dict and set(body)=={'header','ephemeral_public_key','nonce','ciphertext'}
         and body['header']==meta['scope'],'RECIPIENT_ENVELOPE_INVALID')
    need(len(_decode(body['ephemeral_public_key'],32))==32 and len(_decode(body['nonce'],12))==12
         and len(_decode(body['ciphertext'],MAX_TRANSFER))>=16,'RECIPIENT_AEAD_PARAMETERS_INVALID')
    git=transport or GitStateRepository(repo,ref=TRANSFER_REF)
    need(git.ref==TRANSFER_REF,'RECIPIENT_TRANSFER_REF_REQUIRED');parent=git.head()
    path='state/boat-pdca-incoming/v1/'+meta['cipher_sha256']+'.enc';metadata=path.removesuffix('.enc')+'.json'
    encoded=(wire(meta)+'\n').encode()
    if parent:
        git.fetch(parent)
        if git.exists(parent,path) or git.exists(parent,metadata):
            need(git.exists(parent,path) and git.exists(parent,metadata)
                 and git.read(parent,path,MAX_TRANSFER)==raw and git.read(parent,metadata,16384)==encoded,
                 'RECIPIENT_IMMUTABLE_TRANSFER_CONFLICT')
            return dict(meta,status='READY',source_commit=parent,cipher_path=path)
    commit=git.commit({path:raw,metadata:encoded},parent);git.push(commit,parent)
    need(git.read(commit,path,MAX_TRANSFER)==raw,'RECIPIENT_TRANSFER_REMOTE_MISMATCH')
    return dict(meta,status='READY',source_commit=commit,cipher_path=path)


def publish_received(repo,folder,*,consumer_proof,expected_run_id,expected_source_head,expected_transfer_sha,
                     expected_consumer_sha,expected_recipient_key_id,expected_incoming_content_sha256=None,
                     initialize=False,expected_parent=None,transport=None):
    """Publish ciphertext after caller authenticates both Actions artifact digests.

    The independently supplied consumer-file hash MUST come from its verified
    same-run, reviewed-head GitHub artifact, not a self-written proof alone.
    Canonical production readback is still required after Git publication.
    """
    folder=private_root(folder);consumer_raw=_file(consumer_proof,32768)
    need(sha(consumer_raw)==_hex(expected_consumer_sha),'RECIPIENT_CONSUMER_PIN_REQUIRED')
    consumer=_json(consumer_raw,32768);handoff=_json(_file(folder/'handoff-proof.json',16384),16384)
    need(type(consumer) is dict and type(handoff) is dict and handoff.get('schema')==HANDOFF
         and consumer.get('status')=='OWNER_PDCA_TRANSFER_READBACK_VERIFIED'
         and consumer.get('production_schema_readback_verified') is True,'RECIPIENT_VERIFIED_CONSUMER_REQUIRED')
    expected={'producer_run_id':_run(expected_run_id),'source_head':_hex(expected_source_head,HEAD),
              'transfer_sha256':_hex(expected_transfer_sha),'recipient_key_id':_hex(expected_recipient_key_id)}
    need(all(consumer.get(k)==v and handoff.get(k)==v for k,v in expected.items()),'RECIPIENT_PRODUCER_IDENTITY_INVALID')
    contribution=_hex(handoff['incoming_content_sha256'])
    need(consumer.get('incoming_content_sha256')==contribution and consumer.get('incoming_originals_verified') is True,
         'RECIPIENT_INCOMING_ORIGINALS_REQUIRED')
    if expected_incoming_content_sha256 is not None:
        need(contribution==_hex(expected_incoming_content_sha256),'RECIPIENT_SOURCE_CONTENT_MISMATCH')
    scope=_scope(handoff['scope']);cipher_sha=_hex(handoff['cipher_sha256'])
    need(consumer.get('scope')==scope and consumer.get('cipher_sha256')==cipher_sha,'RECIPIENT_CONSUMER_CHECKPOINT_MISMATCH')
    inventory=handoff['source_inventory']
    need(type(inventory) is dict and inventory.get('mode')=='production'
         and all(consumer.get(k)==v for k,v in inventory.items()),'RECIPIENT_INVENTORY_CHANGED')
    raw=_file(folder/'state.enc',MAX_TRANSFER);proof_raw=_file(folder/'proof.json',8192)
    need(sha(raw)==cipher_sha,'RECIPIENT_CIPHER_HASH_MISMATCH')
    proof=_json(proof_raw,8192);body=_json(raw,MAX_TRANSFER)
    need(proof==dict(scope=scope,cipher_sha256=cipher_sha,synthetic_only=False,plaintext_published=False)
         and type(body) is dict and set(body)=={'header','nonce','ciphertext'} and body['header']==scope,
         'RECIPIENT_CHECKPOINT_PROOF_MISMATCH')
    need(len(_decode(body['nonce'],12))==12 and len(_decode(body['ciphertext'],MAX_TRANSFER))>=16,
         'RECIPIENT_AEAD_PARAMETERS_INVALID')
    git=transport or GitStateRepository(repo);need(git.ref==STATE_REF,'RECIPIENT_CANONICAL_REF_REQUIRED');parent=git.head()
    if parent is None:
        need(initialize is True and expected_parent is None and scope['generation']==1
             and scope['previous_cipher_sha256'] is None,'RECIPIENT_INITIALIZATION_REQUIRED')
    else:
        need(initialize is False and expected_parent==parent and expected_parent is not None,'RECIPIENT_TRUSTED_PARENT_REQUIRED')
        git.fetch(parent);old=_json(git.read(parent,HEAD_PATH,8192),8192)
        oldscope=_scope(old['scope'])
        need(old['schema']=='RACE_AI_BOAT_ENCRYPTED_HEAD_V1' and old['repository_id']==REPO_ID
             and old['cipher_path']==_cipher_path(oldscope) and scope['generation']==oldscope['generation']+1
             and scope['previous_cipher_sha256']==old['cipher_sha256'],'RECIPIENT_PREVIOUS_STATE_MISMATCH')
    path=_cipher_path(scope);proof_path=path.removesuffix('state.enc')+'proof.json'
    if parent:need(not git.exists(parent,path) and not git.exists(parent,proof_path),'RECIPIENT_GENERATION_EXISTS')
    latest=dict(schema='RACE_AI_BOAT_ENCRYPTED_HEAD_V1',repository_id=REPO_ID,scope=scope,cipher_path=path,cipher_sha256=cipher_sha)
    commit=git.commit({path:raw,proof_path:proof_raw,HEAD_PATH:(wire(latest)+'\n').encode()},parent)
    git.push(commit,parent);need(git.read(commit,path,MAX_TRANSFER)==raw,'RECIPIENT_CANONICAL_REMOTE_MISMATCH')
    return dict(schema=INPUT_SCHEMA,status='READY',repository_id=REPO_ID,source_commit=commit,
                cipher_path=path,cipher_sha256=cipher_sha,scope=scope)
