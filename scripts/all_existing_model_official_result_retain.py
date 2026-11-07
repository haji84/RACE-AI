"""Retain pinned RESULT originals once per existing source-worker run.

Only actual GitHub artifact reads and the existing transfer-ref append occur.
Authenticated local DONE/HOLD markers suppress repeated work in the same run.
"""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re

from race_ai.actions_contract import digest
from race_ai import all_existing_model_result_retention as retention
from race_ai import all_existing_model_official_results as results
from race_ai.boat_pdca_state import state_key
from race_ai.all_existing_model_runtime import _private_directory,_private_file
from scripts import all_existing_model_official_result_freeze as freeze
from scripts import all_existing_model_future_p0 as future
from scripts.boat_all_racers import _read,_write
from scripts.boat_saved_view_feed import git_auth

ROOT=Path(__file__).resolve().parents[1]
SCHEMA='RACE_AI_OFFICIAL_RESULT_RETAIN_INPUT_V1'
STATUS='RACE_AI_OFFICIAL_RESULT_RETAIN_COUNTS_V1'
MARKER='RACE_AI_OFFICIAL_RESULT_RETAIN_LOCAL_MARKER_V1'
DOMAIN=b'RACE_AI_OFFICIAL_RESULT_RETAIN_LOCAL_MARKER_MAC_V1'


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_OFFICIAL_RESULT_RETAIN_'+reason)


def utc_now():return datetime.now(timezone.utc)


def validate_manifest(value):
    need(type(value) is dict and set(value)=={'schema','native_artifacts','result_artifacts','allow_order_only'} and
         value['schema']==SCHEMA and type(value['allow_order_only']) is bool,'MANIFEST_SCHEMA')
    seen=set()
    for name in ('native_artifacts','result_artifacts'):
        pins=value[name];need(type(pins) is list and 1<=len(pins)<=16,'BOUNDED_ARTIFACT_PINS')
        for pin in pins:
            need(type(pin) is dict and set(pin)=={'id','digest','run_id','head_sha'} and
                 type(pin['id']) is int and 0<pin['id']<10**16 and pin['id'] not in seen and
                 type(pin['run_id']) is int and 0<pin['run_id']<10**20 and
                 type(pin['digest']) is str and re.fullmatch('sha256:[a-f0-9]{64}',pin['digest']) and
                 type(pin['head_sha']) is str and re.fullmatch('[a-f0-9]{40}',pin['head_sha']),'ARTIFACT_PIN')
            seen.add(pin['id'])
    return value


def local_environment():
    state_key('production')
    need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI' and
         os.environ.get('GITHUB_REPOSITORY_ID')=='1416489937','TRUSTED_ACTIONS_REQUIRED')
    run=os.environ.get('GITHUB_RUN_ID','');head=os.environ.get('GITHUB_SHA','')
    need(re.fullmatch('[1-9][0-9]{0,19}',run) and re.fullmatch('[a-f0-9]{40}',head),'CURRENT_RUN_REQUIRED')
    temp=Path(os.environ.get('RUNNER_TEMP',''))
    need(temp.is_absolute() and temp.is_dir() and not any(p.is_symlink() for p in (temp,*temp.parents)) and
         not any((p/'.git').exists() for p in (temp,*temp.parents)),'PRIVATE_TEMP_REQUIRED')
    return dict(run_id=int(run),head_sha=head,temp=temp)


def _scope(manifest,env):
    return dict(repository_id=results.REPOSITORY_ID,workflow_run_id=env['run_id'],head_sha=env['head_sha'],
                manifest_sha256=digest(manifest))


def _paths(root,scope):
    suffix=str(scope['workflow_run_id'])+'-'+scope['manifest_sha256']+'.json'
    return root/('done-'+suffix),root/('hold-'+suffix)


def _signed(state,key):
    domain=hmac.digest(key,DOMAIN,'sha256')
    return future.wire(dict(state=state,mac=hmac.digest(domain,future.wire(state),'sha256').hex()))


def _marker(path,scope,key,kind,now,manifest):
    _private_file(path);raw=_read(path,128*1024);value=retention.vault._json(raw,128*1024)
    need(type(value) is dict and set(value)=={'state','mac'} and type(value.get('state')) is dict and
         type(value.get('mac')) is str and re.fullmatch('[a-f0-9]{64}',value['mac']),'LOCAL_MARKER_SCHEMA')
    need(hmac.compare_digest(_signed(value['state'],key),raw),'LOCAL_MARKER_MAC')
    state=value['state']
    need(set(state)=={'schema','purpose','scope','completed_at','summary'} and state['schema']==MARKER and
         state['purpose']==kind and state['scope']==scope and type(state['summary']) is dict and
         future.stamp(state['completed_at'])<=now,'LOCAL_MARKER_BINDING')
    summary=state['summary']
    need(summary.get('schema')==STATUS and summary.get('ready') is (kind=='DONE') and
         summary.get('source_provider_requests')==0 and summary.get('manifest_sha256')==scope['manifest_sha256'],
         'LOCAL_MARKER_SUMMARY')
    if kind=='DONE':
        pointers=summary.get('pointers')
        need(type(pointers) is list and len(pointers)==len(manifest['result_artifacts']) and
             summary.get('retained_result_artifact_count')==len(pointers),'LOCAL_DONE_COUNTS')
        for pointer,pin in zip(pointers,manifest['result_artifacts']):
            retention._validate_pointer(pointer)
            need(pointer['artifact_id']==pin['id'] and pointer['workflow_run_id']==pin['run_id'] and
                 pointer['head_sha']==pin['head_sha'] and 'sha256:'+pointer['original_zip_sha256']==pin['digest'],
                 'LOCAL_DONE_ARTIFACT_BINDING')
    return dict(summary,skipped=True)


