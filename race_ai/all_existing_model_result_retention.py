"""Append exact authenticated RESULT originals to the existing transfer ref.

This backup creates no vault kind, latest pointer, source grant or new GitHub
receipt. Historical native replay uses its authenticated original admission
clock. The caller still owns independent frozen-input admission and every
current label/training authorization decision.
"""
import base64
import binascii
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import re

from . import all_existing_model_official_results as results
from . import boat_all_model_store as store
from . import boat_private_original_vault as vault
from .boat_pdca_github_handoff import TRANSFER_REF
from .boat_pdca_state import state_key

SCHEMA='RACE_AI_ALL_EXISTING_OFFICIAL_RESULT_RETENTION_V1'
POINTER='RACE_AI_ALL_EXISTING_OFFICIAL_RESULT_RETENTION_POINTER_V1'
PURPOSE='EXACT_OFFICIAL_RESULT_ORIGINAL_BACKUP'
PREFIX='state/all-existing-model-official-results/v1/'
FIELDS={'schema','purpose','repository_id','archived_at','allow_order_only','raw_zip_base64',
        'metadata_raw_base64','frozen_native_payloads','admission_receipt'}
POINTER_FIELDS={'schema','repository_id','ref','source_commit','cipher_path','cipher_sha256',
    'original_zip_sha256','metadata_sha256','artifact_id','workflow_run_id','head_sha','archived_at',
    'independent_git_readback_verified'}


def need(value,reason):
    if not value:raise ValueError('ALL_MODEL_RESULT_RETENTION_'+reason)


def utc_now():return datetime.now(timezone.utc)


