"""Actions-only fresh literal JRA card -> sealed originals and V3 native inputs.

Upload only source/ and native/ under the returned names. Private cache/staging
paths are never upload paths. No workflow or source URL is generated here.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
from urllib.request import build_opener
import zipfile

from race_ai.actions_contract import digest
from race_ai import future_source_cooldown as cooldown
from race_ai import jra_future_source_capture as core
from race_ai import manual_official_capture as capture
from race_ai.jra_capture_metadata import build_jra_http_metadata
from race_ai.boat_all_model_store import seal_forecasts,open_forecasts,MAX_WIRE
from race_ai.boat_pdca_state import state_key
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_source_capture as common
from scripts import all_existing_model_official_freeze as freeze
from scripts import all_existing_model_future_p0 as future
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

need=core.need
history=common.history
environment=common.environment
MAX_ARCHIVE=96*1024*1024


def utc_now():return datetime.now(timezone.utc)


def wait_for_prior_window(manifest,env,*,reader=None,marker_transport=None,clock=None,sleeper=None,monotonic=None):
    need(type(manifest) is dict and manifest.get('schema')==core.SCHEMA,'WAIT_SCHEMA')
    return cooldown.wait_for_prior_window(manifest,env,reader=reader,marker_transport=marker_transport,
        clock=clock or utc_now,sleeper=sleeper,monotonic=monotonic)


def guarded_opener(plan,opener,*,clock=utc_now,before=None):
    def get(request,timeout):
        now=clock();need(core.clock(plan['available_after'])<=now<core.clock(plan['not_after']),'WIRE_AUTHORIZATION_CLOCK')
        need(request.get_method()=='GET' and request.full_url in plan['urls'],'LITERAL_GET_ONLY')
        if before is not None:before(request.full_url)
        # Recheck after local validation, immediately before the actual GET.
        now=clock();need(core.clock(plan['available_after'])<=now<core.clock(plan['not_after']),'WIRE_AUTHORIZATION_CLOCK')
        return opener(request,timeout=timeout)
    return get


def _sidecar(directory,*,locked=False):
    cache=capture._load(directory,locked=locked)
    bodies={url:capture._read(directory/source['raw_file'],capture.MAX_BYTES) for url,source in cache['captures'].items()}
    return cache,build_jra_http_metadata(cache,bodies)


def collect(manifest,plan,directory,*,opener=None,sleeper=time.sleep,monotonic=time.monotonic):
    need(not directory.exists(),'FRESH_CACHE_REQUIRED')
    fetch=opener or build_opener(capture._NoRedirect()).open
    def before(url):
        if url!=manifest['card_url']:return
        cache,sidecar=_sidecar(directory,locked=True);need(sidecar['state']=='READY_ORIGINAL_METADATA','FRESH_DISCOVERY_REQUIRED')
        actual=sidecar['document']['metadata_by_url'][manifest['discovery_url']]
        content_type=next(v for k,v in actual['headers'].items() if k.lower()=='content-type')
        encoding=re.search(r'charset\s*=\s*[\'\"]?([\w-]+)',content_type,re.I)[1]
        encoding={'shift_jis':'cp932','shift-jis':'cp932','utf8':'utf-8'}.get(encoding.lower(),encoding.lower())
        source=cache['captures'][manifest['discovery_url']]
        core.verify_discovery(manifest,capture._read(directory/source['raw_file'],capture.MAX_BYTES),encoding)
    return capture.collect_once(plan['urls'],execution_day=manifest['execution_day'],terms_manifest=manifest['terms_manifest'],
        cache_dir=directory,clock=utc_now,opener=guarded_opener(plan,fetch,clock=utc_now,before=before),
        sleeper=sleeper,monotonic=monotonic,request_limit=32)


def _known(cache):
    return bool(cache['attempts']) and all(a['state']!='RESERVED' and type(a['http_status']) is int for a in cache['attempts'])


def _staging(source,fm,directory):
    freeze.validate_manifest(fm,now=utc_now())
    need(fm['schema']==freeze.V3_SCHEMA and fm['maximum_races']==1 and
        fm['sealed_path']=='audit/state/manual-official-capture/'+fm['index_sha256'] and
        fm['source_metadata_path']=='audit/state/manual-official-source-metadata-'+fm['source_metadata_sha256']+'.enc',
        'CANONICAL_SEALED_SOURCE_PATHS')
    need(type(source) is dict and type(source.get('index.enc')) is bytes and type(source.get('metadata.enc')) is bytes and
        sha256(source['index.enc']).hexdigest()==fm['index_sha256'] and
        sha256(source['metadata.enc']).hexdigest()==fm['source_metadata_sha256'],'STAGING_ORIGINAL_CIPHER_HASHES')
    need(not directory.exists(),'STAGING_EXISTS');directory.mkdir(mode=0o700)
    target=directory/fm['sealed_path'];target.mkdir(parents=True,mode=0o700)
    for name,raw in source.items():
        if re.fullmatch(r'(?:index|source-[0-9]{4})\.enc',name):_write(target/name,raw)
    path=directory/fm['source_metadata_path'];path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    _write(path,source['metadata.enc'])
    return directory


def _margin(manifest,now):need(now+timedelta(seconds=600)<core.clock(manifest['cutoff_at']),'INDEPENDENT_RECEIPT_MARGIN')


def _exact_native_case(records,manifest):
    need(len(records)==1 and records[0]['race_id']==manifest['race_id'],'EXACT_NATIVE_CASE_CUTOFF')
    native=records[0]['captured_native_inputs']
    asofs={c['native_payload']['snapshot']['race']['as_of'] for c in native}
    need(len(native)==5 and len(asofs)==1 and all(
        c['native_payload']['snapshot']['race']['race_id']==manifest['race_id'] and
        core.clock(c['native_payload']['snapshot']['race']['sales_cutoff_at'])==core.clock(manifest['cutoff_at'])
        for c in native),'EXACT_NATIVE_CASE_CUTOFF')
    return asofs.pop()


def generate(manifest,root,env,*,marker_transport=None,opener=None,sleeper=time.sleep,monotonic=time.monotonic):
    cache_dir=root.with_name(root.name+'.jra-cache');stage=root.with_name(root.name+'.jra-staging')
    need(not root.exists() and not cache_dir.exists() and not stage.exists(),'OUTPUT_EXISTS_DO_NOT_RESET')
    now=utc_now();core.validate_manifest(manifest,now=now);key=state_key('production')
    transport=marker_transport or core.MarkerTransport()
    need(transport.read_file(transport.head(),core.PATH,MAX_WIRE) is None,'ONCE_ALREADY_CONSUMED')
    baseline=freeze._load_horse_baseline(manifest['horse_baseline_artifact'])
    carrier=freeze._load_carrier(manifest['carrier_artifact'])
    need(carrier['training']['scope']=='OPERATOR_SUPPLIED_RESEARCH' and len(carrier['training']['models'])==14 and
        all(c.startswith('boat/') for c in carrier['training']['models']),'EXACT_BOAT_FOURTEEN_CARRIER')
    core.prepare(manifest,baseline,now=utc_now())
    excluded,_=freeze.authenticated_excluded_races(dict(manifest,schema=freeze.V3_SCHEMA),now=utc_now())
    need(manifest['race_id'] not in excluded,'EXCLUDED_NATIVE_RACE')
    admitted=history(manifest,env,key=key,now=utc_now());audit={k:v for k,v in admitted.items() if k not in ('bodies','receipts','runs')}
    now=utc_now();plan=core.prepare(manifest,baseline,now=now)
    body=core.marker_body(manifest,env,baseline,audit,plan,now=now)
    root.mkdir(mode=0o700);source=root/'source';source.mkdir(mode=0o700)
    reservation=dict(schema=core.JOURNAL,state='RESERVED',manifest=deepcopy(manifest),manifest_sha256=digest(manifest),
        workflow_run_id=env['run_id'],code_sha=env['head_sha'],epoch_started_at=now.isoformat(),plan_sha256=digest(plan),
        once_body=body,history=audit,maximum_requests=32,source_requests_actual=None)
    common._seal(source/'reservation.enc',reservation,env,key);common._seal(source/'plan.enc',plan,env,key)
    failure=False;once_proof=None;cache=None
    try:
        consumed=core.reserve(body,key,transport,now=utc_now());raw=consumed.pop('_ciphertext');once_proof=consumed
        _write(source/'once.enc',raw);core.validate_marker(raw,body,key,now=utc_now())
        core.prepare(manifest,baseline,now=utc_now())
        collect(manifest,plan,cache_dir,opener=opener,sleeper=sleeper,monotonic=monotonic)
    except Exception:failure=True
    items,complete=common.inventory(cache_dir,source,env,key=key)
    try:cache=capture._load(cache_dir)
    except Exception:pass
    journal=dict(reservation,state='CAPTURE_RETAINED',completed_at=utc_now().isoformat(),capture_inventory=items,
        raw_retention_complete=complete,source_requests_actual=len(cache['attempts']) if not failure and cache and _known(cache) else None,
        source_request_upper_bound=32,native_ready=False,fixed_as_of=None,capture_cache=cache)
    if once_proof is not None:journal['once_proof']=once_proof
    result=dict(audit,ready=False,state='HOLD_JRA_FUTURE_SOURCE_CAPTURE',source_requests=journal['source_requests_actual'],
        source_request_upper_bound=32,raw_retention_complete=complete)
    try:
        need(not failure and complete and cache is not None and _known(cache) and not cache['failures'] and
            not cache['blocked_hosts'] and set(cache['captures'])==set(plan['urls']),'CAPTURE_UNKNOWN_DENIED_OR_INCOMPLETE')
        need(all(core.clock(plan['available_after'])<=core.clock(a['started_at'])<core.clock(plan['not_after']) and
            a['state']=='SUCCESS' for a in cache['attempts']),'ORIGINAL_WIRE_BOUNDARY')
        bodies={url:capture.read_capture(cache_dir,url)['raw'] for url in cache['captures']}
        sidecar=core.originals(manifest,plan,cache,bodies)
        sealed=root.with_name(root.name+'.jra-sealed')
        seal=capture.seal_cache(cache_dir,sealed,key=key,run_id=str(env['run_id']),round_no=freeze.ROUND)
        for path in sealed.iterdir():_write(source/path.name,path.read_bytes())
        metadata=seal_forecasts(sidecar['document'],run_id=str(env['run_id']),round_no=freeze.ROUND,key=key)
        _write(source/'metadata.enc',metadata);metadata_sha=sha256(metadata).hexdigest()
        fm=dict(schema=freeze.V3_SCHEMA,execution_day=manifest['execution_day'],maximum_races=1,
            sealed_path='audit/state/manual-official-capture/'+seal['index_sha256'],index_sha256=seal['index_sha256'],
            source_metadata_path='audit/state/manual-official-source-metadata-'+metadata_sha+'.enc',source_metadata_sha256=metadata_sha,
            horse_baseline_artifact=deepcopy(manifest['horse_baseline_artifact']),carrier_artifact=deepcopy(manifest['carrier_artifact']),
            excluded_native_artifacts=deepcopy(manifest['excluded_native_artifacts']))
        staged=_staging({p.name:p.read_bytes() for p in source.iterdir()},fm,stage)
        _margin(manifest,utc_now())
        status=freeze.generate(manifest['carrier_artifact']['id'],root/'native',env,fm,source_root=staged,
            target_case={k:manifest[k] for k in ('race_id','cutoff_at','card_url')})
        need(status['ready'] and status['captured_native_input_count']==5,'FIVE_NATIVE_INPUTS_REQUIRED')
        records=freeze.local_records(root/'native');fixed=_exact_native_case(records,manifest)
        _margin(manifest,utc_now())
        generation=dict(status,schema=freeze.STATUS,workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'])
        _write(root/'native.status.json',future.wire(generation))
        journal.update(native_ready=True,fixed_as_of=fixed,freeze_manifest=fm,native_generation=generation)
        result.update(status,state='JRA_FUTURE_SOURCE_NATIVE_INPUTS_ENCRYPTED_LOCAL_ONLY',fixed_as_of=fixed)
    except Exception as exc:
        code=str(exc);journal['native_failure_code']=code if re.fullmatch(r'(?:JRA_FUTURE_SOURCE|ALL_MODEL_OFFICIAL_FREEZE)_[A-Z_]{1,100}',code) else 'NATIVE_OPERATION_REJECTED'
        result['reason']=journal['native_failure_code']
    common._seal(source/'collection.enc',journal,env,key)
    result.update(source_artifact_name='official-jra-future-source-capture-'+str(env['run_id']),source_capture_encrypted=True,
        independent_pre_cutoff_receipt_verified=False,old_source_requests_actual=None,old_source_requests_upper_bound=32)
    if result['ready']:result['artifact_name']=f'all-existing-model-pairs-{env["run_id"]}-{freeze.ROUND}'
    return result


def source_archive(raw,actual,env,*,now,key):
    need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE and actual.get('id') is not None and actual.get('expired') is False and
        actual.get('name')=='official-jra-future-source-capture-'+str(env['run_id']) and actual.get('size_in_bytes')==len(raw) and
        actual.get('digest')=='sha256:'+sha256(raw).hexdigest(),'SOURCE_ACTUAL_BYTES')
    run=actual.get('workflow_run',{})
    need(run.get('id')==env['run_id'] and run.get('head_sha')==env['head_sha'] and
        all(run.get(k)==1416489937 for k in ('repository_id','head_repository_id')) and
        core.clock(actual['created_at'])<=now<core.clock(actual['expires_at']),'SOURCE_ACTUAL_IDENTITY_CLOCK')
    need(raw.startswith(b'PK\x03\x04') and raw[-22:-18]==b'PK\x05\x06' and raw[-2:]==b'\0\0','SOURCE_ZIP_ENVELOPE')
    source={};used=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist();need(3<=len(entries)<=170 and not archive.comment,'SOURCE_ZIP_BOUND')
        for entry in entries:
            name=entry.filename
            need(name==entry.orig_filename and name not in source and re.fullmatch(
                r'(?:reservation|plan|collection|once|metadata|index|source-[0-9]{4}|raw-[0-9]{3}-[a-f0-9]{64})\.enc',name) and
                stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and not entry.flag_bits&0x41 and
                entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and 0<entry.file_size<=MAX_WIRE,'SOURCE_ZIP_MEMBER')
            used+=entry.file_size;need(used<=MAX_ARCHIVE,'SOURCE_ZIP_TOTAL')
            with archive.open(entry) as member:source[name]=member.read(MAX_WIRE+1)
            need(len(source[name])==entry.file_size,'SOURCE_ZIP_SIZE')
    journal=common._open(source['collection.enc'],env,key);reservation=common._open(source['reservation.enc'],env,key)
    need(journal['schema']==reservation['schema']==core.JOURNAL and reservation['state']=='RESERVED' and
        journal['state']=='CAPTURE_RETAINED' and journal['manifest_sha256']==digest(journal['manifest']) and
        all(journal.get(k)==v for k,v in reservation.items() if k not in ('state','source_requests_actual')) and
        journal['workflow_run_id']==env['run_id'] and journal['code_sha']==env['head_sha'] and
        core.clock(journal['epoch_started_at'])<=core.clock(journal['completed_at'])<=min(now,core.clock(actual['created_at'])+timedelta(seconds=1)),
        'SOURCE_JOURNAL_BINDING')
    plan=common._open(source['plan.enc'],env,key);core.validate_manifest(journal['manifest'],now=core.clock(journal['epoch_started_at']))
    need(digest(plan)==journal['plan_sha256'] and plan==journal['once_body']['plan'],'SOURCE_PLAN_BINDING')
    files=common._files(source,journal['capture_inventory'],env,key)
    if journal['capture_cache'] is not None:
        need('cache.json' in files and read_json_bytes(files['cache.json'])==journal['capture_cache'],'SOURCE_ORIGINAL_CACHE')
    need(type(journal['raw_retention_complete']) is bool and (not journal['raw_retention_complete'] or
        all(i['status']=='RETAINED' for i in journal['capture_inventory'])),'SOURCE_RETENTION_TRUTH')
    count=journal['source_requests_actual'];cache=journal['capture_cache']
    need(count is None or type(count) is int and cache is not None and _known(cache) and count==len(cache['attempts'])<=32,
        'SOURCE_REQUEST_COUNT_TRUTH')
    expected={'reservation.enc','plan.enc','collection.enc'}|{i['cipher_file'] for i in journal['capture_inventory'] if i['status']=='RETAINED'}
    if 'once.enc' in source:
        audit=core.validate_marker(source['once.enc'],journal['once_body'],key,now=core.clock(journal['epoch_started_at']))
        need(set(journal['once_proof'])==set(audit)|{'commit_sha'} and all(journal['once_proof'][k]==v for k,v in audit.items()) and
            journal['once_body']['manifest']==journal['manifest'] and journal['once_body']['target']==dict(run_id=env['run_id'],head_sha=env['head_sha'],run_attempt=1),
            'SOURCE_ONCE_BINDING');expected.add('once.enc')
    if 'metadata.enc' in source:expected.add('metadata.enc')
    expected|={name for name in source if re.fullmatch(r'(?:index|source-[0-9]{4})\.enc',name)}
    need(set(source)==expected,'SOURCE_EXACT_INVENTORY')
    return journal,source,files


def _verify_once(journal,source,key,transport):
    need('once.enc' in source and transport.read_file(journal['once_proof']['commit_sha'],core.PATH,MAX_WIRE)==source['once.enc'] and
        transport.read_file(transport.head(),core.PATH,MAX_WIRE)==source['once.enc'],'ONCE_INDEPENDENT_GIT_READBACK')
    core.validate_marker(source['once.enc'],journal['once_body'],key,now=core.clock(journal['epoch_started_at']))


def readback_source(source_id,root,env,manifest,*,marker_transport=None):
    key=state_key('production');now=utc_now();actual=future.metadata(source_id)
    journal,source,_=source_archive(future.gh('actions/artifacts/'+str(source_id)+'/zip'),actual,env,now=now,key=key)
    need(journal['manifest']==manifest and all((root/'source'/name).read_bytes()==raw for name,raw in source.items()),'ACTUAL_LOCAL_SOURCE')
    verified='once.enc' in source
    if verified:_verify_once(journal,source,key,marker_transport or core.MarkerTransport())
    return dict(state='JRA_FUTURE_SOURCE_CAPTURE_ACTUAL_SAVED_ONLY',ready=False,source_requests=journal['source_requests_actual'],
        source_request_upper_bound=32,source_artifact_id=source_id,source_artifact_digest=actual['digest'],
        independent_source_capture_receipt_verified=True,independent_pre_cutoff_receipt_verified=False,
        raw_retention_complete=journal['raw_retention_complete'],durable_source_reservation_verified=verified,
        old_source_requests_actual=None,old_source_requests_upper_bound=32)


def readback(native_id,source_id,root,env,manifest,*,marker_transport=None):
    key=state_key('production');now=utc_now();core.validate_manifest(manifest,now=now);actual=future.metadata(source_id)
    journal,source,files=source_archive(future.gh('actions/artifacts/'+str(source_id)+'/zip'),actual,env,now=now,key=key)
    need(journal['manifest']==manifest and journal['native_ready'] is True and journal['raw_retention_complete'] is True,'SOURCE_NATIVE_READY')
    _verify_once(journal,source,key,marker_transport or core.MarkerTransport())
    need(all((root/'source'/name).read_bytes()==raw for name,raw in source.items()),'ACTUAL_LOCAL_SOURCE')
    cache=journal['capture_cache'];capture._validate_cache(cache)
    bodies={url:files[entry['raw_file']] for url,entry in cache['captures'].items()}
    plan=common._open(source['plan.enc'],env,key)
    sidecar=core.originals(manifest,plan,cache,bodies)
    need(open_forecasts(source['metadata.enc'],key=key)==sidecar['document'],'SOURCE_METADATA_REPLAY')
    need(all(core.clock(plan['available_after'])<=core.clock(a['started_at'])<core.clock(plan['not_after']) and
        a['state']=='SUCCESS' for a in cache['attempts']),'SOURCE_WIRE_AUTHORIZATION')
    fm=journal['freeze_manifest'];stage=root.with_name(root.name+'.jra-readback')
    need(all(fm[k]==manifest[k] for k in ('execution_day','horse_baseline_artifact','carrier_artifact','excluded_native_artifacts')) and
        fm['schema']==freeze.V3_SCHEMA and fm['maximum_races']==1,'SOURCE_FREEZE_MANIFEST_BINDING')
    staged=_staging(source,fm,stage)
    try:
        restored=stage/'restored';capture.restore_cache(staged/fm['sealed_path'],restored,key=key,expected_index_sha256=fm['index_sha256'])
        need(capture._load(restored)==cache and all(capture.read_capture(restored,url)['raw']==raw for url,raw in bodies.items()),'SOURCE_SEALED_RAW_REPLAY')
        _margin(manifest,max(now,core.clock(actual['created_at'])+timedelta(seconds=1)))
        result=freeze.readback(native_id,root/'native',env,manifest=fm,source_root=staged)
        records=freeze.local_records(root/'native')
        need(_exact_native_case(records,manifest)==journal['fixed_as_of'],'EXACT_NATIVE_CASE_CUTOFF')
        need(all(c['native_payload']['snapshot']['race']['as_of']==journal['fixed_as_of'] for r in records for c in r['captured_native_inputs']),
            'FIXED_NATIVE_ASOF')
        native=future.metadata(native_id);_margin(manifest,max(utc_now(),core.clock(native['created_at'])+timedelta(seconds=1)))
    finally:shutil.rmtree(stage)
    return dict(result,fixed_as_of=journal['fixed_as_of'],source_artifact_id=source_id,source_artifact_digest=actual['digest'],
        source_requests=journal['source_requests_actual'],source_request_upper_bound=32,independent_source_capture_receipt_verified=True,
        durable_source_reservation_verified=True,old_source_requests_actual=None,old_source_requests_upper_bound=32)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True);parser.add_argument('--out-dir',required=True)
    parser.add_argument('--readback-native',type=int);parser.add_argument('--readback-source',type=int);args=parser.parse_args(argv)
    result=dict(schema=core.STATUS,state='HOLD_JRA_FUTURE_SOURCE_CAPTURE',ready=False,source_requests=0,
        plaintext_published=False,actual_purchases=False,production_promoted=False,independent_pre_cutoff_receipt_verified=False,
        old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN');root=None
    try:
        env=environment(check_owner_key=args.readback_source is not None or args.readback_native is not None)
        root=future.output_path(args.out_dir,env)
        manifest=core.validate_manifest(read_json_bytes(_read(Path(args.input),65536)),now=utc_now())
        need(args.readback_native is None or args.readback_source is not None,'BOTH_READBACK_ARTIFACTS_REQUIRED')
        if args.readback_native is not None:
            result.update(readback(args.readback_native,args.readback_source,root,env,manifest))
        elif args.readback_source is not None:
            result.update(readback_source(args.readback_source,root,env,manifest))
        else:
            wait_for_prior_window(manifest,env)
            result.update(generate(manifest,root,env))
    except Exception as exc:
        code=str(exc);result['reason']=code if re.fullmatch(r'(?:JRA_FUTURE_SOURCE|OFFICIAL_ISSUE_TRANSPORT)_[A-Z_]{1,100}',code) else 'JRA_FUTURE_SOURCE_OPERATION_REJECTED'
        if root is not None and (root/'source'/'reservation.enc').exists():
            result.update(source_requests=None,source_request_upper_bound=32,source_capture_encrypted=True,
                source_artifact_name='official-jra-future-source-capture-'+str(env['run_id']))
    if root is not None:
        status=root.with_name(root.name+'.status.json');save(status,future.wire(result),replace=status.exists())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(result['ready']).lower()+'\n')
            for field in ('artifact_name','source_artifact_name'):
                if field in result:output.write(field+'='+result[field]+'\n')
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
