"""Reuse frozen artifacts and observe later official results in the same workflow.

The forecast process and outcome process never share result inputs. This runner
is not a scheduler, does not publish raw pages or change model coefficients.
"""
from datetime import datetime,timezone,timedelta,date
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
from urllib import request,error
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
race_ai.__path__.append(str(ROOT/'pr64-reference'/'race_ai'))
from race_ai.frozen_day_cycle import read_p0,read_p1,evaluate,need,ts
from race_ai.first_receipt_continuity import first_receipt_rows,latest_result_observations
from race_ai.cycle_recovery import recover,load_state,due_rows
from race_ai.observed_weight_learning import attach_snapshots
JST=timezone(timedelta(hours=9));REPO='haji84/RACE-AI'

def event_day(*,now=None):
    """Pin one real transaction's event day, never a client supplied clock."""
    now=now or datetime.now(timezone.utc)
    need(now.utcoffset() is not None,'aware event clock')
    today=now.astimezone(JST).date()
    value=os.environ.get('RACE_AI_EVENT_DAY')
    if value is None:return today.isoformat()
    pinned=date.fromisoformat(value)
    need(pinned.isoformat()==value and today-timedelta(days=1)<=pinned<=today,
         'EVENT_DAY_PIN_REJECTED')
    return value

def source_identity_conflict(reason):
    """Only definite provenance contradictions quarantine the shared source."""
    return reason in {
        'B_SOURCE_IDENTITY','foreign program source','B cutoff identity mismatch',
        'B registration mismatch','B duplicate allocation','duplicate or foreign B race',
        'OFFICIAL_RESULT_SOURCE_IDENTITY_MISMATCH','update URL race identity mismatch',
        'update body day or venue mismatch','update selected race mismatch',
        'explicit result program race identity conflict','result and program racer name conflict',
        'external official archive redirect rejected','redirect rejected','unexpected archive entry name',
    }

def gh(path):
    result=subprocess.run(['gh','api',f'repos/{REPO}/'+path],check=True,capture_output=True,timeout=50)
    return result.stdout

def original(day):
    index=ROOT/'docs/evidence'/day/'p0-first-receipt.json'
    if not index.is_file():raise ValueError('FIRST_RECEIPT_REGISTRY_MISSING_NO_BLIND_REGENERATION')
    known=json.loads(index.read_text());ident=known['artifact_id']
    receipt=json.loads(gh(f'actions/artifacts/{ident}'));raw=gh(f'actions/artifacts/{ident}/zip')
    need(receipt['created_at']==known['server_created_at'] and receipt['digest']=='sha256:'+known['zip_sha256'],'original receipt changed')
    doc,rows=read_p0(raw,receipt,expected_day=day)
    need(rows[0]['original_json_sha256']==known['json_sha256'],'original body changed')
    return doc,attach_snapshots(doc,rows),receipt,raw

def _video_sources(state,requested,reader=None):
    """Lazy optional archive reads; no video source GET occurs in the default flow."""
    from race_ai.boat_video_archive import VideoContextArchiveReader
    reader=reader or VideoContextArchiveReader(gh)
    try:
        inherited=state.get('video_context_artifact_ids',[])
        need(type(inherited) is list and type(requested) in (tuple,list),
             'BOAT_VIDEO_ARCHIVE_REJECTED')
        reader.load(inherited+list(requested))
        return reader,None
    except (ValueError,KeyError,TypeError):
        return reader,'BOAT_VIDEO_ARCHIVE_REJECTED'

