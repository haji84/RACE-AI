"""Actions-only fresh AUTO/KEIRIN cards -> fixed native input-only artifacts.

Upload only ``native/`` and ``source/`` as the separately named opaque artifacts
returned below. The browser directory is private temporary state, never an
upload path. Readback requires both actual independently fetched artifact ZIPs.
"""
import argparse
import base64
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import zipfile

from race_ai.actions_contract import digest
from race_ai import future_source_cooldown as cooldown
from race_ai import all_existing_model_future_source_capture as core
from race_ai import all_existing_model_future_source_once as once
from race_ai import official_future_source_packet as builder
from race_ai import all_existing_model_official_recovery as recovery
from race_ai.all_existing_model_prior_static_cache import extract_static_cache,merge_static_cache
from race_ai.boat_all_model_store import seal_forecasts,open_forecasts,forecast_header,MAX_WIRE
from race_ai.boat_pdca_state import state_key
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_p0 as future
from scripts import all_existing_model_source_packet_freeze as freeze
from scripts import all_existing_model_official_result_collect as collector
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

need=core.need
MAX_RAW=8*1024*1024
MAX_ARCHIVE=96*1024*1024


def utc_now():return datetime.now(timezone.utc)


def wait_for_prior_window(manifest,env,*,reader=None,marker_transport=None,clock=None,sleeper=None,monotonic=None):
    need(type(manifest) is dict and manifest.get('schema')==core.SCHEMA,'WAIT_SCHEMA')
    return cooldown.wait_for_prior_window(manifest,env,reader=reader,marker_transport=marker_transport,
        clock=clock or utc_now,sleeper=sleeper,monotonic=monotonic)

def environment(*,check_owner_key=True):
    # Scope is checked before the first owner-secret lookup.
    need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI' and
        os.environ.get('GITHUB_REPOSITORY_ID')=='1416489937' and os.environ.get('GITHUB_EVENT_NAME')=='pull_request',
        'ACTIONS_PR_ONLY')
    event=read_json_bytes(_read(Path(os.environ.get('GITHUB_EVENT_PATH','')),1024*1024))
    need(event.get('number')==71 and event.get('pull_request',{}).get('head',{}).get('repo',{}).get('full_name')=='haji84/RACE-AI',
        'SAME_REPOSITORY_PR71')
    env=future.environment(check_owner_key=check_owner_key)
    current=read_json_bytes(future.gh('actions/runs/'+str(env['run_id'])))
    receipt=recovery.run_receipt(current)
    need(receipt['id']==env['run_id'] and receipt['head_sha']==env['head_sha'] and
        receipt['status']=='in_progress' and receipt['run_attempt']==1,'CURRENT_RUN_IDENTITY')
    env['run_attempt']=receipt['run_attempt']
    return env


def load_manifest(path,*,now):
    return core.validate_manifest(read_json_bytes(_read(Path(path),65536)),now=now)


def history(manifest,env,*,key,now):
    archives=[];total=0
    for pin in manifest['prior_journal_artifacts']:
        actual=future.metadata(pin['id']);size=actual.get('size_in_bytes')
        need(type(size) is int and 0<size<=MAX_ARCHIVE,'PRIOR_ARCHIVE_BOUND')
        raw=future.gh('actions/artifacts/'+str(pin['id'])+'/zip');total+=len(raw)
        need(len(raw)==size and total<=256*1024*1024,'PRIOR_AGGREGATE_BOUND')
        archives.append(dict(raw=raw,metadata=actual))
    runs={n:read_json_bytes(future.gh('actions/runs/'+str(n))) for n in
        {p['run_id'] for p in manifest['prior_journal_artifacts']}}
    old=runs.pop(recovery.OLD_RUN)
    return core.authenticate_future_history(manifest,journal_archives=archives,old_run=old,
        prior_runs=list(runs.values()),current_run=env['run_id'],now=now,key=key)


