"""Count-only national P1 model matrix from independently read owner evidence.

This pure calculator cannot authenticate official source bytes, source clocks,
AES decryptions or GH receipts. Call it ONLY after the existing immutable
owner reader has independently accepted those inputs. It never fetches or
generates a forecast, and never exposes race IDs or private model inputs.
"""
from collections import Counter
import re

SCHEMA='RACE_AI_BOAT_OWNER_NATIONAL_P1_MATRIX_V1'
MODEL=re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')


def _need(ok):
    if not ok:raise ValueError('BOAT_OWNER_NATIONAL_P1_MATRIX_REJECTED')


def calculate(report,model_ids,*,independent_original_reader=False,allow_pending_audit=False):
    _need(type(report) is dict and report.get('schema')==
          'RACE_AI_OWNER_ORIGINAL_EVIDENCE_AUDIT_V1')
    _need(type(model_ids) in (tuple,list) and 0<len(model_ids)<=128 and
          len(set(model_ids))==len(model_ids) and
          all(type(m) is str and MODEL.fullmatch(m) for m in model_ids))
    _need(type(independent_original_reader) is bool)
    valid=report.get('official_program_verified')
    _need(type(valid) is bool)
    scheduled=report.get('scheduled_races')
    retained=report.get('retained_schedule_rows')
    _need(type(retained) is int and 0<retained<=288)
    _need(scheduled is None or (type(scheduled) is int and 0<scheduled<=288))
    _need((valid and scheduled==retained) or (not valid and scheduled is None))
    p1=report.get('p1_models')
    _need(type(p1) is dict and all(type(k) is str and MODEL.fullmatch(k) and
          type(v) is int and 0<=v<=retained for k,v in p1.items()))
    p0=report.get('p0_models')
    _need(type(p0) is dict and all(type(k) is str and MODEL.fullmatch(k) and
          type(v) is int and 0<=v<=retained for k,v in p0.items()))
    _need(report.get('baseline_p1_unique_model_slots')==sum(p1.values()))
    _need(type(report.get('baseline_p1_races')) is int and
          0<=report['baseline_p1_races']<=retained)
    _need(type(report.get('baseline_p0_races')) is int and
          0<=report['baseline_p0_races']<=retained)
    _need(type(report.get('p1_schedule_cutoff_conflict_races')) is int and
          0<=report['p1_schedule_cutoff_conflict_races']<=retained)
    _need(type(report.get('verified_video_prediction_rows')) is int and
          report['verified_video_prediction_rows']>=0)
    _need(report.get('official_source_requests')==0 and
          report.get('originals_changed') is False and
          report.get('successor_dispatch_allowed') is False)
    _need(report.get('owner_conclusion') in ('success','failure'))
    control=report.get('source_control')
    _need(type(allow_pending_audit) is bool and type(control) is dict and
          type(control.get('completed_round')) is int and control['completed_round']>=0)
    pending=control.get('prepared_round')
    _need(pending is None or (allow_pending_audit and independent_original_reader and
          report['owner_conclusion']=='failure' and type(pending) is int and
          pending==control['completed_round']+1))
    _need(type(report.get('owner_run_id')) is int and report['owner_run_id']>0 and
          type(report.get('day_jst')) is str and
          re.fullmatch(r'20[0-9]{2}-[01][0-9]-[0-3][0-9]',report['day_jst']))
    expected=set(model_ids)
    expected_total=retained*len(expected)
    present=sum(p1.get(mid,0) for mid in expected)
    _need(present<=expected_total)
    extras={key:value for key,value in p1.items() if key not in expected}
    missing=expected_total-present
    by_model=[dict(model_id=mid,p1_saved_races=p1.get(mid,0),
                   missing_races=retained-p1.get(mid,0),
                   p1_saved_rate=round(p1.get(mid,0)/retained,6))
              for mid in sorted(expected)]
    full=(pending is None and independent_original_reader and valid and
          report['owner_conclusion']=='success' and
          report['p1_schedule_cutoff_conflict_races']==0 and
          missing==0 and not extras and
          report['baseline_p1_races']==retained)
    state=('HOLD_INTERRUPTED_ROUND_PARTIAL_AUDIT' if pending is not None else
           'INDEPENDENT_P1_MODEL_MATRIX_PRESENT' if full else
           'HOLD_SOURCE_OR_INDEPENDENT_READBACK' if not (independent_original_reader and valid) else
           'HOLD_P1_INCOMPLETE_OR_CONFLICTED')
    return dict(schema=SCHEMA,status=state,day_jst=report['day_jst'],
        owner_run_id=report['owner_run_id'],official_schedule_authenticated=valid,
        owner_original_reader_independently_verified=independent_original_reader,
        source_owner_conclusion=report['owner_conclusion'],
        observed_source_control={k:control[k] for k in (
            'completed_round','prepared_round','previous_session_requests','lifetime_requests',
            'day_start_lifetime_requests','lifetime_completed_rounds','previous_stop_reason') if k in control},
        successor_dispatch_allowed=False,
        expected_active_model_count=len(expected),scheduled_races=scheduled,
        retained_schedule_races=retained,baseline_p0_races=report['baseline_p0_races'],
        baseline_p1_any_races=report['baseline_p1_races'],
        expected_p1_model_slots=expected_total,p1_saved_expected_slots=present,
        missing_p1_model_slots=missing,unrecognized_p1_model_count=len(extras),
        p1_source_cutoff_conflicts=report['p1_schedule_cutoff_conflict_races'],
        by_model=by_model,verified_video_prediction_rows=report['verified_video_prediction_rows'],
        all_expected_models_p1_readback_proven=full,
        public_video_usable=False,full_e2e_website_proven=False,
        original_forecasts_unchanged=True,racing_provider_gets=0,
        no_forecast_generation=True)