def restore(day,*,video_context_artifacts=(),video_reader=None):
    import zipfile,io
    doc,rows,meta,raw=original(day);folder=ROOT/'boat_all_day_output';folder.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:body=z.read('forecasts.json')
    target=folder/'forecasts.json'
    if target.exists():
        need(target.read_bytes()==body,'FIRST_P0_RESTORE_LOCAL_BYTES_CONFLICT')
    else:
        with target.open('xb') as f:f.write(body)
    (folder/'first-receipt.json').write_text(json.dumps(meta,ensure_ascii=False))
    reader,error=_video_sources({},video_context_artifacts,video_reader)
    state=recover(gh,day,current_run=int(os.environ['GITHUB_RUN_ID']),out=ROOT/'cycle_recovery_output',
                  video_receipt_verifier=reader.verify)
    if reader.artifact_ids or error:
        from race_ai.repeated_cycle import write_state
        if reader.artifact_ids:
            state['video_context_artifact_ids']=sorted(set(state.get('video_context_artifact_ids',[]))|
                                                       set(reader.artifact_ids))
        if error:
            state.setdefault('video_context_rejections',[]).append({'reason':error})
        write_state(ROOT/'cycle_recovery_output/continuity.json',state,key='state_sha256')
    print(json.dumps(dict(state='ORIGINAL_REUSED_NO_REGENERATION',races=doc['race_count'],forecasts=len(rows),artifact_id=meta['id'])))

def forecast(day,*,video_context_artifacts=(),video_reader=None):
    from scripts import boat_nationwide_ab_pilot as pilot
    state=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    index=json.loads(pilot.FROZEN_INDEX.read_text())
    first={}
    for row in sorted(index['entries']+state['index_entries'],key=lambda x:(ts(x['server_created_at']),x['artifact_id'])):
        first.setdefault(row['race_id'],row)
    index['entries']=list(first.values())
    target=ROOT/'cycle_recovery_output/freeze-index.json'
    target.write_text(json.dumps(index,ensure_ascii=False))
    # Point the unchanged predictor at the verified union, not yesterday alone.
    pilot.FROZEN_INDEX=target
    from race_ai.repeated_cycle import SourceGuard
    session=ROOT/'cycle_recovery_output/repeat-session.json'
    if session.exists():pilot.SOURCE_GUARD=SourceGuard(session)
    pilot.OBSERVED_HISTORY_CONTEXT=state.get('history_context')
    pilot.ENTRY_OBSERVATION_HISTORY=state.get('entry_observation_history')
    # Optional archive I/O precedes fresh official model snapshots. It must not
    # consume the remaining physical-save window of already generated P1 rows.
    reader,video_error=_video_sources(state,video_context_artifacts,video_reader)
    result=pilot.run(schedule_snapshot=state.get('schedule_cache'))
    from race_ai.observed_weight_learning import make_shadows
    result['learned_pairwise_shadows']=[];result['learning_failures']=[]
    if video_error:
        result['learning_failures'].append({'reason':video_error})
    context=state.get('learning_context')
    for bundle in result.get('observed_pairwise_p1_bundles',[]):
        if context is None or 'suite' not in bundle:continue
        try:
            need(ts(bundle['snapshot']['sales_cutoff_at'])-datetime.now(timezone.utc)>timedelta(seconds=210),
                 'learned inference too near cutoff')
            if context['training']['schema']=='RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1':
                need(video_error is None,video_error)
                envelope=reader.select(bundle['snapshot'])
                need(envelope is not None,'AUTHENTICATED_VIDEO_CONTEXT_UNAVAILABLE')
                result['learned_pairwise_shadows']+=make_shadows(bundle['snapshot'],bundle['suite'],context,
                    video_context=envelope,video_receipt_verifier=reader.verify)
            else:
                result['learned_pairwise_shadows']+=make_shadows(bundle['snapshot'],bundle['suite'],context)
        except (ValueError,KeyError,TypeError) as exc:
            result['learning_failures'].append({'race_id':bundle['race_id'],'reason':str(exc)[:180]})
    if reader.artifact_ids:
        result['video_context_artifact_ids']=reader.artifact_ids
    (pilot.OUTPUT/'national.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')))


