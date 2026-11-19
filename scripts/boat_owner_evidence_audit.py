"""Read-only original coverage audit; no source acquisition or dispatch permission.

The runtime uses the exact released owner package for AES/receipt validation.
Pure aggregation never authenticates inputs by itself. Only aggregate counts
are exported; predictions, rosters, media and owner keys remain private.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

OWNER_SHA='eff296f6d54ad4be297d93e32f1ee0d4592ad9e3'
PREVIOUS_OWNER_SHA='5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4'
REVIEWED_PREVIOUS_OWNER_SHA='84128e0ec8bd9fe3da64ad49f74b8511b07e72be'
RETAINED_OWNER_SHA='b491fb21ce58ba085dd8f54bb7326442b840d8f4'
PRE_STORAGE_REPAIR_SHA='c123b8538006b3189181195bbc91d8f28d216ba5'
HISTORIC_RUN=43348227701
HISTORIC_SHA='0796b52c2804177976e4c2e5ab9b65f32589720b'
JST=timezone(timedelta(hours=9))
RID=re.compile(r'20[0-9]{6}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])\Z')


def need(ok, reason):
    if not ok: raise ValueError('OWNER_AUDIT_'+reason)


def _source_pinned(run_id,head_sha):
    # Historical acceptance is confined to this read-only auditor. Dispatch
    # and the live reader checkout still use the single exact OWNER_SHA.
    return (type(run_id) is int and run_id>0 and type(head_sha) is str and
            (head_sha in (OWNER_SHA,PREVIOUS_OWNER_SHA,REVIEWED_PREVIOUS_OWNER_SHA,RETAINED_OWNER_SHA,PRE_STORAGE_REPAIR_SHA) or
             (run_id==HISTORIC_RUN and head_sha==HISTORIC_SHA)))


def stamp(value):
    try:
        at=datetime.fromisoformat(value.replace('Z','+00:00'))
        need(at.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
        return at
    except (ValueError,TypeError,AttributeError):
        raise ValueError('OWNER_AUDIT_CLOCK_INVALID') from None


def retained_attempts(document):
    """Read the real producer schema, never treat an unknown field as no attempts."""
    need(type(document) is dict and document.get('schema')=='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
         'P1_DOCUMENT_SCHEMA_INVALID')
    rows=document.get('candidate_attempts')
    need(type(rows) is list and all(type(row) is dict for row in rows),'P1_ATTEMPTS_MISSING')
    return rows


def first_p0_original(get, run, listing):
    """Resolve a continuation's earlier canonical first P0 without regeneration."""
    first=[x for x in listing if x.get('name')==f'boat-p0-existing-{run["id"]}']
    if first:
        need(len(first)==1,'FIRST_P0_MISSING_OR_DUPLICATE')
        return first[0],run
    # This auditor is loaded from exact main while its native AES readers run
    # in the pinned producer checkout. Load the adjacent main gate explicitly.
    import importlib.util
    path=Path(__file__).with_name('boat_main_dispatch_gate.py')
    spec=importlib.util.spec_from_file_location('canonical_p0_recovery_gate',path)
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    def document(endpoint):
        return json.loads(get(endpoint))
    reference=document('git/ref/heads/feat/four-sport-forecast-audit-view-20261022')
    commit=(reference.get('object') or {}).get('sha')
    need(type(commit) is str and re.fullmatch('[a-f0-9]{40}',commit),'FIRST_P0_RECEIPT_REF_INVALID')
    selected=gate.resolve_recovery_selection(run=run,
        artifacts=dict(total_count=len(listing),artifacts=listing),get=document,receipt_commit=commit)
    origin=document(f'actions/runs/{selected["source_run_id"]}')
    item=document(f'actions/artifacts/{selected["p0_artifact"]}')
    need(origin.get('id')==selected['source_run_id'] and origin.get('head_sha')==selected['source_sha'],
         'FIRST_P0_ORIGIN_CHANGED')
    return item,origin


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
        found={};count=0;conflicts=set()
        for row in rows:
            rid=row.get('race_id');mid=row.get('model_id')
            need(rid in ledger and row.get('stage')==stage and type(mid) is str and 0<len(mid)<=256,
                 'FORECAST_IDENTITY_INVALID')
            generated,saved=stamp(row['as_of']),stamp(row['server_saved_at'])
            # Preserve the original reader's GitHub whole-second receipt rule.
            ordered=generated<=saved or (saved.microsecond==0 and saved<=generated<saved+timedelta(seconds=1))
            cutoff=stamp(row['cutoff_at'])
            need(cutoff.astimezone(JST).date().isoformat()==day,'FORECAST_SOURCE_DAY_MISMATCH')
            need(generated<cutoff and saved<cutoff,'FORECAST_ORIGINAL_CUTOFF_INVALID')
            need(ordered and saved<=now,'FORECAST_CLOCK_INVALID')
            if cutoff!=ledger[rid]:conflicts.add(rid)
            count+=1;found.setdefault((rid,mid),row)
        return found,count-len(found),conflicts
    p0,p0_repeats,p0_conflicts=slots(p0_rows,'P0')
    p1,p1_repeats,p1_conflicts=slots(p1_rows,'P1')
    p0_races={k[0] for k in p0};p1_races={k[0] for k in p1}
    last={};ready=set(p1_races)
    for row in attempts:
        rid=row.get('race_id')
        if rid not in ledger: continue  # Venue/network diagnostic, not an invented race.
        state=row.get('state') or row.get('reason')
        if not (type(state) is str and re.fullmatch('[A-Z0-9_]{1,100}',state)):state='UNCLASSIFIED_OBSERVATION'
        last[rid]=state
        if state=='AB_GENERATED_NOT_YET_EXTERNAL_FROZEN' and rid not in p1_races:
            need(re.fullmatch('[a-f0-9]{64}',str(row.get('exhibition_sha256'))) is not None and
                 stamp(row['generated_at'])<=now,'EXHIBITION_READY_EVIDENCE_INVALID')
            if stamp(row['generated_at'])<ledger[rid]:ready.add(rid)
            else:last[rid]='GENERATED_AFTER_PROGRAM_CUTOFF_UNRESOLVED'
    missing=set(ledger)-p1_races
    vrows=list(video_rows)
    for row in vrows:
        need(row.get('variant')=='LEARNED_VIDEO_EXPERIMENTAL','VIDEO_VARIANT_INVALID')
    video,_,video_conflicts=slots(vrows,'P1')
    need(type(video_rejections) is int and video_rejections>=0,'VIDEO_COUNT_INVALID')
    return dict(schema='RACE_AI_OWNER_ORIGINAL_EVIDENCE_AUDIT_V1',day_jst=day,
        audited_at=now.isoformat(),scope='BASELINE_ORIGINALS_IN_SELECTED_OWNER_RUN',
        official_program_verified=official_program_verified,
        scheduled_races=len(ledger) if official_program_verified else None,
        retained_schedule_rows=len(ledger),scheduled_venues=len({r[9:11] for r in ledger}),
        baseline_p0_races=len(p0_races),baseline_p1_races=len(p1_races),
        baseline_p0_unique_model_slots=len(p0),baseline_p1_unique_model_slots=len(p1),
        baseline_p0_repeated_slots=p0_repeats,baseline_p1_repeated_slots=p1_repeats,
        p0_schedule_cutoff_conflict_races=len(p0_conflicts),
        p1_schedule_cutoff_conflict_races=len(p1_conflicts),
        video_schedule_cutoff_conflict_races=len(video_conflicts),
        scheduled_without_baseline_p1=len(missing),exhibition_ready_proven_races=len(ready),
        p1_missing_after_confirmed_ready=len(ready-p1_races),p1_eligibility_unknown=len(set(ledger)-ready),
        missing_p1_last_observation=dict(sorted(Counter(last.get(r,'NO_RETAINED_OBSERVATION') for r in missing).items())),
        p0_models=dict(sorted(Counter(k[1] for k in p0).items())),
        p1_models=dict(sorted(Counter(k[1] for k in p1).items())),
        video_scope='SELECTED_OWNER_P1_ORIGINALS_ONLY',verified_video_prediction_rows=len(video),
        verified_video_prediction_races=len({k[0] for k in video}),rejected_video_rows=video_rejections,
        all_scheduled_baseline_p1_present=official_program_verified and not missing and not p1_conflicts,
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


def inspect_failed_checkpoint(*,get,run_id,now,key=None):
    """Audit a historical zero-round AES checkpoint without creating a proof.

    A failed P0 save can have no same-run first P0. Authenticate its exact
    continuity and public companion at the real audit clock instead. This
    reader never calls the same-day recovery admission or changes counters.
    """
    from race_ai import boat_all_model_recovery as R
    from race_ai.cycle_recovery import artifact_pages
    from race_ai import boat_private_original_archive as archive
    from race_ai import boat_source_control as source
    need(callable(get) and type(run_id) is int and run_id>0 and
         isinstance(now,datetime) and now.utcoffset() is not None,'CHECKPOINT_INPUT_INVALID')
    reader=R._MetadataReader(get)
    run=R._run(reader.read(f'actions/runs/{run_id}',1024*1024),run_id,now)
    need(_source_pinned(run_id,run['head_sha']) and
         run.get('head_branch')=='production/boat-p0-p1-20261111' and
         run.get('event')=='workflow_dispatch' and run.get('status')=='completed' and
         run.get('conclusion')=='failure' and type(run.get('run_attempt')) is int and
         run['run_attempt']==1,'FAILED_CHECKPOINT_RUN_REJECTED')
    listed=artifact_pages(reader,run_id)
    need(2<=len(listed)<=128 and all(type(a.get('name')) is str for a in listed) and
         len({a['name'] for a in listed})==len(listed),'CHECKPOINT_INVENTORY_INVALID')
    forbidden=re.compile(r'(?:boat-national-cutoff|race-existing-cycle)-'+str(run_id)+
                         r'(?:-cycle-[0-9]+)?\Z')
    need(not any(forbidden.fullmatch(a['name']) for a in listed),'CHECKPOINT_HAS_PENDING_ARTIFACTS')
    packets=[]
    for prefix,limit in (('race-source-control',source.MAX_SUMMARY_ZIP),
                         ('race-cycle-continuity',source.MAX_CONTINUITY_ZIP)):
        selected=[a for a in listed if a['name']==f'{prefix}-{run_id}']
        need(len(selected)==1,'CHECKPOINT_MISSING_OR_DUPLICATE')
        item=selected[0];ident=item['id']
        meta=json.loads(reader.read(f'actions/artifacts/{ident}',128*1024))
        need(all(meta.get(k)==item.get(k) for k in
                 ('id','name','size_in_bytes','digest','created_at','expired')) and
             meta.get('expired') is False and
             stamp(run['created_at'])<=stamp(meta.get('created_at'))<=stamp(run['updated_at']) and
             now<stamp(meta.get('expires_at')),'CHECKPOINT_METADATA_CHANGED_OR_EXPIRED')
        raw=get(f'actions/artifacts/{ident}/zip')
        need(type(raw) is bytes and 0<len(raw)<=limit,'CHECKPOINT_ZIP_BOUND_INVALID')
        packets.append((raw,meta))
    public,public_meta=packets[0];continuity,continuity_meta=packets[1]
    control=source.read_summary(public,public_meta,continuity,continuity_meta,
                                run_id=run_id,head_sha=run['head_sha'])
    with archive._checked_zip(continuity,max_zip_bytes=source.MAX_CONTINUITY_ZIP) as z:
        need(z.namelist()==[archive.CIPHER_MEMBER],'CHECKPOINT_CIPHER_REQUIRED')
        cipher=z.read(archive.CIPHER_MEMBER)
    # build_summary performs real AES authentication, validates the sealed
    # session, and exports only whitelisted fields. Opaque ZIP binding alone
    # is insufficient; every public field must equal this decrypted summary.
    derived=source.build_summary(cipher,run_id=run_id,head_sha=run['head_sha'],key=key)
    with archive._checked_zip(public,max_zip_bytes=source.MAX_SUMMARY_ZIP,
                              max_expanded=source.MAX_SUMMARY) as z:
        need(z.namelist()==[source.MEMBER],'CHECKPOINT_PUBLIC_MEMBERS_INVALID')
        need(source._json(z.read(source.MEMBER))==derived,'CHECKPOINT_AES_PUBLIC_DISAGREE')
    need(control['completed_round']==0 and control['prepared_round'] is None and
         control['previous_session_requests']==0 and control['source_wait'] is None and
         control['previous_halted_reason'] is None and control['previous_stop_reason'] is None and
         type(control.get('day_start_lifetime_requests')) is int and
         control['day_start_lifetime_requests']<=control['lifetime_requests'],
         'CHECKPOINT_NOT_ZERO_ROUND')
    return dict(status='FAILED_OWNER_CHECKPOINT_AES_VERIFIED_READONLY',
        owner_run_id=run_id,owner_head_sha=run['head_sha'],day_jst=control['day_jst'],
        audit_at=now.isoformat(),failed_session_requests=control['previous_session_requests'],
        inherited_same_day_requests=control['lifetime_requests']-control['day_start_lifetime_requests'],
        lifetime_requests=control['lifetime_requests'],
        lifetime_completed_rounds=control['lifetime_completed_rounds'],
        continuity_artifact_id=continuity_meta['id'],continuity_zip_digest=continuity_meta['digest'],
        source_control_artifact_id=public_meta['id'],source_control_zip_digest=public_meta['digest'],
        aes_authenticated=True,public_counters_match_AES=True,
        successor_dispatch_allowed=False,live_recovery_to_new_p1_proven=False,
        official_source_requests=0,new_forecasts=0,original_forecasts_changed=False)


def native_official_schedule(document,receipt,program,*,now):
    """Derive only the exact first-P0 ledger authenticated against raw B bytes."""
    from race_ai.boat_seller_inputs import official_b_cards_source,OFFICIAL_B_SCHEMA
    need(type(program) is dict and program.get('schema')==OFFICIAL_B_SCHEMA,
         'NATIVE_OFFICIAL_B_SOURCE_REQUIRED')
    # Reuse the actual source parser: a boolean, a forecast cutoff, or a typed
    # dictionary without the retained B bytes cannot manufacture this ledger.
    checked=official_b_cards_source(program.get('raw'),document,receipt,
        day=document.get('day_jst'),as_of=now)
    need(checked==program,'NATIVE_OFFICIAL_B_BINDING_CHANGED')
    return [dict(race_id=row['race_id'],cutoff_at=row['cutoff_at'],
                 schedule_captured_at=document['captured_at'],source_sha256=document['source_sha256'])
            for row in document['schedule']]


def hydrate_native_matrix_view(view,context,*,now):
    """Consume the inspector's private AES readback without altering forecasts."""
    if type(context) is not dict or context.get('status')!='AUTHENTICATED_OWNER_NATIVE_CONTEXT':
        return deepcopy(view),dict(status='HOLD_NATIVE_OFFICIAL_CONTEXT',native_pre_cutoff_qualified=0)
    try:
        from race_ai.boat_saved_prediction_evidence import hydrate_prediction_evidence,native_coverage_evidence
    except ImportError:
        return deepcopy(view),dict(status='HOLD_NATIVE_READER_UNAVAILABLE',native_pre_cutoff_qualified=0)
    from race_ai.saved_view_feed import forecast_inventory
    ledger=native_official_schedule(context['first_p0_document'],context['first_p0_receipt'],
                                   context['official_program'],now=now)
    need(ledger==context['official_schedule'],'NATIVE_OFFICIAL_LEDGER_CHANGED')
    before=forecast_inventory(view)
    output,counts=hydrate_prediction_evidence(view,context['p1_originals'],
        official_schedule=ledger,now=now)
    need(forecast_inventory(output)==before and counts['originals_unchanged'] is True,
         'NATIVE_ORIGINALS_CHANGED')
    return output,dict(counts,status='AUTHENTICATED_NATIVE_COVERAGE')


def _matrix_native_prediction_bodies(document,entries,wrapper,metadata):
    """Enumerate exact existing legacy/enriched native projection protocols.

    Inputs come only from the reopened AES document and GH receipt. Row-level
    names/results/sidecars are outside a prediction dictionary. No view value
    supplies a field, a hash, or a projection exception here.
    """
    from race_ai.actions_contract import digest
    from race_ai.private_cycle_projection import _prediction
    from race_ai.boat_saved_prediction_evidence import _native_facts
    from race_ai.boat_saved_view_intake import _native_key
    bodies={}
    for key,matches in entries.items():
        need(len(matches)==1,'MATRIX_NATIVE_ENTRY_AMBIGUOUS')
        entry=matches[0];model=entry['model']
        roster=_native_facts(document,entry,metadata)[1]
        saved=dict(race_id=entry['race_id'],sport='boat',stage=entry['stage'],model_id=model['model_id'],
            as_of=entry['as_of'],cutoff_at=entry['cutoff_at'],server_saved_at=metadata['created_at'],
            artifact_id=metadata['id'],original_json_sha256=wrapper['member_sha256'],model_sha256=key[3],
            roster={str(k):v for k,v in roster.items()},top8=entry['top8'],ranked=entry['ranked'],calibrated=False)
        for field in ('variant','training_sha256','baseline_model_sha256'):
            if field in model:saved[field]=deepcopy(model[field])
        receipt=model.get('training_receipt')
        for enrich in (False,True):
            # Existing project_state without retained documents, or its exact
            # native enrichment. Missing legacy metadata stays explicit null.
            projected_row=deepcopy(saved)
            if enrich and type(receipt) is dict:
                projected_row.update(training_artifact_id=receipt.get('id'),training_receipt_digest=receipt.get('digest'))
            prediction=_prediction(projected_row,entries if enrich else {})[0]
            profiles=[prediction,dict(prediction,source_code_commit=metadata['workflow_run']['head_sha'])]
            # Exact project_native_state receipt acknowledgement protocol.
            acknowledged=deepcopy(profiles[-1]);acknowledged['external_receipt_verified']=True
            acknowledged['missing_reasons']=[r for r in acknowledged['missing_reasons']
                if r!='EXTERNAL_RECEIPT_NOT_INDEPENDENTLY_VERIFIED']
            profiles.append(acknowledged)
            for candidate in profiles:
                body_key=digest(_native_key(entry['race_id'],candidate))
                bodies.setdefault(body_key,set()).add(digest(candidate))
    return bodies


def reopen_matrix_view(view,get,*,selected_owner,day,now,key=None):
    """Fresh readback of all owners cited by this day's immutable originals.

    Only the audit copy loses derived caches. Exact GitHub responses and the
    existing AES readers establish scope; saved receipt booleans establish none.
    The returned private context must never be serialized to public output.
    """
    from hashlib import sha256
    from race_ai import boat_all_model_recovery as R
    from race_ai.actions_contract import digest
    from race_ai.boat_pdca_state import state_key
    from race_ai.saved_view_feed import forecast_inventory
    from race_ai.boat_saved_view_intake import _native_key
    from race_ai.boat_source_control import _metadata
    from race_ai.boat_saved_prediction_evidence import _read_archive
    need(type(selected_owner) is int and selected_owner>0 and callable(get), 'MATRIX_OWNER_REQUIRED')
    R._day(day);before=forecast_inventory(view)
    class Reads:
        def __init__(self):self.responses={}
        def __call__(self,path):
            raw=get(path)
            need(type(raw) is bytes,'MATRIX_RESPONSE_BYTES_REQUIRED')
            self.responses[path]=raw
            return raw
        def is_archived(self,ident):
            capability=R._declared_capability(get,'is_archived')
            return capability is not None and capability(ident) is True
    reads=Reads();runs={};metadata={}
    def owner(ident):
        if ident not in runs:
            raw=reads(f'actions/runs/{ident}')
            run=R._run(raw,ident,max(now,R._observed_clock()))
            need(stamp(run['created_at']).astimezone(JST).date().isoformat()==day,
                 'MATRIX_OWNER_DAY_CONFLICT')
            runs[ident]=run
        return runs[ident]
    def artifact(ident):
        if ident not in metadata:
            raw=reads(f'actions/artifacts/{ident}')
            meta=R._json(raw,128*1024)
            need(type(meta) is dict and meta.get('id')==ident,'MATRIX_ARTIFACT_ID_CONFLICT')
            run=owner(meta.get('workflow_run',{}).get('id'))
            observed=max(now,R._observed_clock())
            need(stamp(run['created_at'])<=stamp(meta['created_at'])<=observed,
                 'MATRIX_ARTIFACT_OWNER_CLOCK_CONFLICT')
            metadata[ident]=R._metadata(raw,meta,run,observed,reads)[0]
        return metadata[ident]
    def predictions(value):
        return [(row,p) for row in value['records'] if row.get('event_date_jst')==day
                for p in [row.get('prediction'),*row.get('comparison_predictions',[])]
                if p is not None and p.get('stage')=='P1']
    def discover(value):
        for row,p in predictions(value):
            ident=p.get('artifact_id')
            if type(ident) is not int or ident<=0:continue
            meta=artifact(ident);run=meta['workflow_run']
            need((p.get('source_code_commit') is None or p['source_code_commit']==run['head_sha']) and
                 (p.get('receipt_run_id') is None or str(p['receipt_run_id'])==str(run['id'])),
                 'MATRIX_ORIGINAL_OWNER_CONFLICT')
            need(all(p.get(field) is None or stamp(p[field])==stamp(meta['created_at'])
                     for field in ('server_saved_at','persisted_at')), 'MATRIX_PHYSICAL_CLOCK_CONFLICT')
    owner(selected_owner);discover(view)
    need(len(runs)<=R.MAX_RUNS,'MATRIX_LINEAGE_BOUND')
    audit_view=deepcopy(view)
    for row in audit_view['records']:
        for field in (R.EVIDENCE_FIELD,'saved_prediction_evidence','saved_prediction_coverage'):
            row.pop(field,None)
    replayed,counts=R.recover_saved_models(audit_view,reads,run_ids=sorted(runs),day=day,
                                         key=key,max_artifacts=R.MAX_ARTIFACTS)
    discover(replayed)
    actual_key=state_key('production',key)
    coverage=R._read_coverage(replayed,R._coverage_key(actual_key),max(now,R._observed_clock())).get(day,{})
    verified={};opened={};native=[];native_bodies={}
    def descriptor(meta):
        ident=meta['id'];meta_raw=reads.responses[f'actions/artifacts/{ident}']
        raw=reads.responses[f'actions/artifacts/{ident}/zip']
        need(meta['digest']=='sha256:'+sha256(raw).hexdigest() and meta['size_in_bytes']==len(raw),
             'MATRIX_READBACK_HASH_CONFLICT')
        need(stamp(owner(meta['workflow_run']['id'])['created_at'])<=stamp(meta['created_at'])<=max(now,R._observed_clock()),
             'MATRIX_ARTIFACT_OWNER_CLOCK_CONFLICT')
        return dict(artifact_id=ident,run_id=meta['workflow_run']['id'],head_sha=meta['workflow_run']['head_sha'],
                    metadata_sha256=sha256(meta_raw).hexdigest(),zip_sha256=sha256(raw).hexdigest(),
                    created_at=meta['created_at'])
    for entry in coverage.values():
        state=entry['state'];ident=state['artifact']['id']
        need(f'actions/artifacts/{ident}/zip' in reads.responses,'MATRIX_CACHE_IS_NOT_FRESH_READBACK')
        meta=R._json(reads.responses[f'actions/artifacts/{ident}'],128*1024)
        desc=descriptor(meta)
        need(desc['metadata_sha256']==state['artifact']['metadata_sha256'] and
             desc['run_id']==state['run_id'] and desc['head_sha']==state['head_sha'],
             'MATRIX_ARCHIVE_SCOPE_CONFLICT')
        run=owner(state['run_id'])
        fresh,_,_=R._project(reads.responses[f'actions/artifacts/{ident}/zip'],meta,run,state['round_no'],key)
        genuine={_native_key(row['race_id'],p):p for row,p in predictions(fresh) if p.get('artifact_id')==ident}
        for row,p in predictions(fresh):
            if p.get('artifact_id')!=ident:
                native_bodies.setdefault(digest(_native_key(row['race_id'],p)),set()).add(digest(p))
        own={}
        for row,p in predictions(replayed):
            if p.get('artifact_id')!=ident:continue
            original=genuine.get(_native_key(row['race_id'],p))
            need(original is not None and digest(p)==digest(original),'MATRIX_PROJECTED_BODY_CONFLICT')
            own[digest([row['race_id'],R.saved_prediction_identity(original)])]=digest(original)
        opened[ident]=dict(desc,kind='ALL_MODEL')
        # Reused native outputs cite a different physical artifact. They need
        # their own native AES readback below, even when this MAC also names them.
        need(all(state['scoped_inventory'].get(k)==v for k,v in own.items()),'MATRIX_INVENTORY_CONFLICT')
        verified.update(own)
    for ident,meta in sorted(metadata.items()):
        if not re.fullmatch(r'boat-national-cutoff-'+str(meta['workflow_run']['id'])+r'(?:-cycle-[0-9]{2,})?',meta['name']):
            continue
        raw=reads(f'actions/artifacts/{ident}/zip')
        _metadata(raw,meta,name=meta['name'],run_id=meta['workflow_run']['id'],head_sha=meta['workflow_run']['head_sha'])
        from race_ai.boat_private_original_archive import _checked_zip,CIPHER_MEMBER
        with _checked_zip(raw,max_zip_bytes=R.MAX_ZIP_BYTES,max_expanded=R.MAX_ZIP_BYTES) as z:
            need(z.namelist()==[CIPHER_MEMBER],'MATRIX_NATIVE_AES_REQUIRED')
        document,entries,wrapper=_read_archive(raw,meta,key)
        for body_key,hashes in _matrix_native_prediction_bodies(document,entries,wrapper,meta).items():
            native_bodies.setdefault(body_key,set()).update(hashes)
        opened[ident]=dict(descriptor(meta),kind='P1');native.append((raw,meta))
    for row,p in predictions(replayed):
        artifact=opened.get(p.get('artifact_id'))
        if artifact is not None and artifact['kind']=='P1':
            need(digest(p) in native_bodies.get(digest(_native_key(row['race_id'],p)),set()),
                 'MATRIX_NATIVE_BODY_CONFLICT')
    after=forecast_inventory(replayed)
    need(all(after.get(k)==v for k,v in before.items()),'MATRIX_ORIGINAL_INVENTORY_CHANGED')
    context=dict(schema='BOAT_PRIVATE_FRESH_MATRIX_READBACK_V2',day_jst=day,
        checked_at=max(now,R._observed_clock()).isoformat(),
        run_ids=sorted(runs),inventory=verified,artifacts=opened,native_originals=native,
        native_prediction_bodies={k:sorted(v) for k,v in native_bodies.items()})
    context['context_sha256']=digest({k:v for k,v in context.items() if k not in ('native_originals','context_sha256')})
    return replayed,counts,context


def matrix_readback_scope(view,context,*,now):
    """Bind freshly reopened native/ALL_MODEL outputs to preserved dictionaries."""
    from race_ai.actions_contract import digest
    from race_ai.boat_saved_model_view import saved_prediction_identity
    from race_ai.saved_view_feed import forecast_inventory
    from race_ai.boat_saved_view_intake import _native_key
    need(type(context) is dict and context.get('schema')=='BOAT_PRIVATE_FRESH_MATRIX_READBACK_V2' and
         stamp(context['checked_at'])<=now and context['context_sha256']==digest({k:v for k,v in context.items()
             if k not in ('native_originals','context_sha256')}),'MATRIX_FRESH_CONTEXT_REQUIRED')
    current=forecast_inventory(view);verified=dict(context['inventory'])
    need(all(current.get(k)==v for k,v in verified.items()),'MATRIX_READBACK_ORIGINAL_CHANGED')
    try:
        from race_ai.boat_saved_prediction_evidence import native_coverage_evidence
    except ImportError:
        native_coverage_evidence=None
    for row in view['records']:
        if row.get('event_date_jst')!=context['day_jst']:continue
        for p in [row.get('prediction'),*row.get('comparison_predictions',[])]:
            if p is None or p.get('stage')!='P1':continue
            artifact=context['artifacts'].get(p.get('artifact_id'))
            if artifact is None or artifact['kind']!='P1' or native_coverage_evidence is None:continue
            need(digest(p) in context['native_prediction_bodies'].get(digest(_native_key(row['race_id'],p)),[]),
                 'MATRIX_NATIVE_BODY_CONFLICT')
            proof=native_coverage_evidence(row,p,now=now)
            if proof is None:continue
            need(proof['artifact_id']==artifact['artifact_id'] and stamp(proof['server_saved_at'])==stamp(artifact['created_at']),
                 'MATRIX_NATIVE_RECEIPT_CONFLICT')
            verified[digest([row['race_id'],saved_prediction_identity(p)])]=digest(p)
    artifacts=context['artifacts']
    scope=dict(schema='BOAT_INDEPENDENT_ORIGINAL_READBACK_SCOPE_V2',day_jst=context['day_jst'],
        checked_at=context['checked_at'],run_ids=context['run_ids'],inventory=verified,
        archives_reopened=len(artifacts),all_model_archives_reopened=sum(v['kind']=='ALL_MODEL' for v in artifacts.values()),
        native_archives_reopened=sum(v['kind']=='P1' for v in artifacts.values()),
        artifacts=deepcopy(artifacts))
    scope['scope_sha256']=digest(scope)
    return scope


def inspect_run(repo,run_id,*,now,private_native=None):
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
    need(private_native is None or (type(private_native) is dict and not private_native),
         'FRESH_PRIVATE_NATIVE_CONTEXT_REQUIRED')
    _environment(repo)
    run=json.loads(gh(f'actions/runs/{run_id}'))
    need(authenticated_live_owner_run(run) and run.get('id')==run_id and
         run.get('head_branch')=='production/boat-p0-p1-20261111' and run.get('event')=='workflow_dispatch' and
         run.get('status')=='completed','OWNER_RUN_REJECTED')
    need(_source_pinned(run_id,run['head_sha']),
         'OWNER_SOURCE_NOT_PINNED')
    day=stamp(run['created_at']).astimezone(JST).date().isoformat()
    need(stamp(run['created_at'])<=stamp(run['updated_at'])<=now,'RUN_CLOCK_INVALID')
    listing=artifact_pages(gh,run_id)
    def read(item,kind,*,origin=None):
        origin=run if origin is None else origin
        meta_raw=gh(f'actions/artifacts/{item["id"]}');meta=json.loads(meta_raw)
        need(meta.get('id')==item['id'],'ARTIFACT_ID_CHANGED')
        raw=gh(f'actions/artifacts/{item["id"]}/zip')
        _metadata(raw,meta,name=item['name'],run_id=origin['id'],head_sha=origin['head_sha'])
        _artifact(raw,meta_raw,key=None,now=now,expected_kind=kind)
        return raw,meta
    first,p0_origin=first_p0_original(gh,run,listing)
    raw,meta=read(first,'P0',origin=p0_origin);document,p0=read_p0(raw,meta,expected_day=day)
    normalized=dict(repository_id=REPO_ID,repository='haji84/RACE-AI',
        run_id=str(meta['workflow_run']['id']),head_sha=meta['workflow_run']['head_sha'],
        artifact_id=meta['id'],created_at=meta['created_at'],payload_sha256=digest(document),independently_verified=True)
    program=load_program_source(day,document,normalized,repo,as_of=now.isoformat())
    p1=[];attempts=[];videos=[];rejected=0;p1_originals={}
    reader=VideoContextArchiveReader(gh)
    for item in sorted(listing,key=lambda x:(x['created_at'],x['id'])):
        if not re.fullmatch(r'boat-national-cutoff-'+str(run_id)+r'(?:-cycle-[0-9]{2,})?',item['name']):continue
        raw,meta=read(item,'P1');doc,rows=read_p1(raw,meta)
        p1.extend(rows);attempts.extend(retained_attempts(doc));p1_originals[item['name']]=(raw,meta)
        accepted,errors=read_optional_video_shadows(doc,meta,rows,receipt_verifier=reader.verify)
        videos.extend(r for r in accepted if r.get('variant')=='LEARNED_VIDEO_EXPERIMENTAL')
        rejected+=sum(e['rejected_shadows'] for e in errors)
    result=summarize(document['schedule'],p0,p1,attempts,day=day,now=now,
        official_program_verified=program is not None,video_rows=videos,video_rejections=rejected)
    result.update(owner_run_id=run_id,owner_head_sha=run['head_sha'],reader_head_sha=OWNER_SHA,
                  first_p0_origin_run_id=p0_origin['id'],first_p0_origin_sha=p0_origin['head_sha'],
                  owner_conclusion=run['conclusion'],authenticated_p1_artifacts=len(p1_originals),
                  source_program_sha256=document['source_sha256'])
    control=read_final_control(gh,run)
    result['source_control']={k:control.get(k) for k in ('completed_round','prepared_round',
        'previous_session_requests','lifetime_requests','day_start_lifetime_requests',
        'lifetime_completed_rounds','previous_stop_reason')}
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
    if private_native is not None:
        # This object stays in this job's memory. It is deliberately absent
        # from the returned public count report and all uploaded artifacts.
        if program is None:
            private_native.update(status='HOLD_OFFICIAL_B_SOURCE_UNAVAILABLE')
        else:
            ledger=native_official_schedule(document,normalized,program,now=now)
            private_native.update(status='AUTHENTICATED_OWNER_NATIVE_CONTEXT',
                owner_run_id=run_id,owner_head_sha=run['head_sha'],day_jst=day,
                first_p0_document=document,first_p0_receipt=normalized,official_program=program,
                official_schedule=ledger,p1_originals=list(p1_originals.values()),attempts=attempts,
                source_control=deepcopy(result['source_control']))
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
