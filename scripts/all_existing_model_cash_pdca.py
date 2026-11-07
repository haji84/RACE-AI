"""Explicit Actions cash19 PDCA; ORDER_ONLY future30 remains out of cash scope."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from race_ai.actions_contract import digest
from race_ai import all_existing_model_cash_pdca as core
from race_ai.all_existing_model_receipt import MAX_ARCHIVE_BYTES
from race_ai.all_existing_model_runtime import _private_file
from race_ai.boat_pdca_state import state_key
from race_ai.boat_venue_learning import read_candidate
from race_ai.permissioned_source_delivery import read_json_bytes
from race_ai.repeated_cycle import matches as legacy_artifact_matches
from scripts import all_existing_model_future_p0 as future
from scripts import all_existing_model_order_only_pdca as shared
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

SCHEMA='RACE_AI_CASH_NATIVE_PDCA_INPUT_V1'
STATUS='RACE_AI_CASH_NATIVE_PDCA_ACTIONS_COUNTS_V1'
ROUND=900012
COUNT_FIELDS=('candidate_cell_count','cash_cell_scope','cash_sports','partition_count','baseline_forecast_count',
    'learned_forecast_count','paired_forecasts','observation_count','result_state_counts','source_artifact_id',
    'source_artifact_digest','source_workflow_run_id','source_head_sha','training_sha256','source_context_sha256',
    'origin_artifact_id','origin_artifact_digest','outside_cash_forecast_count','source_forecast_count',
    'matched_cash_result_count','unmatched_cash_result_count','outside_normal_cash_result_state_counts',
    'independent_pre_cutoff_receipt_verified','independent_origin_receipt_verified',
    'independent_result_artifact_receipt_verified','independent_pdca_artifact_receipt_verified',
    'encrypted_readback_verified','all_thirty_cells_scored','missing_results_are_not_losses')


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_CASH_PDCA_CLI_'+reason)


def utc_now():return datetime.now(timezone.utc)


def validate_manifest(value):
    fields={'schema','candidate_cell_count','future_artifact','origin_artifact','result_artifacts','additional_native_artifacts'}
    need(type(value) is dict and set(value)==fields and value['schema']==SCHEMA and
        type(value['candidate_cell_count']) is int and value['candidate_cell_count'] in (19,30) and
        type(value['result_artifacts']) is list and 1<=len(value['result_artifacts'])<=16 and
        type(value['additional_native_artifacts']) is list and len(value['additional_native_artifacts'])<=16,'MANIFEST_SCHEMA')
    pins=[shared._pin(value['future_artifact']),shared._pin(value['origin_artifact'])]
    for item in value['result_artifacts']:
        need(type(item) is dict and set(item)==shared.PIN_FIELDS|{'kind'} and item['kind'] in ('BOAT','OFFICIAL'),'RESULT_KIND')
        pins.append(shared._pin({k:v for k,v in item.items() if k!='kind'}))
    pins.extend(shared._pin(item) for item in value['additional_native_artifacts'])
    need(len({pin['id'] for pin in pins})==len(pins),'DISTINCT_ARTIFACTS')
    return value


def load_manifest(path):return validate_manifest(read_json_bytes(_read(Path(path),32768)))


def environment():return shared.environment()


def _actual(value,pin,kind,now):
    run=value.get('workflow_run') if type(value) is dict else None
    patterns={'native':f'all-existing-model-pairs-{pin["run_id"]}-[1-9][0-9]*',
        'origin':f'all-native-future-origin-{pin["run_id"]}-900010',
        'OFFICIAL':f'all-existing-official-results-{pin["run_id"]}-[1-9][0-9]*',
        'BOAT':f'race-existing-cycle-{pin["run_id"]}-.+',
        'pdca':f'all-existing-model-cash-pdca-{pin["run_id"]}-{ROUND}'}
    need(type(value) is dict and type(value.get('id')) is int and value['id']==pin['id'] and
        value.get('digest')==pin['digest'] and value.get('expired') is False and
        type(value.get('name')) is str and (legacy_artifact_matches(value['name'],'race-existing-cycle-'+str(pin['run_id']))
        if kind=='BOAT' else re.fullmatch(patterns[kind],value['name'])) and
        type(value.get('size_in_bytes')) is int and 0<value['size_in_bytes']<=MAX_ARCHIVE_BYTES and
        type(run) is dict and type(run.get('id')) is int and run['id']==pin['run_id'] and
        run.get('head_sha')==pin['head_sha'] and all(type(run.get(k)) is int and run[k]==1416489937
        for k in ('repository_id','head_repository_id')),'ACTUAL_ARTIFACT_METADATA')
    need(future.stamp(value.get('created_at'))<=now<future.stamp(value.get('expires_at')),'ACTUAL_ARTIFACT_CLOCK')
    return value


def _sources(manifest,now):
    sources=[('native',manifest['future_artifact']),('origin',manifest['origin_artifact'])]
    sources.extend((pin['kind'],{k:v for k,v in pin.items() if k!='kind'}) for pin in manifest['result_artifacts'])
    sources.extend(('native',pin) for pin in manifest['additional_native_artifacts'])
    metas=[_actual(future.metadata(pin['id']),pin,kind,now) for kind,pin in sources]
    need(sum(meta['size_in_bytes'] for meta in metas)<=core.MAX_TOTAL_BYTES,'TOTAL_ARCHIVE_BOUND')
    raws=[shared._download(pin,meta) for (_,pin),meta in zip(sources,metas)]
    total=sum(map(len,raws));need(total<=core.MAX_TOTAL_BYTES,'TOTAL_ARCHIVE_BOUND')
    count=len(manifest['result_artifacts']);results=[];extras=[]
    for index,((kind,pin),raw,meta) in enumerate(zip(sources[2:],raws[2:],metas[2:])):
        item=dict(raw=raw,metadata=meta,expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'])
        if index<count:results.append(dict(item,kind=kind))
        else:extras.append(item)
    return raws[0],metas[0],raws[1],metas[1],results,extras,total


def _args(manifest,now,extras):
    pin=manifest['future_artifact']
    return dict(now=now,expected_native_run_id=pin['run_id'],expected_native_head_sha=pin['head_sha'],
        candidate_cell_count=manifest['candidate_cell_count'],additional_native_artifacts=extras)


def _counts(summary):return {name:summary[name] for name in COUNT_FIELDS if name in summary}


def _local_members(root,manifest):
    # Existing opaque-layout/private-mode and bounded ZIP-member validation.
    from race_ai.all_existing_model_runtime import _private_directory
    from race_ai.boat_venue_learning_context import MEMBER_LIMITS
    _private_directory(root);members={};folders=list(root.iterdir());total=0
    need(0<len(folders)<=30 and all(p.is_dir() and not p.is_symlink() and re.fullmatch('[a-f0-9]{64}',p.name)
        for p in folders),'OPAQUE_PARTITIONS_ONLY')
    for folder in sorted(folders):
        _private_directory(folder);need({p.name for p in folder.iterdir()}==set(MEMBER_LIMITS),'EXACT_THREE_MEMBERS')
        for name,limit in MEMBER_LIMITS.items():
            path=folder/name;_private_file(path);body=_read(path,limit);total+=len(body)
            need(total<=MAX_ARCHIVE_BYTES,'LOCAL_ARCHIVE_BOUND');members[folder.name+'/'+name]=body
        payload=read_candidate(folder);core.verify_private_cash_pdca(payload);context=payload['source_context']
        shared._bound_receipt(context['source_admission'],manifest['future_artifact'])
        need(context['candidate_cell_count']==manifest['candidate_cell_count'] and
            context['origin']['origin_metadata']['id']==manifest['origin_artifact']['id'] and
            context['origin']['origin_metadata']['digest']==manifest['origin_artifact']['digest'],'ORIGIN_MANIFEST_BINDING')
        need(len(context['result_contexts'])==len(manifest['result_artifacts']) and
            len(context['additional_native_admissions'])==len(manifest['additional_native_artifacts']),'SOURCE_MANIFEST_BINDING')
        for item,pin in zip(context['result_contexts'],manifest['result_artifacts']):
            need(item['kind']==pin['kind'],'RESULT_MANIFEST_KIND');shared._bound_receipt(item['receipt'],pin)
        for receipt,pin in zip(context['additional_native_admissions'],manifest['additional_native_artifacts']):shared._bound_receipt(receipt,pin)
    return members


def generate(root,env,manifest,*,now):
    state_key('production');need(not root.exists() and not any(root.with_name(root.name+suffix).exists() for suffix in
        ('.status.json','.generation.json','.summary.json')),'OUTPUT_EXISTS_DO_NOT_RESET')
    need(manifest['candidate_cell_count']==19,'ORDER_ONLY_CANDIDATE_CASH_SCOPE_REQUIRES_SEPARATE_OWNER_DECISION')
    native,nmeta,origin,ometa,results,extras,total=_sources(manifest,now)
    summary=core.score_cash_pairs_artifacts(native,nmeta,origin,ometa,results,root,**_args(manifest,now,extras))
    members=_local_members(root,manifest)
    return dict(_counts(summary),ready=summary['paired_forecasts']>0,manifest_sha256=digest(manifest),
        state='CASH_NATIVE_PDCA_ENCRYPTED_LOCAL_ONLY' if summary['paired_forecasts'] else 'HOLD_CASH_NATIVE_PDCA_NO_NORMAL_PAIRS',
        core_summary_sha256=digest(summary),local_members_sha256=shared._fingerprint(members),local_member_count=len(members),
        source_archive_bytes=total,actual_uploaded_archive_capacity_verified=False)


def readback(ident,root,env,manifest,*,now):
    state_key('production')
    need(manifest['candidate_cell_count']==19,'ORDER_ONLY_CANDIDATE_CASH_SCOPE_REQUIRES_SEPARATE_OWNER_DECISION')
    members=_local_members(root,manifest)
    generation=root.with_name(root.name+'.generation.json');_private_file(generation)
    previous=read_json_bytes(_read(generation,256*1024))
    need(previous.get('schema')==STATUS and previous.get('ready') is True and previous.get('workflow_run_id')==env['run_id'] and
        previous.get('expected_head_sha')==env['head_sha'] and previous.get('manifest_sha256')==digest(manifest) and
        previous.get('local_members_sha256')==shared._fingerprint(members) and previous.get('local_member_count')==len(members),'LOCAL_IMMUTABLE_GENERATION')
    path=root.with_name(root.name+'.summary.json');_private_file(path);summary=read_json_bytes(_read(path,1024*1024))
    need(previous.get('core_summary_sha256')==digest(summary) and summary['paired_forecasts']>0,'LOCAL_SUMMARY_BINDING')
    # Fresh original metadata/ZIP replay independently re-authenticates result
    # normalization and original originMAC, rather than trusting local claims.
    native,nmeta,origin,ometa,results,extras,_=_sources(manifest,now)
    context,_,_=core.admit_sources(native,nmeta,origin,ometa,results,**_args(manifest,now,extras))
    need(digest(context)==summary['source_context_sha256'],'ORIGINAL_SOURCE_REPLAY')
    actual=future.metadata(ident);pin=shared._pin(dict(id=ident,digest=actual.get('digest'),run_id=env['run_id'],head_sha=env['head_sha']))
    _actual(actual,pin,'pdca',now);raw=shared._download(pin,actual)
    checked=core.verify_cash_pdca_artifact(raw,actual,now=now,expected_run_id=env['run_id'],expected_head_sha=env['head_sha'],
        expected_source_context_sha256=digest(context))
    need(shared._remote_members(raw)==members and all(checked.get(k)==v for k,v in summary.items()
        if k not in ('independent_pdca_artifact_receipt_verified','source_archive_bytes')),'ACTUAL_ORIGINAL_READBACK')
    return dict(_counts(checked),manifest_sha256=digest(manifest),state='CASH_NATIVE_PDCA_ACTUAL_ARTIFACT_VERIFIED',ready=True,
        pdca_artifact_id=ident,pdca_artifact_digest=actual['digest'],pdca_saved_at=actual['created_at'],pdca_expires_at=actual['expires_at'],
        core_summary_sha256=digest(summary),local_members_sha256=shared._fingerprint(members),
        actual_uploaded_archive_capacity_verified=True,actual_uploaded_archive_bytes=len(raw))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True);parser.add_argument('--out-dir',required=True)
    parser.add_argument('--readback-artifact',type=int);args=parser.parse_args(argv)
    status=dict(schema=STATUS,state='HOLD_CASH_NATIVE_PDCA',ready=False,source_requests=0,plaintext_published=False,
        public_redistribution=False,provider_model_training_permission_confirmed=False,production_promoted=False,actual_purchases=False,
        missing_results_are_not_losses=True,all_thirty_cells_scored=False,independent_pdca_artifact_receipt_verified=False,
        actual_uploaded_archive_capacity_verified=False)
    root=None
    try:
        env=environment();root=future.output_path(args.out_dir,env);manifest=load_manifest(args.input)
        status.update(workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],
            artifact_name=f'all-existing-model-cash-pdca-{env["run_id"]}-{ROUND}')
        status.update(generate(root,env,manifest,now=utc_now()) if args.readback_artifact is None else
            readback(args.readback_artifact,root,env,manifest,now=utc_now()))
        if args.readback_artifact is None and status['ready']:_write(root.with_name(root.name+'.generation.json'),future.wire(status))
    except Exception as exc:status.update(state='HOLD_CASH_NATIVE_PDCA',ready=False,**future.safe_diagnostic(exc))
    if root is not None:
        try:
            path=root.with_name(root.name+'.status.json');save(path,future.wire(status),replace=path.exists())
        except Exception as exc:status.update(state='HOLD_CASH_NATIVE_PDCA',ready=False,**future.safe_diagnostic(exc))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(status['ready']).lower()+'\n')
            if status.get('artifact_name'):output.write('artifact_name='+status['artifact_name']+'\n')
    print(json.dumps(status,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
