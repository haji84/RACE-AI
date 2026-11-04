"""Read explicitly pinned local Actions artifacts without fetching or writing.

Inputs and returned documents are private. Local SHA correlations are not
GitHub timestamp authentication, source permission, or full-day completeness.
At most 100 artifacts, 1 MiB metadata and 32 MiB per ZIP are accepted. Disk
bytes plus declared uncompressed ZIP bytes share a 256 MiB read budget.
The separate owner-private research JSON reader keeps its original 4 MiB cap.
"""
from datetime import date, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import zipfile
import zlib

from .actions_contract import digest
from .cycle_recovery import result_archive
from .existing_model_coverage import catalog
from .first_receipt_continuity import first_receipt_rows, latest_result_observations
from .frozen_day_cycle import read_p0, read_p1, ts

MAX_ARTIFACTS = 100
MAX_METADATA_BYTES = 1024 * 1024
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_JST = timezone(timedelta(hours=9))
_MEMBERS = {'p0':'forecasts.json','p1':'national.json','result':'official-result-observations.json'}


class PrivateRestoreError(ValueError):
    """Reject private paths/data without including them in exception text."""


def _need(condition):
    if not condition:
        raise PrivateRestoreError('PRIVATE_ARTIFACT_RESTORE_REJECTED')


def _sha(value):
    return isinstance(value,str) and _SHA.fullmatch(value) is not None


def _root(value):
    path=Path(value).expanduser()
    _need(path.is_absolute() and '..' not in path.parts and path.is_dir())
    for item in (path,*path.parents):
        _need(not item.is_symlink() and not (item/'.git').exists())
    return path.resolve(strict=True)


def _parts(value):
    _need(type(value) is str and 0<len(value)<=240 and
          '\\' not in value and '\x00' not in value and ':' not in value)
    parts=value.split('/')
    _need(all(p not in ('','.','..','.git') for p in parts))
    return parts


def _read(root,name,limit,budget):
    """Walk directory FDs without following links; verify unchanged file bytes."""
    parts=_parts(name);descriptors=[]
    flags=os.O_RDONLY|getattr(os,'O_CLOEXEC',0)|getattr(os,'O_NOFOLLOW',0)
    try:
        parent=os.open(root,flags|getattr(os,'O_DIRECTORY',0));descriptors.append(parent)
        for part in parts[:-1]:
            parent=os.open(part,flags|getattr(os,'O_DIRECTORY',0),dir_fd=parent)
            descriptors.append(parent)
            try:os.stat('.git',dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:pass
            else:_need(False)
        before=os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<=limit)
        budget[0]+=before.st_size;_need(budget[0]<=MAX_TOTAL_BYTES)
        fd=os.open(parts[-1],flags,dir_fd=parent);descriptors.append(fd)
        opened=os.fstat(fd)
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
        _need(identity(before)==identity(opened))
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(limit+1)
        after=os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
        _need(len(raw)==before.st_size and identity(before)==identity(os.fstat(fd))==identity(after))
        return raw
    finally:
        for fd in reversed(descriptors):os.close(fd)


def _json(raw):
    def unique(pairs):
        value={}
        for key,item in pairs:
            _need(key not in value);value[key]=item
        return value
    def invalid(value):
        _need(False)
    return json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid)


def _day_identity(rid,day):
    _need(type(rid) is str and re.fullmatch(day.replace('-','')+
          r'-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])',rid) is not None)


def restore_manifest(manifest,root):
    """Return private original documents and baseline rows from explicit pins.

    Required manifest keys: repo, repository_id, day_jst, artifacts. Optional
    schema is RACE_AI_PRIVATE_ARTIFACT_MANIFEST_V1. Artifact descriptors require
    kind, artifact_id, run_id, metadata_file, zip_file, metadata_sha256 and
    zip_sha256; optional member_sha256 pins the primary JSON, and created_at
    pins the exact metadata timestamp. No filename, payload or path is logged.

    Learned documents remain intact but are not replayed through predictors.
    Their dependency limitations are explicit rather than counted as restored.
    """
    try:
        return _restore(manifest,root)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,
            OSError,RuntimeError,RecursionError,zipfile.BadZipFile,zlib.error):
        raise PrivateRestoreError('PRIVATE_ARTIFACT_RESTORE_REJECTED') from None


