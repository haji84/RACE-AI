"""Explicit PR71 Actions all-thirty rank-only PDCA; no provider or cash scoring."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from race_ai.actions_contract import digest
from race_ai import all_existing_model_thirty_order_pdca as core
from race_ai.all_existing_model_receipt import MAX_ARCHIVE_BYTES
from race_ai.all_existing_model_runtime import _private_directory,_private_file
from race_ai.boat_pdca_state import state_key
from race_ai.boat_venue_learning import read_candidate
from race_ai.boat_venue_learning_context import MEMBER_LIMITS
from race_ai.permissioned_source_delivery import read_json_bytes
from race_ai.repeated_cycle import matches
from scripts import all_existing_model_future_p0 as future
from scripts import all_existing_model_order_only_pdca as shared
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

SCHEMA='RACE_AI_ALL_THIRTY_ORDER_PDCA_INPUT_V1'
SCHEMA_V2='RACE_AI_ALL_THIRTY_ORDER_PDCA_INPUT_V2'
STATUS='RACE_AI_ALL_THIRTY_ORDER_PDCA_ACTIONS_COUNTS_V1'
STATUS_V2='RACE_AI_ALL_THIRTY_ORDER_PDCA_ACTIONS_COUNTS_V2'
ROUND=900023
COUNT_FIELDS=('scope','candidate_cell_count','evaluation_scope','monetary_evaluation_available',
    'partition_count','baseline_forecast_count','learned_forecast_count','paired_forecasts','teacher_matched_forecasts',
    'matched_order_result_count','unmatched_order_result_count','outside_normal_order_result_state_counts',
    'result_state_counts','source_artifact_id','source_artifact_digest','source_workflow_run_id','source_head_sha',
    'training_sha256','origin_artifact_id','origin_artifact_digest','source_context_sha256','all_thirty_cells_produced',
    'all_thirty_cells_scored','independent_pre_cutoff_receipt_verified','independent_origin_receipt_verified',
    'independent_result_artifact_receipt_verified','independent_pdca_artifact_receipt_verified',
    'paired_cohorts_within_cells_only','cross_model_equal_cohort_comparison_claimed','encrypted_readback_verified',
    'forecast_batch_count','forecast_counts_by_sport')


def need(ok,reason):
    if not ok:raise ValueError('ALL_THIRTY_ORDER_PDCA_CLI_'+reason)


def utc_now():return datetime.now(timezone.utc)


def validate_manifest(value):
    multi=type(value) is dict and value.get('schema')==SCHEMA_V2
    fields={'schema','candidate_cell_count','result_artifacts','additional_native_artifacts'}|(
        {'forecast_batches'} if multi else {'future_artifact','origin_artifact'})
    need(type(value) is dict and set(value)==fields and value['schema'] in (SCHEMA,SCHEMA_V2) and
        type(value['candidate_cell_count']) is int and value['candidate_cell_count']==30 and
        type(value['result_artifacts']) is list and 1<=len(value['result_artifacts'])<=16 and
        type(value['additional_native_artifacts']) is list and len(value['additional_native_artifacts'])<=16,'MANIFEST_SCHEMA')
    if multi:
        from race_ai.all_existing_model_future_batches import validate_forecast_batches
        batches=validate_forecast_batches(value['forecast_batches'])
        need(len(value['additional_native_artifacts'])+len(batches)-1<=16,'TEACHER_NATIVE_BOUND')
        ordinary=[pin for batch in batches for pin in batch.values()]+value['additional_native_artifacts']
    else:ordinary=[value['future_artifact'],value['origin_artifact'],*value['additional_native_artifacts']]
    for pin in ordinary:shared._pin(pin)
    results=[]
    for source in value['result_artifacts']:
        need(type(source) is dict and set(source)==shared.PIN_FIELDS|{'kind'} and
            source['kind'] in ('BOAT','OFFICIAL'),'RESULT_KIND')
        results.append(shared._pin({k:v for k,v in source.items() if k!='kind'}))
    pins=ordinary+results
    need(len(pins)<=32 and len({p['id'] for p in pins})==len(pins),'DISTINCT_BOUNDED_ARTIFACTS')
    return value


def load_manifest(path):return validate_manifest(read_json_bytes(_read(Path(path),32768)))


def environment():
    # The new explicit path checks local trusted Actions/event identity before
    # delegating to the existing key + independently fetched current-run guard.
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
    return shared.environment()


def _actual(value,pin,kind,now):
    if kind in ('native','OFFICIAL'):
        return shared._actual(value,pin,'native' if kind=='native' else 'result',now)
    run=value.get('workflow_run') if type(value) is dict else None
    name=value.get('name') if type(value) is dict else None
    valid_name=(name==f'all-native-future-origin-{pin["run_id"]}-900010' if kind=='origin' else
                matches(name,'race-existing-cycle-'+str(pin['run_id'])) if kind=='BOAT' and type(name) is str else
                name==f'all-existing-model-thirty-order-pdca-{pin["run_id"]}-{ROUND}' if kind=='pdca' else False)
    need(type(value) is dict and value.get('id')==pin['id'] and type(value.get('id')) is int and
        value.get('digest')==pin['digest'] and value.get('expired') is False and valid_name and
        type(value.get('size_in_bytes')) is int and 0<value['size_in_bytes']<=MAX_ARCHIVE_BYTES and
        type(run) is dict and type(run.get('id')) is int and run['id']==pin['run_id'] and
        run.get('head_sha')==pin['head_sha'] and all(type(run.get(k)) is int and run[k]==1416489937
            for k in ('repository_id','head_repository_id')),'ACTUAL_ARTIFACT_METADATA')
    need(future.stamp(value.get('created_at'))<=now<future.stamp(value.get('expires_at')),'ACTUAL_ARTIFACT_CLOCK')
    return value


def _sources(manifest,now):
    entries=([entry for batch in manifest['forecast_batches'] for entry in
        (('native',batch['future_artifact']),('origin',batch['origin_artifact']))]
        if manifest['schema']==SCHEMA_V2 else [('native',manifest['future_artifact']),('origin',manifest['origin_artifact'])])
    entries.extend((source['kind'],{k:v for k,v in source.items() if k!='kind'}) for source in manifest['result_artifacts'])
    entries.extend(('native',pin) for pin in manifest['additional_native_artifacts'])
    # Admit every actual metadata object before downloading even the first ZIP.
    metas=[_actual(future.metadata(pin['id']),pin,kind,now) for kind,pin in entries]
    need(sum(meta['size_in_bytes'] for meta in metas)<=core.MAX_TOTAL_BYTES,'TOTAL_ARCHIVE_BOUND')
    raws=[];total=0
    for (_kind,pin),meta in zip(entries,metas):
        raw=shared._download(pin,meta);total+=len(raw);need(total<=core.MAX_TOTAL_BYTES,'TOTAL_ARCHIVE_BOUND');raws.append(raw)
    return entries,raws,metas,total


def _counts(summary):return {field:summary[field] for field in COUNT_FIELDS if field in summary}


def _local_members(root,manifest):
    if manifest['schema']==SCHEMA_V2:
        from race_ai.all_existing_model_thirty_order_aggregate import verify_local
        return verify_local(root,manifest)[1]
    _private_directory(root);folders=list(root.iterdir());members={};total=0
    need(0<len(folders)<=30 and all(p.is_dir() and not p.is_symlink() and re.fullmatch('[a-f0-9]{64}',p.name)
        for p in folders),'OPAQUE_NATIVE_PARTITIONS')
    for folder in sorted(folders):
        _private_directory(folder);need({p.name for p in folder.iterdir()}==set(MEMBER_LIMITS),'EXACT_THREE_MEMBERS')
        for name,limit in MEMBER_LIMITS.items():
            path=folder/name;_private_file(path);raw=_read(path,limit);total+=len(raw)
            need(total<=MAX_ARCHIVE_BYTES,'LOCAL_ARCHIVE_BOUND');members[folder.name+'/'+name]=raw
        payload=read_candidate(folder);core.verify_private_thirty_order_pdca(payload);context=payload['source_context']
        shared._bound_receipt(context['source_admission'],manifest['future_artifact'])
        origin=context['origin']['origin_metadata'];pin=manifest['origin_artifact']
        need(origin['id']==pin['id'] and origin['digest']==pin['digest'] and
            origin['workflow_run']['id']==pin['run_id'] and origin['workflow_run']['head_sha']==pin['head_sha'],'ORIGIN_MANIFEST_BINDING')
        need(len(context['result_contexts'])==len(manifest['result_artifacts']) and
            len(context['additional_native_admissions'])==len(manifest['additional_native_artifacts']),'SOURCE_MANIFEST_BOUND')
        for result,pin in zip(context['result_contexts'],manifest['result_artifacts']):
            need(result['kind']==pin['kind'],'RESULT_KIND_BINDING');shared._bound_receipt(result['receipt'],pin)
        for receipt,pin in zip(context['additional_native_admissions'],manifest['additional_native_artifacts']):
            shared._bound_receipt(receipt,pin)
    return members


def generate(root,env,manifest,*,now):
    state_key('production')
    need(not root.exists() and not any(root.with_name(root.name+suffix).exists() for suffix in
        ('.status.json','.summary.json','.generation.json')),'OUTPUT_EXISTS_DO_NOT_RESET')
    if manifest['schema']==SCHEMA_V2:validate_manifest(manifest)
    entries,raws,metas,total=_sources(manifest,now);nresults=len(manifest['result_artifacts'])
    def item(index):
        pin=entries[index][1]
        return dict(raw=raws[index],metadata=metas[index],expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'])
    if manifest['schema']==SCHEMA_V2:
        from race_ai import all_existing_model_thirty_order_aggregate as aggregate
        count=len(manifest['forecast_batches']);offset=2*count
        archives=[dict(future={k:v for k,v in item(2*i).items() if k in ('raw','metadata')},
                       origin={k:v for k,v in item(2*i+1).items() if k in ('raw','metadata')}) for i in range(count)]
        results=[dict(item(i),kind=entries[i][0]) for i in range(offset,offset+nresults)]
        extras=[item(i) for i in range(offset+nresults,len(entries))]
        summary=aggregate.score(manifest,archives,results,extras,root,now=now,
            producer={k:env[k] for k in ('run_id','head_sha')})
        members=_local_members(root,manifest)
        return dict(_counts(summary),ready=summary['all_thirty_cells_scored'],manifest_sha256=digest(manifest),
            state=summary['state'],core_summary_sha256=digest(summary),local_members_sha256=shared._fingerprint(members),
            local_member_count=len(members),local_uncompressed_output_bytes=sum(map(len,members.values())),
            source_archive_bytes=total,actual_uploaded_archive_capacity_verified=False)
    results=[dict(item(index),kind=entries[index][0]) for index in range(2,2+nresults)]
    extras=[item(index) for index in range(2+nresults,len(entries))]
    native=manifest['future_artifact']
    summary=core.score_thirty_order_pairs_artifacts(raws[0],metas[0],raws[1],metas[1],results,root,now=now,
        expected_native_run_id=native['run_id'],expected_native_head_sha=native['head_sha'],additional_native_artifacts=extras)
    members=_local_members(root,manifest)
    return dict(_counts(summary),ready=summary['teacher_matched_forecasts']>0,manifest_sha256=digest(manifest),
        state='THIRTY_ORDER_PDCA_ENCRYPTED_LOCAL_ONLY' if summary['teacher_matched_forecasts']>0 else 'HOLD_THIRTY_ORDER_PDCA_NO_NORMAL_TEACHER',
        core_summary_sha256=digest(summary),local_members_sha256=shared._fingerprint(members),local_member_count=len(members),
        local_uncompressed_output_bytes=sum(map(len,members.values())),source_archive_bytes=total,
        actual_uploaded_archive_capacity_verified=False)


def readback(ident,root,env,manifest,*,now):
    state_key('production');members=_local_members(root,manifest)
    generation=root.with_name(root.name+'.generation.json');_private_file(generation)
    previous=read_json_bytes(_read(generation,256*1024))
    need(type(previous) is dict and previous.get('schema')==(STATUS_V2 if manifest['schema']==SCHEMA_V2 else STATUS) and previous.get('ready') is True and
        previous.get('workflow_run_id')==env['run_id'] and previous.get('expected_head_sha')==env['head_sha'] and
        previous.get('manifest_sha256')==digest(manifest) and previous.get('local_members_sha256')==shared._fingerprint(members) and
        previous.get('local_member_count')==len(members),'LOCAL_IMMUTABLE_GENERATION')
    summary_path=root.with_name(root.name+'.summary.json');_private_file(summary_path)
    summary=read_json_bytes(_read(summary_path,1024*1024))
    need(previous.get('core_summary_sha256')==digest(summary) and all(previous.get(k)==v for k,v in _counts(summary).items()) and
        summary['teacher_matched_forecasts']>0,'LOCAL_SUMMARY_BINDING')
    actual=future.metadata(ident);pin=shared._pin(dict(id=ident,digest=actual.get('digest'),run_id=env['run_id'],head_sha=env['head_sha']))
    _actual(actual,pin,'pdca',now);raw=shared._download(pin,actual)
    if manifest['schema']==SCHEMA_V2:
        from race_ai.all_existing_model_thirty_order_aggregate import verify_artifact
        verifier=verify_artifact
    else:verifier=core.verify_thirty_order_pdca_artifact
    checked=verifier(raw,actual,now=now,expected_run_id=env['run_id'],expected_head_sha=env['head_sha'],
        expected_source_context_sha256=summary['source_context_sha256'])
    if manifest['schema']==SCHEMA_V2:
        import io,zipfile
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:remote={e.filename:archive.read(e) for e in archive.infolist()}
    else:remote=shared._remote_members(raw)
    need(remote==members and all(checked.get(k)==v for k,v in summary.items()
        if k not in ('independent_pdca_artifact_receipt_verified','source_archive_bytes')),'ACTUAL_ORIGINAL_READBACK')
    return dict(_counts(checked),manifest_sha256=digest(manifest),state='THIRTY_ORDER_PDCA_ACTUAL_ARTIFACT_VERIFIED',ready=True,
        pdca_artifact_id=ident,pdca_artifact_digest=actual['digest'],pdca_saved_at=actual['created_at'],
        pdca_expires_at=actual['expires_at'],core_summary_sha256=digest(summary),
        local_members_sha256=shared._fingerprint(members),actual_uploaded_archive_capacity_verified=True,
        actual_uploaded_archive_bytes=len(raw))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True);parser.add_argument('--out-dir',required=True)
    parser.add_argument('--readback-artifact',type=int);args=parser.parse_args(argv)
    status=dict(schema=STATUS,state='HOLD_THIRTY_ORDER_PDCA',ready=False,source_requests=0,
        plaintext_published=False,public_redistribution=False,provider_model_training_permission_confirmed=False,
        production_promoted=False,actual_purchases=False,monetary_evaluation_available=False,
        missing_results_are_not_losses=True,actual_thirty_model_future_proof_claimed=False,
        storage_capacity_for_all_thirty_models_verified=False,independent_pdca_artifact_receipt_verified=False,
        actual_uploaded_archive_capacity_verified=False)
    root=None
    try:
        env=environment();root=future.output_path(args.out_dir,env);manifest=load_manifest(args.input)
        if manifest['schema']==SCHEMA_V2:status['schema']=STATUS_V2
        status.update(workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],
                      artifact_name=f'all-existing-model-thirty-order-pdca-{env["run_id"]}-{ROUND}')
        now=utc_now();status.update(generate(root,env,manifest,now=now) if args.readback_artifact is None else
                                   readback(args.readback_artifact,root,env,manifest,now=now))
        if args.readback_artifact is None and status['ready']:
            _write(root.with_name(root.name+'.generation.json'),future.wire(status))
    except Exception as exc:status.update(state='HOLD_THIRTY_ORDER_PDCA',ready=False,**future.safe_diagnostic(exc))
    if root is not None:
        try:
            path=root.with_name(root.name+'.status.json');save(path,future.wire(status),replace=path.exists())
        except Exception as exc:status.update(state='HOLD_THIRTY_ORDER_PDCA',ready=False,**future.safe_diagnostic(exc))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(status['ready']).lower()+'\n')
            if status.get('artifact_name'):output.write('artifact_name='+status['artifact_name']+'\n')
    print(json.dumps(status,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
