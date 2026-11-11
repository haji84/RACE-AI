"""Restore authenticated first receipts across existing Actions runs.

No source requests, new models, forecast regeneration or production promotion.
The caller supplies authenticated GitHub API reads. Incomplete history stops
new forecasts; it is never silently treated as an empty database.
"""
from datetime import datetime,timedelta,timezone
from contextlib import contextmanager
import copy,hashlib,io,json,re,zipfile
from .frozen_day_cycle import need,ts,read_p1,read_p0,archive_json,original_archive_bound
from .first_receipt_continuity import first_receipt_rows,latest_result_observations
from .repeated_cycle import matches as artifact_matches
from .saved_view_run import display_only_run
from .boat_private_original_archive import open_original_zip
from .boat_owner_source_identity import owner_run_origin
BRANCH='feat/four-sport-forecast-audit-view-20261022'
WORKFLOW=405276784
JST=timezone(timedelta(hours=9))
# Legacy continuity checkpoints can contain nested parent archives. Keep their
# authenticated intake bounded while preserving compatibility with that history.
CONTINUITY_ARCHIVE_MAX_BYTES=128*1024*1024

def artifact_pages(get, run_id):
    """Read a complete, duplicate-free artifact listing, including page 2+."""
    need(type(run_id) is int and run_id > 0, 'invalid artifact run')
    # Only an explicitly declared capability may replace live enumeration.
    # Dynamic __getattr__ proxies are ordinary transports, not archive stores.
    archived=vars(get).get('archived_artifact_pages') if hasattr(get,'__dict__') else None
    declared=getattr(type(get),'archived_artifact_pages',None)
    if archived is None and callable(declared):archived=lambda ident:declared(get,ident)
    if callable(archived):
        rows=archived(run_id)
        if rows is not None:
            need(type(rows) is list and len({r['id'] for r in rows})==len(rows),'ARTIFACT_PAGINATION_INCOMPLETE')
            return rows
    found=[];seen=set();page=1;total=None
    while True:
        suffix='' if page == 1 else f'&page={page}'
        response=json.loads(get(f'actions/runs/{run_id}/artifacts?per_page=100{suffix}'))
        rows=response.get('artifacts')
        need(type(rows) is list and len(rows)<=100,'ARTIFACT_PAGINATION_INCOMPLETE')
        count=response.get('total_count',len(rows))
        need(type(count) is int and count>=0 and (total is None or count==total),
             'ARTIFACT_PAGINATION_CHANGED')
        total=count
        for row in rows:
            ident=row.get('id') if isinstance(row,dict) else None
            need(type(ident) is int and ident>0 and ident not in seen,
                 'ARTIFACT_PAGINATION_DUPLICATE')
            seen.add(ident);found.append(row)
        need(len(found)<=total,'ARTIFACT_PAGINATION_CHANGED')
        if len(found)==total:return found
        need(len(rows)==100,'ARTIFACT_PAGINATION_INCOMPLETE')
        page+=1

@contextmanager
def _verified_zip(raw, meta, expected_name):
    need(original_archive_bound(raw,CONTINUITY_ARCHIVE_MAX_BYTES),'bounded cycle archive')
    need(meta.get('expired') is False and meta.get('name')==expected_name and
         meta.get('workflow_run',{}).get('head_repository_id')==1416489937,
         'foreign/expired continuity archive')
    need(meta.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest(),
         'continuity archive hash mismatch')
    ts(meta['created_at'])
    def members(archive):
        need(len(archive.namelist())==len(set(archive.namelist())),'duplicate continuity member')
        need(sum(info.file_size for info in archive.infolist())<=512*1024*1024,
             'oversized continuity members')
        need(archive.testzip() is None,'continuity member CRC mismatch')
    # Preserve legacy rejection reasons before the shared opener's stricter
    # generic ZIP checks. Encrypted native members are read only after AEAD.
    with zipfile.ZipFile(io.BytesIO(raw)) as outer:
        encrypted='private-original.enc' in outer.namelist()
        if not encrypted:members(outer)
    with open_original_zip(raw,meta,expected_kind='CONTINUITY',
                           max_plain_zip_bytes=CONTINUITY_ARCHIVE_MAX_BYTES) as archive:
        if encrypted:members(archive)
        yield archive

