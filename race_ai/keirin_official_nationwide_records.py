"""Private source-bound dynamic originals in the existing owner Git archive.

The fixed trial stays untouched. This scope uses its own bounded index, the
existing pinned RSA/AES evidence envelopes, and the same pre-cutoff model and
GitHub server-origin checks. No provider transport is present here.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import json
import os
import re
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import keirin_nationwide_auto_generator as model
from . import keirin_confidence as confidence
from . import keirin_nationwide_auto_storage as storage
from . import keirin_nationwide_auto_settlement as decrypt
from . import keirin_nationwide_cipher_history as archive
from . import keirin_official_run_history as history
from . import keirin_github_origin_evidence as origin
from . import keirin_official_nationwide_extension as extension
from . import keirin_form_fall_shadow as shadow
from . import keirin_official_form_history as form
from . import keirin_official_nationwide_sources as sources
from scripts import keirin_official_day_pipeline as pipeline

PRE_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_NATIONWIDE_PRE_CUTOFF_V1'
DAY_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_NATIONWIDE_DAY_V1'
RESULT_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_NATIONWIDE_RESULT_V1'
INDEX_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_SP_EVIDENCE_INDEX_V1'
ROOT = 'state/keirin/ab/official-sp/v1'
MAX_RACES, MAX_INDEX_BYTES = 600, 2_000_000
POLICY = origin.OriginPolicy(producer_job_name='official-sp-capture',
    readback_job_name='official-sp-independent-readback',
    producer_artifact_name='keirin-official-sp-receipt-{run_id}',
    readback_artifact_name='keirin-official-sp-readback-{run_id}')
STATES = frozenset(('WAITING_SOURCE_CAPTURE','UNSUPPORTED_CLASS_OR_ROUND',
    'PUBLISHED_RESULT_NO_PRE_CUTOFF_ORIGINAL','FROZEN_ORIGINAL_PRESERVED',
    'SOURCE_CAPTURE_BUDGET_PENDING','CUTOFF_MARGIN_INSUFFICIENT','BASELINE_SOURCE_UNVERIFIED',
    'PROVIDER_STOPPED','SOURCE_UNAVAILABLE','A_B_ARCHIVED_AWAITING_INDEPENDENT_READBACK',
    'A_B_AUTHENTICATED_PRE_CUTOFF','ORIGIN_PROOF_PENDING','FROZEN_ARCHIVE_UNVERIFIED',
    'RACE_DISAPPEARED_FROM_CURRENT_LIST'))
CONDITION_STATES = frozenset(('HISTORY_NOT_COLLECTED','HISTORY_SOURCE_UNAVAILABLE',
    'HISTORY_UNVERIFIED','INSUFFICIENT_CAPTURE_MARGIN','CONDITIONED_ARCHIVED_AWAITING_READBACK',
    'CONDITIONED_AUTHENTICATED_PRE_CUTOFF','CONDITIONED_ORIGIN_PROOF_PENDING',
    'CONDITIONED_ARCHIVE_UNVERIFIED','NO_CONDITIONED_ORIGINAL'))


def need(ok, code):
    if not ok: raise ValueError('OFFICIAL_SP_RECORD_'+code)


def wire(value):
    if isinstance(value,datetime): return form._aware(value).isoformat()
    if type(value) is dict: return {key:wire(item) for key,item in value.items()}
    if type(value) in (list,tuple): return [wire(item) for item in value]
    return pipeline.private_snapshot_json(value)


def cohort(registry):
    return dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_DAY_COHORT_V1',day_jst=registry['event_day'],
        race_ids=sorted(registry['registered_race_ids']),max_tickets_per_arm=12,
        calendar_source_sha256=registry['calendar_source_sha256'])


def checked_states(rows, race_ids):
    need(type(rows) is list and len(rows)==len(race_ids),'DAY_STATE_COUNT')
    need({row.get('race_id') for row in rows}==set(race_ids),'DAY_STATE_IDENTITIES')
    for row in rows:
        need(type(row) is dict and set(row)=={'race_id','state','condition_state'} and
             row['state'] in STATES and row['condition_state'] in CONDITION_STATES,'DAY_STATE_INVALID')
    return rows


def decrypt_conditioned(raw, *, expected_sha256, owner_private_pem, baseline):
    """Same conditioned envelope authentication, with dynamic race/cutoff pins."""
    need(type(raw) is bytes and 0<len(raw)<2_000_000 and sha256(raw).hexdigest()==expected_sha256,
         'CONDITIONED_CIPHER_SHA')
    doc=decrypt._json(raw);rid=baseline['race_id'];cutoff=baseline['published_cutoff_at']
    need(doc.get('schema')==shadow.SEALED_SCHEMA and doc.get('race_id')==rid and
         doc.get('original_baseline_sha256')==baseline['prediction_sha256'] and
         doc.get('owner_spki_sha256')==storage.PINNED_OWNER_SPKI_SHA256 and
         doc.get('actual_official_result_included') is False,'CONDITIONED_PARENT')
    pipeline.check_owner_private_key(owner_private_pem)
    key=serialization.load_pem_private_key(owner_private_pem,password=None)
    aad=('RACE_AI_FORM_FALL_V1|'+rid+'|'+baseline['prediction_sha256']).encode()
    need(doc.get('aad_ascii')==aad.decode() and doc.get('generated_at')==baseline['generated_at'] and
         doc.get('cutoff_at')==cutoff and model.when(doc['generated_at'])<=model.when(doc['sealed_at']) and
         (model.when(cutoff)-model.when(doc['sealed_at'])).total_seconds()>=65,'CONDITIONED_CLOCK')
    try:
        aes=key.decrypt(base64.b64decode(doc['rsa_wrapped_aes_key_b64'],validate=True),
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        need(len(aes)==32,'AES_256_REQUIRED')
        cipher=base64.b64decode(doc['ciphertext_b64'],validate=True)
        need(sha256(cipher).hexdigest()==doc['ciphertext_sha256'],'CONDITIONED_CIPHERTEXT_SHA')
        compressed=AESGCM(aes).decrypt(base64.b64decode(doc['nonce_b64'],validate=True),cipher,aad)
        decompressor=zlib.decompressobj();plain=decompressor.decompress(compressed,2_000_001)
        need(len(plain)<=2_000_000 and decompressor.eof and not decompressor.unused_data and
             not decompressor.unconsumed_tail and sha256(plain).hexdigest()==doc['private_shadow_plaintext_sha256'],
             'CONDITIONED_PLAINTEXT')
    except (ValueError,InvalidTag,zlib.error,KeyError,TypeError):
        raise ValueError('OFFICIAL_SP_RECORD_CONDITIONED_DECRYPT_FAILED') from None
    result=decrypt._json(plain)
    need(set(result)=={'shadow','supplement'} and
         result['shadow'].get('baseline_prediction_sha256')==baseline['prediction_sha256'] and
         result['shadow'].get('sha256')==model.digest({k:v for k,v in result['shadow'].items() if k!='sha256'}) and
         result['shadow'].get('condition_supplement_sha256')==model.digest(result['supplement']),
         'CONDITIONED_PLAIN_LINEAGE')
    return result


def replay_original(*, payload, raw_baseline, raw_conditioned, owner_private_pem):
    """Authenticate stored models and original source bytes, not server timing."""
    need(type(payload) is dict and payload.get('schema')==PRE_SCHEMA,'ORIGINAL_SCHEMA')
    rid=payload['race_id'];day=payload['day_jst'];base=payload['baseline']
    need(model.VENUE.fullmatch(rid) and rid[:8]==day.replace('-','') and
         payload['cohort_sha256']==model.digest(payload['cohort']) and
         payload['cohort'].get('schema')=='RACE_AI_KEIRIN_OFFICIAL_SP_DAY_COHORT_V1' and
         payload['cohort'].get('day_jst')==day and payload['cohort'].get('max_tickets_per_arm')==12 and
         rid in payload['cohort'].get('race_ids',[]),'ORIGINAL_COHORT')
    envelope,baseline,_,assessment=decrypt.decrypt_original_with_assessment(raw_cipher=raw_baseline,
        expected_cipher_sha256=payload['baseline_cipher_sha256'],owner_private_pem=owner_private_pem)
    rebuilt=extension.build_baseline_candidate(**payload['baseline_arguments'],now=model.when(base['generated_at']))
    need(baseline==base and rebuilt['snapshot']==payload['snapshot'] and
         baseline['source_facts_sha256']==model.digest(payload['snapshot']) and
         envelope['sealed_at']==payload['baseline_sealed_at'],'ORIGINAL_SOURCE_OR_MODEL_CHANGED')
    has_assessment='confidence_assessment' in payload
    need(has_assessment==(assessment is not None),'CONFIDENCE_PRESENCE_MISMATCH')
    if has_assessment:
        saved=confidence.checked_assessment(payload['confidence_assessment'],
            snapshot=payload['snapshot'],baseline=baseline,sealed_at=envelope['sealed_at'])
        need(model.canonical(saved)==model.canonical(assessment),'CONFIDENCE_SOURCE_CIPHER_MISMATCH')
    out={key:deepcopy(payload[key]) for key in ('schema','day_jst','race_id','cohort','cohort_sha256',
        'producer_run_id','producer_commit','snapshot','baseline','baseline_cipher_sha256','baseline_sealed_at',
        'conditioned','supplement','conditioned_cipher_sha256','conditioned_sealed_at','condition_state')}
    if has_assessment:out['confidence_assessment']=deepcopy(assessment)
    if payload.get('conditioned') is not None:
        try:
            decoded=decrypt_conditioned(raw_conditioned,expected_sha256=payload['conditioned_cipher_sha256'],
                owner_private_pem=owner_private_pem,baseline=baseline)
            args=payload['baseline_arguments']
            joined=sources.build_condition_candidate(snapshot=payload['snapshot'],
                card_arguments=args['card_arguments'],prediction_source=args['prediction_source'],
                prediction_scripts=args['prediction_scripts'],history_manifest=payload['history_manifest'],
                source_bytes_by_sha=payload['source_bytes_by_sha'],now=model.when(base['generated_at']))
            need(decoded['shadow']==payload['conditioned'] and decoded['supplement']==joined['supplement']==payload['supplement'] and
                 joined['identity_proof']==payload['identity_proof'] and joined['availability']==payload['availability'] and
                 decrypt._json(raw_conditioned)['sealed_at']==payload['conditioned_sealed_at'],'CONDITIONED_SOURCE_CHANGED')
        except (ValueError,TypeError,KeyError,OverflowError):
            out.update(conditioned=None,supplement=None,conditioned_cipher_sha256=None,conditioned_sealed_at=None,
                       condition_state='CONDITIONED_ARCHIVE_UNVERIFIED')
    else:
        need(all(payload.get(k) is None for k in ('supplement','conditioned_cipher_sha256','conditioned_sealed_at')),
             'ABSENT_CONDITION_FIELDS')
    return out


def verify_origins(payload, raw_baseline, raw_conditioned, packets):
    """Separate dynamic main policy; fixed-canary policy is never broadened."""
    common=dict(race_id=payload['race_id'],official_cutoff_at=payload['baseline']['published_cutoff_at'],
        expected_producer_run_id=payload['producer_run_id'],expected_producer_commit=payload['producer_commit'],
        producer=packets['producer'],readback=packets['readback'],policy=POLICY)
    baseline=origin.verify_origin_evidence(raw_cipher=raw_baseline,
        expected_cipher_sha256=payload['baseline_cipher_sha256'],**common)
    conditioned=None
    if payload.get('conditioned') is not None:
        need(type(raw_conditioned) is bytes and sha256(raw_conditioned).hexdigest()==payload['conditioned_cipher_sha256'],
             'CONDITIONED_SERVER_CIPHER')
        first=origin._bundle(packets['producer'],role='producer',policy=POLICY)
        second=origin._bundle(packets['readback'],role='readback',policy=POLICY)
        need(first['run_id']==second['run_id'] and first['commit']==second['commit'],'CONDITIONED_SAME_RUN')
        before=origin._conditioned_report_rows(first['report'],producer=True)
        after=origin._conditioned_report_rows(second['report'],producer=False)
        need(before==after and before.get(payload['race_id'])==(
            payload['conditioned_cipher_sha256'],payload['baseline']['prediction_sha256'],
            payload['cohort_sha256'],payload['baseline_cipher_sha256']),'CONDITIONED_SERVER_BINDING')
        conditioned={k:v for k,v in baseline.items() if k!='evidence_sha256'}
        conditioned.update(schema='RACE_AI_KEIRIN_CONDITIONED_GITHUB_SERVER_ORIGIN_EVIDENCE_V1',
            state='GITHUB_PRE_CUTOFF_CONDITIONED_ORIGIN_VERIFIED',
            cipher_sha256=payload['conditioned_cipher_sha256'],
            baseline_cipher_sha256=payload['baseline_cipher_sha256'],
            baseline_prediction_sha256=payload['baseline']['prediction_sha256'],cohort_sha256=payload['cohort_sha256'],
            baseline_origin_evidence_sha256=baseline['evidence_sha256'],plaintext_parent_linkage_verified=False)
        conditioned['evidence_sha256']=model.digest(conditioned)
    return baseline,conditioned


def _empty(day):
    history._day(day)
    return dict(schema=INDEX_SCHEMA,day_jst=day,registry=None,originals={},results={})


def checked_index(doc, day):
    need(type(doc) is dict and set(doc)=={'schema','day_jst','registry','originals','results'} and
         doc['schema']==INDEX_SCHEMA and doc['day_jst']==day and type(doc['originals']) is dict and
         type(doc['results']) is dict and len(doc['originals'])<=MAX_RACES and
         set(doc['results'])<=set(doc['originals']),'INDEX_SHAPE')
    rows=[]
    if doc['registry'] is not None: rows.append(('registry',None,doc['registry']))
    for rid,meta in doc['originals'].items():
        need(model.VENUE.fullmatch(rid) and rid.startswith(day.replace('-','')),'INDEX_RACE')
        rows.append(('original',rid,meta))
    for rid,versions in doc['results'].items():
        need(type(versions) is list and 1<=len(versions)<=16,'RESULT_REVISION_BOUND')
        rows.extend(('result',rid,meta) for meta in versions)
    for kind,rid,meta in rows:
        keys={'kind','evidence_sha256','cipher_sha256','observed_at','producer_run_id','producer_commit'}
        if rid is not None: keys|={'race_id'}
        if kind=='original':keys|={'cutoff_at','baseline_cipher_sha256'}
        if kind=='result':keys|={'monetary_complete'}
        need(type(meta) is dict and set(meta)==keys and meta['kind']==kind and
             (rid is None or meta['race_id']==rid) and
             model.SHA.fullmatch(meta['evidence_sha256']) and model.SHA.fullmatch(meta['cipher_sha256']) and
             archive.RUN.fullmatch(meta['producer_run_id']) and archive.COMMIT.fullmatch(meta['producer_commit']),
             'INDEX_RECEIPT')
        form._aware(meta['observed_at'])
        if kind=='original':
            need(model.SHA.fullmatch(meta['baseline_cipher_sha256']) and
                 form._aware(meta['cutoff_at']).astimezone(form.JST).date().isoformat()==day,'INDEX_CUTOFF')
        if kind=='result':need(type(meta['monetary_complete']) is bool,'INDEX_RESULT_STATE')
    return doc


class RecordStore:
    """Select bounded encrypted records without scanning all historical bytes."""
    def __init__(self, repo, day, *, synthetic_local=False, partial_read=False, retry_archive_timeout=False):
        self.repo=archive._remote(repo,synthetic_local=synthetic_local)
        self.day=history._day(day);self.path=ROOT+'/'+day+'/index.json'
        if partial_read:
            branch=archive.BRANCH
            tracking=f'refs/remotes/origin/{branch}'
            archive._cmd(self.repo,'fetch','--no-tags','--depth=1','--filter=blob:none',
                '--no-recurse-submodules','origin',f'refs/heads/{branch}:{tracking}')
            head=archive._cmd(self.repo,'rev-parse','--verify',f'{tracking}^{{commit}}')[1]
            need(archive.COMMIT.fullmatch(head),'PARTIAL_ARCHIVE_HEAD')
            self._load_index(head)
        elif retry_archive_timeout:
            self._load_index(archive._refresh(self.repo, retry_on_timeout=True))
        else:
            self.refresh()

    def refresh(self):
        return self._load_index(archive._refresh(self.repo))

    def _load_index(self, head):
        self.head=head
        raw=archive.read_blob_bytes(self.repo,self.head,self.path,max_bytes=MAX_INDEX_BYTES)
        self.index=checked_index(history._json(raw),self.day) if raw is not None else _empty(self.day)
        return self.index

    def read(self, meta, owner_private_pem):
        path=ROOT+'/'+self.day+'/'+meta['evidence_sha256']+'.sealed.json'
        raw=archive.read_blob_bytes(self.repo,self.head,path,max_bytes=history.MAX_CIPHER_BYTES)
        need(raw is not None and sha256(raw).hexdigest()==meta['cipher_sha256'],'EVIDENCE_CIPHER_SHA')
        envelope=history._checked_cipher(raw)
        need(envelope['day_jst']==self.day and envelope['evidence_plaintext_sha256']==meta['evidence_sha256'] and
             envelope['observed_at']==meta['observed_at'],'EVIDENCE_ENVELOPE')
        payload=pipeline.restore_private_snapshot_json(history.decrypt_evidence(raw,owner_private_pem))
        need(payload.get('day_jst')==self.day and payload.get('schema')=={
            'registry':DAY_SCHEMA,'original':PRE_SCHEMA,'result':RESULT_SCHEMA}[meta['kind']] and
             payload.get('producer_run_id')==meta['producer_run_id'] and
             payload.get('producer_commit')==meta['producer_commit'],'EVIDENCE_DAY_OR_WRITER')
        if meta['kind']!='registry':need(payload.get('race_id')==meta['race_id'],'EVIDENCE_RACE')
        if meta['kind']=='original':
            need(payload.get('producer_run_id')==meta['producer_run_id'] and
                 payload.get('producer_commit')==meta['producer_commit'] and
                 payload.get('race_id')==meta['race_id'] and
                 payload.get('baseline_cipher_sha256')==meta['baseline_cipher_sha256'],'EVIDENCE_PRODUCER')
        return payload

    def append(self, *, kind, payload, public_pem, observed_at, race_id=None, monetary_complete=False):
        need(kind in ('registry','original','result') and payload.get('day_jst')==self.day and
             payload.get('producer_run_id')==os.environ['GITHUB_RUN_ID'] and
             payload.get('producer_commit')==os.environ['GITHUB_SHA'],'APPEND_SCOPE')
        raw=history.seal_evidence(wire(payload),public_pem,self.day,form._aware(observed_at).isoformat())
        envelope=history._checked_cipher(raw);digest=envelope['evidence_plaintext_sha256']
        meta=dict(kind=kind,evidence_sha256=digest,cipher_sha256=sha256(raw).hexdigest(),
            observed_at=envelope['observed_at'],producer_run_id=os.environ['GITHUB_RUN_ID'],
            producer_commit=os.environ['GITHUB_SHA'])
        if kind!='registry':meta['race_id']=race_id
        if kind=='original':meta.update(cutoff_at=payload['baseline']['published_cutoff_at'],
            baseline_cipher_sha256=payload['baseline_cipher_sha256'])
        if kind=='result':meta['monetary_complete']=monetary_complete
        cipher_path=ROOT+'/'+self.day+'/'+digest+'.sealed.json'
        for _ in range(3):
            self.refresh();prior=self.index
            updated=deepcopy(prior)
            if kind=='registry':
                if prior['registry'] and prior['registry']['evidence_sha256']==digest:return prior['registry']
                updated['registry']=meta
            elif kind=='original':
                existing=prior['originals'].get(race_id)
                if existing:
                    need(existing['evidence_sha256']==digest,'IMMUTABLE_ORIGINAL_CHANGED')
                    return existing
                updated['originals'][race_id]=meta
            else:
                need(race_id in prior['originals'],'RESULT_WITHOUT_ORIGINAL')
                existing=prior['results'].get(race_id,[])
                for row in existing:
                    if row['evidence_sha256']==digest:return row
                updated['results'][race_id]=existing+[meta]
            checked_index(updated,self.day)
            index_raw=history._canonical(updated)
            need(len(index_raw)<MAX_INDEX_BYTES,'INDEX_BYTE_BOUND')
            with TemporaryDirectory(prefix='keirin-official-sp-record-') as folder:
                tree=Path(folder)/'tree';archive._cmd(self.repo,'worktree','add','--detach',str(tree),self.head)
                try:
                    target=tree/cipher_path;history._create_parent(tree,cipher_path)
                    need(not target.exists() and not target.is_symlink(),'EVIDENCE_CREATE_ONCE')
                    with target.open('xb') as stream:stream.write(raw)
                    index_path=tree/self.path;need(not index_path.is_symlink(),'INDEX_SYMLINK')
                    index_path.write_bytes(index_raw)
                    archive._cmd(tree,'add','--',cipher_path,self.path)
                    archive._cmd(tree,'-c','user.name=RACE-AI','-c','user.email=race-ai@users.noreply.github.com',
                                 'commit','-m','archive(keirin): encrypted official SP '+kind)
                    commit=archive._cmd(tree,'rev-parse','HEAD')[1]
                    code,_=archive._cmd(tree,'push','origin','HEAD:refs/heads/'+archive.BRANCH,okay=True)
                finally:archive._cmd(self.repo,'worktree','remove','--force',str(tree),okay=True)
            if code==0:
                self.refresh()
                need(archive._cmd(self.repo,'merge-base','--is-ancestor',commit,self.head,okay=True)[0]==0 and
                     archive.read_blob_bytes(self.repo,self.head,cipher_path,max_bytes=history.MAX_CIPHER_BYTES)==raw,
                     'EVIDENCE_READBACK')
                if kind=='registry':need(self.index['registry']==meta,'INDEX_READBACK')
                elif kind=='original':need(self.index['originals'].get(race_id)==meta,'INDEX_READBACK')
                else:need(meta in self.index['results'].get(race_id,[]),'INDEX_READBACK')
                return meta
        raise ValueError('OFFICIAL_SP_RECORD_CONCURRENT_APPEND_FAILED')


def replay_registry(payload):
    need(payload.get('schema')==DAY_SCHEMA,'REGISTRY_SCHEMA')
    inventory=payload['inventory'];prior=payload['prior_race_ids']
    rebuilt=extension.register_day(calendar_receipt=inventory['calendar_receipt'],
        list_sources=inventory['list_sources'],event_day=payload['day_jst'],
        now=form._aware(payload['observed_at']),prior_race_ids=prior)
    need(rebuilt==payload['registry'],'REGISTRY_SOURCE_CHANGED')
    checked_states(payload['states'],rebuilt['registered_race_ids'])
    attempts=payload.get('source_attempt_counts',{})
    need(type(attempts) is dict and set(attempts)<=set(rebuilt['registered_race_ids']) and
         all(type(count) is int and count>0 for count in attempts.values()),'REGISTRY_ATTEMPT_COUNTS')
    return rebuilt


def archived_original(store, payload):
    rid=payload['race_id'];head=store.head;repo=store.repo
    receipt=archive._read_at(repo,head,rid,payload['baseline_cipher_sha256'])
    need(receipt is not None and receipt['producer_run_id']==payload['producer_run_id'] and
         receipt['producer_commit']==payload['producer_commit'] and
         receipt.get('cohort_sha256')==payload['cohort_sha256'],'BASELINE_ARCHIVE_LINEAGE')
    raw=archive.read_blob_bytes(repo,head,archive._refs(rid)[0])
    adjusted=None
    if payload.get('conditioned_cipher_sha256'):
        try:
            archive._read_conditioned_at(repo,head,rid,payload['conditioned_cipher_sha256'],
                payload['baseline_cipher_sha256'],payload['baseline']['prediction_sha256'],payload['cohort_sha256'])
            adjusted=archive.read_blob_bytes(repo,head,archive._form_refs(rid)[0])
        except (ValueError,KeyError,TypeError):pass
    return raw,adjusted


def admit_original(store, payload, owner_private_pem, *, origin_client=None, packet_cache=None):
    from .keirin_github_evidence_client import GitHubEvidenceClient
    raw,adjusted=archived_original(store,payload)
    original=replay_original(payload=payload,raw_baseline=raw,raw_conditioned=adjusted,
                             owner_private_pem=owner_private_pem)
    client=origin_client or GitHubEvidenceClient();cache=packet_cache if packet_cache is not None else {}
    run=payload['producer_run_id']
    if run not in cache:cache[run]=client.read_run_bundle(run,policy=POLICY)
    packets=cache[run]
    # Baseline origin is independent of conditioned archive/readback success.
    base_only=dict(original,conditioned=None)
    base_origin,_=verify_origins(base_only,raw,None,packets)
    condition_origin=None
    if original['conditioned'] is not None:
        try:
            _,condition_origin=verify_origins(original,raw,adjusted,packets)
            original['condition_state']='CONDITIONED_AUTHENTICATED_PRE_CUTOFF'
        except (ValueError,KeyError,TypeError):
            original.update(conditioned=None,supplement=None,conditioned_cipher_sha256=None,
                conditioned_sealed_at=None,condition_state='CONDITIONED_ORIGIN_PROOF_PENDING')
    original['origin_receipts']=dict(baseline_origin=base_origin,condition_origin=condition_origin)
    return original,packets


def load_admitted_day(repo, owner_private_pem, day, *, origin_client=None, clock=None, partial_read=False):
    pipeline.check_owner_private_key(owner_private_pem)
    store=RecordStore(repo,day,partial_read=partial_read);registry=None;states={}
    observed=form._aware((clock or (lambda:datetime.now(timezone.utc)))()).isoformat()
    if store.index['registry']:
        payload=store.read(store.index['registry'],owner_private_pem);registry=replay_registry(payload)
        states={row['race_id']:deepcopy(row) for row in payload['states']};observed=payload['observed_at']
    originals=[];cache={}
    for rid,meta in sorted(store.index['originals'].items()):
        state=states.setdefault(rid,dict(race_id=rid,state='FROZEN_ARCHIVE_UNVERIFIED',condition_state='NO_CONDITIONED_ORIGINAL'))
        try:
            payload=store.read(meta,owner_private_pem)
            admitted,_=admit_original(store,payload,owner_private_pem,origin_client=origin_client,packet_cache=cache)
            originals.append(admitted)
            state.update(state='A_B_AUTHENTICATED_PRE_CUTOFF',condition_state=admitted['condition_state'])
        except (ValueError,KeyError,TypeError,OSError):
            state['state']='ORIGIN_PROOF_PENDING'
    need(registry is not None or not store.index['originals'],'REGISTRY_REQUIRED_FOR_ORIGINALS')
    if registry is not None:
        need(set(store.index['originals'])<=set(registry['registered_race_ids']),'REGISTRY_LOST_ORIGINAL')
        checked_states(list(states.values()),registry['registered_race_ids'])
    return dict(day_jst=day,registry=registry,records=originals,
                states=sorted(states.values(),key=lambda r:r['race_id']),observed_at=observed)


def discover_days(repo, *, retry_archive_timeout=False):
    """Only the bounded, already existing official-SP namespace is enumerated."""
    repo=archive._remote(repo,synthetic_local=False)
    head = (archive._refresh(repo, retry_on_timeout=True)
            if retry_archive_timeout else archive._refresh(repo))
    code,size=archive._cmd(repo,'--no-replace-objects','cat-file','-s',head+':'+ROOT,okay=True)
    if code!=0:return []
    need(size.isascii() and size.isdecimal() and len(size)<8 and int(size)<=32_000,'DAY_DIRECTORY_BOUND')
    _,listing=archive._cmd(repo,'--no-replace-objects','ls-tree','-z',head+':'+ROOT)
    rows=[r for r in listing.split('\0') if r];need(len(rows)<=400,'DAY_DIRECTORY_COUNT')
    days=[]
    for row in rows:
        match=re.fullmatch(r'040000 tree [0-9a-f]{40}\t(20[0-9]{2}-[0-9]{2}-[0-9]{2})',row)
        need(match is not None,'DAY_DIRECTORY_ENTRY');days.append(history._day(match[1]))
    return sorted(days,reverse=True)


def compare_result(*,original,payload,raw_baseline,raw_conditioned,packets,final_capture):
    """Use the existing exact-ticket scorer; absent adjusted arms stay absent."""
    from . import keirin_form_fall_blind_pdca as pdca
    final=sources.reparse_final(original,final_capture);rid=original['race_id']
    baseline_origin,condition_origin=verify_origins(original,raw_baseline,raw_conditioned,packets)
    cars={r['car'] for r in original['snapshot']['riders']}
    official=dict(race_id=rid,source_sha256=final['source_sha256'],observed_at=final['observed_at'])
    monetary=final['monetary_comparison_eligible'] is True
    paid=pdca._result(final,cars,rid) if monetary else {tuple(t):0 for t in final['winning_triples']}
    arms={}
    for role in ('A','B'):
        arms[role]=pdca._score(pdca._tickets(original['baseline'][role],cars),paid)
        if original['conditioned'] is not None:
            arms['adjusted_'+role]=pdca._score(pdca._tickets(original['conditioned'][role+'_research'],cars),paid)
    comparison=None
    if monetary and original['conditioned'] is not None:
        official['payout_unit_source_sha256']=final['payout_unit_evidence']['source_sha256']
        witnesses=dict(baseline_origin=baseline_origin,condition_origin=condition_origin,official_final=official)
        joined=dict(baseline=original['baseline'],conditioned=original['conditioned'],result=final,starters=sorted(cars),
            baseline_sealed_at=original['baseline_sealed_at'],conditioned_sealed_at=original['conditioned_sealed_at'],
            verified_receipts=witnesses)
        def verify_base(race,row,witness):
            return race==rid and row is joined and verify_origins(original,raw_baseline,raw_conditioned,packets)[0]==witness
        def verify_condition(race,row,witness):
            return race==rid and row is joined and verify_origins(original,raw_baseline,raw_conditioned,packets)[1]==witness
        def verify_final(race,row,witness):
            return race==rid and row is joined and witness==official and sources.reparse_final(original,final_capture)==final
        comparison=pdca.compare_cohort(registered_race_ids=[rid],joined_private_rows={rid:joined},
            independently_verify=dict(baseline_origin=verify_base,condition_origin=verify_condition,official_final=verify_final))
        need(comparison['paired_comparable_races']==1,'FOUR_ARM_COMPARISON_NOT_ADMITTED')
    return dict(official_result=final,arms=arms,comparison=comparison,
        origin_receipts=dict(baseline_origin=baseline_origin,condition_origin=condition_origin,official_final=official),
        monetary_comparison_eligible=monetary)


def result_updates(original,scored,final_capture):
    from . import keirin_result_updates as updates
    from .keirin_result_diagnostics import checked_diagnostics
    final=sources.reparse_final(original,final_capture)
    need(scored['official_result']==final,'SCORE_RESULT_SOURCE_CHANGED')
    monetary=final['monetary_comparison_eligible'] is True
    at=max(form._aware(final['observed_at']),form._aware(final_capture.get('unit_verified_at') or final['observed_at']))
    arms={role:updates.pending_arm() for role in updates.ARMS}
    for role,score in scored['arms'].items():
        need(role in ('A','B','adjusted_A','adjusted_B'),'RESULT_ARM_SCOPE')
        arms[role]=dict(state='hit' if score['all_hit'] else 'miss',points=score['points'],
            stake_yen=score['stake_yen'] if monetary else None,return_yen=score['payout_yen'] if monetary else None)
    row=dict(race_id=original['race_id'],observed_at=at.isoformat(),authority='official',order_status='confirmed',
        payout_status='confirmed' if monetary else 'pending',winning_triples=['-'.join(map(str,t)) for t in final['winning_triples']],
        payouts_100yen={'-'.join(map(str,row['triple'])):row['yen'] for row in final.get('payouts_100yen',[])},
        source_comparison=[dict(source_id='keirin_jp',state='matched')],
        diagnostics=checked_diagnostics(final_capture.get('safe_diagnostics',[])),arms=arms)
    return updates.checked_updates(dict(schema=updates.SCHEMA,observed_at=at.isoformat(),races=[updates._finish(row)]))


def replay_saved_result(store,original_meta,result_meta,owner_private_pem):
    """Source-free reconstruction from archived original and source witnesses."""
    original_payload=store.read(original_meta,owner_private_pem);saved=store.read(result_meta,owner_private_pem)
    need(saved['schema']==RESULT_SCHEMA and saved['race_id']==original_payload['race_id'] and
         saved['original_evidence_sha256']==original_meta['evidence_sha256'],'RESULT_ORIGINAL_BINDING')
    raw,adjusted=archived_original(store,original_payload)
    original=replay_original(payload=original_payload,raw_baseline=raw,raw_conditioned=adjusted,
                             owner_private_pem=owner_private_pem)
    # An originally absent/unverified conditioned arm cannot be added later to
    # a saved comparison. The exact archived origin packets decide admission.
    base_only=dict(original,conditioned=None)
    verify_origins(base_only,raw,None,saved['origin_packets'])
    if original['conditioned'] is not None:
        try:verify_origins(original,raw,adjusted,saved['origin_packets'])
        except (ValueError,KeyError,TypeError):
            original.update(conditioned=None,supplement=None,conditioned_cipher_sha256=None,conditioned_sealed_at=None)
    replay=compare_result(original=original,payload=original_payload,raw_baseline=raw,raw_conditioned=adjusted,
        packets=saved['origin_packets'],final_capture=saved['final_capture'])
    need(replay==saved['scored'] and replay['monetary_comparison_eligible'] is result_meta['monetary_complete'],
         'SAVED_RESULT_NOT_REPRODUCIBLE')
    return result_updates(original,replay,saved['final_capture'])