def _write_marker(path,scope,key,kind,summary,now):
    state=dict(schema=MARKER,purpose=kind,scope=scope,completed_at=now.isoformat(),summary=summary)
    _write(path,_signed(state,key))


def _safe_error(exc):
    code=str(exc)
    return code if re.fullmatch(r'(?:ALL_MODEL_|OWNER_STATE_|STATE_|VAULT_|GITHUB_|FEED_|BOAT_ALL_MODEL_)[A-Z0-9_]{1,150}',code) else 'RETAIN_OPERATION_REJECTED'


def _result_original(pin,now):
    metadata_raw=future.gh('actions/artifacts/'+str(pin['id']))
    metadata=retention.vault._json(metadata_raw,retention.vault.MAX_METADATA)
    run=metadata.get('workflow_run') if type(metadata) is dict else None
    need(type(metadata) is dict and type(metadata.get('id')) is int and metadata['id']==pin['id'] and
         metadata.get('digest')==pin['digest'] and metadata.get('expired') is False and
         type(metadata.get('size_in_bytes')) is int and 0<metadata['size_in_bytes']<=results.MAX_ARCHIVE_BYTES and
         type(metadata.get('name')) is str and re.fullmatch('all-existing-official-results-'+str(pin['run_id'])+
             '-[1-9][0-9]{0,5}',metadata['name']) and type(run) is dict and type(run.get('id')) is int and
         run['id']==pin['run_id'] and run.get('head_sha')==pin['head_sha'] and
         all(type(run.get(k)) is int and run[k]==results.REPOSITORY_ID for k in
             ('repository_id','head_repository_id')),'ACTUAL_RESULT_METADATA')
    need(future.stamp(metadata.get('created_at'))<=now<future.stamp(metadata.get('expires_at')),
         'RESULT_ARTIFACT_CLOCK')
    raw=future.gh('actions/artifacts/'+str(pin['id'])+'/zip')
    need(type(raw) is bytes and len(raw)==metadata['size_in_bytes'] and
         'sha256:'+sha256(raw).hexdigest()==pin['digest'],'RESULT_ARTIFACT_BYTES')
    return raw,metadata_raw,metadata


def retain_manifest(manifest,root,env,*,transport=None,readback_transport=None):
    key=state_key('production');validate_manifest(manifest);now=utc_now();scope=_scope(manifest,env)
    root=future.output_path(root,env)
    if root.exists():_private_directory(root)
    else:root.mkdir(mode=0o700)
    done,held=_paths(root,scope)
    # Existing markers never trigger a current receipt query or another push.
    if held.exists() or held.is_symlink():return _marker(held,scope,key,'HOLD',now,manifest)
    if done.exists() or done.is_symlink():return _marker(done,scope,key,'DONE',now,manifest)
    summary=dict(schema=STATUS,state='HOLD_OFFICIAL_RESULT_RETENTION',ready=False,skipped=False,
        source_provider_requests=0,retained_result_artifact_count=0,pointers=[],manifest_sha256=scope['manifest_sha256'],
        current_label_or_training_admission_created=False,production_promoted=False,actual_purchases=False,
        plaintext_published=False)
    try:
        actual=future.environment()
        need(actual==env,'ACTUAL_CURRENT_RUN_BINDING')
        frozen=freeze.frozen_inputs(manifest,now=now)
        originals=[];total=0
        for pin in manifest['result_artifacts']:
            raw,metadata_raw,metadata=_result_original(pin,now);total+=len(raw)
            need(total<=256*1024*1024,'TOTAL_RESULT_ARCHIVE_BOUND')
            # Admit every pinned original before touching the state writer.
            results.observations_from_official_result_artifact(raw,metadata,now=now,
                expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],frozen_native_payloads=frozen,
                key=key,allow_order_only=manifest['allow_order_only'])
            originals.append((raw,metadata_raw))
        git_auth();git=retention._transport(ROOT,transport);parent=git.head()
        need(type(parent) is str and re.fullmatch('[a-f0-9]{40}',parent),'EXISTING_TRANSFER_PARENT_REQUIRED')
        for raw,metadata_raw in originals:
            pointer=retention.retain(raw,metadata_raw,frozen,ROOT,expected_parent=parent,
                allow_order_only=manifest['allow_order_only'],key=key,transport=git,
                readback_transport=readback_transport,now=now)
            summary['pointers'].append(pointer);summary['retained_result_artifact_count']+=1
            parent=pointer['source_commit']
        summary.update(state='OFFICIAL_RESULT_ORIGINALS_RETAINED',ready=True)
        _write_marker(done,scope,key,'DONE',summary,utc_now())
        return summary
    except Exception as exc:
        summary.update(state='HOLD_OFFICIAL_RESULT_RETENTION',ready=False,reason=_safe_error(exc))
        if not held.exists():_write_marker(held,scope,key,'HOLD',summary,utc_now())
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True)
    parser.add_argument('--out-dir',required=True);args=parser.parse_args(argv)
    status=dict(schema=STATUS,state='HOLD_OFFICIAL_RESULT_RETENTION',ready=False,source_provider_requests=0,
                plaintext_published=False,production_promoted=False,actual_purchases=False)
    try:
        env=local_environment();manifest=validate_manifest(retention.vault._json(_read(Path(args.input),32768),32768))
        status=retain_manifest(manifest,Path(args.out_dir),env)
    except Exception as exc:status['reason']=_safe_error(exc)
    print(json.dumps(status,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
