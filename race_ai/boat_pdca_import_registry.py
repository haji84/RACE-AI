"""Reuse authenticated initial import streams without resetting canonical state.

The owner MAC binds a once-verified independent consumer proof to immutable
encrypted Git storage. A different transfer still uses the original receiver
and generation checks. This module never pushes or changes a canonical ref.
"""
from datetime import datetime,timezone
import hmac
from pathlib import Path
import tempfile

from .boat_history_store import wire
from .boat_pdca_state import state_key,restore_state,sha,need,MAX_CIPHER
from .boat_pdca_github_handoff import _scope,_audit,_fetch_cipher,REPO
from .boat_pdca_recipient import _json,_file,_hex,_run,_pointer,verify_received_checkpoint,HEAD
from scripts.boat_history_collect import private_root,save

SCHEMA='RACE_AI_BOAT_ACCEPTED_IMPORTS_V1'
ENTRY='RACE_AI_BOAT_ACCEPTED_INITIAL_IMPORT_V1'
DOMAIN=b'RACE_AI_BOAT_ACCEPTED_INITIAL_IMPORT_V1\0'


def _mac(entry,key):
    return hmac.new(key,DOMAIN+wire(entry).encode(),'sha256').hexdigest()


def register_import(folder,consumer_proof,*,expected_consumer_sha,archive_commit,key=None,now=None):
    """Caller pins the consumer-file hash from verified GitHub artifact bytes."""
    key=state_key('production',key);_hex(archive_commit,HEAD)
    raw=_file(consumer_proof,32768);need(sha(raw)==expected_consumer_sha,'IMPORT_CONSUMER_PIN_REQUIRED')
    consumer=_json(raw,32768)
    need(consumer.get('status')=='OWNER_PDCA_TRANSFER_READBACK_VERIFIED' and
         consumer.get('production_schema_readback_verified') is True,'IMPORT_INDEPENDENT_CONSUMER_REQUIRED')
    folder=Path(folder);handoff=_json(_file(folder/'handoff-proof.json',16384),16384)
    with tempfile.TemporaryDirectory(prefix='boat-accepted-import-') as temp:
        report=verify_received_checkpoint(folder,private_root(Path(temp)/'verified'),key=key,
            expected_run_id=consumer['producer_run_id'],expected_source_head=consumer['source_head'],
            expected_transfer_sha=consumer['transfer_sha256'],now=now)
    inventory=handoff['source_inventory'];scope=_scope(handoff['scope'])
    need(scope['generation']==1 and all(consumer.get(k)==v for k,v in inventory.items()) and
         all(consumer.get(k)==report.get(k) for k in ('scope','cipher_sha256','recipient_key_id')),
         'IMPORT_CONSUMER_CONTENT_MISMATCH')
    entry=dict(schema=ENTRY,repository_id='1416489937',transfer_sha256=consumer['transfer_sha256'],
        producer_run_id=consumer['producer_run_id'],source_head=consumer['source_head'],
        recipient_key_id=consumer['recipient_key_id'],archive_commit=archive_commit,
        archive_folder='state/boat-pdca-imports/v1/'+consumer['transfer_sha256'],
        cipher_sha256=consumer['cipher_sha256'],scope=scope,source_inventory=inventory,
        consumer_file_sha256=expected_consumer_sha)
    entry['mac']=_mac(entry,key);return entry


def reuse_import(pointer,registry,root,*,key=None,fetch=None,now=None):
    """Unknown inputs return None so the original strict receiver remains active."""
    need(type(registry) is dict and set(registry)=={'schema','repository_id','imports'} and
         registry['schema']==SCHEMA and registry['repository_id']=='1416489937' and
         type(registry['imports']) is list and len(registry['imports'])<=288,'IMPORT_REGISTRY_INVALID')
    if type(pointer) is not dict or pointer.get('status')!='READY':return None
    if not registry['imports']:return None
    try:key=state_key('production',key)
    except ValueError:return dict(status='HOLD_OWNER_STATE_KEY_MISSING',encrypted_checkpoint_created=False,source_gets=0)
    entries=[]
    fields={'schema','repository_id','transfer_sha256','producer_run_id','source_head','recipient_key_id',
            'archive_commit','archive_folder','cipher_sha256','scope','source_inventory','consumer_file_sha256','mac'}
    for item in registry['imports']:
        need(type(item) is dict and set(item)==fields,'IMPORT_ENTRY_INVALID')
        entry=dict(item);tag=entry.pop('mac')
        need(type(tag) is str and hmac.compare_digest(tag,_mac(entry,key)),'IMPORT_REGISTRY_AUTHENTICATION_FAILED')
        need(entry['schema']==ENTRY and entry['repository_id']=='1416489937' and
             entry['archive_folder']=='state/boat-pdca-imports/v1/'+_hex(entry['transfer_sha256']), 'IMPORT_PATH_INVALID')
        _hex(entry['archive_commit'],HEAD)
        _hex(entry['cipher_sha256']);_run(entry['producer_run_id']);_scope(entry['scope'])
        entries.append(entry)
    need(len({e['transfer_sha256'] for e in entries})==len(entries),'IMPORT_DUPLICATE_ENTRY')
    pointer=_pointer(pointer);matches=[e for e in entries if e['transfer_sha256']==pointer['cipher_sha256']]
    if not matches:return None
    entry=matches[0]
    need(entry['recipient_key_id']==pointer['scope']['recipient_key_id'] and entry['scope']['generation']==1,
         'IMPORT_OWNER_OR_GENERATION_MISMATCH')
    url='https://raw.githubusercontent.com/'+REPO+'/'+entry['archive_commit']+'/'+entry['archive_folder']+'/state.enc'
    raw=(fetch or _fetch_cipher)(url)
    need(type(raw) is bytes and len(raw)<=MAX_CIPHER and sha(raw)==entry['cipher_sha256'],'IMPORT_CIPHERTEXT_HASH_MISMATCH')
    root=private_root(root);save(root/'import.enc',raw)
    state=restore_state(root/'import.enc',root/'state.sqlite',expected_sha256=entry['cipher_sha256'],expected_scope=entry['scope'],key=key)
    try:
        need(state.inventory()==entry['source_inventory'],'IMPORT_INVENTORY_CHANGED')
        report=_audit(state,root,now or datetime.now(timezone.utc))
    finally:state.close()
    return dict(report,status='REUSED_VERIFIED_OWNER_INITIAL_IMPORT',production_schema_readback_verified=True,
        encrypted_checkpoint_created=False,canonical_state_changed=False,source_gets=1,
        original_independent_consumer_run=entry['producer_run_id'],transfer_sha256=entry['transfer_sha256'])
