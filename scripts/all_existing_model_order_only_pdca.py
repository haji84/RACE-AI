"""Explicit PR71 Actions entry for authenticated rank-only shadow PDCA.

Only GitHub artifacts are read. Original forecasts, normalized official labels,
model parameters and monetary evaluation remain in their existing contracts.
"""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_order_only_pdca as core
from race_ai.all_existing_model_receipt import MAX_ARCHIVE_BYTES,_entries
from race_ai.all_existing_model_runtime import _private_directory,_private_file
from race_ai.boat_pdca_state import state_key
from race_ai.boat_venue_learning import read_candidate
from race_ai.boat_venue_learning_context import MEMBER_LIMITS
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_p0 as future
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

SCHEMA='RACE_AI_ORDER_ONLY_PDCA_INPUT_V1'
STATUS='RACE_AI_ORDER_ONLY_PDCA_ACTIONS_COUNTS_V1'
ROUND=900009
MAX_TOTAL_BYTES=256*1024*1024
PIN_FIELDS={'id','digest','run_id','head_sha'}
COUNT_FIELDS=('evaluation_scope','monetary_evaluation_available','partition_count','baseline_forecast_count',
    'learned_forecast_count','paired_forecasts','order_only_result_count','unmatched_order_only_results',
    'outside_order_only_result_state_counts','result_state_counts','source_artifact_id','source_artifact_digest',
    'source_workflow_run_id','source_head_sha','result_artifact_id','result_artifact_digest','training_sha256',
    'independent_pre_cutoff_receipt_verified','independent_result_artifact_receipt_verified',
    'independent_pdca_artifact_receipt_verified','paired_cohorts_within_cells_only',
    'cross_model_equal_cohort_comparison_claimed','encrypted_readback_verified')


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_ORDER_ONLY_PDCA_CLI_'+reason)

def utc_now():return datetime.now(timezone.utc)


def _pin(value):
    need(type(value) is dict and set(value)==PIN_FIELDS and type(value['id']) is int and 0<value['id']<10**16 and
        type(value['run_id']) is int and 0<value['run_id']<10**20 and type(value['digest']) is str and
        re.fullmatch('sha256:[a-f0-9]{64}',value['digest']) and type(value['head_sha']) is str and
        re.fullmatch('[a-f0-9]{40}',value['head_sha']),'ARTIFACT_PIN')
    return value


def load_manifest(path):
    value=read_json_bytes(_read(Path(path),32768))
    need(type(value) is dict and set(value)=={'schema','future_artifact','result_artifact','additional_native_artifacts'} and
        value['schema']==SCHEMA and type(value['additional_native_artifacts']) is list and
        len(value['additional_native_artifacts'])<=16,'MANIFEST_SCHEMA')
    pins=[value['future_artifact'],value['result_artifact'],*value['additional_native_artifacts']]
    for pin in pins:_pin(pin)
    need(len({p['id'] for p in pins})==len(pins),'DISTINCT_ARTIFACTS')
    return value


def environment():
    # No GitHub endpoint is touched before owner-key and trusted PR context.
    state_key('production')
    need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI' and
        os.environ.get('GITHUB_REPOSITORY_ID')=='1416489937' and os.environ.get('GITHUB_EVENT_NAME')=='pull_request' and
        os.environ.get('GITHUB_REF') in ('refs/pull/71/merge','refs/pull/71/head'),'TRUSTED_PR71_ACTIONS_REQUIRED')
    event=read_json_bytes(_read(Path(os.environ.get('GITHUB_EVENT_PATH','')),2*1024*1024))
    pr=event.get('pull_request') if type(event) is dict else None
    need(type(pr) is dict and type(event.get('number')) is int and event['number']==71 and
        type(pr.get('number')) is int and pr['number']==71 and all(type(pr.get(side)) is dict and
        type(pr[side].get('repo')) is dict and type(pr[side]['repo'].get('id')) is int and
        pr[side]['repo']['id']==1416489937 and pr[side]['repo'].get('full_name')=='haji84/RACE-AI'
        for side in ('head','base')) and type(pr['head'].get('sha')) is str and
        re.fullmatch('[a-f0-9]{40}',pr['head']['sha']),'SAME_REPOSITORY_PR71_REQUIRED')
    env=future.environment()
    need(pr['head'].get('sha')==env['head_sha'],'PR71_ACTUAL_HEAD_BINDING')
    return env


