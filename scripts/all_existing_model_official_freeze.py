"""One-time authenticated official-cache native freeze; no provider requests."""
import argparse
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from urllib.parse import urlsplit

from race_ai.actions_contract import digest
from race_ai import manual_official_capture as capture
from race_ai import jra_official_sparse_adapter as jra
from race_ai.all_existing_model_learning import _sources
from race_ai.all_existing_model_pairs import (make_private_pairs,verify_private_record,record_partition_key,
    record_identity,INPUTS_SCHEMA,_seal_cutoff,_race_key)
from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
from race_ai.boat_all_model_store import open_forecasts
from race_ai.boat_pdca_state import state_key
from race_ai.boat_venue_learning import read_candidate
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.four_sport_learning import LEARNED_ID
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_p0 as future
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

ROOT=Path(__file__).resolve().parents[1]
ROUND=900002
SCHEMA='RACE_AI_MANUAL_OFFICIAL_NATIVE_FREEZE_INPUT_V1'
V2_SCHEMA='RACE_AI_MANUAL_OFFICIAL_NATIVE_FREEZE_INPUT_V2'
STATUS='RACE_AI_MANUAL_OFFICIAL_NATIVE_FREEZE_COUNTS_V1'
CELLS={'horse/'+mid for mid in (*ALL_MODELS,LEARNED_ID)}


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_OFFICIAL_FREEZE_'+reason)


def utc_now():return datetime.now(timezone.utc)


def load_manifest(path,*,now):
    value=read_json_bytes(_read(Path(path),16384))
    fields={'schema','execution_day','sealed_path','index_sha256','maximum_races',
            'source_metadata_path','source_metadata_sha256'}
    need(type(value) is dict and ((value.get('schema')==SCHEMA and set(value)==fields) or
         (value.get('schema')==V2_SCHEMA and set(value)==fields|{'excluded_native_artifacts'})),
         'MANIFEST_SCHEMA')
    if value['schema']==V2_SCHEMA:_exclusion_pins(value)
    need(type(value['maximum_races']) is int and 1<=value['maximum_races']<=8 and
        value['execution_day']==now.astimezone(jra.JST).date().isoformat(),'EXECUTION_DAY_OR_BOUND')
    need(type(value['sealed_path']) is str and re.fullmatch(
        r'audit/state/manual-official-capture/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,150}',value['sealed_path']),
        'SEALED_PATH')
    need(type(value['source_metadata_path']) is str and re.fullmatch(
        r'audit/state/manual-official-source-metadata-[a-f0-9]{64}\.enc',value['source_metadata_path']),
        'METADATA_PATH')
    need(all(type(value[k]) is str and re.fullmatch('[a-f0-9]{64}',value[k])
        for k in ('index_sha256','source_metadata_sha256')),'MANIFEST_SHA')
    return value


def _exclusion_pins(manifest):
    values=manifest.get('excluded_native_artifacts')
    need(type(values) is list and 1<=len(values)<=8,'EXCLUDED_NATIVE_ARTIFACTS_BOUND')
    seen=set()
    for value in values:
        need(type(value) is dict and set(value)=={'id','digest','run_id','head_sha'} and
             all(type(value[k]) is int and 0<value[k]<10**20 for k in ('id','run_id')) and
             type(value['digest']) is str and re.fullmatch('sha256:[a-f0-9]{64}',value['digest']) and
             type(value['head_sha']) is str and re.fullmatch('[a-f0-9]{40}',value['head_sha']) and
             value['id'] not in seen,'EXCLUDED_NATIVE_ARTIFACT_PIN')
        seen.add(value['id'])
    return values


