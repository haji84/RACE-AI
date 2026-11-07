"""Replay encrypted official result sources and read back their opaque artifact.

Only GitHub artifact reads occur here. Source collection, owner authorization,
model fitting and monetary evaluation are separate operations.
"""
import argparse
from collections import Counter
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from race_ai.actions_contract import digest
from race_ai import all_existing_model_official_results as results
from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact,MAX_ARCHIVE_BYTES
from race_ai.boat_all_model_store import MAX_WIRE,MAX_PLAIN,open_forecasts,forecast_header
from race_ai.boat_pdca_state import state_key
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_p0 as future
from scripts.all_existing_model_official_freeze import _repository_file
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

ROOT=Path(__file__).resolve().parents[1]
ROUND=900005
SCHEMA='RACE_AI_OFFICIAL_RESULT_FREEZE_INPUT_V1'
PACKET='RACE_AI_OFFICIAL_RESULT_SOURCE_PACKET_V1'
STATUS='RACE_AI_OFFICIAL_RESULT_FREEZE_COUNTS_V1'
JST=timezone(timedelta(hours=9))


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_OFFICIAL_RESULT_FREEZE_'+reason)


def utc_now():return datetime.now(timezone.utc)


def _manifest(value,now):
    need(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    need(type(value) is dict and set(value)=={'schema','execution_day','packet_path','packet_sha256',
         'native_artifacts','allow_order_only'} and value['schema']==SCHEMA,'MANIFEST_SCHEMA')
    need(value['execution_day']==now.astimezone(JST).date().isoformat(),'EXECUTION_DAY')
    need(type(value['allow_order_only']) is bool,'EXPLICIT_ORDER_ONLY_MODE')
    hashed=value['packet_sha256']
    need(type(hashed) is str and re.fullmatch('[a-f0-9]{64}',hashed) and
         value['packet_path']=='audit/state/official-result-source-packet-'+hashed+'.enc','PACKET_PATH_SHA')
    pins=value['native_artifacts'];seen=set()
    need(type(pins) is list and 1<=len(pins)<=16,'BOUNDED_NATIVE_ARTIFACTS')
    for pin in pins:
        need(type(pin) is dict and set(pin)=={'id','digest','run_id','head_sha'} and
             type(pin['id']) is int and 0<pin['id']<10**16 and pin['id'] not in seen and
             type(pin['run_id']) is int and 0<pin['run_id']<10**20 and
             type(pin['digest']) is str and re.fullmatch('sha256:[a-f0-9]{64}',pin['digest']) and
             type(pin['head_sha']) is str and re.fullmatch('[a-f0-9]{40}',pin['head_sha']),'NATIVE_ARTIFACT_PIN')
        seen.add(pin['id'])
    return value


def load_manifest(path,*,now):
    return _manifest(read_json_bytes(_read(Path(path),32768)),now)


def _actual_metadata(value,pin,now):
    run=value.get('workflow_run') if type(value) is dict else None
    need(type(value) is dict and type(value.get('id')) is int and value['id']==pin['id'] and
         value.get('digest')==pin['digest'] and value.get('expired') is False and
         type(value.get('size_in_bytes')) is int and 0<value['size_in_bytes']<=MAX_ARCHIVE_BYTES and
         type(value.get('name')) is str and re.fullmatch(
             'all-existing-model-pairs-'+str(pin['run_id'])+'-[1-9][0-9]{0,5}',value['name']) and
         type(run) is dict and type(run.get('id')) is int and run['id']==pin['run_id'] and
         run.get('head_sha')==pin['head_sha'] and all(type(run.get(k)) is int and
             run[k]==results.REPOSITORY_ID for k in ('repository_id','head_repository_id')),
         'ACTUAL_NATIVE_METADATA')
    need(future.stamp(value.get('created_at'))<=now<future.stamp(value.get('expires_at')),
         'NATIVE_ARTIFACT_CLOCK')
    return value


def frozen_inputs(manifest,*,now):
    values=[];total=0
    for pin in manifest['native_artifacts']:
        actual=_actual_metadata(future.metadata(pin['id']),pin,now)
        raw=future.gh('actions/artifacts/'+str(pin['id'])+'/zip')
        need(type(raw) is bytes and len(raw)==actual['size_in_bytes'] and
             'sha256:'+sha256(raw).hexdigest()==pin['digest'],'NATIVE_ARTIFACT_BYTES')
        total+=len(raw);need(total<=256*1024*1024,'TOTAL_NATIVE_ARCHIVE_BOUND')
        admitted,records=_verified_private_pairs_artifact(raw,actual,now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'])
        need(admitted.get('independent_pre_cutoff_receipt_verified') is True and
             type(records) is list and bool(records),'AUTHENTICATED_NATIVE_INPUTS_REQUIRED')
        for record in records:
            capsules=record.get('captured_native_inputs') if type(record) is dict else None
            need(type(capsules) is list and bool(capsules),'CAPTURED_NATIVE_INPUTS_REQUIRED')
            for capsule in capsules:
                need(type(capsule) is dict and type(capsule.get('native_payload')) is dict,
                     'CAPTURED_NATIVE_PAYLOAD_REQUIRED')
                values.append(capsule['native_payload'])
                need(len(values)<=10000,'TOTAL_NATIVE_INPUT_BOUND')
    # Detect conflicting frozen snapshots before opening result sources.
    results._frozen(values)
    return values


def load_packet(manifest,*,key):
    raw=_repository_file(ROOT/manifest['packet_path'],MAX_WIRE)
    need(sha256(raw).hexdigest()==manifest['packet_sha256'],'PACKET_CIPHER_SHA')
    value=open_forecasts(raw,key=key)
    need(type(value) is dict and set(value)=={'schema','execution_day','captures','observations'} and
         value.get('schema')==PACKET and value.get('execution_day')==manifest['execution_day'],
         'PACKET_SCHEMA')
    need(len(future.wire(value))<=MAX_PLAIN and type(value['captures']) is list and
         1<=len(value['captures'])<=32 and type(value['observations']) is list and
         1<=len(value['observations'])<=10000,'PACKET_BOUND')
    return value


def _counts(payload,natives,*,now,allow_order_only):
    latest,details=results._validated(payload,now=now,frozen_native_payloads=natives,
        allow_order_only=allow_order_only)
    counts=Counter(row['status'] for row in latest)
    summary=dict(original_observation_count=len(payload['observations']),latest_observation_count=len(latest),
        capture_count=details['capture_count'],unique_revision_count=details['unique_revision_count'],
        duplicate_revision_count=details['duplicate_revision_count'],ordinary_settled_result_count=counts['settled'],
        pending_result_count=counts['pending'],special_result_count=counts['special'],
        order_only_confirmed_result_count=counts['rank_confirmed'],
        frozen_native_inputs_sha256=details['frozen_inputs_sha256'])
    if counts['rank_confirmed']:
        from race_ai.official_order_only_result import EVALUATION_SCOPE
        summary.update(label_evaluation_scope=EVALUATION_SCOPE,monetary_evaluation_available=False)
    return summary


def _lineage(manifest):
    return dict(source_packet_sha256=manifest['packet_sha256'],manifest_sha256=digest(manifest),
        native_artifact_pins_sha256=digest(manifest['native_artifacts']),
        native_input_artifact_count=len(manifest['native_artifacts']),allow_order_only=manifest['allow_order_only'])


def _private_local(root):
    from race_ai.all_existing_model_runtime import _private_directory,_private_file
    _private_directory(root)
    need({p.name for p in root.iterdir()}=={'results.enc'},'EXACT_LOCAL_CIPHER')
    _private_file(root/'results.enc')
    return _read(root/'results.enc',MAX_WIRE)


def _local_payload(cipher,env,*,key):
    payload=open_forecasts(cipher,key=key);header=forecast_header(cipher)
    need(header['run_id']==str(env['run_id']) and header['round_no']==ROUND and
         payload.get('run_id')==env['run_id'] and payload.get('code_sha')==env['head_sha'],
         'LOCAL_AUTHENTICATED_IDENTITY')
    return payload


def generate(root,env,manifest):
    key=state_key('production');now=utc_now();_manifest(manifest,now)
    need(not root.exists() and not any(p.is_symlink() for p in (root,*root.parents)),
         'OUTPUT_EXISTS_DO_NOT_RESET')
    natives=frozen_inputs(manifest,now=now);packet=load_packet(manifest,key=key)
    generated=utc_now();need(generated.astimezone(JST).date().isoformat()==manifest['execution_day'],
        'EXECUTION_DAY_ELAPSED')
    payload=results.build_result_payload(packet['captures'],packet['observations'],run_id=env['run_id'],
        code_sha=env['head_sha'],generated_at=generated,day_jst=manifest['execution_day'],
        frozen_native_payloads=natives,allow_order_only=manifest['allow_order_only'])
    cipher=results.seal_results(payload,round_no=ROUND,frozen_native_payloads=natives,key=key,
        allow_order_only=manifest['allow_order_only'])
    need(_local_payload(cipher,env,key=key)==payload,'LOCAL_ENCRYPTED_REPLAY')
    summary=_counts(payload,natives,now=utc_now(),allow_order_only=manifest['allow_order_only'])
    root.mkdir(mode=0o700,exist_ok=False);_write(root/'results.enc',cipher)
    need(_private_local(root)==cipher,'LOCAL_CIPHER_READBACK')
    return dict(summary,**_lineage(manifest),state='OFFICIAL_RESULTS_ENCRYPTED_LOCAL_ONLY',ready=True,
        result_cipher_sha256=sha256(cipher).hexdigest(),result_payload_sha256=digest(payload),
        encrypted_readback_verified=True,independent_result_artifact_receipt_verified=False)


def readback(ident,root,env,manifest):
    key=state_key('production');now=utc_now();_manifest(manifest,now)
    need(type(ident) is int and ident>0,'RESULT_ARTIFACT_ID')
    natives=frozen_inputs(manifest,now=now);cipher=_private_local(root)
    payload=_local_payload(cipher,env,key=key)
    from race_ai.all_existing_model_runtime import _private_file
    # Readback failures may update the current status. Preserve the successful
    # generation proof so a transient GitHub failure never prevents a retry.
    generation_path=root.with_name(root.name+'.generation.json')
    status_path=generation_path if generation_path.exists() else root.with_name(root.name+'.status.json')
    _private_file(status_path)
    previous=read_json_bytes(_read(status_path,128*1024))
    need(type(previous) is dict and previous.get('schema')==STATUS and previous.get('ready') is True and
         previous.get('workflow_run_id')==env['run_id'] and previous.get('expected_head_sha')==env['head_sha'] and
         all(previous.get(k)==v for k,v in _lineage(manifest).items()) and
         previous.get('result_cipher_sha256')==sha256(cipher).hexdigest() and
         previous.get('result_payload_sha256')==digest(payload),'LOCAL_GENERATION_STATUS')
    summary=_counts(payload,natives,now=now,allow_order_only=manifest['allow_order_only'])
    need(all(previous.get(k)==v for k,v in summary.items()),'LOCAL_GENERATION_COUNTS')
    actual=future.metadata(ident)
    expected_name=f'all-existing-official-results-{env["run_id"]}-{ROUND}'
    need(type(actual) is dict and type(actual.get('id')) is int and actual['id']==ident and
         actual.get('name')==expected_name,'ACTUAL_RESULT_ARTIFACT_NAME')
    raw=future.gh('actions/artifacts/'+str(ident)+'/zip')
    admitted=results.observations_from_official_result_artifact(raw,actual,now=now,
        expected_run_id=env['run_id'],expected_head_sha=env['head_sha'],frozen_native_payloads=natives,
        key=key,allow_order_only=manifest['allow_order_only'])
    need(results._cipher(raw)==cipher and admitted['receipt']['original_payload_sha256']==digest(payload) and
         admitted['receipt']['frozen_inputs_sha256']==summary['frozen_native_inputs_sha256'],
         'ACTUAL_ORIGINAL_CIPHER_READBACK')
    return dict(summary,**_lineage(manifest),state='OFFICIAL_RESULTS_ACTUAL_ARTIFACT_VERIFIED',ready=True,
        artifact_id=ident,artifact_digest=actual['digest'],saved_at=actual['created_at'],
        result_cipher_sha256=sha256(cipher).hexdigest(),result_payload_sha256=digest(payload),
        encrypted_readback_verified=True,independent_result_artifact_receipt_verified=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True);parser.add_argument('--out-dir',required=True)
    parser.add_argument('--readback-artifact',type=int);args=parser.parse_args(argv)
    result=dict(schema=STATUS,state='HOLD_OFFICIAL_RESULT_FREEZE',ready=False,source_requests=0,
        independent_result_artifact_receipt_verified=False,plaintext_published=False,public_redistribution=False,
        provider_model_training_permission_confirmed=False,production_promoted=False,actual_purchases=False,
        missing_results_are_not_losses=True);status=None
    try:
        env=future.environment();root=future.output_path(args.out_dir,env)
        status=root.with_name(root.name+'.status.json')
        result.update(workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],
            artifact_name=f'all-existing-official-results-{env["run_id"]}-{ROUND}')
        manifest=load_manifest(args.input,now=utc_now())
        if args.readback_artifact is not None:result.update(readback(args.readback_artifact,root,env,manifest))
        else:result.update(generate(root,env,manifest))
    except Exception as exc:
        result.update(state='HOLD_OFFICIAL_RESULT_FREEZE',ready=False,**future.safe_diagnostic(exc))
    if status is not None:
        try:
            if args.readback_artifact is None and result['ready']:
                _write(root.with_name(root.name+'.generation.json'),future.wire(result))
            save(status,future.wire(result),replace=status.exists())
        except Exception as exc:
            result.update(state='HOLD_OFFICIAL_RESULT_FREEZE',ready=False,**future.safe_diagnostic(exc))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(result['ready']).lower()+'\n')
            if result.get('artifact_name'):output.write('artifact_name='+result['artifact_name']+'\n')
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