def _clock(now):
    now=utc_now() if now is None else now
    need(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    return now


def _hash(value,length=64):
    need(type(value) is str and re.fullmatch('[a-f0-9]{'+str(length)+'}',value),'HASH_INVALID')
    return value


def _metadata(raw):
    value=vault._json(raw,vault.MAX_METADATA)
    need(type(value) is dict and type(value.get('workflow_run')) is dict,'EXACT_METADATA_REQUIRED')
    return value


def _admit(raw,metadata,frozen,*,now,key,allow_order_only):
    need(type(allow_order_only) is bool,'EXPLICIT_ORDER_ONLY_FLAG_REQUIRED')
    run=metadata['workflow_run']
    return results.observations_from_official_result_artifact(raw,metadata,now=now,
        expected_run_id=run.get('id'),expected_head_sha=run.get('head_sha'),
        frozen_native_payloads=frozen,key=key,allow_order_only=allow_order_only)


def _bytes(value,limit):
    need(type(value) is str and 0<len(value)<=((limit+2)//3)*4,'BASE64_BOUND_INVALID')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error):raise ValueError('ALL_MODEL_RESULT_RETENTION_BASE64_INVALID') from None
    need(0<len(raw)<=limit and base64.b64encode(raw).decode('ascii')==value,'BASE64_INVALID')
    return raw


def _material(payload,*,key):
    need(type(payload) is dict and set(payload)==FIELDS and payload['schema']==SCHEMA and
         payload['purpose']==PURPOSE and payload['repository_id']==store.REPO_ID,'ENVELOPE_SCOPE_INVALID')
    archived=results._time(payload['archived_at'])
    raw=_bytes(payload['raw_zip_base64'],results.MAX_ARCHIVE_BYTES)
    metadata_raw=_bytes(payload['metadata_raw_base64'],vault.MAX_METADATA);metadata=_metadata(metadata_raw)
    admitted=_admit(raw,metadata,payload['frozen_native_payloads'],now=archived,key=key,
                    allow_order_only=payload['allow_order_only'])
    need(admitted['receipt']==payload['admission_receipt'],'ORIGINAL_ADMISSION_BINDING_INVALID')
    return dict(payload=payload,raw_zip=raw,metadata_raw=metadata_raw,metadata=metadata)


def _pointer(cipher,commit,material):
    metadata=material['metadata'];payload=material['payload']
    raw_sha=sha256(material['raw_zip']).hexdigest();metadata_sha=sha256(material['metadata_raw']).hexdigest()
    return dict(schema=POINTER,repository_id=store.REPO_ID,ref=TRANSFER_REF,source_commit=_hash(commit,40),
        cipher_path=PREFIX+raw_sha+'/'+metadata_sha+'.enc',cipher_sha256=sha256(cipher).hexdigest(),
        original_zip_sha256=raw_sha,metadata_sha256=metadata_sha,artifact_id=metadata['id'],
        workflow_run_id=metadata['workflow_run']['id'],head_sha=metadata['workflow_run']['head_sha'],
        archived_at=payload['archived_at'],independent_git_readback_verified=True)


def _validate_pointer(pointer):
    need(type(pointer) is dict and set(pointer)==POINTER_FIELDS and pointer['schema']==POINTER and
         pointer['repository_id']==store.REPO_ID and pointer['ref']==TRANSFER_REF and
         pointer['independent_git_readback_verified'] is True,'POINTER_SCOPE_INVALID')
    _hash(pointer['source_commit'],40);_hash(pointer['head_sha'],40)
    for name in ('cipher_sha256','original_zip_sha256','metadata_sha256'):_hash(pointer[name])
    need(all(type(pointer[name]) is int and 0<pointer[name]<10**20 for name in
         ('artifact_id','workflow_run_id')),'POINTER_IDENTITY_INVALID')
    results._time(pointer['archived_at'])
    need(pointer['cipher_path']==PREFIX+pointer['original_zip_sha256']+'/'+pointer['metadata_sha256']+'.enc',
         'POINTER_PATH_INVALID')


def _transport(repo,transport):
    git=transport if transport is not None else vault.VaultGitRepository(repo,ref=TRANSFER_REF)
    need(git.ref==TRANSFER_REF,'EXISTING_TRANSFER_REF_REQUIRED')
    return git


def _opened(pointer,git,*,key):
    _validate_pointer(pointer);commit=pointer['source_commit'];git.fetch(commit)
    cipher=git.read(commit,pointer['cipher_path'],store.MAX_WIRE)
    need(type(cipher) is bytes and sha256(cipher).hexdigest()==pointer['cipher_sha256'],'CIPHER_HASH_INVALID')
    payload=store.open_forecasts(cipher,key=key);material=_material(payload,key=key)
    header=store.forecast_header(cipher);metadata=material['metadata']
    need(header['run_id']==str(metadata['workflow_run']['id']) and
         header['round_no']==int(metadata['name'].rsplit('-',1)[1]),'BACKUP_HEADER_BINDING_INVALID')
    need(_pointer(cipher,commit,material)==pointer,'POINTER_ORIGINAL_BINDING_INVALID')
    return material


def restore(pointer,repo,*,key=None,transport=None):
    """Restore historical exact bytes; create no current input/label/grant receipt."""
    key=state_key('production',key);_validate_pointer(pointer)
    material=_opened(pointer,_transport(repo,transport),key=key);payload=material['payload']
    provenance=dict(receipt_scope='ARCHIVED_OFFICIAL_RESULT_ORIGINAL_BYTES',
        archived_original_bytes_verified=True,original_source_replay_verified=True,
        original_admission_clock=payload['archived_at'],original_saved_at=material['metadata']['created_at'],
        original_allow_order_only=payload['allow_order_only'],current_artifact_status='NOT_QUERIED',
        current_label_or_training_admission_created=False,current_training_authorization_granted=False,
        independent_pre_cutoff_input_receipt_created=False,github_receipt_created=False,
        github_artifact_receipt_created=False,source_commit=pointer['source_commit'],
        cipher_sha256=pointer['cipher_sha256'])
    return dict(raw_zip=material['raw_zip'],metadata_raw=material['metadata_raw'],provenance=provenance)


def retain(raw_zip,exactmetadata_raw,frozen_native_payloads,repo,*,expected_parent,
           allow_order_only=False,key=None,transport=None,readback_transport=None,now=None):
    """Authenticate once, append bounded owner ciphertext and independently replay.

    All caller native inputs must already have independent input-artifact
    admission. The stored copies support original source replay only. Existing
    transfer-ref trees and pointers are inherited unchanged, including on retry.
    """
    key=state_key('production',key);clock=_clock(now);_hash(expected_parent,40)
    metadata=_metadata(exactmetadata_raw);frozen=deepcopy(frozen_native_payloads)
    admitted=_admit(raw_zip,metadata,frozen,now=clock,key=key,allow_order_only=allow_order_only)
    known,_=results._frozen(frozen)
    payload=dict(schema=SCHEMA,purpose=PURPOSE,repository_id=store.REPO_ID,archived_at=clock.isoformat(),
        allow_order_only=allow_order_only,raw_zip_base64=base64.b64encode(raw_zip).decode('ascii'),
        metadata_raw_base64=base64.b64encode(exactmetadata_raw).decode('ascii'),
        frozen_native_payloads=[known[name] for name in sorted(known)],admission_receipt=admitted['receipt'])
    need(len(store._wire(payload))<=store.MAX_PLAIN,'PLAIN_BOUND_EXCEEDED')
    raw_sha=sha256(raw_zip).hexdigest();metadata_sha=sha256(exactmetadata_raw).hexdigest()
    path=PREFIX+raw_sha+'/'+metadata_sha+'.enc';git=_transport(repo,transport)
    with vault._independent_reader(git,readback_transport) as reader:
        parent=git.head();need(parent is not None and parent==expected_parent,'REF_CONCURRENT_UPDATE')
        git.fetch(parent)
        if git.exists(parent,path):
            cipher=git.read(parent,path,store.MAX_WIRE)
            previous=_material(store.open_forecasts(cipher,key=key),key=key)
            # Both admissions have already replayed independently: the current
            # inputs above, and the stored original context in _material. A
            # larger current native cohort or research-mode flag is not a
            # change to these exact immutable ZIP/metadata bytes. Keep the
            # original admission receipt, mode and archive clock untouched.
            need(previous['raw_zip']==raw_zip and previous['metadata_raw']==exactmetadata_raw,
                 'IMMUTABLE_ORIGINAL_CONFLICT')
            pointer=_pointer(cipher,parent,previous)
        else:
            round_no=int(metadata['name'].rsplit('-',1)[1])
            cipher=store.seal_forecasts(payload,run_id=str(metadata['workflow_run']['id']),round_no=round_no,key=key)
            commit=git.commit({path:cipher},parent);git.push(commit,parent)
            pointer=_pointer(cipher,commit,dict(payload=payload,raw_zip=raw_zip,
                metadata_raw=exactmetadata_raw,metadata=metadata))
        restored=restore(pointer,reader.repo,key=key,transport=reader)
        need(restored['raw_zip']==raw_zip and restored['metadata_raw']==exactmetadata_raw,
             'INDEPENDENT_ORIGINAL_READBACK_MISMATCH')
        return pointer
