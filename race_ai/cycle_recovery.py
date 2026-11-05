"""Restore authenticated first receipts across existing Actions runs.

No source requests, new models, forecast regeneration or production promotion.
The caller supplies authenticated GitHub API reads. Incomplete history stops
new forecasts; it is never silently treated as an empty database.
"""
from datetime import datetime,timedelta,timezone
import copy,hashlib,io,json,re,zipfile
from .frozen_day_cycle import need,ts,read_p1,read_p0,archive_json
from .first_receipt_continuity import first_receipt_rows,latest_result_observations
from .repeated_cycle import matches as artifact_matches
BRANCH='feat/four-sport-forecast-audit-view-20261022'
WORKFLOW=405276784
JST=timezone(timedelta(hours=9))
# Legacy continuity checkpoints can contain nested parent archives. Keep their
# authenticated intake bounded while preserving compatibility with that history.
CONTINUITY_ARCHIVE_MAX_BYTES=128*1024*1024

def artifact_pages(get, run_id):
    """Read a complete, duplicate-free artifact listing, including page 2+."""
    need(type(run_id) is int and run_id > 0, 'invalid artifact run')
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

def _verified_zip(raw, meta, expected_name):
    need(isinstance(raw,bytes) and 0<len(raw)<=CONTINUITY_ARCHIVE_MAX_BYTES,'bounded cycle archive')
    need(meta.get('expired') is False and meta.get('name')==expected_name and
         meta.get('workflow_run',{}).get('head_repository_id')==1416489937,
         'foreign/expired continuity archive')
    need(meta.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest(),
         'continuity archive hash mismatch')
    ts(meta['created_at'])
    archive=zipfile.ZipFile(io.BytesIO(raw))
    need(len(archive.namelist())==len(set(archive.namelist())),'duplicate continuity member')
    need(sum(info.file_size for info in archive.infolist())<=512*1024*1024,
         'oversized continuity members')
    need(archive.testzip() is None,'continuity member CRC mismatch')
    return archive

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
                      'SESSION_SOURCE_BUDGET_EXHAUSTED','SOURCE_BUDGET_EXHAUSTED',
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
    return dict(source_wait=wait,previous_run_id=run,
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
            if run['id']==current_run or run['head_branch']!=BRANCH:continue
            if run['event'] not in ('push','workflow_dispatch'):continue
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

def result_archive(raw,meta,day):
    need(isinstance(raw,bytes) and len(raw)<=32*1024*1024,'bounded result archive')
    run=meta['workflow_run']['id']
    need(meta.get('expired') is False and artifact_matches(meta.get('name'),f'race-existing-cycle-{run}') and
         meta['workflow_run'].get('head_repository_id')==1416489937,'foreign/expired cycle archive')
    need(meta.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest(),'cycle archive hash mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        member='official-result-observations.json'
        need(len(z.namelist())==len(set(z.namelist())) and member in z.namelist(),'cycle member missing/duplicate')
        need(z.getinfo(member).file_size<=16*1024*1024,'oversized result journal')
        items=json.loads(z.read(member))
    need(isinstance(items,list) and len(items)<=20000,'bounded observation journal')
    for row in items:
        need(row['race_id'].startswith(day.replace('-','')+'-'),'foreign result day')
        ts(row['captured_at'])
    return items

def _result_day(raw,meta):
    """Determine an authenticated payload day before filtering a lookback run."""
    run=meta['workflow_run']['id']
    need(isinstance(raw,bytes) and len(raw)<=32*1024*1024 and meta.get('expired') is False and
         artifact_matches(meta.get('name'),f'race-existing-cycle-{run}') and
         meta['workflow_run'].get('head_repository_id')==1416489937 and
         meta.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest(),'cycle archive identity')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
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

def recover(get,day,*,current_run,out,clock=None):
    """Read every same-day P1 original and every saved result journal, no writes upstream."""
    rows=[];observations=[];receipts=[];scanned=[];index_entries=[]
    learning_shadows=[];learning_context=None;training_proofs={}
    history_context=None;history_proofs={};history_documents=[]
    entry_history_cache=None;entry_history_order=None;entry_history_rejections=0
    clock=clock or (lambda:datetime.now(timezone.utc))
    from .observed_result_history import context_from_result_archive as history_from_archive,history_proof
    source_control=previous_source_control(get,day,current_run=current_run)
    from .observed_weight_learning import read_shadow_rows,context_from_result_archive,merge_shadow_rows,training_proof,validate_shadow_training,attach_snapshots
    out.mkdir(parents=True,exist_ok=True)
    for run in day_runs(get,day,current_run=current_run):
        artifacts=artifact_pages(get,run['id'])
        scanned.append(run['id'])
        for listed in artifacts:
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
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        body_sha=hashlib.sha256(archive.read('national.json')).hexdigest()
                    learning_shadows+=read_shadow_rows(doc,meta,items)
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
                if candidate is not None:training_proofs[str(meta['id'])]=training_proof(candidate)
                if payload_day==day and candidate is not None and (learning_context is None or ts(meta['created_at'])>ts(learning_context['receipt']['created_at'])):
                    learning_context=candidate
    validate_shadow_training(learning_shadows,training_proofs)
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
    state['state_sha256']=hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    (out/'continuity.json').write_text(json.dumps(state,ensure_ascii=False))
    return state

def load_state(path,day):
    data=json.loads(path.read_text());digest=data.pop('state_sha256')
    need(digest==hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'recovered state hash mismatch')
    need(data.get('schema')=='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1' and data.get('complete') is True and data.get('day_jst')==day,'recovery missing or wrong day')
    return data

def due_rows(rows,observations,now,*,limit=None):
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
    ordered=sorted(due,key=lambda x:x[:3])
    return [item[3] for item in (ordered if limit is None else ordered[:limit])]