def saved_view_coverage(view, *, day, model_ids, scheduled_races, now,
                        native_coverage_reader=None,official_schedule=None,independent_scope=None):
    """Read-only P1 projection count from an already AES-authenticated view.

    A caller's boolean receipt flag is not proof of its GitHub ZIP. The
    independent native ALL_MODEL recovery reader must attest ZIP clocks and
    AES content *before* this count can supplement the original-only report.
    Return model/race counts only, never race IDs, persons, or predictions.
    """
    from datetime import datetime, timezone, timedelta, date
    _need(type(day) is str and type(view) is dict and
          type(view.get('records')) is list and
          isinstance(now,datetime) and now.utcoffset() is not None)
    _need(date.fromisoformat(day).isoformat()==day)
    _need(type(scheduled_races) is int and 0<scheduled_races<=288)
    _need(type(model_ids) in (list,tuple) and len(model_ids)>0 and
          len(model_ids)==len(set(model_ids)) and
          all(type(m) is str and MODEL.fullmatch(m) for m in model_ids))
    expected=set(model_ids);seen_races=set();qualified=set();counted_originals=[]
    excluded=Counter();extra=set();observed_p1=set();conflicts=0
    clock=now.astimezone(timezone.utc)
    official=None
    if official_schedule is not None:
        _need(type(official_schedule) is list and len(official_schedule)==scheduled_races)
        official={}
        for row in official_schedule:
            _need(type(row) is dict and set(row)=={'race_id','cutoff_at','schedule_captured_at','source_sha256'})
            rid=row['race_id'];cutoff=_clock(row['cutoff_at']);captured=_clock(row['schedule_captured_at'])
            _need(type(rid) is str and re.fullmatch(r'[0-9]{8}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])',rid)
                  and rid.startswith(day.replace('-','')) and rid not in official and captured<=clock
                  and captured.astimezone(timezone(timedelta(hours=9))).date().isoformat()==day
                  and cutoff.astimezone(timezone(timedelta(hours=9))).date().isoformat()==day
                  and type(row['source_sha256']) is str and re.fullmatch('[a-f0-9]{64}',row['source_sha256']))
            official[rid]=cutoff
    for row in view['records']:
        if row.get('sport')!='boat' or row.get('event_date_jst')!=day:
            continue
        rid=row.get('race_id')
        _need(type(rid) is str and re.fullmatch(r'[0-9]{8}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])',rid)
              and rid.startswith(day.replace('-','')) and rid not in seen_races)
        seen_races.add(rid)
        # A real saved-view row can have no top-level cutoff while its source
        # forecast still has a date. Never infer a matching official cutoff
        # from that forecast, a race number, or a guessed timetable.
        # Keep the row in the national denominator and HOLD its P1 slots.
        try:
            cutoff=_clock(row.get('cutoff_at'))
        except (TypeError,ValueError,AttributeError):
            excluded['ROW_OFFICIAL_CUTOFF_MISSING_OR_INVALID']+=1
            continue
        if cutoff.astimezone(timezone(timedelta(hours=9))).date().isoformat()!=day:
            excluded['ROW_OFFICIAL_CUTOFF_OUTSIDE_DAY']+=1
            continue
        if official is not None and official.get(rid)!=cutoff:
            conflicts+=1
            excluded['INDEPENDENT_OFFICIAL_CUTOFF_CONFLICT']+=1
            continue
        preds=[row.get('prediction'),*(row.get('comparison_predictions') or [])]
        _need(len(preds)<=128)
        for p in preds:
            if p is None or p.get('stage')!='P1':continue
            mid=p.get('model_id')
            _need(type(mid) is str and MODEL.fullmatch(mid))
            if mid not in expected:
                extra.add(mid)
                continue
            slot=(rid,mid);observed_p1.add(slot)
            original=p
            native=None
            if row.get('saved_prediction_coverage'):
                try:
                    reader=native_coverage_reader
                    if reader is None:
                        from race_ai.boat_saved_prediction_evidence import native_coverage_evidence
                        reader=native_coverage_evidence
                    native=reader(row,p,now=clock)
                except (ImportError,ValueError,KeyError,TypeError,AttributeError):
                    excluded['NATIVE_COVERAGE_EVIDENCE_UNAVAILABLE_OR_INVALID']+=1
                    continue
                if native is not None:
                    if native['status']!='QUALIFIED_PRE_CUTOFF':
                        excluded['NATIVE_'+native['reason']]+=1
                        continue
                    # Audit-local projection only: retain the exact saved body.
                    p=dict(p,as_of=native['as_of'],generated_at=native['generated_at'],
                           server_saved_at=native['server_saved_at'],cutoff_at=native['cutoff_at'],
                           external_receipt_verified=True,eligible_pre_cutoff=True,
                           computation_completed_at=native.get('computation_completed_at'),
                           clock_proof_kind=native.get('clock_proof_kind'))
            if (p.get('dispatch_status')=='ORIGINAL_REUSED' and mid in {
                    'boat-local-start-course-shadow-v0.1-UNTRAINED',
                    'boat-observed-pairwise-factor-v1','boat-observed-pairwise-start-v1'} and native is None):
                excluded['REUSED_NATIVE_GENERATION_CLOCK_UNVERIFIED']+=1
                continue
            if (p.get('external_receipt_verified') is not True or
                p.get('eligible_pre_cutoff') is not True or
                type(p.get('artifact_id')) is not int or p['artifact_id']<=0 or
                type(p.get('original_json_sha256')) is not str or
                re.fullmatch('[a-f0-9]{64}',p['original_json_sha256']) is None):
                excluded['RECEIPT_OR_PRE_CUTOFF_UNVERIFIED']+=1
                continue
            try:
                asof=_clock(p.get('as_of'))
                saved=_clock(p.get('server_saved_at'))
                proof_clock=(_clock(p['generated_at']) if p.get('generated_at') is not None else
                    _clock(p.get('computation_completed_at')) if native is not None and p.get('clock_proof_kind')=='ACTUAL_NATIVE_CALL_COMPLETION' else
                    _clock(None))
                original_cutoff=_clock(p.get('cutoff_at') or row.get('cutoff_at'))
            except (TypeError,ValueError,AttributeError):
                excluded['P1_TIMESTAMP_INVALID']+=1
                continue
            if original_cutoff!=cutoff:
                conflicts+=1;continue
            # GitHub's artifact metadata can truncate fractional seconds.
            ordered=asof<=saved or (saved.microsecond==0 and
                                    saved<=asof<saved+timedelta(seconds=1))
            if (not ordered or max(asof,proof_clock,saved)>clock or
                max(asof,proof_clock,saved)>=cutoff):
                excluded['P1_NOT_PHYSICALLY_BEFORE_CUTOFF']+=1
                continue
            qualified.add(slot)
            counted_originals.append((rid,original))
    _need(len(seen_races)<=scheduled_races)
    by_model=[dict(model_id=mid,p1_saved_races=sum(k[1]==mid for k in qualified),
                   missing_races=scheduled_races-sum(k[1]==mid for k in qualified))
              for mid in sorted(expected)]
    present=len(qualified);total=scheduled_races*len(expected)
    missing_by_time={'NOT_DUE':0,'PRE_CUTOFF_PENDING':0,'DEADLINE_MISSED':0}
    if official is not None:
        for rid,cutoff in official.items():
            missing=sum((rid,mid) not in qualified for mid in expected)
            state=('NOT_DUE' if clock<cutoff-timedelta(minutes=15) else
                   'PRE_CUTOFF_PENDING' if clock<cutoff else 'DEADLINE_MISSED')
            missing_by_time[state]+=missing
    else:
        missing_by_time={'OFFICIAL_SCHEDULE_NOT_SUPPLIED':total-present}
    scope=_readback_scope_counts(independent_scope,counted_originals,day=day,now=clock)
    return dict(schema='RACE_AI_BOAT_AES_SAVED_VIEW_P1_COUNTS_V1',day_jst=day,
        scheduled_races=scheduled_races,saved_view_race_rows=len(seen_races),
        expected_model_count=len(expected),expected_model_slots=total,
        p1_qualified_unique_slots=present,missing_p1_model_slots=total-present,
        p1_seen_unqualified_slots=len(observed_p1-qualified),
        missing_by_time=missing_by_time,
        unsupported_or_extra_models=len(extra),
        cutoff_conflicts=conflicts,excluded_reasons=dict(sorted(excluded.items())),
        by_model=by_model,independent_scope=scope,
        independently_authenticated_source_zip_claim=scope['whole_counted_scope_reopened'],
        original_forecasts_changed=False,official_source_gets=0)