def _restore(manifest,root):
    required={'repo','repository_id','day_jst','artifacts'}
    _need(type(manifest) is dict and required<=set(manifest)<=required|{'schema'})
    _need(manifest.get('schema','RACE_AI_PRIVATE_ARTIFACT_MANIFEST_V1')=='RACE_AI_PRIVATE_ARTIFACT_MANIFEST_V1')
    _need(manifest['repo']=='haji84/RACE-AI' and type(manifest['repository_id']) is int and
          manifest['repository_id']==1416489937)
    day=manifest['day_jst'];_need(type(day) is str and date.fromisoformat(day).isoformat()==day)
    entries=manifest['artifacts']
    _need(type(entries) is list and 1<=len(entries)<=MAX_ARTIFACTS)
    private_root=_root(root);budget=[0];seen=set();files=set()
    rows=[];observations=[];receipts=[];documents=[];learned=[]
    models={m['model_id'] for m in catalog()}
    entry_keys={'kind','artifact_id','run_id','metadata_file','zip_file','metadata_sha256','zip_sha256'}
    for entry in entries:
        _need(type(entry) is dict and entry_keys<=set(entry)<=entry_keys|{'member_sha256','created_at'})
        kind=entry['kind'];ident=entry['artifact_id'];run=entry['run_id']
        _need(type(kind) is str and kind in _MEMBERS and type(ident) is int and ident>0 and
              type(run) is int and run>0 and ident not in seen)
        seen.add(ident)
        _need(all(_sha(entry[k]) for k in ('metadata_sha256','zip_sha256')))
        if 'member_sha256' in entry:_need(_sha(entry['member_sha256']))
        for field in ('metadata_file','zip_file'):
            name=entry[field];_parts(name);_need(name not in files);files.add(name)
        meta_raw=_read(private_root,entry['metadata_file'],MAX_METADATA_BYTES,budget)
        _need(hashlib.sha256(meta_raw).hexdigest()==entry['metadata_sha256'])
        meta=_json(meta_raw)
        _need(type(meta) is dict and type(meta.get('id')) is int and meta['id']==ident and
              meta.get('expired') is False and type(meta.get('workflow_run')) is dict)
        workflow=meta['workflow_run']
        _need(type(workflow.get('id')) is int and workflow['id']==run and
              type(workflow.get('head_repository_id')) is int and workflow['head_repository_id']==1416489937)
        if 'repository_id' in workflow:
            _need(type(workflow['repository_id']) is int and workflow['repository_id']==1416489937)
        saved=ts(meta['created_at'])
        if 'created_at' in entry:_need(meta['created_at']==entry['created_at'])
        raw=_read(private_root,entry['zip_file'],MAX_ZIP_BYTES,budget)
        _need(hashlib.sha256(raw).hexdigest()==entry['zip_sha256'] and meta.get('digest')=='sha256:'+entry['zip_sha256'])
        primary=_MEMBERS[kind]
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names=z.namelist();_need(len(names)==len(set(names)) and primary in names)
            sizes=[i.file_size for i in z.infolist()]
            _need(all(type(n) is int and n>=0 for n in sizes))
            budget[0]+=sum(sizes);_need(budget[0]<=MAX_TOTAL_BYTES)
            selected=[primary]
            if kind=='result':selected += [n for n in ('status.json','trained_observed_models.json') if n in names]
            parsed={}
            for member in selected:
                limit=4*1024*1024 if member=='trained_observed_models.json' else 16*1024*1024 if kind=='result' else MAX_ZIP_BYTES
                _need(0<z.getinfo(member).file_size<=limit)
                body=z.read(member);body_sha=hashlib.sha256(body).hexdigest()
                if member==primary and 'member_sha256' in entry:_need(body_sha==entry['member_sha256'])
                parsed[member]=_json(body)
                documents.append(dict(artifact_id=ident,member_name=member,member_sha256=body_sha,document=parsed[member]))
        doc=parsed[primary]
        if kind=='p0':doc,items=read_p0(raw,meta,expected_day=day)
        elif kind=='p1':
            doc,items=read_p1(raw,meta)
            for field in ('paired_forecasts','additional_official_feature_shadows',
                          'observed_pairwise_p1_bundles','learned_pairwise_shadows'):
                values=doc.get(field,[]);_need(type(values) is list and len(values)<=20000)
                for item in values:
                    _need(type(item) is dict)
                    if field!='learned_pairwise_shadows' or 'race_id' in item:_day_identity(item['race_id'],day)
                    if field=='learned_pairwise_shadows':
                        receipt=item.get('training_receipt',{})
                        training_id=receipt.get('id') if type(receipt) is dict else None
                        learned.append(dict(artifact_id=ident,training_artifact_id=training_id,
                            reason='LEARNED_SHADOW_REPLAY_AND_TRAINING_RECEIPT_VALIDATION_NOT_PERFORMED'))
            if 'paired_forecast_count' in doc:_need(doc['paired_forecast_count']==len(doc.get('paired_forecasts',[])))
            if not items:
                observed=doc.get('observed_at',meta['created_at'])
                _need(ts(observed).astimezone(_JST).date().isoformat()==day)
        else:
            items=[];journal=result_archive(raw,meta,day)
            for event in journal:
                _day_identity(event['race_id'],day)
                _need(ts(event['captured_at'])<=saved+timedelta(seconds=1))
                if 'closed_at' in event:
                    closed=ts(event['closed_at'])
                    _need(closed.astimezone(_JST).date().isoformat()==day and ts(event['captured_at'])>=closed)
            observations+=journal
        for row in items:
            _day_identity(row['race_id'],day);_need(row['model_id'] in models)
            _need(ts(row['cutoff_at']).astimezone(_JST).date().isoformat()==day)
        rows+=items;receipts.append(meta)
    first,excluded=first_receipt_rows(rows)
    _,versions=latest_result_observations(observations)
    result_ids={e['artifact_id'] for e in entries if e['kind']=='result'}
    for dependency in learned:
        dependency['training_artifact_supplied']=dependency['training_artifact_id'] in result_ids
    state=dict(schema='RACE_AI_PRIVATE_ARTIFACT_READBACK_V1',day_jst=day,rows=first,
        observations=versions,receipts=receipts,original_documents=documents,excluded_repeats=excluded,
        coverage_scope='EXPLICIT_ARTIFACTS_ONLY',complete=False,external_receipts_verified=False,
        independent_receipts_verified=False,external_time_attested=False,
        source_rights_verified=False,official_results_authenticated=False,all_models_operational=False,
        learned_shadows_restored=False,unresolved_learned_dependencies=learned,
        authenticity_scope='LOCAL_SHA_PIN_CORRELATION_ONLY',external_source_requests=0)
    state['state_sha256']=digest(state)
    return state