def static_cache(admitted,*,key,now):
    """Only authenticated old static originals; no old document/JSON replay."""
    original=admitted['bodies'][recovery.OLD_ARTIFACT]
    old_plan=collector.load_plan(original['manifest'],key=key,now=core.clock(original['epoch_started_at']))
    entries=merge_static_cache([],old_plan.get('static_cache',[]),now=now,sports=core.SPORTS)
    for ident,body in admitted['bodies'].items():
        if body.get('schema')==core.JOURNAL:
            # Its plan's cache and captured JS/CSS are already authenticated by
            # the source ZIP reader. Result-journal extraction is a different
            # schema and must not reinterpret a fresh-card document as static.
            continue
        if ident==recovery.OLD_ARTIFACT or 'browser_quarantine' not in body:continue
        if not any(e.get('resource_type') in ('script','stylesheet') for e in body.get('browser_index',{}).get('responses',[])):continue
        additions=extract_static_cache(body,admitted['receipts'][ident]['artifact_metadata'],now=now)
        entries=merge_static_cache(entries,additions,now=now,sports=core.SPORTS)
    return entries


def _node_environment():
    """One trusted runner tooling path; owner/Git/module injection stays out."""
    names=('PATH','HOME','LANG','LC_ALL','TMPDIR','XDG_CACHE_HOME','HTTP_PROXY','HTTPS_PROXY','NO_PROXY',
        'http_proxy','https_proxy','no_proxy','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS','REQUESTS_CA_BUNDLE','CHROMIUM_PATH')
    env={name:os.environ[name] for name in names if name in os.environ}
    if 'NODE_PATH' in os.environ:
        base=Path(os.environ.get('RUNNER_TEMP',''));value=os.environ['NODE_PATH']
        expected=base/'race-ai-future-ui-tools'/'node_modules'
        need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI' and
            os.environ.get('GITHUB_REPOSITORY_ID')=='1416489937' and base.is_absolute() and
            base.is_dir() and base==base.resolve() and value==str(expected) and os.pathsep not in value and
            expected.is_dir() and expected==expected.resolve() and
            not any(p.is_symlink() or (p/'.git').exists() for p in (expected,*expected.parents)),
            'PINNED_NODE_MODULES_PATH')
        env['NODE_PATH']=value
    return env


def capture_browser(plan,directory,*,diagnostic_sink=None):
    """Use the existing Node UI, with an allowlisted environment for Node too."""
    env=_node_environment()
    request=directory.with_name(directory.name+'.plan.json');_write(request,future.wire(plan))
    process=None;error=None
    try:
        process=subprocess.run(['node',str(freeze.ROOT/'scripts/official_result_browser_capture.cjs'),
            '--plan',str(request),'--out-dir',str(directory)],capture_output=True,timeout=100,env=env,check=False)
    except (subprocess.TimeoutExpired,OSError) as exc:error=exc
    if diagnostic_sink is not None:diagnostic_sink(collector._process_diagnostic(process,error))
    need(error is None and process is not None and process.returncode==0,'BROWSER_PROCESS_INCOMPLETE')
    need((directory/'capture-index.json').exists(),'BROWSER_INDEX_UNAVAILABLE')
    return read_json_bytes(collector._safe_file(directory,'capture-index.json',4*1024*1024))


def _seal(path,value,env,key):
    _write(path,seal_forecasts(value,run_id=str(env['run_id']),round_no=core.ROUND,key=key))


def _open(raw,env,key):
    header=forecast_header(raw)
    need(header['run_id']==str(env['run_id']) and header['round_no']==core.ROUND,'SOURCE_CIPHER_RUN')
    return open_forecasts(raw,key=key)


def inventory(directory,source,env,*,key):
    """Preserve bounded raw/checkpoint files even when native parsing fails."""
    items=[];used=0;complete=True
    if not directory.is_dir():return [],False
    paths=sorted(directory.rglob('*'))
    for path in paths:
        if path.is_dir() and not path.is_symlink():continue
        name=path.relative_to(directory).as_posix()
        item=dict(file=name,status='UNRETAINED')
        try:
            need(len(items)<128 and used<MAX_RAW,'RAW_INVENTORY_BOUND')
            limit=4*1024*1024 if name=='capture-index.json' or re.fullmatch('request-ledger-[0-9]{3}\\.json',name) else collector.MAX_BYTES
            raw=collector._safe_file(directory,name,min(limit,MAX_RAW-used));used+=len(raw)
            digest_raw=sha256(raw).hexdigest();cipher_name='raw-'+str(len(items)+1).zfill(3)+'-'+digest_raw+'.enc'
            _seal(source/cipher_name,dict(schema=core.JOURNAL,kind='ORIGINAL_PRIVATE_FILE',file=name,
                source_sha256=digest_raw,raw_base64=base64.b64encode(raw).decode()),env,key)
            item.update(status='RETAINED',byte_count=len(raw),source_sha256=digest_raw,cipher_file=cipher_name)
        except Exception:complete=False
        items.append(item)
    return items,complete