def _actual(value,pin,kind,now):
    run=value.get('workflow_run') if type(value) is dict else None
    prefix={'native':'all-existing-model-pairs-','result':'all-existing-official-results-',
        'pdca':'all-existing-model-order-only-pdca-'}[kind]
    name=value.get('name') if type(value) is dict else None
    pattern=prefix+str(pin['run_id'])+'-'+(str(ROUND) if kind=='pdca' else '[1-9][0-9]*')
    need(type(value) is dict and type(value.get('id')) is int and value['id']==pin['id'] and
        value.get('digest')==pin['digest'] and value.get('expired') is False and type(name) is str and
        re.fullmatch(pattern,name) and type(value.get('size_in_bytes')) is int and
        0<value['size_in_bytes']<=MAX_ARCHIVE_BYTES and type(run) is dict and type(run.get('id')) is int and
        run['id']==pin['run_id'] and run.get('head_sha')==pin['head_sha'] and all(type(run.get(k)) is int and
        run[k]==1416489937 for k in ('repository_id','head_repository_id')),'ACTUAL_ARTIFACT_METADATA')
    need(future.stamp(value.get('created_at'))<=now<future.stamp(value.get('expires_at')),'ACTUAL_ARTIFACT_CLOCK')
    return value


def _download(pin,metadata):
    raw=future.gh('actions/artifacts/'+str(pin['id'])+'/zip')
    need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE_BYTES and len(raw)==metadata['size_in_bytes'] and
        'sha256:'+sha256(raw).hexdigest()==pin['digest'],'ACTUAL_ARCHIVE_BYTES')
    return raw


def _sources(manifest,now):
    pins=[manifest['future_artifact'],manifest['result_artifact'],*manifest['additional_native_artifacts']]
    metas=[_actual(future.metadata(pin['id']),pin,'result' if index==1 else 'native',now) for index,pin in enumerate(pins)]
    need(sum(m['size_in_bytes'] for m in metas)<=MAX_TOTAL_BYTES,'TOTAL_ARCHIVE_BOUND')
    raws=[];total=0
    for pin,meta in zip(pins,metas):
        raw=_download(pin,meta);total+=len(raw);need(total<=MAX_TOTAL_BYTES,'TOTAL_ARCHIVE_BOUND');raws.append(raw)
    return raws,metas,total


def _bound_receipt(receipt,pin):
    need(receipt.get('artifact_id')==pin['id'] and receipt.get('artifact_digest',receipt.get('digest'))==pin['digest'] and
        receipt.get('workflow_run_id')==pin['run_id'] and receipt.get('head_sha')==pin['head_sha'],'ORIGINAL_MANIFEST_BINDING')


def _local_members(root,manifest):
    _private_directory(root);folders=list(root.iterdir());members={};count=0
    need(len(folders)<=16384 and all(p.is_dir() and not p.is_symlink() and re.fullmatch('[a-f0-9]{64}',p.name)
        for p in folders),'OPAQUE_PARTITIONS_ONLY')
    for folder in sorted(folders):
        _private_directory(folder);need({p.name for p in folder.iterdir()}==set(MEMBER_LIMITS),'EXACT_THREE_MEMBERS')
        for name,limit in MEMBER_LIMITS.items():
            path=folder/name;_private_file(path);raw=_read(path,limit);count+=len(raw)
            need(count<=MAX_ARCHIVE_BYTES,'LOCAL_ARCHIVE_BOUND');members[folder.name+'/'+name]=raw
        payload=read_candidate(folder);core.verify_private_order_only_pdca(payload)
        _bound_receipt(payload['source_forecast'],manifest['future_artifact'])
        _bound_receipt(payload['source_result'],manifest['result_artifact'])
        extras=payload['additional_native_admissions']
        need(len(extras)==len(manifest['additional_native_artifacts']),'ADDITIONAL_MANIFEST_BINDING')
        for receipt,pin in zip(extras,manifest['additional_native_artifacts']):_bound_receipt(receipt,pin)
    return members


def _fingerprint(members):return digest([[name,sha256(raw).hexdigest()] for name,raw in sorted(members.items())])

def _counts(summary):return {name:summary[name] for name in COUNT_FIELDS if name in summary}


