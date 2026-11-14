"""Actions-only first forward official RESULT capture.

Upload only result/ and source/, using the exact names returned by main. Browser
plaintext is private temporary state. This does not issue a forecast or fit.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import time
import zipfile
from urllib.error import HTTPError

from race_ai.actions_contract import digest
from race_ai import all_existing_model_future_result_capture as core
from race_ai import all_existing_model_official_results as results
from race_ai import all_existing_model_official_recovery as recovery
from race_ai import official_future_horse_result as horse
from race_ai.boat_all_model_store import seal_forecasts,open_forecasts,forecast_header,MAX_WIRE
from race_ai.boat_pdca_state import state_key
from race_ai import boat_private_original_archive as originals
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_source_capture as common
from scripts import all_existing_model_official_result_collect as C
from scripts import all_existing_model_future_p0 as future
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

need=core.need
MAX_ARCHIVE=common.MAX_ARCHIVE
REPLAY_SCHEMA='RACE_AI_FORWARD_ORIGINAL_BATCH_ARCHIVES_V1'
MAX_REPLAY_CIPHER=48*1024*1024


def utc_now():return datetime.now(timezone.utc)


def _seal(value,env,key):return seal_forecasts(value,run_id=str(env['run_id']),round_no=core.ROUND,key=key)


def _open(raw,env,key):
    header=forecast_header(raw)
    need(header['run_id']==str(env['run_id']) and header['round_no']==core.ROUND,'JOURNAL_CIPHER_IDENTITY')
    return open_forecasts(raw,key=key)


def _admit(manifest,*,now,key,transport,manifest_at=None):
    if manifest['schema']==core.SCHEMA_V2:
        batches=[dict(future=transport.archive(p['future_artifact']),origin=transport.archive(p['origin_artifact']))
                 for p in manifest['forecast_batches']]
        admitted=core.admit_forecast(manifest,batch_archives=batches,now=now,key=key,manifest_at=manifest_at)
    else:
        forecast=transport.archive(manifest['forecast_artifact']);origin=transport.archive(manifest['origin_artifact'])
        admitted=core.admit_forecast(manifest,forecast_raw=forecast['raw'],forecast_metadata=forecast['metadata'],
            origin_raw=origin['raw'],origin_metadata=origin['metadata'],now=now,key=key,manifest_at=manifest_at)
    sources=[transport.archive(p) for p in admitted['source_input_artifacts']]
    proof=core.admit_native_sources(admitted,sources,now=now,key=key)
    if manifest['schema']==core.SCHEMA_V2:
        need(sum(len(item['raw']) for batch in batches for item in batch.values())+
             sum(len(item['raw']) for item in sources)<=MAX_REPLAY_CIPHER,'ORIGINAL_BATCH_REPLAY_BOUND')
        admitted['_replay_originals']=dict(batches=batches,source_archives=sources)
    return admitted,proof


def seal_retained_forecasts(admitted,env,key):
    """Retain exact ZIP bytes under a specific existing-AES envelope kind."""
    private=admitted['_replay_originals'];members={};total=0
    def retained(item):
        nonlocal total
        name='forecast-original-'+str(len(members)).zfill(3)+'.enc';raw=item['raw']
        need(len(members)<24 and 0<len(raw)<MAX_WIRE-65536,'ORIGINAL_BATCH_MEMBER_BOUND')
        cipher=originals.seal_forecast_batch_original_zip(raw,run_id=env['run_id'],head_sha=env['head_sha'],key=key)
        total+=len(cipher);need(len(cipher)<=MAX_WIRE and total<=MAX_REPLAY_CIPHER,'ORIGINAL_BATCH_REPLAY_BOUND')
        members[name]=cipher
        return dict(file=name,raw_size=len(raw),raw_sha256=sha256(raw).hexdigest(),cipher_sha256=sha256(cipher).hexdigest(),
                    metadata=deepcopy(item['metadata']))
    index=dict(schema=REPLAY_SCHEMA,batches=[{k:retained(batch[k]) for k in ('future','origin')} for batch in private['batches']],
               source_archives=[retained(item) for item in private['source_archives']])
    members['forecast-batches.enc']=_seal(index,env,key)
    return members


def _source_capacity(members,plan_cipher,reservation_cipher,once_cipher):
    # Existing MAX_RAW is 8 MiB: reserve 16 MiB for its base64, all 128 file
    # headers/paths, and inventory overhead; collection keeps its old 24 MiB.
    need(common.MAX_RAW<=8*1024*1024,'ORIGINAL_RAW_BUDGET_CHANGED')
    fixed=sum(map(len,members.values()))+len(plan_cipher)+len(reservation_cipher)+len(once_cipher)
    need(fixed+24*1024*1024+65536+16*1024*1024+1024*1024<=MAX_ARCHIVE,
         'WHOLE_SOURCE_ARCHIVE_CAPACITY_BEFORE_DISPATCH')


def replay_retained_forecasts(journal,source,env,*,now,key):
    """Re-admit exact original ZIP bytes, never construct a combined origin."""
    need(journal['manifest']['schema']==core.SCHEMA_V2 and 'forecast-batches.enc' in source,'ORIGINAL_BATCH_BUNDLE_REQUIRED')
    bundle=_open(source['forecast-batches.enc'],env,key)
    need(type(bundle) is dict and set(bundle)=={'schema','batches','source_archives'} and
        bundle['schema']==REPLAY_SCHEMA and type(bundle['batches']) is list and
        len(bundle['batches'])==len(journal['manifest']['forecast_batches']) and
        type(bundle['source_archives']) is list and 1<=len(bundle['source_archives'])<=16,'ORIGINAL_BATCH_BUNDLE_FIELDS')
    used=[];total=0
    def original(value):
        nonlocal total
        need(type(value) is dict and set(value)=={'file','raw_size','raw_sha256','cipher_sha256','metadata'} and
            type(value['metadata']) is dict and value['file']=='forecast-original-'+str(len(used)).zfill(3)+'.enc' and
            len(used)<24 and value['file'] in source,'ORIGINAL_BATCH_MEMBER')
        name=value['file'];cipher=source[name];total+=len(cipher)
        need(0<len(cipher)<=MAX_WIRE and total<=MAX_REPLAY_CIPHER and
            sha256(cipher).hexdigest()==value['cipher_sha256'],'ORIGINAL_BATCH_CIPHER')
        raw=originals.open_forecast_batch_original_zip(cipher,run_id=env['run_id'],head_sha=env['head_sha'],
            key=key,max_plain_zip_bytes=MAX_WIRE)
        need(type(value['raw_size']) is int and len(raw)==value['raw_size'] and
            sha256(raw).hexdigest()==value['raw_sha256'],'ORIGINAL_BATCH_BYTES')
        used.append(name)
        return dict(raw=raw,metadata=deepcopy(value['metadata']))
    batches=[]
    for batch in bundle['batches']:
        need(type(batch) is dict and set(batch)=={'future','origin'},'ORIGINAL_BATCH_PAIR')
        batches.append({k:original(v) for k,v in batch.items()})
    admitted=core.admit_forecast(journal['manifest'],batch_archives=batches,now=now,key=key,
        manifest_at=journal['epoch_started_at'])
    proof=core.admit_native_sources(admitted,[original(v) for v in bundle['source_archives']],now=now,key=key)
    need({name for name in source if re.fullmatch(r'forecast-original-[0-9]{3}\.enc',name)}==set(used),
         'ORIGINAL_BATCH_EXACT_MEMBERS')
    retained=journal['native_source_proof'];history_fields={'authenticated_future_source_sports','original_future_source_journals_joined'}
    need(admitted['forecast_identity']==journal['forecast_identity'] and set(retained)==set(proof)|history_fields and
        all(retained[k]==v for k,v in proof.items()) and retained['authenticated_future_source_sports']==sorted(core.SPORTS) and
        retained['original_future_source_journals_joined'] is True,'ORIGINAL_BATCH_REPLAY_BINDING')
    admitted['_replay_member_names']=used
    return admitted,proof


def _wire_window(plan,now):
    need(core.clock(plan['not_before'])<=now<core.clock(plan['not_after']),'SOURCE_AUTHORIZATION_CLOCK')


@contextmanager
def _private_capture_files(files):
    import tempfile
    with tempfile.TemporaryDirectory(prefix='future-result-wire-') as temporary:
        directory=Path(temporary)
        for name,raw in files.items():
            need(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts and
                '\\' not in name,'SOURCE_PRIVATE_FILENAME')
            path=directory/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);_write(path,raw)
        yield directory


def _browser_known(index,files,plan,*,started,finished):
    """Count only completed retained original wires, never a reserved checkpoint."""
    try:
        recovery.no_known_denial(index)
        C._index_header(index,plan['cases'],started=started,now=finished,remaining=plan['request_budget'])
        with _private_capture_files(files) as directory:
            rows={}
            for row in index['responses']:
                raw=C._safe_file(directory,row['body_file'],C.MAX_BYTES)
                metadata=read_json_bytes(C._safe_file(directory,row['metadata_file'],65536))
                request=C._safe_file(directory,row['request_body_file'],16384) if row.get('request_body_file') else None
                rows[row['sequence']]=(raw,metadata,request)
            C._browser_complete_source_wire(index,rows,directory,started=started,now=finished)
        entries=[e for e in index['ledger'] if 'sequence' in e]
        return all(core.clock(plan['not_before'])<=core.clock(e['request_started_at'])<core.clock(plan['not_after']) for e in entries)
    except (ValueError,KeyError,TypeError,AttributeError,OSError):return False


def replay_capture(journal,files,admitted,plan):
    """Replay original UI/link/parser decisions at the original completion clock."""
    at=core.clock(journal['completed_at']);epoch=core.clock(journal['epoch_started_at'])
    expected=core.prepare_plan(journal['manifest'],admitted,now=epoch,expires_at=plan['not_after'],static_cache=plan.get('static_cache'))
    need(expected==plan,'ORIGINAL_FORECAST_PLAN_REPLAY')
    with _private_capture_files(files) as directory:
        found,_,_=C.browser_sources(journal['browser_index'],directory,plan['cases'],started=epoch,now=at,remaining=30)
    natives={i['case']['sport']:i['native_payload'] for i in admitted['cases']};observations=[]
    for sport,_,capture in found:observations.append(C._parse(capture,natives[sport],sport,now=at,allow_order_only=True))
    horse_case=next(i for i in admitted['cases'] if i['case']['sport']=='horse')
    direct=journal['direct_captures'];need(type(direct) is list and len(direct)<=2,'ORIGINAL_DIRECT_CAPTURE_BOUND')
    if direct:
        target=horse.discover_result(horse_case['case'],horse_case['native_payload'],direct[0],now=at)
        if len(direct)==2:
            need(target is not None,'ORIGINAL_PUBLISHED_RESULT_REQUIRED')
            observations.append(horse.bind_result(horse_case['case'],horse_case['native_payload'],direct[0],direct[1],now=at))
    need(observations==journal['observations'],'ORIGINAL_RESULT_NORMALIZATION_REPLAY')
    return observations


def _status(journal,env,*,ready=False):
    normal={r['sport'] for r in journal['observations'] if r['status'] in ('settled','rank_confirmed')}
    return dict(schema=core.STATUS,state='FUTURE_RESULTS_ENCRYPTED_LOCAL_ONLY' if ready else 'HOLD_FUTURE_RESULT_CAPTURE',
        ready=ready,workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],
        source_requests=journal['source_requests_actual'],source_request_upper_bound=32,
        old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',
        result_observation_count=len(journal['observations']),raw_retention_complete=journal['raw_retention_complete'],
        confirmed_cases_by_sport={s:int(s in normal) for s in sorted(core.SPORTS)},
        all_requested_cases_confirmed=normal==core.SPORTS,missing_results_are_not_losses=True,
        evaluation_scope='ORDER_ONLY_NO_MONETARY_EVALUATION',monetary_evaluation_available=False,
        result_artifact_name=f'all-existing-official-results-{env["run_id"]}-{core.RESULT_ROUND}' if ready else None,
        source_artifact_name='official-future-result-capture-'+str(env['run_id']),
        actual_purchases=False,production_promoted=False,plaintext_published=False)


def _recording_opener(opener,directory,journal,clock,persist,plan):
    """Retain even denied/non-200 response bodies without another request."""
    fetch=opener or C.build_opener(C.policy._NoRedirect()).open
    def open_response(request,timeout):
        started=clock();_wire_window(plan,started)
        number=len(journal['attempts']);base='direct-'+str(number).zfill(3)
        retained=dict(sequence=number,source_url=request.full_url,request_started_at=started.isoformat(),
            state='RESERVED',raw_body_complete=False)
        journal.setdefault('direct_wire_retention',[]).append(retained);persist()
        try:
            started=clock();_wire_window(plan,started)
            retained['request_started_at']=started.isoformat()
            try:response=fetch(request,timeout=timeout)
            except HTTPError as exc:response=exc
        except Exception:
            retained['state']='OPEN_UNAVAILABLE';persist();raise
        class Recorded:
            status=getattr(response,'status',None) or getattr(response,'code',None)
            headers=response.headers
            def __init__(self):self.raw=None;self.attempted=False
            def geturl(self):return response.geturl()
            def read(self,maximum):
                if self.raw is None:
                    self.attempted=True
                    try:self.raw=response.read(C.MAX_BYTES+1)
                    except Exception:
                        retained['state']='BODY_UNAVAILABLE';persist();raise
                    completed=clock()
                    complete=type(self.raw) is bytes and len(self.raw)<=C.MAX_BYTES
                    body=self.raw[:C.MAX_BYTES] if type(self.raw) is bytes else b''
                    directory.mkdir(mode=0o700,exist_ok=True)
                    _write(directory/(base+'.body'),body)
                    retained.update(final_url=self.geturl(),status=self.status,method='GET',http_method='GET',
                        request_started_at=started.isoformat(),response_received_at=completed.isoformat(),
                        source_sha256=sha256(body).hexdigest(),byte_count=len(body),raw_body_complete=complete,
                        state='RETAINED',body_file=base+'.body',metadata_file=base+'.metadata.json')
                    _write(directory/(base+'.metadata.json'),future.wire(retained));persist()
                return self.raw[:maximum]
            def close(self):
                try:
                    if not self.attempted:self.read(C.MAX_BYTES+1)
                finally:response.close()
        return Recorded()
    return open_response


def _direct_known(journal,files,plan):
    """Join every reserved direct request to its retained original wire bytes."""
    try:
        attempts=journal['attempts'];rows=journal.get('direct_wire_retention',[]);used=[]
        need(type(attempts) is list and len(attempts)<=2 and len(rows)==len(attempts),'DIRECT_WIRE_COUNT')
        epoch=core.clock(journal['epoch_started_at']);finished=core.clock(journal['completed_at'])
        previous=core.clock(journal['browser_index']['completed_at'])
        for number,(attempt,row) in enumerate(zip(attempts,rows,strict=True),1):
            need(row['sequence']==number and type(row['sequence']) is int and row['state']=='RETAINED' and
                row['raw_body_complete'] is True and type(row['status']) is int and
                row['status']==attempt['http_status'] and attempt['state']!='RESERVED' and
                attempt['url']==row['source_url']==row['final_url'],'DIRECT_WIRE_IDENTITY')
            start=core.clock(attempt['started_at']);sent=core.clock(row['request_started_at']);completed=core.clock(row['response_received_at'])
            end=core.clock(attempt['finished_at'])
            need(epoch<=start<=sent<core.clock(plan['not_after']) and
                previous+timedelta(seconds=C.INTERVAL)<=sent<=completed<=end<=finished,'DIRECT_WIRE_CLOCK')
            raw=files[row['body_file']];metadata=read_json_bytes(files[row['metadata_file']])
            need(metadata==row and type(raw) is bytes and len(raw)==row['byte_count']<=C.MAX_BYTES and
                sha256(raw).hexdigest()==row['source_sha256'],'DIRECT_ORIGINAL_BYTES')
            if attempt['state']=='SUCCESS':
                matches=[c for c in journal['direct_captures'] if c['metadata']['source_url']==attempt['url'] and
                    c['metadata']['source_sha256']==row['source_sha256']]
                need(row['status']==200 and len(matches)==1 and C._blob(matches[0]['raw_base64'])==raw and
                    matches[0]['metadata']['status']==row['status'] and
                    matches[0]['metadata']['final_url']==row['final_url'] and
                    matches[0]['metadata']['method']==matches[0]['metadata']['http_method']==row['method']==row['http_method']=='GET' and
                    matches[0]['metadata']['byte_count']==row['byte_count'] and
                    core.clock(matches[0]['metadata']['fetched_at'])==sent and
                    core.clock(matches[0]['metadata']['response_received_at'])==completed,'DIRECT_CAPTURE_WIRE_JOIN')
                used.append(matches[0])
            previous=end
        need(len(used)==len(journal['direct_captures']),'DIRECT_CAPTURE_COUNT')
        return True
    except (ValueError,TypeError,KeyError,AttributeError):return False


def generate(manifest,root,env,*,marker_transport=None,clock=utc_now,browser=common.capture_browser,opener=None,sleeper=time.sleep):
    now=clock();core.validate_manifest(manifest,now=now)
    root=future.output_path(root,env)
    need(not root.exists() and not root.with_name(root.name+'.browser').exists() and
        not root.with_name(root.name+'.browser.plan.json').exists(),'OUTPUT_EXISTS_DO_NOT_RESET')
    need(env.get('run_attempt')==1 and type(env.get('run_attempt')) is int,'ACTUAL_ATTEMPT_ONE')
    common._node_environment();key=state_key('production');transport=marker_transport or core.MarkerTransport()
    need(transport.read_file(transport.head(),core.PATH,MAX_WIRE) is None,'ONCE_ALREADY_CONSUMED')
    admitted,source_proof=_admit(manifest,now=now,key=key,transport=transport)
    now=clock();core.validate_manifest(manifest,now=now)
    need(all(r['training']['scope']=='OPERATOR_SUPPLIED_RESEARCH' for r in admitted['records']),'REAL_THIRTY_FORECAST_REQUIRED')
    selected_horse=next(i for i in admitted['cases'] if i['case']['sport']=='horse')
    horse._case(selected_horse['case'],selected_horse['native_payload'],now)
    history=common.history(manifest,env,key=key,now=clock())
    source_proof.update(core.bind_source_history(admitted,source_proof,history))
    assets=common.static_cache(history,key=key,now=clock());now=clock()
    midnight=now.astimezone(C.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    plan=core.prepare_plan(manifest,admitted,now=now,expires_at=min(now+timedelta(hours=1),midnight),static_cache=assets)
    body=core.marker_body(manifest,env,admitted,history,plan,now=now)
    source=root/'source'
    directory=root.with_name(root.name+'.browser')
    journal=dict(schema=core.JOURNAL_V2 if manifest['schema']==core.SCHEMA_V2 else core.JOURNAL,state='RESERVED',manifest=deepcopy(manifest),manifest_sha256=digest(manifest),
        workflow_run_id=env['run_id'],code_sha=env['head_sha'],execution_day=manifest['execution_day'],
        epoch_started_at=now.isoformat(),completed_at=now.isoformat(),maximum_requests=32,
        forecast_identity=admitted['forecast_identity'],native_source_proof=source_proof,
        prior_history={k:v for k,v in history.items() if k not in ('bodies','receipts','runs')},
        plan_sha256=digest(plan),once_body=body,once_proof=None,browser_index=None,browser_reserved_upper_bound=30,
        attempts=[],captures=[],direct_captures=[],observations=[],capture_inventory=[],capture_directory_present=False,
        raw_retention_complete=False,source_requests_actual=None,source_request_upper_bound=32)
    def persist():save(source/'collection.enc',_seal(journal,env,key),replace=(source/'collection.enc').exists())
    plan_cipher=_seal(plan,env,key);reservation_cipher=_seal(journal,env,key);retained={}
    if manifest['schema']==core.SCHEMA_V2:
        retained=seal_retained_forecasts(admitted,env,key)
        _source_capacity(retained,plan_cipher,reservation_cipher,core.issue_marker(body,key))
    _wire_window(plan,clock())
    root.mkdir(mode=0o700);source.mkdir(mode=0o700)
    for name,cipher in retained.items():_write(source/name,cipher)
    _write(source/'reservation.enc',reservation_cipher);_write(source/'plan.enc',plan_cipher);persist()
    index=None;process_finished=False;browser_count=None;observations=[];captures=[]
    try:
        once=core.reserve(body,key,transport,now=clock());raw=once.pop('_ciphertext');_write(source/'once.enc',raw)
        journal['once_proof']=once;persist();_wire_window(plan,clock())
        def diagnostic(value):journal['browser_process_diagnostic']=value;persist()
        try:
            index=browser(plan,directory,diagnostic_sink=diagnostic);process_finished=True
        finally:
            if index is None and (directory/'capture-index.json').exists():
                index=read_json_bytes(C._safe_file(directory,'capture-index.json',4*1024*1024))
            journal['browser_index']=index;persist()
        finished=clock();recovery.no_known_denial(index)
        C._index_header(index,plan['cases'],started=now,now=finished,remaining=30)
        found,states,originals=C.browser_sources(index,directory,plan['cases'],started=now,now=finished,remaining=30)
        need(process_finished,'BROWSER_PROCESS_INCOMPLETE');browser_count=index['actual_request_count']
        _wire_window(plan,clock())
        captures.extend(originals)
        native_by_sport={i['case']['sport']:i['native_payload'] for i in admitted['cases']}
        for sport,race,capture in found:
            parsed=C._parse(capture,native_by_sport[sport],sport,now=clock(),allow_order_only=True)
            observations.append(parsed)
        # The browser receives 30 of the global 32 reservations. JRA can use
        # only the remaining two, and only after a known completed UI process.
        direct=dict(epoch_started_at=now.isoformat(),execution_day=manifest['execution_day'],attempts=journal['attempts'],captures=journal['direct_captures'])
        budget=C.Budget(32,direct,persist,clock,sleeper,_recording_opener(opener,directory,journal,clock,persist,plan));budget.used=browser_count
        budget.last=finished;budget.last_mono=time.monotonic()
        def guarded_get(url):
            _wire_window(plan,clock());answer=budget.get(url);_wire_window(plan,clock())
            if answer is not None:
                row=journal['direct_wire_retention'][-1]
                answer['metadata'].update(fetched_at=row['request_started_at'],response_received_at=row['response_received_at'])
                persist()
            return answer
        selected=next(i for i in admitted['cases'] if i['case']['sport']=='horse')
        card=guarded_get(selected['case']['route']['card_url'])
        if card is not None:
            target=horse.discover_result(selected['case'],selected['native_payload'],card,now=clock())
            if target is not None:
                result=guarded_get(target)
                if result is not None:
                    observations.append(horse.bind_result(selected['case'],selected['native_payload'],card,result,now=clock()))
                    captures.append(result)
        # The fresh card is discovery evidence retained in the encrypted source
        # journal. The existing RESULT schema admits only parser-used captures.
        recovery.no_known_denial(direct)
    except Exception as exc:
        code=str(exc);journal['failure_code']=code if re.fullmatch(r'(?:ALL_MODEL_[A-Z_]+|MANUAL_OFFICIAL_[A-Z_]+)',code) else 'SOURCE_OPERATION_REJECTED'
    finally:
        journal['observations']=observations;journal['captures']=captures or journal['captures']
        items,complete=common.inventory(directory,source,env,key=key)
        complete=complete and all(row['raw_body_complete'] is True for row in journal.get('direct_wire_retention',[]))
        journal.update(capture_inventory=items,raw_retention_complete=complete,capture_directory_present=directory.is_dir(),
            completed_at=clock().isoformat(),state='CAPTURE_RETAINED')
        files=common._files({p.name:p.read_bytes() for p in source.iterdir()},items,env,key)
        known=process_finished and complete and index is not None and _browser_known(index,files,plan,started=now,finished=clock())
        direct_known=_direct_known(journal,files,plan)
        if not direct_known:journal['raw_retention_complete']=False
        if known and direct_known:journal['source_requests_actual']=index['actual_request_count']+len(journal['attempts'])
        persist()
    ready=False
    if observations and journal['raw_retention_complete'] and journal['source_requests_actual'] is not None and not journal.get('failure_code'):
        generated=clock();_wire_window(plan,generated)
        payload=results.build_result_payload(captures,observations,run_id=env['run_id'],code_sha=env['head_sha'],generated_at=generated,
            day_jst=manifest['target_event_day'],frozen_native_payloads=admitted['natives'],allow_order_only=True)
        cipher=results.seal_results(payload,round_no=core.RESULT_ROUND,frozen_native_payloads=admitted['natives'],key=key,allow_order_only=True)
        header=forecast_header(cipher)
        need(header['run_id']==str(env['run_id']) and header['round_no']==core.RESULT_ROUND and
            open_forecasts(cipher,key=key)==payload,'LOCAL_RESULT_REPLAY')
        result=root/'result';result.mkdir(mode=0o700);_write(result/'results.enc',cipher)
        journal.update(result_cipher_sha256=sha256(cipher).hexdigest(),result_payload_sha256=digest(payload));persist();ready=True
    status=_status(journal,env,ready=ready);save(root/'counts.json',future.wire(status));return status


def source_archive(raw,actual,env,*,now,key):
    """Read actual private ZIP and retain UNKNOWN honestly, including no directory."""
    need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE and actual.get('expired') is False and
        actual.get('name')=='official-future-result-capture-'+str(env['run_id']) and actual.get('size_in_bytes')==len(raw) and
        actual.get('digest')=='sha256:'+sha256(raw).hexdigest(),'SOURCE_ACTUAL_BYTES')
    run=actual.get('workflow_run',{})
    need(run.get('id')==env['run_id'] and run.get('head_sha')==env['head_sha'] and
        all(run.get(k)==1416489937 for k in ('repository_id','head_repository_id')) and
        core.clock(actual['created_at'])<=now<core.clock(actual['expires_at']),'SOURCE_ACTUAL_IDENTITY_CLOCK')
    source={};used=0
    need(raw.startswith(b'PK\x03\x04') and raw[-22:-18]==b'PK\x05\x06' and raw[-2:]==b'\0\0','SOURCE_ZIP_ENVELOPE')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist();limit=157 if any(e.filename=='forecast-batches.enc' for e in entries) else 132
        need(3<=len(entries)<=limit and not archive.comment,'SOURCE_ZIP_BOUND')
        for entry in entries:
            name=entry.filename
            need(name==entry.orig_filename and name not in source and re.fullmatch(
                r'(?:reservation|plan|collection|once|forecast-batches|forecast-original-[0-9]{3}|raw-[0-9]{3}-[a-f0-9]{64})\.enc',name) and
                stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and not entry.flag_bits&0x41 and
                entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and 0<entry.file_size<=MAX_WIRE,'SOURCE_ZIP_MEMBER')
            used+=entry.file_size;need(used<=MAX_ARCHIVE,'SOURCE_ZIP_TOTAL')
            with archive.open(entry) as member:source[name]=member.read(MAX_WIRE+1)
            need(len(source[name])==entry.file_size,'SOURCE_ZIP_SIZE')
    journal=_open(source['collection.enc'],env,key);reservation=_open(source['reservation.enc'],env,key)
    expected_schema=core.JOURNAL_V2 if journal['manifest'].get('schema')==core.SCHEMA_V2 else core.JOURNAL
    need(journal['schema']==reservation['schema']==expected_schema and reservation['state']=='RESERVED' and
        journal['state']=='CAPTURE_RETAINED' and journal['manifest_sha256']==digest(journal['manifest']) and
        type(journal['maximum_requests']) is int and journal['maximum_requests']==32 and
        type(journal['browser_reserved_upper_bound']) is int and journal['browser_reserved_upper_bound']==30 and
        journal['workflow_run_id']==env['run_id'] and journal['code_sha']==env['head_sha'] and
        all(journal[k]==reservation[k] for k in ('manifest','forecast_identity','native_source_proof','prior_history','plan_sha256','once_body')) and
        core.clock(journal['epoch_started_at'])<=core.clock(journal['completed_at'])<=min(now,core.clock(actual['created_at'])+timedelta(seconds=1)),
        'SOURCE_JOURNAL_BINDING')
    core.validate_manifest(journal['manifest'],now=core.clock(journal['epoch_started_at']))
    plan=_open(source['plan.enc'],env,key);need(digest(plan)==journal['plan_sha256']==journal['once_body']['plan_sha256'],'SOURCE_PLAN_BINDING')
    need(plan.get('schema')=='RACE_AI_OFFICIAL_RESULT_BROWSER_PLAN_V1' and plan.get('request_budget')==30 and
        plan.get('not_before')==journal['epoch_started_at']==journal['once_body']['issued_at'] and
        plan.get('not_after')==journal['once_body']['expires_at'],'SOURCE_ORIGINAL_WINDOW')
    need(journal['once_body']['manifest_sha256']==digest(journal['manifest']) and
        journal['once_body']['forecast_identity_sha256']==digest(journal['forecast_identity']) and
        journal['once_body']['history_sha256']==digest(journal['prior_history']) and
        journal['once_body']['target']==dict(run_id=env['run_id'],head_sha=env['head_sha'],run_attempt=1),'SOURCE_ONCE_BINDING')
    files=common._files(source,journal['capture_inventory'],env,key)
    if 'capture-index.json' in files:
        need(read_json_bytes(files['capture-index.json'])==journal['browser_index'],'SOURCE_ORIGINAL_INDEX')
    complete=journal['raw_retention_complete'];need(type(complete) is bool and type(journal['capture_directory_present']) is bool and
        (not complete or journal['capture_directory_present'] and all(i['status']=='RETAINED' for i in journal['capture_inventory'])),
        'SOURCE_RETENTION_TRUTH')
    count=journal['source_requests_actual'];need(count is None or type(count) is int and 0<=count<=32 and complete and
        _browser_known(journal['browser_index'],files,plan,started=core.clock(journal['epoch_started_at']),finished=core.clock(journal['completed_at'])) and
        count==journal['browser_index']['actual_request_count']+len(journal['attempts']) and
        _direct_known(journal,files,plan),'SOURCE_COUNT_TRUTH')
    expected={'reservation.enc','plan.enc','collection.enc'}|{i['cipher_file'] for i in journal['capture_inventory'] if i['status']=='RETAINED'}
    if journal['manifest']['schema']==core.SCHEMA_V2:
        replayed,_=replay_retained_forecasts(journal,source,env,now=now,key=key)
        expected|={'forecast-batches.enc',*replayed['_replay_member_names']}
    if 'once.enc' in source:
        audit=core.validate_marker(source['once.enc'],journal['once_body'],key,now=core.clock(journal['epoch_started_at']))
        need(set(journal['once_proof'])==set(audit)|{'commit_sha'} and all(journal['once_proof'][k]==v for k,v in audit.items()),'SOURCE_MARKER_PROOF')
        expected.add('once.enc')
    need(set(source)==expected,'SOURCE_EXACT_INVENTORY')
    return journal,source,files


def _verify_marker(journal,source,key,transport):
    if 'once.enc' not in source:return False
    need('once.enc' in source and transport.read_file(journal['once_proof']['commit_sha'],core.PATH,MAX_WIRE)==source['once.enc'] and
        transport.read_file(transport.head(),core.PATH,MAX_WIRE)==source['once.enc'],'INDEPENDENT_RESULT_MARKER_READBACK')
    return True


def readback_source(ident,root,env,manifest,*,marker_transport=None,clock=utc_now):
    key=state_key('production');actual=future.metadata(ident);raw=future.gh('actions/artifacts/'+str(ident)+'/zip')
    journal,source,_=source_archive(raw,actual,env,now=clock(),key=key)
    need(journal['manifest']==manifest and all((root/'source'/name).read_bytes()==body for name,body in source.items()),'ACTUAL_LOCAL_SOURCE')
    verified=_verify_marker(journal,source,key,marker_transport or core.MarkerTransport())
    return dict(_status(journal,env),state='FUTURE_RESULT_SOURCE_ACTUAL_ARTIFACT_VERIFIED',source_artifact_id=ident,
        source_artifact_digest=actual['digest'],independent_source_capture_receipt_verified=True,durable_source_reservation_verified=verified)


def readback(ident,source_id,root,env,manifest,*,marker_transport=None,clock=utc_now):
    key=state_key('production');now=clock();transport=marker_transport or core.MarkerTransport()
    actual=future.metadata(source_id);source_raw=future.gh('actions/artifacts/'+str(source_id)+'/zip')
    journal,source,files=source_archive(source_raw,actual,env,now=now,key=key)
    need(journal['manifest']==manifest and all((root/'source'/name).read_bytes()==body for name,body in source.items()),'ACTUAL_LOCAL_SOURCE')
    need(journal['raw_retention_complete'] is True and type(journal['source_requests_actual']) is int and
        not journal.get('failure_code'),'RESULT_SOURCE_KNOWN_COMPLETE')
    recovery.no_known_denial(journal)
    need(_verify_marker(journal,source,key,transport),'ACTUAL_RESULT_MARKER_REQUIRED');admitted,_=_admit(manifest,now=now,key=key,transport=transport,
        manifest_at=journal['epoch_started_at'])
    need(admitted['forecast_identity']==journal['forecast_identity'],'ORIGINAL_FORECAST_REPLAY')
    replay_capture(journal,files,admitted,_open(source['plan.enc'],env,key))
    result_meta=future.metadata(ident);result_raw=future.gh('actions/artifacts/'+str(ident)+'/zip')
    verified=results.observations_from_official_result_artifact(result_raw,result_meta,now=now,expected_run_id=env['run_id'],
        expected_head_sha=env['head_sha'],frozen_native_payloads=admitted['natives'],key=key,allow_order_only=True)
    cipher=results._cipher(result_raw)
    need(result_meta['name']==f'all-existing-official-results-{env["run_id"]}-{core.RESULT_ROUND}' and
        cipher==(root/'result/results.enc').read_bytes() and sha256(cipher).hexdigest()==journal['result_cipher_sha256'] and
        verified['receipt']['original_payload_sha256']==journal['result_payload_sha256'] and
        sorted(digest(r) for r in verified['observations'])==sorted(digest(r) for r in journal['observations']),
        'ACTUAL_RESULT_REPLAY')
    return dict(_status(journal,env,ready=True),state='FUTURE_RESULTS_ACTUAL_ARTIFACT_VERIFIED',artifact_id=ident,
        artifact_digest=result_meta['digest'],source_artifact_id=source_id,source_artifact_digest=actual['digest'],
        independent_result_artifact_receipt_verified=True,independent_source_capture_receipt_verified=True,
        durable_source_reservation_verified=True)


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out-dir',required=True)
    p.add_argument('--readback-source',type=int);p.add_argument('--readback-result',type=int);args=p.parse_args(argv)
    need(all(n is None or n>0 for n in (args.readback_source,args.readback_result)) and
        (args.readback_result is None or args.readback_source is not None),'READBACK_IDS')
    env=common.environment();manifest=read_json_bytes(_read(Path(args.input),65536));root=future.output_path(args.out_dir,env)
    if args.readback_result:
        need(args.readback_source is not None,'SOURCE_ARTIFACT_REQUIRED');status=readback(args.readback_result,args.readback_source,root,env,manifest)
    elif args.readback_source:status=readback_source(args.readback_source,root,env,manifest)
    else:status=generate(core.validate_manifest(manifest,now=utc_now()),root,env)
    proof=root.with_name(root.name+'.status.json');save(proof,future.wire(status),replace=proof.exists())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
            for name,value in (('ready',str(status['ready']).lower()),('result_artifact_name',status.get('result_artifact_name') or ''),
                ('source_artifact_name',status['source_artifact_name']),('result_path',str(root/'result') if status['ready'] else ''),
                ('source_path',str(root/'source'))):stream.write(name+'='+value+'\n')
    print(json.dumps(status,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