def _files(source,items,env,key):
    files={}
    for item in items:
        if item['status']=='UNRETAINED':continue
        need(item['status']=='RETAINED' and item['file'] not in files,'COMPLETE_ORIGINAL_INVENTORY')
        raw_cipher=source[item['cipher_file']]
        value=_open(raw_cipher,env,key)
        need(value['schema']==core.JOURNAL and value['kind']=='ORIGINAL_PRIVATE_FILE' and
            value['file']==item['file'] and value['source_sha256']==item['source_sha256'],'SOURCE_FILE_BINDING')
        raw=base64.b64decode(value['raw_base64'],validate=True)
        need(len(raw)==item['byte_count'] and sha256(raw).hexdigest()==item['source_sha256'],'SOURCE_FILE_SHA')
        files[item['file']]=raw
    need(sum(map(len,files.values()))<=MAX_RAW,'SOURCE_RAW_BOUND')
    return files


def _known(index,*,started,finished):
    """A returned stdout count or a reserved checkpoint is not a wire count."""
    try:
        count=index['actual_request_count'];entries=[e for e in index['ledger'] if 'sequence' in e]
        return (index['schema']==builder.CAPTURE and type(count) is int and 0<count<=32 and
            len(entries)==len(index['responses'])==count and
            {e['sequence'] for e in entries}==set(range(1,count+1)) and
            {e['sequence']:e for e in entries}=={e['sequence']:e for e in index['responses']} and
            started<=core.clock(index['started_at'])<=core.clock(index['completed_at'])<=finished and
            all(type(e.get('status')) is int and 100<=e['status']<=599 and
                started<=core.clock(e['request_started_at'])<=core.clock(e['body_captured_at'])<=finished for e in entries))
    except (KeyError,ValueError,TypeError):return False