def _wait(value):
    if value is None:return None
    need(type(value) is dict and set(value)=={'state','reason','retry_at','http_status','attempts'},
         'source wait shape')
    need(value['state'] in ('RATE_LIMIT_WAIT','TRANSIENT_SOURCE_WAIT','AUTHORIZATION_WAIT',
                           'WAITING_PUBLICATION','SOURCE_REVIEW_WAIT'), 'source wait state')
    need(isinstance(value['reason'],str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',value['reason']),
         'source wait reason')
    need(type(value['attempts']) is int and value['attempts']>=1,'source wait attempts')
    need(value['http_status'] is None or type(value['http_status']) is int and
         100<=value['http_status']<=599,'source wait HTTP status')
    if value['retry_at'] is not None:ts(value['retry_at'])
    return copy.deepcopy(value)

def authenticated_source_control(raw, meta, *, expected_run=None, now=None):
    """Recover source waits/counters from an independently stored final checkpoint.

    Merely trusting a successful run conclusion loses source failures. Both the
    artifact bytes and its internal session hash are checked before inheritance.
    """
    run=meta.get('workflow_run',{}).get('id')
    need(type(run) is int and run>0 and (expected_run is None or run==expected_run),
         'continuity run identity mismatch')
    with _verified_zip(raw,meta,f'race-cycle-continuity-{run}') as archive:
        member=('repeat-session.json' if 'repeat-session.json' in archive.namelist() else
                'bootstrap-source-control.json' if 'bootstrap-source-control.json' in archive.namelist() else None)
        if member is None:return None
        info=archive.getinfo(member)
        need(info.file_size<=1024*1024,'oversized source session')
        state=json.loads(archive.read(info))
    claimed=state.pop('session_sha256' if member=='repeat-session.json' else 'source_control_sha256',None)
    need(claimed==hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':'),
         ensure_ascii=False,allow_nan=False).encode()).hexdigest(),'source session hash mismatch')
    need(state.get('schema') in ('RACE_AI_BOUNDED_REPEAT_V1','RACE_AI_CONTINUOUS_REPEAT_V2',
                                'RACE_AI_BOOTSTRAP_SOURCE_CONTROL_V1') and
         state.get('run_id')==run,'source session identity')
    datetime.fromisoformat(state['day_jst']+'T00:00:00+09:00')
    for key in ('requests_used','completed_round'):
        need(type(state.get(key)) is int and state[key]>=0,'source session count')
    prepared=state.get('prepared_round')
    need(prepared is None or type(prepared) is int and prepared==state['completed_round']+1,
         'source session prepared round')
    lifetime_requests=state.get('lifetime_requests',state['requests_used'])
    lifetime_rounds=state.get('lifetime_completed_rounds',state['completed_round'])
    need(type(lifetime_requests) is int and lifetime_requests>=state['requests_used'] and
         type(lifetime_rounds) is int and lifetime_rounds>=state['completed_round'],
         'source lifetime count')
    for key,total,used in (('lifetime_requests_base',lifetime_requests,state['requests_used']),
                           ('lifetime_completed_rounds_base',lifetime_rounds,state['completed_round'])):
        if key in state:
            need(type(state[key]) is int and state[key]>=0 and total==state[key]+used,
                 'source lifetime count')
    wait=_wait(state.get('source_wait'));reason=(state.get('halted_reason') or
        state.get('previous_halted_reason') or state.get('control_reason'))
    need(reason is None or isinstance(reason,str) and
         re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',reason),'source stop reason')
    normal=reason in (None,'BOUNDED_SESSION_END','MAX_ROUNDS_REACHED',
                      'SESSION_SOURCE_BUDGET_EXHAUSTED','SOURCE_BUDGET_EXHAUSTED','ROUND_SOURCE_BUDGET_EXHAUSTED',
                      'DAY_CHANGED','DAY_HANDOFF','WORKER_HANDOFF')
    if not normal:
        from .source_retry_policy import plan_http_wait
        matched=re.fullmatch(r'SOURCE_HTTP_(\d{3})_NO_RETRY',reason)
        status=int(matched[1]) if matched else None
        if status in (401,403):
            wait=plan_http_wait(status,{},ts(meta['created_at']))
        elif status==429:
            if wait is None or wait['state']!='RATE_LIMIT_WAIT' or wait['http_status']!=429:
                # A legacy denial has no recorded Retry-After. Its fallback
                # must remain tied to the authenticated receipt, not slide on
                # every recovery/supervisor poll.
                wait=plan_http_wait(status,{},ts(meta['created_at']))
        else:
            wait=dict(state='SOURCE_REVIEW_WAIT',reason=reason,retry_at=None,
                      http_status=status,attempts=1)
    # A known temporary HTTP wait is not an unqualified legacy hard halt. Keep
    # the original reason separately so this is an auditable policy migration.
    hard_reason=None if normal or wait and wait['retry_at'] is not None else reason
    return dict(source_wait=wait,previous_run_id=run,day_jst=state['day_jst'],
        previous_session_requests=state['requests_used'],
        completed_round=state['completed_round'],prepared_round=prepared,
        lifetime_requests=lifetime_requests,lifetime_completed_rounds=lifetime_rounds,
        previous_halted_reason=hard_reason,previous_stop_reason=reason,
        receipt={k:copy.deepcopy(meta[k]) for k in ('id','digest','created_at')})

def _previous_runs(get,*,current_run,earliest=None):
    """Newest first; source control is allowed to outlive a race-day window."""
    seen=set();page=1
    while True:
        response=json.loads(get(f'actions/workflows/{WORKFLOW}/runs?per_page=100&page={page}'))
        runs=response['workflow_runs'];need(isinstance(runs,list),'invalid run page')
        for run in sorted(runs,key=lambda r:(ts(r['created_at']),r['id']),reverse=True):
            need(run['id'] not in seen,'duplicate run page');seen.add(run['id'])
            at=ts(run['created_at'])
            if earliest is not None and at<earliest:continue
            if run['id']==current_run:continue
            if not owner_run_origin(run.get('head_branch'),run.get('event')):continue
            if display_only_run(run):continue
            # Queued successors are not prior executions. An earlier in-flight
            # writer is unresolved and cannot safely be assumed to have no receipt.
            if run['id']>current_run:continue
            need(run['status']=='completed','UNRESOLVED_PREVIOUS_RUN')
            yield run
        if len(runs)<100 or earliest is not None and any(ts(x['created_at'])<earliest for x in runs):return
        page+=1

def day_runs(get,day,*,current_run):
    start=datetime.fromisoformat(day+'T00:00:00+09:00');end=start+timedelta(days=1)
    lookback=start-timedelta(hours=6)
    selected=[run for run in _previous_runs(get,current_run=current_run,earliest=lookback)
              if ts(run['created_at'])<end]
    return sorted(selected,key=lambda x:(ts(x['created_at']),x['id']))

def result_archive(raw,meta,day,*,key=None):
    need(original_archive_bound(raw,32*1024*1024),'bounded result archive')
    run=meta['workflow_run']['id']
    need(meta.get('expired') is False and artifact_matches(meta.get('name'),f'race-existing-cycle-{run}') and
         meta['workflow_run'].get('head_repository_id')==1416489937,'foreign/expired cycle archive')
    need(meta.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest(),'cycle archive hash mismatch')
    with open_original_zip(raw,meta,expected_kind='RESULT',key=key,max_plain_zip_bytes=32*1024*1024) as z:
        member='official-result-observations.json'
        need(len(z.namelist())==len(set(z.namelist())) and member in z.namelist(),'cycle member missing/duplicate')
        need(z.getinfo(member).file_size<=16*1024*1024,'oversized result journal')
        items=json.loads(z.read(member))
    need(isinstance(items,list) and len(items)<=20000,'bounded observation journal')
    for row in items:
        need(row['race_id'].startswith(day.replace('-','')+'-'),'foreign result day')
        ts(row['captured_at'])
    return items

def _result_day(raw,meta,*,key=None):
    """Determine an authenticated payload day before filtering a lookback run."""
    run=meta['workflow_run']['id']
    need(original_archive_bound(raw,32*1024*1024) and meta.get('expired') is False and
         artifact_matches(meta.get('name'),f'race-existing-cycle-{run}') and
         meta['workflow_run'].get('head_repository_id')==1416489937 and
         meta.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest(),'cycle archive identity')
    with open_original_zip(raw,meta,expected_kind='RESULT',key=key,max_plain_zip_bytes=32*1024*1024) as archive:
        need(len(archive.namelist())==len(set(archive.namelist())),'duplicate cycle member')
        if 'status.json' in archive.namelist():
            need(archive.getinfo('status.json').file_size<=16*1024*1024,'oversized cycle report')
            report=json.loads(archive.read('status.json'))
            if report.get('day_jst') is not None:return _day(report['day_jst'])
        need('official-result-observations.json' in archive.namelist(),'cycle observations missing')
        need(archive.getinfo('official-result-observations.json').file_size<=16*1024*1024,
             'oversized result journal')
        rows=json.loads(archive.read('official-result-observations.json'))
    need(type(rows) is list,'result observation list')
    days={_race_day(row['race_id']) for row in rows}
    need(len(days)<=1,'mixed result days')
    return next(iter(days),ts(meta['created_at']).astimezone(JST).date().isoformat())

def _day(value):
    need(isinstance(value,str) and re.fullmatch(r'\d{4}-\d\d-\d\d',value),'event day format')
    datetime.fromisoformat(value+'T00:00:00+09:00')
    return value

def _race_day(value):
    need(isinstance(value,str) and re.fullmatch(r'\d{8}-\d\d-\d\d',value),'race day identity')
    return _day(value[:4]+'-'+value[4:6]+'-'+value[6:8])

def previous_source_control(get,day,*,current_run):
    """Get the newest authenticated final source checkpoint, even across midnight."""
    for run in _previous_runs(get,current_run=current_run):
        candidates=[item for item in artifact_pages(get,run['id'])
                    if item.get('name')==f'race-cycle-continuity-{run["id"]}']
        need(len(candidates)<=1,'duplicate final continuity')
        if not candidates:continue
        listed=candidates[0];meta=json.loads(get(f'actions/artifacts/{listed["id"]}'))
        need(meta.get('id')==listed['id'],'continuity artifact ID mismatch')
        control=authenticated_source_control(get(f'actions/artifacts/{listed["id"]}/zip'),
                                              meta,expected_run=run['id'])
        if control is not None:return control
    return None

def p0_original_or_empty(raw,meta,day):
    """Authenticate older failed attempts, without manufacturing forecasts."""
    run=meta['workflow_run']['id']
    doc,_=archive_json(raw,meta,'forecasts.json',f'boat-p0-existing-{run}')
    need(doc.get('schema')=='RACE_AI_EXISTING_P0_DAY_V1' and doc.get('day_jst')==day,
         'foreign P0 attempt schema/day')
    if (doc.get('predictions')==[] and doc.get('race_count') in (None,0)
            and doc.get('model_forecast_count') in (None,0)
            and doc.get('actual_purchases') is False):
        return doc,[]
    return read_p0(raw,meta,expected_day=day)

def _retain_original(path,raw):
    if path.exists():
        need(path.read_bytes()==raw,'ORIGINAL_ARCHIVE_LOCAL_BYTES_CONFLICT')
    else:
        with path.open('xb') as stream:stream.write(raw)

def validate_document_history(document,proofs):
    """Match new history evidence to independently read parent archives."""
    evidence=[bundle['history_evidence'] for bundle in document.get('observed_pairwise_p1_bundles',[])
              if 'history_evidence' in bundle]
    if not evidence:return
    from .observed_result_history import validate_history_proofs
    for item in evidence:validate_history_proofs(item,proofs)

def recover(get,day,*,current_run,out,clock=None,video_receipt_verifier=None):
    """Read every same-day P1 original and every saved result journal, no writes upstream."""
    rows=[];observations=[];receipts=[];scanned=[];index_entries=[]
    learning_shadows=[];learning_context=None;training_proofs={}
    history_context=None;history_proofs={};history_documents=[]
    entry_history_cache=None;entry_history_order=None;entry_history_rejections=0
    clock=clock or (lambda:datetime.now(timezone.utc))
    if video_receipt_verifier is None:
        from .boat_video_archive import VideoContextArchiveReader
        video_receipt_verifier=VideoContextArchiveReader(get,clock=clock).verify
    video_context_artifact_ids=set()
    video_shadow_rejections=[]
    venue_research_refs=[];venue_research_ref_rejections=0
    from .observed_result_history import context_from_result_archive as history_from_archive,history_proof
    source_control=previous_source_control(get,day,current_run=current_run)
    from .observed_weight_learning import context_from_result_archive,merge_shadow_rows,training_proof,attach_snapshots
    out.mkdir(parents=True,exist_ok=True)
    for run in day_runs(get,day,current_run=current_run):
        artifacts=artifact_pages(get,run['id'])
        scanned.append(run['id'])
        for listed in artifacts:
            private_name=listed.get('name')
            private_prefix=next((prefix for prefix in ('boat-venue-research-p1-', 'all-existing-model-pairs-')
                                 if type(private_name) is str and private_name.startswith(prefix)),None)
            if private_prefix is not None:
                # Discover saved handles even when the worker stopped before
                # publishing its result report. No ZIP, key or admission here.
                try:
                    need(re.fullmatch(re.escape(private_prefix)+str(run['id'])+'-[1-9][0-9]*',private_name),
                         'PRIVATE_VENUE_ARTIFACT_NAME_INVALID')
                    ident=listed['id'];need(type(ident) is int and ident>0,'PRIVATE_VENUE_ARTIFACT_ID_INVALID')
                    meta=json.loads(get(f'actions/artifacts/{ident}'))
                    need(type(meta) is dict and type(meta.get('id')) is int and meta['id']==ident and
                         meta.get('name')==private_name and meta.get('expired') is False and
                         type(meta.get('size_in_bytes')) is int and 0<meta['size_in_bytes']<=64*1024*1024,
                         'PRIVATE_VENUE_ARTIFACT_METADATA_INVALID')
                    workflow=meta.get('workflow_run')
                    need(type(workflow) is dict and type(workflow.get('id')) is int and workflow['id']==run['id'] and
                         all(type(workflow.get(key)) is int and workflow[key]==1416489937
                             for key in ('repository_id','head_repository_id')) and
                         ('head_sha' not in run or workflow.get('head_sha')==run['head_sha']),
                         'PRIVATE_VENUE_ARTIFACT_RUN_INVALID')
                    from .boat_venue_research_receipt import validate_research_refs
                    handles=validate_research_refs([dict(artifact_id=ident,run_id=workflow['id'],
                        head_sha=workflow.get('head_sha'),digest=meta.get('digest'))])
                    need(type(meta.get('created_at')) is str and len(meta['created_at'])<=64,
                         'PRIVATE_VENUE_ARTIFACT_CLOCK_INVALID')
                    saved=ts(meta['created_at']);observed=clock()
                    need(isinstance(observed,datetime) and observed.utcoffset() is not None and saved<=observed,
                         'PRIVATE_VENUE_ARTIFACT_CLOCK_INVALID')
                    if saved.astimezone(JST).date().isoformat()==day:
                        venue_research_refs=validate_research_refs(venue_research_refs+handles)
                except Exception:venue_research_ref_rejections+=1
                continue
            prefix=('boat-p0-existing-' if artifact_matches(listed['name'],f'boat-p0-existing-{run["id"]}') else
                    'boat-national-cutoff-' if artifact_matches(listed['name'],f'boat-national-cutoff-{run["id"]}') else
                    'race-existing-cycle-' if artifact_matches(listed['name'],f'race-existing-cycle-{run["id"]}') else
                    'race-cycle-continuity-' if listed['name']==f'race-cycle-continuity-{run["id"]}' else None)
            if prefix is None:continue
            ident=listed['id'];meta=json.loads(get(f'actions/artifacts/{ident}'))
            need(meta.get('id')==ident and meta['workflow_run']['id']==run['id'],'artifact/run identity mismatch')
            raw=get(f'actions/artifacts/{ident}/zip')
            if prefix=='race-cycle-continuity-':
                control=authenticated_source_control(raw,meta,expected_run=run['id'])
                if control is not None and (source_control is None or
                        ts(meta['created_at'])>ts(source_control['receipt']['created_at'])):
                    source_control=control
                _retain_original(out/f'source-control-{ident}.zip',raw)
                continue
            if prefix in ('boat-national-cutoff-','boat-p0-existing-'):
                if prefix=='boat-p0-existing-':
                    unfiltered,_=archive_json(raw,meta,'forecasts.json',f'boat-p0-existing-{run["id"]}')
                    payload_day=_day(unfiltered.get('day_jst'))
                    doc,items=p0_original_or_empty(raw,meta,payload_day)
                else:
                    doc,items=read_p1(raw,meta)
                    days={_race_day(row['race_id']) for row in items}
                    need(len(days)<=1,'mixed forecast days')
                    payload_day=next(iter(days),_day(doc['day_jst']) if doc.get('day_jst') else
                        ts(doc.get('observed_at',meta['created_at'])).astimezone(JST).date().isoformat())
                if payload_day!=day:continue
                need(all(x['race_id'].startswith(day.replace('-','')+'-') for x in items),'foreign forecast day')
                items=attach_snapshots(doc,items)
                rows+=items
                if prefix=='boat-national-cutoff-':
                    from .boat_entry_source_collection import optional_cache_from_document
                    candidate_cache,rejection=optional_cache_from_document(doc,day=day,as_of=meta['created_at'])
                    if rejection is not None:entry_history_rejections+=1
                    if candidate_cache is not None:
                        order=(ts(candidate_cache['checked_at']),ts(meta['created_at']),ident)
                        if entry_history_order is None or order>entry_history_order:
                            entry_history_cache=candidate_cache;entry_history_order=order
                    with open_original_zip(raw,meta,expected_kind='P1',max_plain_zip_bytes=32*1024*1024) as archive:
                        body_sha=hashlib.sha256(archive.read('national.json')).hexdigest()
                    from .boat_video_archive import read_optional_video_shadows
                    accepted,rejected=read_optional_video_shadows(doc,meta,items,
                        receipt_verifier=video_receipt_verifier)
                    learning_shadows+=accepted;video_shadow_rejections+=rejected
                    if not rejected:
                        video_context_artifact_ids.update(record['video_receipt']['id']
                            for record in doc.get('learned_pairwise_shadows',[])
                            if record.get('schema')=='RACE_AI_EXISTING_OBSERVED_VIDEO_SHADOW_V1')
                    history_documents.append(doc)
                    for pair in doc.get('paired_forecasts',[]):
                        index_entries.append(dict(race_id=pair['race_id'],cutoff_at=pair['cutoff_at'],run_id=run['id'],artifact_id=ident,server_created_at=meta['created_at'],zip_sha256=hashlib.sha256(raw).hexdigest(),json_sha256=body_sha,bundle_sha256=pair['bundle_sha256']))
                # Preserve original bytes, not reconstructed predictions.
                _retain_original(out/f'original-{ident}.zip',raw)
                receipts.append(meta)
            else:
                payload_day=_result_day(raw,meta)
                # Authentication and schema/day checks precede filtering. The
                # previous evening's legitimate archive is never relabeled.
                day_observations=result_archive(raw,meta,payload_day)
                prior_history=history_from_archive(raw,meta,verified_at=clock().isoformat())
                history_proofs[str(meta['id'])]=history_proof(prior_history)
                if history_context is None or ts(meta['created_at'])>ts(history_context['receipt']['created_at']):
                    history_context=prior_history
                if payload_day==day:observations+=day_observations
                candidate=context_from_result_archive(raw,meta)
                if candidate is not None:
                    training_proofs[str(meta['id'])]=training_proof(candidate)
                    if candidate['training']['schema']=='RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1':
                        video_context_artifact_ids.update(lineage['video_receipt_proof']['id']
                            for lineage in candidate['training']['source_lineage']
                            if lineage.get('video_receipt_proof') is not None)
                # Retain source handles even before enough races support a fit.
                # Their parent result bytes are authenticated above; these IDs
                # are independently read again before any next fit/inference.
                with open_original_zip(raw,meta,expected_kind='RESULT',max_plain_zip_bytes=32*1024*1024) as archive:
                    if 'status.json' in archive.namelist():
                        need(archive.getinfo('status.json').file_size<=16*1024*1024,
                             'oversized cycle report')
                        report=json.loads(archive.read('status.json'))
                        handles=report.get('video_context_artifact_ids',[])
                        need(type(handles) is list and len(handles)<=10000 and
                             all(type(value) is int and value>0 for value in handles) and
                             handles==sorted(set(handles)),'BOAT_VIDEO_ARCHIVE_REJECTED')
                        video_context_artifact_ids.update(handles)
                        if payload_day==day and 'venue_research_artifact_refs' in report:
                            # Handles are independently authenticated/decrypted
                            # by the private scorer before any outcome is admitted.
                            from .boat_venue_research_receipt import validate_research_refs
                            try:
                                venue_research_refs=validate_research_refs(
                                    venue_research_refs+report['venue_research_artifact_refs'])
                            except (ValueError,TypeError):venue_research_ref_rejections+=1
                if payload_day==day and candidate is not None and (learning_context is None or ts(meta['created_at'])>ts(learning_context['receipt']['created_at'])):
                    learning_context=candidate
    from .boat_video_archive import validate_optional_video_training
    learning_shadows,rejected=validate_optional_video_training(learning_shadows,training_proofs)
    video_shadow_rejections+=rejected
    for document in history_documents:validate_document_history(document,history_proofs)
    unique,excluded=first_receipt_rows(rows)
    _,journal=latest_result_observations(observations)
    state=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst=day,rows=unique,
               excluded_repeats=excluded,receipts=receipts,observations=journal,
               scanned_runs=scanned,index_entries=index_entries,complete=True,
               learning_shadows=merge_shadow_rows(learning_shadows),learning_context=learning_context,
               training_proofs=training_proofs,source_control=source_control,
               history_context=history_context,history_proofs=history_proofs,
               entry_observation_history=entry_history_cache,
               entry_observation_history_rejections=entry_history_rejections,
               entry_observation_history_rejection_reason='ENTRY_HISTORY_CACHE_REJECTED' if entry_history_rejections else None)
    if video_context_artifact_ids:
        # IDs are handles for the next invocation to independently re-read;
        # they are not JSON authentication claims or substitute receipt proofs.
        state['video_context_artifact_ids']=sorted(video_context_artifact_ids)
    if video_shadow_rejections:
        state['video_shadow_rejections']=video_shadow_rejections
    if venue_research_refs:state['venue_research_artifact_refs']=venue_research_refs
    if venue_research_ref_rejections:state['venue_research_ref_rejections']=venue_research_ref_rejections
    state['state_sha256']=hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    (out/'continuity.json').write_text(json.dumps(state,ensure_ascii=False))
    return state