def generate(root,env,manifest,*,now):
    state_key('production')
    need(not root.exists() and not any(root.with_name(root.name+suffix).exists() for suffix in
        ('.status.json','.summary.json','.generation.json')),'OUTPUT_EXISTS_DO_NOT_RESET')
    raws,metas,total=_sources(manifest,now);native=manifest['future_artifact'];result=manifest['result_artifact']
    extras=[dict(raw=raw,metadata=meta,expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'])
        for raw,meta,pin in zip(raws[2:],metas[2:],manifest['additional_native_artifacts'])]
    summary=core.score_order_only_pairs_artifacts(raws[0],metas[0],raws[1],metas[1],root,now=now,
        expected_native_run_id=native['run_id'],expected_native_head_sha=native['head_sha'],
        expected_result_run_id=result['run_id'],expected_result_head_sha=result['head_sha'],additional_native_artifacts=extras)
    members=_local_members(root,manifest)
    return dict(_counts(summary),ready=summary['paired_forecasts']>0,manifest_sha256=digest(manifest),
        state='ORDER_ONLY_PDCA_ENCRYPTED_LOCAL_ONLY' if summary['paired_forecasts']>0 else 'HOLD_ORDER_ONLY_PDCA_NO_TYPED_PAIRS',
        core_summary_sha256=digest(summary),local_members_sha256=_fingerprint(members),local_member_count=len(members),
        local_uncompressed_output_bytes=sum(map(len,members.values())),source_archive_bytes=total,
        additional_native_artifact_count=len(extras),actual_uploaded_archive_capacity_verified=False)


def _remote_members(raw):
    need(raw.startswith(b'PK\x03\x04') and len(raw)>=22 and raw[-22:-18]==b'PK\x05\x06' and raw[-2:]==b'\0\0',
        'ACTUAL_ZIP_ENVELOPE')
    members={}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        need(not archive.comment,'ACTUAL_ZIP_COMMENT')
        for folder,entries in _entries(archive).items():
            for name,entry in entries.items():
                with archive.open(entry) as stream:body=stream.read(MEMBER_LIMITS[name]+1)
                need(len(body)==entry.file_size,'ACTUAL_MEMBER_BYTES');members[folder+'/'+name]=body
    return members


def readback(ident,root,env,manifest,*,now):
    state_key('production');members=_local_members(root,manifest)
    generation=root.with_name(root.name+'.generation.json');_private_file(generation)
    previous=read_json_bytes(_read(generation,256*1024))
    need(type(previous) is dict and previous.get('schema')==STATUS and previous.get('ready') is True and
        previous.get('workflow_run_id')==env['run_id'] and previous.get('expected_head_sha')==env['head_sha'] and
        previous.get('manifest_sha256')==digest(manifest) and previous.get('local_members_sha256')==_fingerprint(members) and
        previous.get('local_member_count')==len(members),'LOCAL_IMMUTABLE_GENERATION')
    path=root.with_name(root.name+'.summary.json');_private_file(path);summary=read_json_bytes(_read(path,1024*1024))
    need(previous.get('core_summary_sha256')==digest(summary) and all(previous.get(k)==v for k,v in _counts(summary).items()) and
        summary['paired_forecasts']>0,'LOCAL_SUMMARY_BINDING')
    actual=future.metadata(ident);pin=_pin(dict(id=ident,digest=actual.get('digest'),run_id=env['run_id'],head_sha=env['head_sha']))
    _actual(actual,pin,'pdca',now);raw=_download(pin,actual)
    checked=core.verify_order_only_pdca_artifact(raw,actual,now=now,expected_run_id=env['run_id'],expected_head_sha=env['head_sha'])
    need(_remote_members(raw)==members and all(checked.get(k)==v for k,v in summary.items()
        if k!='independent_pdca_artifact_receipt_verified'),'ACTUAL_ORIGINAL_READBACK')
    return dict(_counts(checked),manifest_sha256=digest(manifest),state='ORDER_ONLY_PDCA_ACTUAL_ARTIFACT_VERIFIED',ready=True,
        pdca_artifact_id=ident,pdca_artifact_digest=actual['digest'],pdca_saved_at=actual['created_at'],
        pdca_expires_at=actual['expires_at'],core_summary_sha256=digest(summary),local_members_sha256=_fingerprint(members),
        actual_uploaded_archive_capacity_verified=True,actual_uploaded_archive_bytes=len(raw))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True);parser.add_argument('--out-dir',required=True)
    parser.add_argument('--readback-artifact',type=int);args=parser.parse_args(argv)
    status=dict(schema=STATUS,state='HOLD_ORDER_ONLY_PDCA',ready=False,source_requests=0,plaintext_published=False,
        public_redistribution=False,provider_model_training_permission_confirmed=False,production_promoted=False,
        actual_purchases=False,monetary_evaluation_available=False,missing_results_are_not_losses=True,
        actual_thirty_model_future_proof_claimed=False,storage_capacity_for_all_thirty_models_verified=False,
        independent_pdca_artifact_receipt_verified=False,actual_uploaded_archive_capacity_verified=False)
    root=None
    try:
        env=environment();root=future.output_path(args.out_dir,env);manifest=load_manifest(args.input)
        status.update(workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],
            artifact_name=f'all-existing-model-order-only-pdca-{env["run_id"]}-{ROUND}')
        now=utc_now()
        status.update(generate(root,env,manifest,now=now) if args.readback_artifact is None else
            readback(args.readback_artifact,root,env,manifest,now=now))
        if args.readback_artifact is None and status['ready']:
            _write(root.with_name(root.name+'.generation.json'),future.wire(status))
    except Exception as exc:status.update(state='HOLD_ORDER_ONLY_PDCA',ready=False,**future.safe_diagnostic(exc))
    if root is not None:
        try:
            path=root.with_name(root.name+'.status.json');save(path,future.wire(status),replace=path.exists())
        except Exception as exc:status.update(state='HOLD_ORDER_ONLY_PDCA',ready=False,**future.safe_diagnostic(exc))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(status['ready']).lower()+'\n')
            if status.get('artifact_name'):output.write('artifact_name='+status['artifact_name']+'\n')
    print(json.dumps(status,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