def generate(manifest,root,env,*,marker_transport=None):
    need(not root.exists() and not root.with_name(root.name+'.browser').exists() and
        not root.with_name(root.name+'.browser.plan.json').exists(),'OUTPUT_EXISTS_DO_NOT_RESET')
    now=utc_now();core.validate_manifest(manifest,now=now);key=state_key('production')
    _node_environment()  # Reject a bad supplied resolver before consuming once.
    marker_transport=marker_transport or once.FutureSourceMarkerTransport()
    need(marker_transport.read_file(marker_transport.head(),once.PATH,MAX_WIRE) is None,'ONCE_ALREADY_CONSUMED')
    context=freeze._carrier_context(manifest['carrier_artifact']['id'],manifest,now=now)
    need(context['training']['scope']=='OPERATOR_SUPPLIED_RESEARCH','REAL_RESEARCH_CARRIER_REQUIRED')
    need(len(context['training']['models'])==14,'EXACT_BOAT_FOURTEEN_CARRIER')
    contexts=freeze._baseline_contexts(manifest,now=now,carrier_id=manifest['carrier_artifact']['id'])
    need(all(c['training']['scope']=='OPERATOR_SUPPLIED_RESEARCH' for c in contexts.values()),
        'REAL_RESEARCH_BASELINES_REQUIRED')
    need(all(len(c['training']['models']) in (19,30) for c in contexts.values()),'EXISTING_NINETEEN_OR_THIRTY_BASELINE')
    admitted=history(manifest,env,key=key,now=utc_now())
    assets=static_cache(admitted,key=key,now=utc_now())
    now=utc_now();plan=core.prepare_capture(manifest,contexts,now=now,static_cache=assets)
    plan['available_after']=max(core.clock(plan['available_after']),now).isoformat()
    once_body=once.body(manifest,env,contexts,admitted,plan,now=now)
    plan['not_after']=once_body['expires_at']
    once_body=once.body(manifest,env,contexts,admitted,plan,now=now)
    root.mkdir(mode=0o700);source=root/'source';source.mkdir(mode=0o700)
    audit={k:v for k,v in admitted.items() if k not in ('bodies','receipts','runs')}
    reservation=dict(schema=core.JOURNAL,state='RESERVED',manifest=deepcopy(manifest),manifest_sha256=digest(manifest),
        workflow_run_id=env['run_id'],code_sha=env['head_sha'],epoch_started_at=now.isoformat(),
        plan_sha256=digest(plan),source_requests_actual=None,maximum_requests=32,history=audit,once_body=once_body)
    _seal(source/'reservation.enc',reservation,env,key);_seal(source/'plan.enc',plan,env,key)
    directory=root.with_name(root.name+'.browser');index=None;diagnostics=[];failure=False;once_proof=None
    try:
        consumed=once.reserve(once_body,key,marker_transport,now=utc_now())
        raw_marker=consumed.pop('_ciphertext');once_proof=consumed
        _write(source/'once.enc',raw_marker)
        once.validate(raw_marker,once_body,key,now=utc_now())
        core.prepare_capture(manifest,contexts,now=utc_now())
        index=capture_browser(plan,directory,diagnostic_sink=diagnostics.append)
    except Exception:
        failure=True
        if (directory/'capture-index.json').exists():
            try:index=read_json_bytes(collector._safe_file(directory,'capture-index.json',4*1024*1024))
            except Exception:pass
    finished=utc_now();items,complete=inventory(directory,source,env,key=key)
    # No private exception/body/header text enters public output.
    journal=dict(reservation,state='CAPTURE_RETAINED',completed_at=finished.isoformat(),capture_index=index,
        capture_inventory=items,raw_retention_complete=complete,browser_process_diagnostic=diagnostics,
        source_requests_actual=index['actual_request_count'] if not failure and _known(index,started=now,finished=finished) else None,
        source_request_upper_bound=32,fixed_as_of=None,native_ready=False)
    if once_proof is not None:journal['once_proof']=once_proof
    result=dict(ready=False,state='HOLD_FUTURE_SOURCE_CAPTURE',source_requests=journal['source_requests_actual'],
        source_request_upper_bound=32,raw_retention_complete=complete,**audit)
    try:
        need(not failure and complete and journal['source_requests_actual'] is not None,'CAPTURE_OUTCOME_UNKNOWN_OR_UNRETAINED')
        recovery.no_known_denial(index)
        core.prepare_capture(manifest,contexts,now=finished)
        files={item['file']:collector._safe_file(directory,item['file'],4*1024*1024) for item in items}
        built=builder.build_source_packet(plan,index,files,terms_manifest=manifest['terms_manifest'],
            as_of=core.clock(index['completed_at']))
        need(built['state']=='READY_INPUTS_ONLY','NATIVE_BUILDER_HOLD')
        packet_cipher=seal_forecasts(built['packet'],run_id=str(env['run_id']),round_no=core.ROUND,key=key)
        _write(source/'packet.enc',packet_cipher);packet_sha=sha256(packet_cipher).hexdigest()
        fm=dict(schema=freeze.SCHEMA_V2,execution_day=manifest['execution_day'],packet_sha256=packet_sha,
            packet_path='audit/state/official-source-packet-'+packet_sha+'.enc',maximum_races_per_sport={s:1 for s in core.SPORTS},
            baseline_artifacts=deepcopy(manifest['baseline_artifacts']),carrier_artifact=deepcopy(manifest['carrier_artifact']))
        counts=dict(held_cases=0,rejected_cases=0,ready_races_by_sport={s:1 for s in core.SPORTS})
        status=freeze.seal_selected(manifest['carrier_artifact']['id'],root/'native',fm,context,built['packet'],
            core.fixed_selection(built),counts,contexts=contexts,minimum_margin_seconds=600)
        generation=dict(status,schema=freeze.STATUS,workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'])
        _write(root/'native.generation.json',future.wire(generation))
        journal.update(native_ready=True,fixed_as_of=built['fixed_as_of'],freeze_manifest=fm,
            case_bindings=built['case_bindings'],native_generation=generation)
        result.update(status,state='FUTURE_SOURCE_NATIVE_INPUTS_ENCRYPTED_LOCAL_ONLY',fixed_as_of=built['fixed_as_of'])
    except Exception as exc:
        code=str(exc)
        journal['native_failure_code']=code if re.fullmatch(r'(?:ALL_MODEL_FUTURE_SOURCE|ALL_MODEL_SOURCE_PACKET_FREEZE)_[A-Z_]{1,100}',code) else 'NATIVE_OPERATION_REJECTED'
        result['reason']=journal['native_failure_code']
    _seal(source/'collection.enc',journal,env,key)
    result.update(source_artifact_name='official-future-source-capture-'+str(env['run_id']),
        source_capture_encrypted=True,independent_pre_cutoff_receipt_verified=False)
    if result['ready']:result['artifact_name']=f'all-existing-model-pairs-{env["run_id"]}-{freeze.ROUND}'
    return result


def source_archive(raw,actual,env,*,now,key):
    need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE and actual.get('id') is not None and
        actual.get('name')=='official-future-source-capture-'+str(env['run_id']) and actual.get('expired') is False and
        actual.get('size_in_bytes')==len(raw) and actual.get('digest')=='sha256:'+sha256(raw).hexdigest(),'SOURCE_ACTUAL_BYTES')
    run=actual.get('workflow_run',{})
    need(run.get('id')==env['run_id'] and run.get('head_sha')==env['head_sha'] and
        all(run.get(k)==1416489937 for k in ('repository_id','head_repository_id')) and
        core.clock(actual['created_at'])<=now<core.clock(actual['expires_at']),'SOURCE_ACTUAL_IDENTITY_CLOCK')
    need(raw.startswith(b'PK\x03\x04') and raw[-22:-18]==b'PK\x05\x06' and raw[-2:]==b'\0\0','SOURCE_ZIP_ENVELOPE')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist();need(3<=len(entries)<=133 and not archive.comment,'SOURCE_ZIP_BOUND')
        source={};used=0
        for entry in entries:
            name=entry.filename
            need(name==entry.orig_filename and name not in source and re.fullmatch(
                r'(?:reservation|plan|collection|packet|once|raw-[0-9]{3}-[a-f0-9]{64})\.enc',name) and
                stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and not entry.flag_bits&0x41 and
                entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and 0<entry.file_size<=MAX_WIRE,'SOURCE_ZIP_MEMBER')
            used+=entry.file_size;need(used<=MAX_ARCHIVE,'SOURCE_ZIP_TOTAL')
            with archive.open(entry) as member:source[name]=member.read(MAX_WIRE+1)
            need(len(source[name])==entry.file_size,'SOURCE_ZIP_SIZE')
    journal=_open(source['collection.enc'],env,key);reservation=_open(source['reservation.enc'],env,key)
    need(journal['schema']==reservation['schema']==core.JOURNAL and journal['manifest']==reservation['manifest'] and
        journal['manifest_sha256']==reservation['manifest_sha256']==digest(journal['manifest']) and
        journal['workflow_run_id']==env['run_id'] and journal['code_sha']==env['head_sha'] and
        core.clock(journal['epoch_started_at'])<=core.clock(journal['completed_at'])<=min(now,core.clock(actual['created_at'])+timedelta(seconds=1)) and
        reservation['state']=='RESERVED' and journal['state']=='CAPTURE_RETAINED' and
        all(journal.get(k)==v for k,v in reservation.items() if k not in ('state','source_requests_actual')),
        'SOURCE_JOURNAL_BINDING')
    plan=_open(source['plan.enc'],env,key)
    core.validate_manifest(journal['manifest'],now=core.clock(journal['epoch_started_at']))
    need(plan.get('schema')==builder.PLAN and plan.get('intent')==builder.INTENT and
        plan.get('cases')==journal['manifest']['cases'] and plan.get('request_budget')==32 and
        plan.get('available_after')==journal['epoch_started_at'] and digest(plan)==journal['plan_sha256'] and
        journal['maximum_requests']==32,'SOURCE_ORIGINAL_PLAN_BINDING')
    files=_files(source,journal['capture_inventory'],env,key)
    if 'capture-index.json' in files:
        need(read_json_bytes(files['capture-index.json'])==journal['capture_index'],'SOURCE_ORIGINAL_INDEX_BINDING')
    need(type(journal['raw_retention_complete']) is bool and (not journal['raw_retention_complete'] or
        all(i['status']=='RETAINED' for i in journal['capture_inventory'])),'SOURCE_RETENTION_TRUTH')
    count=journal['source_requests_actual']
    need(count is None or type(count) is int and _known(journal['capture_index'],started=core.clock(journal['epoch_started_at']),
        finished=core.clock(journal['completed_at'])) and count==journal['capture_index']['actual_request_count'],
        'SOURCE_REQUEST_COUNT_TRUTH')
    expected={'reservation.enc','plan.enc','collection.enc'}|{i['cipher_file'] for i in journal['capture_inventory'] if i['status']=='RETAINED'}
    if 'packet.enc' in source:expected.add('packet.enc')
    if 'once.enc' in source:
        expected_audit=once.validate(source['once.enc'],journal['once_body'],key,now=core.clock(journal['once_body']['issued_at']))
        need(journal['once_proof']['marker_cipher_sha256']==sha256(source['once.enc']).hexdigest() and
            journal['once_body']['manifest_sha256']==journal['manifest_sha256'] and
            journal['once_body']['plan_sha256']==journal['plan_sha256'] and
            plan.get('not_after')==journal['once_body']['expires_at'] and
            journal['once_body']['issued_at']==journal['epoch_started_at'] and
            journal['once_body']['target']==dict(run_id=env['run_id'],head_sha=env['head_sha'],run_attempt=1) and
            set(journal['once_proof'])==set(expected_audit)|{'commit_sha'} and
            all(journal['once_proof'][k]==v for k,v in expected_audit.items()),'SOURCE_ONCE_BINDING')
        if journal['capture_index'] is not None:
            expires=core.clock(journal['once_body']['expires_at'])
            need(all(core.clock(e['request_started_at'])<expires for e in journal['capture_index']['ledger']
                if 'sequence' in e),'SOURCE_ONCE_WIRE_EXPIRY')
        expected.add('once.enc')
    need(set(source)==expected,'SOURCE_EXACT_CIPHER_INVENTORY')
    return journal,source,files