def _readback_scope_counts(scope,counted,*,day,now):
    """The proof is supplied privately by this audit, never read from the view."""
    result=dict(status='PARTIAL_SCOPE_NOT_REOPENED',qualified_originals=len(counted),
                reopened_qualified_originals=0,unreopened_qualified_originals=len(counted),
                archives_reopened=0,owner_lineages_reopened=0,owner_lineages_verified=0,
                whole_counted_scope_reopened=False)
    if scope is None:return result
    try:
        from race_ai.actions_contract import digest
        from race_ai.boat_saved_model_view import saved_prediction_identity
        _need(type(scope) is dict and scope.get('schema')=='BOAT_INDEPENDENT_ORIGINAL_READBACK_SCOPE_V2'
              and scope.get('day_jst')==day and _clock(scope['checked_at'])<=now
              and scope.get('scope_sha256')==digest({k:v for k,v in scope.items() if k!='scope_sha256'}))
        inventory=scope['inventory'];artifacts=scope['artifacts'];runs=scope['run_ids']
        _need(type(inventory) is dict and type(artifacts) is dict and type(runs) is list
              and runs==sorted(set(runs)) and all(type(r) is int and r>0 for r in runs)
              and type(scope['archives_reopened']) is int and scope['archives_reopened']==len(artifacts))
        _need(all(type(k) is str and re.fullmatch('[a-f0-9]{64}',k) and type(v) is str and
                  re.fullmatch('[a-f0-9]{64}',v) for k,v in inventory.items()))
        for ident,artifact in artifacts.items():
            _need(type(ident) is int and ident>0 and type(artifact) is dict and artifact['artifact_id']==ident
                  and type(artifact['run_id']) is int and artifact['run_id'] in runs
                  and artifact['kind'] in ('ALL_MODEL','P1') and re.fullmatch('[a-f0-9]{40}',artifact['head_sha'])
                  and _clock(artifact['created_at'])<=_clock(scope['checked_at'])
                  and all(type(artifact[k]) is str and re.fullmatch('[a-f0-9]{64}',artifact[k])
                          for k in ('metadata_sha256','zip_sha256')))
        originals={}
        for rid,p in counted:
            identity=digest([rid,saved_prediction_identity(p)]);body=digest(p)
            _need(identity not in originals or originals[identity]==body)
            artifact=artifacts.get(p.get('artifact_id'))
            if inventory.get(identity)==body:
                _need(artifact is not None and
                      (p.get('source_code_commit') is None or p['source_code_commit']==artifact['head_sha']) and
                      (p.get('receipt_run_id') is None or str(p['receipt_run_id'])==str(artifact['run_id'])) and
                      (p.get('server_saved_at') is None or _clock(p['server_saved_at'])==_clock(artifact['created_at'])))
            originals[identity]=body
        reopened=sum(inventory.get(k)==v for k,v in originals.items())
        complete=bool(originals) and scope['archives_reopened']>0 and reopened==len(originals)
        return dict(status='ALL_COUNTED_ORIGINALS_REOPENED' if complete else 'PARTIAL_SCOPE_NOT_REOPENED',
            qualified_originals=len(originals),reopened_qualified_originals=reopened,
            unreopened_qualified_originals=len(originals)-reopened,
            archives_reopened=scope['archives_reopened'],
            owner_lineages_reopened=len({a['run_id'] for a in artifacts.values()}),owner_lineages_verified=len(runs),
            whole_counted_scope_reopened=complete)
    except (ImportError,ValueError,KeyError,TypeError,AttributeError):
        return dict(result,status='HOLD_READBACK_SCOPE_INVALID')