def authenticated_excluded_races(manifest,*,now):
    """Read existing actual HORSE input receipts; never infer exclusions from IDs."""
    if manifest.get('schema')==SCHEMA:return set(),0
    need(manifest.get('schema')==V2_SCHEMA,'MANIFEST_SCHEMA')
    pins=_exclusion_pins(manifest);races=set()
    for pin in pins:
        actual=future.metadata(pin['id'])
        need(type(actual) is dict and actual.get('id')==pin['id'] and actual.get('digest')==pin['digest'],
             'EXCLUDED_NATIVE_ARTIFACT_BINDING')
        raw=future.gh('actions/artifacts/'+str(pin['id'])+'/zip')
        admitted,records=_verified_private_pairs_artifact(raw,actual,now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'])
        need(1<=len(records)<=8 and admitted['forecast_partition_count']==0 and
             admitted['partition_count']==admitted['frozen_input_only_partition_count']==len(records) and
             admitted['captured_native_input_count']==5*len(records),'EXCLUDED_HORSE_INPUT_COUNTS')
        for record in records:
            need(record.get('schema')==INPUTS_SCHEMA and record.get('training',{}).get('scope')==
                 'OPERATOR_SUPPLIED_RESEARCH' and record_identity(record)[0]=='horse',
                 'EXCLUDED_HORSE_INPUT_REQUIRED')
            capsules=record['captured_native_inputs']
            need(len(capsules)==5 and {value['cell_key'] for value in capsules}==CELLS and all(
                 value['native_payload']['snapshot']['race']['sport']=='horse' and
                 value['native_payload']['snapshot']['race']['event_date_jst']==manifest['execution_day']
                 for value in capsules),'EXCLUDED_HORSE_NATIVE_CELLS')
            races.add(record_identity(record)[1])
    return races,len(pins)


def _repository_file(path,limit):
    need(not any(p.is_symlink() for p in (path,*path.parents)) and path.is_file(),'CIPHER_REGULAR_FILE')
    info=path.stat();need(stat.S_ISREG(info.st_mode) and 0<info.st_size<=limit,'CIPHER_BOUND')
    return _read(path,limit)


def copy_sealed(manifest,target):
    source=ROOT/manifest['sealed_path']
    need(source.is_dir() and not any(p.is_symlink() for p in (source,*source.parents)),'SEALED_DIRECTORY')
    paths=list(source.iterdir())
    need(1<=len(paths)<=33 and any(p.name=='index.enc' for p in paths) and all(
        re.fullmatch(r'(?:index|source-[0-9]{4})\.enc',p.name) for p in paths),'SEALED_FLAT_CIPHERS_REQUIRED')
    bodies={path.name:_repository_file(path,4*1024*1024) for path in paths}
    need(sum(map(len,bodies.values()))<=132*1024*1024 and
         sha256(bodies['index.enc']).hexdigest()==manifest['index_sha256'],'INDEX_CIPHER_BINDING')
    target.mkdir(mode=0o700,exist_ok=False)
    for name,body in bodies.items():_write(target/name,body)


def bind_metadata(raw,manual,actual):
    """Keep the actual GET start/completion/status fields from encrypted proof."""
    need(type(manual) is dict and type(actual) is dict and type(raw) is bytes,'ORIGINAL_METADATA_REQUIRED')
    need(actual.get('status')==200 and actual.get('source_url')==manual.get('url') and
         actual.get('final_url')==manual.get('final_url') and
         actual.get('source_sha256')==manual.get('source_sha256')==sha256(raw).hexdigest() and
         type(actual.get('byte_count')) is int and actual['byte_count']==manual.get('size')==len(raw) and
         actual.get('response_received_at')==manual.get('captured_at') and
         type(actual.get('fetched_at')) is str and type(actual.get('headers')) is dict,
         'ORIGINAL_METADATA_BINDING')
    need(future.stamp(actual['fetched_at'])<=future.stamp(actual['response_received_at']),
         'ORIGINAL_CAPTURE_CLOCK')
    return deepcopy(actual)


def original_metadata(manifest,*,key):
    raw=_repository_file(ROOT/manifest['source_metadata_path'],4*1024*1024)
    need(sha256(raw).hexdigest()==manifest['source_metadata_sha256'],'ORIGINAL_METADATA_CIPHER_SHA')
    value=open_forecasts(raw,key=key)
    need(type(value) is dict and set(value)=={'schema','execution_day','metadata_by_url'} and
         value['schema']=='RACE_AI_MANUAL_OFFICIAL_ORIGINAL_METADATA_V1' and
         value['execution_day']==manifest['execution_day'] and type(value['metadata_by_url']) is dict and
         1<=len(value['metadata_by_url'])<=32,'ORIGINAL_METADATA_SCHEMA')
    return value['metadata_by_url']


def local_records(root):
    from race_ai.all_existing_model_runtime import _private_directory,_private_file
    _private_directory(root);children=list(root.iterdir())
    need(1<=len(children)<=8 and all(re.fullmatch('[a-f0-9]{64}',p.name) for p in children),
         'OPAQUE_PARTITIONS_REQUIRED')
    records=[]
    for folder in sorted(children):
        _private_directory(folder)
        need({p.name for p in folder.iterdir()}=={'learning.enc','learning.json','summary.json'},'PARTITION_LAYOUT')
        for path in folder.iterdir():_private_file(path)
        payload=read_candidate(folder)
        need(payload.get('schema')==INPUTS_SCHEMA and verify_private_record(payload) is True and
             record_partition_key(payload)==folder.name,'INPUT_ONLY_READBACK')
        capsules=payload['captured_native_inputs']
        need(len(capsules)==5 and {c['cell_key'] for c in capsules}==CELLS and
             all(c['native_payload']['snapshot']['race']['sport']=='horse' for c in capsules),
             'FIVE_NATIVE_HORSE_CELLS_REQUIRED')
        public=read_json_bytes(_read(folder/'summary.json',1024*1024))
        need(public==dict(payload['summary'],encrypted_readback_verified=True,plaintext_published=False),
             'PUBLIC_SUMMARY_BINDING')
        records.append(payload)
    return records


def generate(ident,root,env,manifest):
    need(not root.exists(),'OUTPUT_EXISTS_DO_NOT_RESET')
    key=state_key('production');context=future.candidate(ident,env)
    need(context['training']['scope']=='OPERATOR_SUPPLIED_RESEARCH','REAL_RESEARCH_CANDIDATE_REQUIRED')
    ready=future.stamp(context['receipt']['created_at'])+timedelta(seconds=1)
    remaining=(ready-utc_now()).total_seconds()
    if 0<remaining<=2:time.sleep(remaining+.02)
    need(utc_now()>=ready,'CANDIDATE_RECEIPT_PRECISION')
    excluded=set();exclusion_counts={}
    if manifest['schema']==V2_SCHEMA:
        excluded,excluded_artifacts=authenticated_excluded_races(manifest,now=utc_now())
        exclusion_counts=dict(excluded_native_artifact_count=excluded_artifacts,
            excluded_native_race_count=len(excluded),excluded_cached_card_count=0)
    holds=0;rejected=0;selected=[]
    with tempfile.TemporaryDirectory(prefix='manual-native-freeze-',dir=env['temp']) as temporary:
        private=Path(temporary);copy_sealed(manifest,private/'sealed')
        restored=private/'restored'
        capture.restore_cache(private/'sealed',restored,key=key,expected_index_sha256=manifest['index_sha256'])
        cache=capture._load(restored);need(cache['execution_day']==manifest['execution_day'],'CACHE_EXECUTION_DAY')
        originals=original_metadata(manifest,key=key)
        proof=capture.read_capture(restored,jra.RULE_URL)
        rule=bind_metadata(proof['raw'],proof['metadata'],originals.get(jra.RULE_URL))
        evidence=dict(raw=proof['raw'],metadata=rule,sales_channel=jra.CHANNEL,
            rule_id='JRA_2026_SATURDAY_ALL_RACES_START_MINUS_60_SECONDS')
        rights=capture.official_rights_ref('horse')
        for url in sorted(cache['captures']):
            parsed=urlsplit(url)
            if parsed.hostname not in capture.HOSTS['horse'] or parsed.path!='/JRADB/accessD.html':continue
            try:
                body=capture.read_capture(restored,url)
                actual=bind_metadata(body['raw'],body['metadata'],originals.get(url))
                converted=jra.build_sparse_payload(body['raw'],actual,now=utc_now(),source_rights_ref=rights,
                    cutoff_evidence=evidence)
                if converted['state']!='READY':holds+=1;continue
                native=converted['native_payload'];race=native['snapshot']['race']
                need(race['event_date_jst']==manifest['execution_day'],'CARD_EXECUTION_DAY')
                if excluded and _race_key(race['race_id'],'horse') in excluded:
                    exclusion_counts['excluded_cached_card_count']+=1;continue
                cutoff=future.stamp(race['sales_cutoff_at'])
                if cutoff<utc_now()+timedelta(seconds=120):holds+=1;continue
                selected.append((cutoff,race['race_id'],native))
            except (ValueError,KeyError,TypeError):rejected+=1
        selected=sorted(selected,key=lambda row:(row[0],row[1]))[:manifest['maximum_races']]
        need(len({race for _,race,_ in selected})==len(selected),'DUPLICATE_RACE_SOURCE')
        if not selected:return dict(exclusion_counts,state='HOLD_NO_READY_FUTURE_NATIVE_INPUTS',ready=False,
            ready_races=0,held_cards=holds,rejected_cards=rejected)
        requests=[dict(cell_key=cell,native_payload=deepcopy(native))
            for _,_,native in selected for cell in sorted(CELLS)]
        refs=set().union(*(_sources(row['native_payload']) for row in requests))
        summary=make_private_pairs(context,requests,root,now=utc_now(),allow_source=lambda source,right,purpose:
            purpose=='analysis' and (source,right) in refs)
        need(summary['partition_count']==summary['frozen_input_only_partition_count']==len(selected) and
             summary['forecast_partition_count']==0 and summary['captured_native_input_count']==5*len(selected),
             'EXACT_FROZEN_INPUT_COUNTS')
        aggregate=read_json_bytes(_read(root/'summary.json',1024*1024))
        need(aggregate==summary,'ROOT_SUMMARY_BINDING');(root/'summary.json').unlink()
        records=local_records(root)
        need(min(_seal_cutoff(p) for p in records)>=utc_now()+timedelta(seconds=120),'FINAL_MARGIN_ELAPSED')
        return dict(exclusion_counts,state='OFFICIAL_NATIVE_INPUTS_ENCRYPTED_LOCAL_ONLY',ready=True,
            ready_races=len(records),held_cards=holds,rejected_cards=rejected,partition_count=len(records),
            frozen_input_only_partition_count=len(records),forecast_partition_count=0,
            captured_native_input_count=5*len(records),candidate_artifact_id=ident,
            training_sha256=context['training']['training_sha256'],source_index_sha256=manifest['index_sha256'],
            original_metadata_cipher_sha256=manifest['source_metadata_sha256'],
            record_sha256=sorted(digest(p) for p in records),encrypted_readback_verified=True,
            independent_pre_cutoff_receipt_verified=False)


def readback(ident,root,env):
    local=local_records(root)
    previous=read_json_bytes(_read(root.with_name(root.name+'.status.json'),128*1024))
    hashes=sorted(digest(p) for p in local)
    need(previous.get('schema')==STATUS and previous.get('workflow_run_id')==env['run_id'] and
         previous.get('expected_head_sha')==env['head_sha'] and previous.get('record_sha256')==hashes and
         previous.get('candidate_artifact_id')==local[0]['training_receipt']['id'] and
         previous.get('training_sha256')==local[0]['training']['training_sha256'],'LOCAL_GENERATION_STATUS')
    actual=future.metadata(ident);raw=future.gh('actions/artifacts/'+str(ident)+'/zip')
    need(actual.get('name')==f'all-existing-model-pairs-{env["run_id"]}-{ROUND}','ACTUAL_ARTIFACT_NAME')
    admitted,records=_verified_private_pairs_artifact(raw,actual,now=utc_now(),
        expected_run_id=env['run_id'],expected_head_sha=env['head_sha'])
    need(admitted['partition_count']==admitted['frozen_input_only_partition_count']==len(local) and
         admitted['forecast_partition_count']==0 and admitted['captured_native_input_count']==5*len(local) and
         sorted(digest(p) for p in records)==hashes,'ACTUAL_NATIVE_INPUT_READBACK')
    lineage={key:previous[key] for key in ('source_index_sha256','original_metadata_cipher_sha256',
        'held_cards','rejected_cards') if key in previous}
    for key,limit in (('excluded_native_artifact_count',8),('excluded_native_race_count',64),
                      ('excluded_cached_card_count',32)):
        if key in previous:
            need(type(previous[key]) is int and 0<=previous[key]<=limit,'LOCAL_EXCLUSION_COUNTS')
            lineage[key]=previous[key]
    return dict(lineage,state='OFFICIAL_NATIVE_INPUTS_ACTUAL_PRE_CUTOFF_VERIFIED',ready=True,
        partition_count=len(local),frozen_input_only_partition_count=len(local),forecast_partition_count=0,
        captured_native_input_count=5*len(local),ready_races=len(local),record_sha256=hashes,
        candidate_artifact_id=previous['candidate_artifact_id'],training_sha256=previous['training_sha256'],
        artifact_id=ident,artifact_digest=actual['digest'],saved_at=actual['created_at'],
        encrypted_readback_verified=True,independent_pre_cutoff_receipt_verified=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--candidate-artifact',type=int);mode.add_argument('--readback-artifact',type=int)
    parser.add_argument('--input');parser.add_argument('--out-dir',required=True);args=parser.parse_args(argv)
    result=dict(schema=STATUS,state='HOLD_OFFICIAL_NATIVE_FREEZE',ready=False,source_requests=0,
        independent_pre_cutoff_receipt_verified=False,plaintext_published=False,production_promoted=False,
        actual_purchases=False,forecast_partition_count=0);status=None
    try:
        env=future.environment();root=future.output_path(args.out_dir,env)
        status=root.with_name(root.name+'.status.json')
        result.update(workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],
            artifact_name=f'all-existing-model-pairs-{env["run_id"]}-{ROUND}')
        if args.candidate_artifact:
            need(args.input is not None,'INPUT_MANIFEST_REQUIRED')
            manifest=load_manifest(args.input,now=utc_now())
            result.update(generate(args.candidate_artifact,root,env,manifest))
        else:result.update(readback(args.readback_artifact,root,env))
    except Exception as exc:
        reason=str(exc)
        result.update(state='HOLD_OFFICIAL_NATIVE_FREEZE',ready=False,reason=reason if re.fullmatch(
            'ALL_MODEL_OFFICIAL_FREEZE_[A-Z_]{1,100}',reason) else 'OFFICIAL_NATIVE_OPERATION_REJECTED')
    if status is not None:save(status,future.wire(result),replace=status.exists())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(result['ready']).lower()+'\n')
            if result.get('artifact_name'):output.write('artifact_name='+result['artifact_name']+'\n')
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