def _verify_once(journal,source,key,transport):
    if 'once.enc' not in source:return False
    commit=journal['once_proof']['commit_sha']
    need(transport.read_file(commit,once.PATH,MAX_WIRE)==source['once.enc'] and
        transport.read_file(transport.head(),once.PATH,MAX_WIRE)==source['once.enc'],'ONCE_INDEPENDENT_GIT_READBACK')
    once.validate(source['once.enc'],journal['once_body'],key,now=core.clock(journal['once_body']['issued_at']))
    return True


def readback_source(source_id,root,env,manifest,*,marker_transport=None):
    """A failed acquisition can prove its saved UNKNOWN without native inputs."""
    key=state_key('production');now=utc_now()
    actual=future.metadata(source_id);raw=future.gh('actions/artifacts/'+str(source_id)+'/zip')
    journal,source,_=source_archive(raw,actual,env,now=now,key=key)
    need(journal['manifest']==manifest and all((root/'source'/name).read_bytes()==cipher
        for name,cipher in source.items()),'ACTUAL_SOURCE_LOCAL_READBACK')
    marker_verified=_verify_once(journal,source,key,marker_transport or once.FutureSourceMarkerTransport())
    return dict(state='FUTURE_SOURCE_CAPTURE_ACTUAL_SAVED_ONLY',ready=False,source_requests=journal['source_requests_actual'],
        source_request_upper_bound=32,raw_retention_complete=journal['raw_retention_complete'],source_artifact_id=source_id,
        source_artifact_digest=actual['digest'],independent_source_capture_receipt_verified=True,
        independent_pre_cutoff_receipt_verified=False,old_source_requests_actual=None,old_source_requests_upper_bound=32,
        durable_source_reservation_verified=marker_verified)