def supplement(day,round_no=None):
    """Fill only previously absent future P0 rows; never edit first morning bytes."""
    need(round_no is None or type(round_no) is int and round_no>=1,'invalid supplement round')
    folder=ROOT/'p0_supplement_output'
    if round_no is not None:folder=folder/f'cycle-{round_no}'
    need(not (folder/'forecasts.json').exists(),'P0_SUPPLEMENT_ALREADY_EXISTS_NO_REGENERATION')
    _,rows,_,_=original(day)
    recovered=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    from scripts.existing_day_program import collect
    frozen={(x['race_id'],x['model_id']) for x in rows+recovered['rows'] if x['stage']=='P0'}
    from race_ai.repeated_cycle import SourceGuard,load as load_session
    from race_ai.source_retry_policy import SourceWait
    guard=SourceGuard(ROOT/'cycle_recovery_output/repeat-session.json')
    def finish(ready,state,**details):
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                output.write('supplement_ready='+('true' if ready else 'false')+'\n')
                output.write('supplement_state='+state+'\n')
        record=dict(state=state,supplement_ready=ready,**details)
        print(json.dumps(record));return record
    def actual_day_clock():
        now=datetime.now(timezone.utc)
        if now.astimezone(JST).date().isoformat()!=day:raise SourceWait('DAY_HANDOFF')
        handoff=os.environ.get('RACE_AI_WORKER_HANDOFF_AT')
        if handoff and now>=ts(handoff):raise SourceWait('WORKER_HANDOFF')
        return now
    try:
        result=collect(already_frozen_models=frozen,clock=actual_day_clock,source_guard=guard)
    except (SourceWait,ValueError) as exc:
        if not isinstance(exc,SourceWait) and str(exc) not in ('DAY_HANDOFF','WORKER_HANDOFF'):raise
        return finish(False,str(exc) if str(exc) in ('DAY_HANDOFF','WORKER_HANDOFF') else 'SOURCE_WAIT',
                      source_wait=load_session(guard.path).get('source_wait'))
    status=result.get('http_status')
    if isinstance(status,int) and status>=400:
        guard.http_failure(status,result.get('source_response_headers',{}),
                           not_yet_published=status==404)
    elif 'failure_class' in result and (result.get('source_error_kind')=='TRANSPORT' or
                                       result['failure_class'] in ('TimeoutError','URLError','OSError')):
        guard.http_failure(None)
    elif 'failure_class' in result and source_identity_conflict(result.get('reason')):
        guard.verification_failure()
    elif 'failure_class' not in result:
        guard.http_success()
    if 'failure_class' in result:
        waiting=load_session(guard.path).get('source_wait')
        return finish(False,result.get('source_control_reason','SOURCE_WAIT' if waiting else 'SOURCE_DATA_PENDING'),
                      source_wait=waiting)
    if not result['predictions']:
        return finish(False,'NO_MISSING_FUTURE_P0',race_count=0)
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'forecasts.json').open('x') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return finish(True,'MISSING_FUTURE_P0_ONLY',race_count=result['race_count'],
                  original_model_slots_not_regenerated=len(frozen))

