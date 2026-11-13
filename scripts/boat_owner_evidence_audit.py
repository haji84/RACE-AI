"""Read-only original coverage audit; no source acquisition or dispatch permission.

The runtime uses the exact released owner package for AES/receipt validation.
Pure aggregation never authenticates inputs by itself. Only aggregate counts
are exported; predictions, rosters, media and owner keys remain private.
"""
from collections import Counter
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

OWNER_SHA='203ca70a2ea04124b2cb0ceba9dc4bdad7cc8da9'
HISTORIC_RUN=43348227701
HISTORIC_SHA='0796b52c2804177976e4c2e5ab9b65f32589720b'
JST=timezone(timedelta(hours=9))
RID=re.compile(r'20[0-9]{6}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])\Z')


def need(ok, reason):
    if not ok: raise ValueError('OWNER_AUDIT_'+reason)


def stamp(value):
    try:
        at=datetime.fromisoformat(value.replace('Z','+00:00'))
        need(at.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
        return at
    except (ValueError,TypeError,AttributeError):
        raise ValueError('OWNER_AUDIT_CLOCK_INVALID') from None


def summarize(schedule,p0_rows,p1_rows,attempts,*,day,now,official_program_verified,
              video_rows=(),video_rejections=0):
    """Aggregate caller-authenticated originals, never fill unobserved eligibility."""
    need(type(official_program_verified) is bool and isinstance(now,datetime) and
         now.utcoffset() is not None,'INPUT_INVALID')
    need(type(schedule) is list and 0<len(schedule)<=288,'SCHEDULE_INVALID')
    ledger={}
    for row in schedule:
        rid=row.get('race_id');cutoff=stamp(row.get('cutoff_at'))
        need(type(rid) is str and RID.fullmatch(rid) and rid not in ledger and
             rid[:8]==day.replace('-','') and cutoff.astimezone(JST).date().isoformat()==day,
             'SCHEDULE_IDENTITY_INVALID')
        ledger[rid]=cutoff
    def slots(rows,stage):
        found={};count=0
        for row in rows:
            rid=row.get('race_id');mid=row.get('model_id')
            need(rid in ledger and row.get('stage')==stage and type(mid) is str and 0<len(mid)<=256,
                 'FORECAST_IDENTITY_INVALID')
            generated,saved=stamp(row['as_of']),stamp(row['server_saved_at'])
            # Preserve the original reader's GitHub whole-second receipt rule.
            ordered=generated<=saved or (saved.microsecond==0 and saved<=generated<saved+timedelta(seconds=1))
            need(stamp(row['cutoff_at'])==ledger[rid] and generated<ledger[rid] and
                 saved<ledger[rid] and ordered and saved<=now,'FORECAST_CLOCK_INVALID')
            count+=1;found.setdefault((rid,mid),row)
        return found,count-len(found)
    p0,p0_repeats=slots(p0_rows,'P0');p1,p1_repeats=slots(p1_rows,'P1')
    p0_races={k[0] for k in p0};p1_races={k[0] for k in p1}
    last={};ready=set(p1_races)
    for row in attempts:
        rid=row.get('race_id')
        if rid not in ledger: continue  # Venue/network diagnostic, not an invented race.
        state=row.get('state') or row.get('reason')
        if not (type(state) is str and re.fullmatch('[A-Z0-9_]{1,100}',state)):state='UNCLASSIFIED_OBSERVATION'
        last[rid]=state
        if state=='AB_GENERATED_NOT_YET_EXTERNAL_FROZEN':
            need(re.fullmatch('[a-f0-9]{64}',str(row.get('exhibition_sha256'))) is not None and
                 stamp(row['generated_at'])<ledger[rid] and stamp(row['generated_at'])<=now,
                 'EXHIBITION_READY_EVIDENCE_INVALID')
            ready.add(rid)
    missing=set(ledger)-p1_races
    vrows=list(video_rows)
    for row in vrows:
        need(row.get('variant')=='LEARNED_VIDEO_EXPERIMENTAL','VIDEO_VARIANT_INVALID')
    video,_=slots(vrows,'P1')
    need(type(video_rejections) is int and video_rejections>=0,'VIDEO_COUNT_INVALID')
    return dict(schema='RACE_AI_OWNER_ORIGINAL_EVIDENCE_AUDIT_V1',day_jst=day,
        audited_at=now.isoformat(),scope='BASELINE_ORIGINALS_IN_SELECTED_OWNER_RUN',
        official_program_verified=official_program_verified,
        scheduled_races=len(ledger) if official_program_verified else None,
        retained_schedule_rows=len(ledger),scheduled_venues=len({r[9:11] for r in ledger}),
        baseline_p0_races=len(p0_races),baseline_p1_races=len(p1_races),
        baseline_p0_unique_model_slots=len(p0),baseline_p1_unique_model_slots=len(p1),
        baseline_p0_repeated_slots=p0_repeats,baseline_p1_repeated_slots=p1_repeats,
        scheduled_without_baseline_p1=len(missing),exhibition_ready_proven_races=len(ready),
        p1_missing_after_confirmed_ready=len(ready-p1_races),p1_eligibility_unknown=len(set(ledger)-ready),
        missing_p1_last_observation=dict(sorted(Counter(last.get(r,'NO_RETAINED_OBSERVATION') for r in missing).items())),
        p0_models=dict(sorted(Counter(k[1] for k in p0).items())),
        p1_models=dict(sorted(Counter(k[1] for k in p1).items())),
        video_scope='SELECTED_OWNER_P1_ORIGINALS_ONLY',verified_video_prediction_rows=len(video),
        verified_video_prediction_races=len({k[0] for k in video}),rejected_video_rows=video_rejections,
        all_scheduled_baseline_p1_present=official_program_verified and not missing,
        all_models_complete_proven=False,live_recovery_to_new_p1_proven=False,
        successor_dispatch_allowed=False,official_source_requests=0,new_forecasts=0,originals_changed=False)


def pending_pair_report(control,p1_raw,result_report,nested_p1,*,run,day,digest):
    """Diagnostic only: no repaired control or successor proof is produced."""
    number=control.get('prepared_round')
    need(type(number) is int and number==control['completed_round']+1,'PENDING_ROUND_INVALID')
    need(nested_p1==p1_raw,'PENDING_NESTED_P1_MISMATCH')
    need(result_report.get('report_sha256')==digest({k:v for k,v in result_report.items() if k!='report_sha256'}),
         'PENDING_REPORT_HASH_INVALID')
    need(result_report.get('round_no')==number and str(result_report.get('run_id'))==str(run['id']) and
         result_report.get('code_sha')==run['head_sha'] and result_report.get('day_jst')==day,
         'PENDING_REPORT_SCOPE_INVALID')
    state=result_report.get('bounded_repeat_session',{})
    for a,b in (('requests_used','previous_session_requests'),('completed_round','completed_round'),
                ('prepared_round','prepared_round'),('lifetime_requests','lifetime_requests'),
                ('lifetime_completed_rounds','lifetime_completed_rounds'),
                ('day_start_lifetime_requests','day_start_lifetime_requests')):
        need(type(state.get(a)) is int and state[a]==control.get(b),'PENDING_COUNTER_MISMATCH')
    need(state.get('source_wait') is None and state.get('halted_reason') is None and
         control.get('source_wait') is None and control.get('previous_halted_reason') is None,
         'PENDING_SOURCE_HOLD')
    return dict(status='PENDING_PAIR_BOUND_TO_FINAL_CHECKPOINT',prepared_round=number,
                completed_round=control['completed_round'],requests_used=control['previous_session_requests'],
                verified=True,successor_dispatch_allowed=False)


def inspect_run(repo,run_id,*,now):
    """Use original cryptographic readers with the real audit clock, never backdate."""
    from scripts.boat_private_original_vault import _environment
    from scripts.github_existing_cycle import gh
    from race_ai.boat_owner_source_identity import authenticated_live_owner_run
    from race_ai.boat_pending_round_recovery import read_final_control
    from race_ai.cycle_recovery import artifact_pages
    from race_ai.boat_source_control import _metadata
    from race_ai.boat_private_original_vault import _artifact,REPO_ID
    from race_ai.boat_private_original_archive import open_original_zip
    from race_ai.frozen_day_cycle import read_p0,read_p1
    from race_ai.actions_contract import digest
    from race_ai.boat_program_source import load_program_source
    from race_ai.boat_video_archive import VideoContextArchiveReader,read_optional_video_shadows
    from race_ai.repeated_cycle import artifact_name
    _environment(repo)
    run=json.loads(gh(f'actions/runs/{run_id}'))
    need(authenticated_live_owner_run(run) and run.get('id')==run_id and
         run.get('head_branch')=='production/boat-p0-p1-20261111' and run.get('event')=='workflow_dispatch' and
         run.get('status')=='completed','OWNER_RUN_REJECTED')
    need(run['head_sha']==OWNER_SHA or (run_id==HISTORIC_RUN and run['head_sha']==HISTORIC_SHA),
         'OWNER_SOURCE_NOT_PINNED')
    day=stamp(run['created_at']).astimezone(JST).date().isoformat()
    need(stamp(run['created_at'])<=stamp(run['updated_at'])<=now,'RUN_CLOCK_INVALID')
    listing=artifact_pages(gh,run_id)
    def read(item,kind):
        meta_raw=gh(f'actions/artifacts/{item["id"]}');meta=json.loads(meta_raw)
        need(meta.get('id')==item['id'],'ARTIFACT_ID_CHANGED')
        raw=gh(f'actions/artifacts/{item["id"]}/zip')
        _metadata(raw,meta,name=item['name'],run_id=run_id,head_sha=run['head_sha'])
        _artifact(raw,meta_raw,key=None,now=now,expected_kind=kind)
        return raw,meta
    first=[x for x in listing if x['name']==f'boat-p0-existing-{run_id}']
    need(len(first)==1,'FIRST_P0_MISSING_OR_DUPLICATE')
    raw,meta=read(first[0],'P0');document,p0=read_p0(raw,meta,expected_day=day)
    normalized=dict(repository_id=REPO_ID,repository='haji84/RACE-AI',run_id=str(run_id),head_sha=run['head_sha'],
        artifact_id=meta['id'],created_at=meta['created_at'],payload_sha256=digest(document),independently_verified=True)
    program=load_program_source(day,document,normalized,repo,as_of=now.isoformat())
    p1=[];attempts=[];videos=[];rejected=0;p1_originals={}
    reader=VideoContextArchiveReader(gh)
    for item in sorted(listing,key=lambda x:(x['created_at'],x['id'])):
        if not re.fullmatch(r'boat-national-cutoff-'+str(run_id)+r'(?:-cycle-[0-9]{2,})?',item['name']):continue
        raw,meta=read(item,'P1');doc,rows=read_p1(raw,meta)
        p1.extend(rows);attempts.extend(doc.get('tries',[]));p1_originals[item['name']]=(raw,meta)
        accepted,errors=read_optional_video_shadows(doc,meta,rows,receipt_verifier=reader.verify)
        videos.extend(r for r in accepted if r.get('variant')=='LEARNED_VIDEO_EXPERIMENTAL')
        rejected+=sum(e['rejected_shadows'] for e in errors)
    result=summarize(document['schedule'],p0,p1,attempts,day=day,now=now,
        official_program_verified=program is not None,video_rows=videos,video_rejections=rejected)
    result.update(owner_run_id=run_id,owner_head_sha=run['head_sha'],reader_head_sha=OWNER_SHA,
                  owner_conclusion=run['conclusion'],authenticated_p1_artifacts=len(p1_originals),
                  source_program_sha256=document['source_sha256'])
    control=read_final_control(gh,run)
    result['source_control']={k:control.get(k) for k in ('completed_round','prepared_round',
        'previous_session_requests','lifetime_requests','day_start_lifetime_requests','previous_stop_reason')}
    result['pending_pair']=dict(status='NO_PENDING_ROUND',verified=False,successor_dispatch_allowed=False)
    if control.get('prepared_round') is not None:
        try:
            n=control['prepared_round'];name=artifact_name('race-existing-cycle',run_id,n)
            found=[x for x in listing if x['name']==name]
            need(len(found)==1,'PENDING_RESULT_MISSING_OR_DUPLICATE')
            raw,meta=read(found[0],'RESULT')
            with open_original_zip(raw,meta,expected_kind='RESULT',max_plain_zip_bytes=32*1024*1024) as bundle:
                need(bundle.getinfo('status.json').file_size<=16*1024*1024,'RESULT_REPORT_BOUND')
                report=json.loads(bundle.read('status.json'));nested=bundle.read('current-p1-original.zip')
            original=p1_originals[artifact_name('boat-national-cutoff',run_id,n)]
            result['pending_pair']=pending_pair_report(control,original[0],report,nested,run=run,day=day,digest=digest)
        except (ValueError,KeyError,TypeError) as exc:
            reason=str(exc)
            result['pending_pair']=dict(status='PENDING_PAIR_UNVERIFIED',verified=False,
                reason=reason if re.fullmatch('OWNER_AUDIT_[A-Z_]{1,80}',reason) else 'ORIGINAL_BINDING_UNAVAILABLE',
                successor_dispatch_allowed=False)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',type=Path,required=True);p.add_argument('--run-id',type=int,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args(argv)
    try:
        root=a.repo_root.resolve()
        need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI',
             'TRUSTED_ACTIONS_REQUIRED')
        event=os.environ.get('GITHUB_EVENT_NAME')
        need(event in ('push','workflow_run') and (event!='push' or a.run_id==HISTORIC_RUN),
             'AUDIT_EVENT_REJECTED')
        need(subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,timeout=10).decode().strip()==OWNER_SHA,
             'READER_HEAD_CHANGED')
        sys.path.insert(0,str(root))
        import race_ai
        for folder in ('pr64-reference','pr72-reference'):
            package=root/folder/'race_ai';need(package.is_dir(),'PINNED_PACKAGE_MISSING')
            race_ai.__path__.append(str(package))
        result=inspect_run(root,a.run_id,now=datetime.now(timezone.utc))
        need(not a.output.exists() and not a.output.is_symlink(),'FRESH_OUTPUT_REQUIRED')
        a.output.write_text(json.dumps(result,sort_keys=True)+'\n')
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as exc:
        reason=str(exc)
        safe=reason if re.fullmatch(r'(?:OWNER_AUDIT|VAULT|PROGRAM_SOURCE|SAFE_SOURCE_CONTROL|SELLER_INPUT)_[A-Z0-9_]{1,100}',reason) else 'ORIGINAL_EVIDENCE_UNAVAILABLE'
        print(json.dumps(dict(status='HOLD_OWNER_EVIDENCE_AUDIT',reason=safe,
            official_source_requests=0,new_forecasts=0,successor_dispatch_allowed=False)))
        return 2

if __name__=='__main__':raise SystemExit(main())