def readback(native_id,source_id,root,env,manifest,*,marker_transport=None):
    key=state_key('production');now=utc_now();core.validate_manifest(manifest,now=now)
    actual=future.metadata(source_id);raw=future.gh('actions/artifacts/'+str(source_id)+'/zip')
    journal,source,files=source_archive(raw,actual,env,now=now,key=key)
    need(journal['manifest']==manifest and journal['native_ready'] is True and journal['raw_retention_complete'] is True,
        'SOURCE_NATIVE_READY_REQUIRED')
    need(_verify_once(journal,source,key,marker_transport or once.FutureSourceMarkerTransport()),'SOURCE_ONCE_REQUIRED')
    need(all((root/'source'/name).read_bytes()==cipher for name,cipher in source.items()),'ACTUAL_SOURCE_LOCAL_READBACK')
    plan=_open(source['plan.enc'],env,key);need(digest(plan)==journal['plan_sha256'],'SOURCE_PLAN_SHA')
    index=journal['capture_index'];recovery.no_known_denial(index)
    built=builder.build_source_packet(plan,index,files,terms_manifest=manifest['terms_manifest'],as_of=core.clock(index['completed_at']))
    need(built['state']=='READY_INPUTS_ONLY' and built['fixed_as_of']==journal['fixed_as_of'] and
        built['case_bindings']==journal['case_bindings'],'FIXED_SOURCE_REPLAY')
    packet=_open(source['packet.enc'],env,key);fm=journal['freeze_manifest']
    need(packet==built['packet'] and sha256(source['packet.enc']).hexdigest()==fm['packet_sha256'],'SOURCE_PACKET_CIPHER_BINDING')
    contexts=freeze._baseline_contexts(fm,now=now,carrier_id=fm['carrier_artifact']['id'])
    core.prepare_capture(manifest,contexts,now=now)
    boundary=max(now,core.clock(actual['created_at'])+timedelta(seconds=1))
    need(all(boundary+timedelta(seconds=600)<core.clock(c['cutoff_at']) for c in manifest['cases']),
        'SOURCE_INDEPENDENT_RECEIPT_MARGIN')
    # Existing V2 readback authenticates actual native ZIPs, native source replay,
    # original baseline MACs/receipts and all immutable member digests.
    result=freeze.readback(native_id,root/'native',env,manifest=fm,_packet_loader=lambda *_args,**_kw:packet)
    native_actual=future.metadata(native_id)
    boundary=max(now,core.clock(native_actual['created_at'])+timedelta(seconds=1))
    need(all(boundary+timedelta(seconds=600)<core.clock(c['cutoff_at']) for c in manifest['cases']),
        'NATIVE_INDEPENDENT_RECEIPT_MARGIN')
    return dict(result,fixed_as_of=journal['fixed_as_of'],source_artifact_id=source_id,source_artifact_digest=actual['digest'],
        independent_source_capture_receipt_verified=True,source_requests=journal['source_requests_actual'],
        source_request_upper_bound=32,old_source_requests_actual=None,old_source_requests_upper_bound=32,
        durable_source_reservation_verified=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True)
    parser.add_argument('--out-dir',required=True);parser.add_argument('--readback-native',type=int)
    parser.add_argument('--readback-source',type=int);args=parser.parse_args(argv)
    result=dict(schema=core.STATUS,state='HOLD_FUTURE_SOURCE_CAPTURE',ready=False,source_requests=0,
        plaintext_published=False,actual_purchases=False,production_promoted=False,
        provider_model_training_permission_confirmed=False,independent_pre_cutoff_receipt_verified=False,
        old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN')
    root=None
    try:
        env=environment(check_owner_key=args.readback_source is not None or args.readback_native is not None)
        root=future.output_path(args.out_dir,env);manifest=load_manifest(args.input,now=utc_now())
        need(args.readback_native is None or args.readback_source is not None,'BOTH_READBACK_ARTIFACTS_REQUIRED')
        if args.readback_native is not None:
            result.update(readback(args.readback_native,args.readback_source,root,env,manifest))
        elif args.readback_source is not None:
            result.update(readback_source(args.readback_source,root,env,manifest))
        else:
            wait_for_prior_window(manifest,env)
            result.update(generate(manifest,root,env))
    except Exception as exc:
        code=str(exc)
        result['reason']=code if re.fullmatch(r'(?:ALL_MODEL_FUTURE_SOURCE|OFFICIAL_ISSUE_TRANSPORT)_[A-Z_]{1,100}',code) else 'FUTURE_SOURCE_OPERATION_REJECTED'
        # Any reserved capture retains unknown, even if a later operation fails.
        if root is not None and (root/'source'/'reservation.enc').exists() and \
                forecast_header((root/'source'/'reservation.enc').read_bytes())['run_id']==str(env['run_id']):
            result.update(source_requests=None,source_request_upper_bound=32,source_capture_encrypted=True,
                source_artifact_name='official-future-source-capture-'+str(env['run_id']))
    if root is not None:
        status=root.with_name(root.name+'.status.json');save(status,future.wire(result),replace=status.exists())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(result['ready']).lower()+'\n')
            for field in ('artifact_name','source_artifact_name'):
                if field in result:output.write(field+'='+result[field]+'\n')
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