def observe_due_results(due,observations,day,guard=None):
    """Keep unsupported formats pending while other qualified races proceed."""
    from race_ai.official_race_updates import endpoint,parse_update,MAX_BYTES
    from race_ai.tokuyama_day_worker import NoRedirects
    observations=list(observations);failures=[];requests_used=0
    from race_ai.source_retry_policy import SourceWait
    blocked=False
    for row in due:
        if blocked:break
        rid=row['race_id'];d=date.fromisoformat(day);venue=rid[9:11];n=int(rid[-2:]);url=endpoint(d,venue,n,'raceresult')
        try:
            req=request.Request(url,headers={'User-Agent':'RACE-AI-owner-existing-result-audit/1.0','Accept':'text/html'})
            if guard is not None:guard.charge('result')
            requests_used+=1
            with request.build_opener(NoRedirects()).open(req,timeout=12) as response:
                raw=response.read(MAX_BYTES+1)
                need(response.status==200,'official response status rejected')
                need(response.geturl()==url,'OFFICIAL_RESULT_SOURCE_IDENTITY_MISMATCH')
                need(0<len(raw)<=MAX_BYTES,'official response body rejected')
            at=datetime.now(timezone.utc).isoformat()
            if os.environ.get('RACE_AI_SAVED_VIEW_CAPTURE')=='true':
                try:
                    from race_ai.saved_view_feed import retain_capture
                    retain_capture(Path(os.environ['RUNNER_TEMP'])/'boat-saved-view-captures',raw,
                        dict(source_url=url,captured_at=at,source_sha256=hashlib.sha256(raw).hexdigest(),http_status=200))
                except Exception:
                    failures.append(dict(race_id=rid,state='DISPLAY_SOURCE_CACHE_UNAVAILABLE',reason='PRIVATE_DISPLAY_CAPTURE_FAILED'))
            observation=parse_update(raw,kind='raceresult',day=d,venue=venue,race_no=n,source_url=url,captured_at=at,entries=None)
            observation.update(source_url=url,source_sha256=hashlib.sha256(raw).hexdigest())
            if guard is not None:guard.http_success()
            observations.append(observation);time.sleep(.35)
        except Exception as exc:
            if isinstance(exc,SourceWait):
                blocked=True
                failures.append(dict(race_id=rid,state='SOURCE_WAIT',reason=exc.reason,
                                     retry_at=exc.retry_at))
                continue
            if str(exc) in ('DAY_HANDOFF','WORKER_HANDOFF'):
                blocked=True
                failures.append(dict(race_id=rid,state=str(exc),reason=str(exc)))
                continue
            if isinstance(exc,error.HTTPError):
                blocked=True
                if guard is not None:
                    guard.http_failure(exc.code,exc.headers,not_yet_published=exc.code==404)
            elif isinstance(exc,(error.URLError,TimeoutError,OSError)):
                blocked=True
                if guard is not None:guard.http_failure(None)
            elif source_identity_conflict(str(exc)):
                blocked=True
                if guard is not None:guard.verification_failure()
            failures.append(dict(race_id=rid,state='SOURCE_OR_PARSE_UNAVAILABLE',reason=type(exc).__name__+': '+str(exc)[:120]))
    return observations,failures,requests_used