def vault_complete(after,recovery,native,baseline):
    """Whole-day completion also requires this audit's whole counted scope."""
    return (recovery.get('status')=='SAVED_MODEL_RECOVERY_COMPLETE' and
            recovery.get('deferred_artifacts')==0 and recovery.get('deferred_runs')==0 and
            recovery.get('unrepresented_scoped_forecasts')==0 and
            after.get('missing_p1_model_slots')==0 and after.get('cutoff_conflicts')==0 and
            after.get('unsupported_or_extra_models')==0 and
            after.get('independently_authenticated_source_zip_claim') is True and
            after.get('independent_scope',{}).get('whole_counted_scope_reopened') is True and
            native.get('status')=='AUTHENTICATED_NATIVE_COVERAGE' and
            baseline.get('source_owner_conclusion')=='success' and
            type(baseline.get('observed_source_control')) is dict and
            'prepared_round' in baseline['observed_source_control'] and
            baseline['observed_source_control']['prepared_round'] is None)

def _clock(text):
    from datetime import datetime
    if type(text) is not str:raise ValueError('BOAT_OWNER_NATIONAL_P1_MATRIX_CLOCK_INVALID')
    try:value=datetime.fromisoformat(text.replace('Z','+00:00'))
    except (ValueError,OverflowError):raise ValueError('BOAT_OWNER_NATIONAL_P1_MATRIX_CLOCK_INVALID') from None
    if value.utcoffset() is None:raise ValueError('BOAT_OWNER_NATIONAL_P1_MATRIX_CLOCK_INVALID')
    return value