def load_state(path,day):
    data=json.loads(path.read_text());digest=data.pop('state_sha256')
    need(digest==hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'recovered state hash mismatch')
    need(data.get('schema')=='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1' and data.get('complete') is True and data.get('day_jst')==day,'recovery missing or wrong day')
    return data

def result_request_budget(session,now):
    """Remaining existing allowance; never mutate or reopen a source session."""
    from .repeated_cycle import SOURCE_LIMIT,ROUND_SOURCE_LIMIT
    from .source_retry_policy import wait_active
    need(type(session) is dict and now.utcoffset() is not None,'result budget session/clock')
    used=session.get('requests_used');started=session.get('round_started_requests',0)
    need(type(used) is int and used>=0 and type(started) is int and 0<=started<=used,
         'result budget counters')
    prepared=session.get('prepared_round')
    need(prepared is None or type(prepared) is int and prepared>=1,'result budget prepared round')
    if (session.get('halted_reason') or wait_active(session.get('source_wait'),now) or
            session.get('stop_at') is not None and now>=ts(session['stop_at']) or
            session.get('worker_handoff_at') is not None and now>=ts(session['worker_handoff_at'])):
        return 0
    bounds=[]
    if SOURCE_LIMIT is not None:bounds.append(SOURCE_LIMIT-used)
    if ROUND_SOURCE_LIMIT is not None and prepared is not None:bounds.append(ROUND_SOURCE_LIMIT-(used-started))
    return max(0,min(bounds)) if bounds else None


def due_rows(rows,observations,now,*,limit=None,priority_races=()):
    """Poll pending first, at most every five minutes; revisit settled after six hours."""
    latest,_=latest_result_observations(observations)
    by_result={x['race_id']:x for x in latest};by_race={x['race_id']:x for x in rows};due=[]
    for row in by_race.values():
        if ts(row['cutoff_at'])+timedelta(seconds=90)>=now:continue
        old=by_result.get(row['race_id']);settled=False
        if old:
            data=old.get('data') or {}
            settled=(data.get('confirmed') is True and data.get('status') in ('settled','cancelled','no_contest'))
            interval=timedelta(hours=6) if settled else timedelta(minutes=5)
            if ts(old['captured_at'])+interval>now:continue
        due.append((settled,ts(old['captured_at']) if old else ts(row['cutoff_at']),row['race_id'],row))
    priority=set(priority_races)
    need(all(type(rid) is str for rid in priority),'result priority race keys')
    ordered=sorted(due,key=lambda x:(x[0],x[2] not in priority,x[1],x[2]))
    return [item[3] for item in (ordered if limit is None else ordered[:limit])]