def audit(day,p1_id,p0_supplement=None,round_no=None,*,video_context_artifacts=(),video_reader=None):
    doc,rows,p0_meta,p0_zip=original(day);sources=[p0_meta];p1_doc=None;p1_meta=None
    recovered=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    reader,video_error=_video_sources(recovered,video_context_artifacts,video_reader)
    rows+=recovered['rows'];sources+=recovered['receipts']
    out=ROOT/'existing_cycle_output';out.mkdir(exist_ok=True)
    (out/'first-p0-original.zip').write_bytes(p0_zip)
    if p0_supplement and p0_supplement != p0_meta['id']:
        meta=json.loads(gh(f'actions/artifacts/{p0_supplement}'));raw=gh(f'actions/artifacts/{p0_supplement}/zip')
        supplement_doc,additional=read_p0(raw,meta,expected_day=day);rows+=attach_snapshots(supplement_doc,additional);sources.append(meta)
        (out/'supplement-p0-original.zip').write_bytes(raw)
    if p1_id:
        meta=json.loads(gh(f'actions/artifacts/{p1_id}'));raw=gh(f'actions/artifacts/{p1_id}/zip')
        p1_doc,p1rows=read_p1(raw,meta);rows+=attach_snapshots(p1_doc,p1rows);sources.append(meta);p1_meta=meta
        (out/'current-p1-original.zip').write_bytes(raw)
    rows,excluded=first_receipt_rows(rows)
    excluded=recovered['excluded_repeats']+excluded
    from race_ai.repeated_cycle import SourceGuard,load as load_session,checkpoint
    session_path=ROOT/'cycle_recovery_output/repeat-session.json'
    guard=SourceGuard(session_path) if session_path.exists() else None
    due=due_rows(rows,recovered['observations'],datetime.now(timezone.utc))
    observations,failures,requests_used=observe_due_results(due,recovered['observations'],day,guard)
    latest_observations,observations=latest_result_observations(observations)
    report=evaluate([{k:v for k,v in r.items() if k not in ('learning_snapshot','learning_snapshot_sha256')} for r in rows],latest_observations)
    report.update(day_jst=day,updated_at=datetime.now(timezone.utc).isoformat(),run_id=os.environ.get('GITHUB_RUN_ID'),
        code_sha=os.environ.get('GITHUB_SHA'),first_forecast_artifacts=sources,source_request_count=requests_used,
        schedule=doc['schedule'],scheduled_boat_races=len(doc['schedule']),
        original_p0_skips=doc['skipped'],no_p0_forecast=[x for x in doc['skipped'] if x['race_id'] not in {r['race_id'] for r in rows if r['stage']=='P0'}],
        result_source_failures=failures,excluded_repeat_forecasts=excluded,
        restored_run_ids=recovered['scanned_runs'],result_observation_versions=len(observations),raw_sources_published=False,continuous_operation_proven=False,
        all_models_operational=False,other_sports_status='LIVE_INPUT_INTEGRATION_NOT_YET_VERIFIED',
        archive_retention_days=7,permanent_private_retention_proven=False)
    from race_ai.existing_model_coverage import coverage
    schedule_counts={'boat':len(doc['schedule'])}
    if day=='2026-11-04':
        schedule_counts.update(keirin=75,autorace=20,horse=59)
        report['nonboat_discovery_receipt']={'artifact_id':13283229052,'zip_sha256':'86ffb2b44fdbb2119a0401533cd9f182eca0d918ab555c48870d01ef422e0e9d','state':'154_CAPTURED_CARDS_NOT_154_FORECASTS'}
    report['model_coverage']=coverage(rows,schedule_counts)
    # Private originals are not copied into public GitHub. This whitelist-only
    # projection keeps their research grade separate from frozen/scored counts.
    from race_ai.external_research_registry import attach_to_report
    manifest_path=ROOT/'docs/evidence'/day/'autorace-research-import.json'
    if manifest_path.is_file():
        try:
            attach_to_report(report,json.loads(manifest_path.read_text()),day=day)
        except (ValueError,KeyError,TypeError) as exc:
            report['external_research']={'state':'IMPORT_REJECTED','reason':str(exc)[:160],
                'research_forecast_count':None,'included_in_formal_scoreboard':False}
    else:
        report['external_research']={'state':'NO_AUDITED_IMPORT_MANIFEST','research_forecast_count':None,
                                     'included_in_formal_scoreboard':False}
    (out/'external_research_summary.json').write_text(json.dumps(report['external_research'],ensure_ascii=False,indent=2))

    from race_ai.observed_weight_learning import (fit_from_verified,
        merge_shadow_rows,score_shadows,coverage_audit)
    shadow_rows=list(recovered.get('learning_shadows',[]))
    from race_ai.boat_video_archive import read_optional_video_shadows,validate_optional_video_training
    video_rejections=list(recovered.get('video_shadow_rejections',[]))
    if p1_doc is not None:
        accepted,rejected=read_optional_video_shadows(p1_doc,p1_meta,rows,receipt_verifier=reader.verify)
        shadow_rows+=accepted;video_rejections+=rejected
    shadow_rows=merge_shadow_rows(shadow_rows)
    shadow_rows,rejected=validate_optional_video_training(shadow_rows,recovered.get('training_proofs',{}))
    video_rejections+=rejected
    if video_rejections:
        report['video_shadow_rejections']=video_rejections
    if p1_doc is not None:
        from race_ai.cycle_recovery import validate_document_history
        validate_document_history(p1_doc,recovered.get('history_proofs',{}))
    recovered['learning_shadows']=shadow_rows
    report['learned_shadow_comparison']=score_shadows(shadow_rows,rows,latest_observations)
    report['coverage_audit']=coverage_audit(rows,doc['schedule'],now=datetime.now(timezone.utc),
        observations=latest_observations,learned_rows=shadow_rows)
    training_path=out/'trained_observed_models.json'
    try:
        need(video_error is None,video_error)
        if reader.artifact_ids:
            training=fit_from_verified(rows,latest_observations,now=datetime.now(timezone.utc),
                video_contexts=reader.contexts_for_rows(rows),video_receipt_verifier=reader.verify)
        else:
            training=fit_from_verified(rows,latest_observations,now=datetime.now(timezone.utc))
        prior=(recovered.get('learning_context') or {}).get('training')
        if prior is not None and {k:v for k,v in prior.items() if k not in ('created_at','training_sha256')}=={k:v for k,v in training.items() if k not in ('created_at','training_sha256')}:
            training=prior  # Do not invent a new candidate version for unchanged evidence.
        training_path.write_text(json.dumps(training,ensure_ascii=False,sort_keys=True))
        report['automatic_learning']={k:v for k,v in training.items() if k not in ('source_lineage','excluded_races')}
    except (ValueError,KeyError,TypeError) as exc:
        if training_path.exists():training_path.unlink()
        report['automatic_learning']={'state':'LEARNING_INPUT_REJECTED','reason':str(exc)[:200],
                                      'auto_promoted':False,'accuracy_improvement_proven':False}
    report['next_action']='FREEZE_TRAINED_CANDIDATES_THEN_COMPARE_FUTURE_RACES'
    if reader.artifact_ids:
        report['video_context_artifact_ids']=reader.artifact_ids
    if video_error:
        report['video_context_status']=video_error
    report['updated_at']=datetime.now(timezone.utc).isoformat()
    report['round_no']=round_no
    if session_path.exists():report['bounded_repeat_session']=load_session(session_path)
    report['report_sha256']=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    (out/'status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (out/'official-result-observations.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2))
    import csv
    with (out/'forecasts.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['race_id','phase','model','cutoff','first_saved_at','top8','artifact_id'])
        for r in rows:writer.writerow([r['race_id'],r['stage'],r['model_id'],r['cutoff_at'],r['server_saved_at'],' / '.join('-'.join(map(str,t)) for t in r['top8']),r['artifact_id']])
    lines=['# Existing-model actual execution status',f'Day: {day}; run: '+str(report['run_id']),
        f'Frozen forecast rows: {len(rows)}; races: {report["distinct_races"]}; scored: {report["scored_forecasts"]}.',
        'Research only. No wagering, model auto-promotion, retrospective forecast edits or all-model completion claim.',
        '| Phase | Model | Forecasts | Scored | Hit | ROI |','|---|---|---:|---:|---:|---:|']
    for x in report['scoreboard']:
        lines.append(f'|{x["stage"]}|{x["model_id"]}|{x["forecast_count"]}|{x["scored"]}|{x["hits"]}|{x["roi"] if x["roi"] is not None else "pending"}|')
    (out/'model_coverage.json').write_text(json.dumps(report['model_coverage'],ensure_ascii=False,indent=2))
    (out/'improvement_candidates.json').write_text(json.dumps(report['improvement_candidates'],ensure_ascii=False,indent=2))
    lines+=['',f'Repeated later predictions excluded: {len(excluded)}; recovered previous runs: {len(recovered["scanned_runs"])}.', 'Unmet: all four sports/all models, perpetual private storage, continuous per-deadline coverage.']
    research=report['external_research']
    lines+=['', '## Separately audited external research (not formal scores)',
            'Imported research forecast count: '+str(research.get('research_forecast_count')),
            'No private picks or source pages copied. Receipt-unverified research is excluded from the scoreboard.']
    text='\n'.join(lines)+'\n';(out/'STATUS.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(text)
    if round_no is not None:
        checkpoint(ROOT/'cycle_recovery_output/continuity.json',recovered,rows,observations,sources,p1_doc=p1_doc,p1_receipt=p1_meta)
    print(json.dumps({k:report[k] for k in ('day_jst','forecast_count','distinct_races','scored_forecasts','source_request_count','auto_promoted')},ensure_ascii=False))

def repeat_start(day):
    from race_ai.repeated_cycle import start, write_state
    need(int(os.environ.get('GITHUB_RUN_ATTEMPT','1'))==1,'RETRY_REQUIRES_NEW_TRIGGER_TO_PRESERVE_RECEIPTS')
    path=ROOT/'cycle_recovery_output/repeat-session.json'
    recovered_path=ROOT/'cycle_recovery_output/continuity.json'
    recovered=load_state(recovered_path,day) if recovered_path.exists() else {}
    control=recovered.get('source_control')
    bootstrap_path=ROOT/'cycle_recovery_output/bootstrap-source-control.json'
    bootstrap=None
    if bootstrap_path.exists():
        from scripts.first_p0_bootstrap import bootstrap_control
        bootstrap=bootstrap_control(day,int(os.environ['GITHUB_RUN_ID']))
        control=dict(control or {})
        need(bootstrap['lifetime_requests_base']==control.get('lifetime_requests',0),
             'SOURCE_CONTROL_CHANGED_DURING_BOOTSTRAP')
        control['source_wait']=bootstrap.get('source_wait')
        control['previous_halted_reason']=bootstrap.get('previous_halted_reason')
    if datetime.now(timezone.utc).astimezone(JST).date().isoformat()!=day:
        from scripts.first_p0_bootstrap import bootstrap_control,_save_control
        bootstrap=bootstrap or bootstrap_control(day,int(os.environ['GITHUB_RUN_ID']),inherited=control)
        bootstrap['control_reason']='DAY_HANDOFF';_save_control(bootstrap)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                output.write('session_ready=false\nhandoff_reason=DAY_HANDOFF\n')
        return dict(state='DAY_HANDOFF',session_ready=False)
    now=datetime.now(timezone.utc)
    handoff=os.environ.get('RACE_AI_WORKER_HANDOFF_AT')
    need(handoff is None or now<ts(handoff)<=now+timedelta(minutes=360),'WORKER_HANDOFF_DEADLINE_REJECTED')
    state=start(path,day=day,run_id=int(os.environ['GITHUB_RUN_ID']),now=now,
                source_control=control)
    need(state.get('worker_handoff_at') in (None,handoff),'WORKER_HANDOFF_PIN_CHANGED')
    state['worker_handoff_at']=handoff
    state=write_state(path,state)
    # First-day B GET belongs to this SAME bounded source session.
    if os.environ.get('RACE_AI_FIRST_P0_CAPTURED')=='true':
        first=json.loads((ROOT/'boat_all_day_output/forecasts.json').read_text())
        count=bootstrap['requests_used'] if bootstrap is not None else 1
        need(first['day_jst']==day and first['source_requests']==1 and
             first['race_count']>0 and type(count) is int and count>=1,
             'FIRST_P0_GET_BUDGET_ACCOUNTING_REJECTED')
        if not state.get('bootstrap_requests_accounted'):
            need(state['requests_used']==0,'FIRST_P0_GET_ACCOUNTING_CONFLICT')
            state['requests_used']=count
            state['requests_by_kind']={'forecast':count}
            state['bootstrap_requests_accounted']=count
            write_state(path,state)
        else:need(state['bootstrap_requests_accounted']==count,'FIRST_P0_GET_ACCOUNTING_CONFLICT')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write('session_ready=true\n')
    return dict(state='SOURCE_SESSION_READY',session_ready=True)

def repeat_prepare(day,round_no):
    from race_ai.repeated_cycle import prepare
    path=ROOT/'cycle_recovery_output/repeat-session.json'
    continuity_path=ROOT/'cycle_recovery_output/continuity.json'
    continuity=load_state(continuity_path,day) if continuity_path.exists() else {}
    next_action=(continuity.get('schedule_cache') or {}).get('next_check_at')
    handoff=ts(os.environ['RACE_AI_WORKER_HANDOFF_AT']) if os.environ.get('RACE_AI_WORKER_HANDOFF_AT') else None
    def decide():
        now=datetime.now(timezone.utc)
        if handoff is not None and now>=handoff:
            return dict(active=False,wait_seconds=0,reason='WORKER_HANDOFF')
        return prepare(path,round_no,now=now,next_action_at=next_action)
    decision=decide()
    while decision['wait_seconds']:
        time.sleep(min(decision['wait_seconds'],30))
        decision=decide()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        for k,v in decision.items():
            if k=='active':v='true' if v else 'false'
            print(f'{k}={v}',file=f)
    print(json.dumps(dict(round=round_no,**decision)))

def repeat_complete(day,round_no,p1_id,result_id):
    import io,zipfile
    from race_ai.repeated_cycle import artifact_name,complete
    from race_ai.cycle_recovery import result_archive
    run_id=int(os.environ['GITHUB_RUN_ID'])
    # GitHub upload completion can precede metadata visibility. Wait before the
    # single strict remote readback; never retry or ignore an HTTP 4xx/429.
    time.sleep(5)
    meta=json.loads(gh(f'actions/artifacts/{result_id}'))
    need(meta['workflow_run']['id']==run_id and
         meta['name']==artifact_name('race-existing-cycle',run_id,round_no),'round result receipt identity')
    raw=gh(f'actions/artifacts/{result_id}/zip')
    result_archive(raw,meta,day)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        report=json.loads(archive.read('status.json'))
    local=json.loads((ROOT/'existing_cycle_output/status.json').read_text())
    need(report==local and report['round_no']==round_no and str(report['run_id'])==str(run_id),'round result readback mismatch')
    from race_ai.observed_weight_learning import context_from_result_archive,training_proof
    from race_ai.repeated_cycle import write_state
    context=context_from_result_archive(raw,meta)
    from race_ai.observed_result_history import context_from_result_archive as history_from_archive,history_proof
    prior_history=history_from_archive(raw,meta,verified_at=datetime.now(timezone.utc).isoformat())
    continuity=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    continuity['history_context']=prior_history
    continuity.setdefault('history_proofs',{})[str(meta['id'])]=history_proof(prior_history)
    if context is not None:
        continuity['learning_context']=context
        continuity.setdefault('training_proofs',{})[str(meta['id'])]=training_proof(context)
    if 'video_context_artifact_ids' in report:
        handles=report['video_context_artifact_ids']
        need(type(handles) is list and all(type(ident) is int and ident>0 for ident in handles) and
             handles==sorted(set(handles)),'BOAT_VIDEO_ARCHIVE_REJECTED')
        continuity['video_context_artifact_ids']=handles
    write_state(ROOT/'cycle_recovery_output/continuity.json',continuity,key='state_sha256')
    state=complete(ROOT/'cycle_recovery_output/repeat-session.json',round_no,
                   now=datetime.now(timezone.utc),forecast_artifact=p1_id,result_artifact=result_id)
    print(json.dumps(dict(state='ROUND_SAVED_AND_READBACK_VERIFIED',round=round_no,
                         forecast_count=report['forecast_count'],scored_forecasts=report['scored_forecasts'],
                         p1_artifact=p1_id,result_artifact=result_id,session_requests=state['requests_used'])))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['restore','forecast','audit','supplement','repeat-start','repeat-prepare','repeat-complete'])
    p.add_argument('--p1-artifact',type=int);p.add_argument('--p0-supplement',type=int)
    p.add_argument('--result-artifact',type=int);p.add_argument('--round',type=int)
    p.add_argument('--video-context-artifact',type=int,action='append',default=[],
                   help='Optional independently read existing-run video-context artifact ID; repeatable')
    a=p.parse_args()
    if a.video_context_artifact and a.command not in ('restore','forecast','audit'):
        p.error('--video-context-artifact applies only to restore, forecast or audit')
    video_options={'video_context_artifacts':a.video_context_artifact} if a.video_context_artifact else {}
    day=event_day()
    if a.command=='restore':restore(day,**video_options)
    elif a.command=='forecast':forecast(day,**video_options)
    elif a.command=='supplement':supplement(day,a.round)
    elif a.command=='repeat-start':repeat_start(day)
    elif a.command=='repeat-prepare':repeat_prepare(day,a.round)
    elif a.command=='repeat-complete':repeat_complete(day,a.round,a.p1_artifact,a.result_artifact)
    else:audit(day,a.p1_artifact,a.p0_supplement,a.round,**video_options)
if __name__=='__main__':main()
