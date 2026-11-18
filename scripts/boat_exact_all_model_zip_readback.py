"""Reopen EVERY exact BOAT ALL_MODEL Actions ZIP on a different Actions runner.

Unlike normal recovery, this verifier never skips archived ZIPs merely because
their HMAC-backed coverage is already recorded. It re-fetches each native
artifact's exact GitHub metadata and ZIP bytes, verifies the physical SHA256,
decrypts the AES payload with the existing production owner key, projects its
original prediction without generating anything, checks cutoff against the
physical GitHub receipt, then matches unchanged prediction contents to the
separately AES-authenticated saved-view original when present.

Only count-level statistics leave the private runner. No racing-provider GET,
prediction regeneration, forecast edits, uploads, or local persistent storage.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import re

OWNER_SHA='eff296f6d54ad4be297d93e32f1ee0d4592ad9e3'
M2_OWNER_SHA='86b029ae5bddd5d4956497d8b32b2c92b8eec521'
PROFILE_OWNER_SHA='f55351dce855177a51330f72c37d6238ba2c9e3e'
RETENTION_OWNER_SHA='bb49215034b779ea1493b35dd91e5c3ebfc04032'
ATOMIC_OWNER_SHA='a74f1e940e7fc0852e63938f8138bdb58bd93163'
RESEARCH_CACHE_OWNER_SHA='f1f8ed4ffb2a29e6b702685f49de63918610479d'
VENUE_DIAGNOSTIC_OWNER_SHA='c979aeb678538d99e277f26726047dccbdc982af'
HTTP_CAPTURE_CLOCK_OWNER_SHA='995ef00a2ffb98a0161e1875d7d2a33145367b40'
PARTIAL_RECEIPT_OWNER_SHAS=(M2_OWNER_SHA,PROFILE_OWNER_SHA,RETENTION_OWNER_SHA,ATOMIC_OWNER_SHA,RESEARCH_CACHE_OWNER_SHA,VENUE_DIAGNOSTIC_OWNER_SHA,HTTP_CAPTURE_CLOCK_OWNER_SHA)
# Read-only replay of already sealed originals. This is not a dispatcher pin.
PREVIOUS_OWNER_SHA='5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4'
REVIEWED_PREVIOUS_OWNER_SHA='84128e0ec8bd9fe3da64ad49f74b8511b07e72be'
RETAINED_OWNER_SHA='b491fb21ce58ba085dd8f54bb7326442b840d8f4'
PRE_STORAGE_REPAIR_SHA='c123b8538006b3189181195bbc91d8f28d216ba5'
SCHEMA='RACE_AI_BOAT_EXACT_ALL_MODEL_ZIP_READBACK_V1'
JST=timezone(timedelta(hours=9))
SHA=re.compile(r'[a-f0-9]{64}\Z')
RACE=re.compile(r'20[0-9]{6}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])\Z')
MODEL=re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')


class OfficialProgramUnavailable(ValueError):
    """Only the program reader's explicit absent-index result creates this HOLD."""
    def __init__(self):
        super().__init__('BOAT_EXACT_ZIP_READBACK_OFFICIAL_PROGRAM_UNAVAILABLE')


def need(ok):
    if not ok:raise ValueError('BOAT_EXACT_ZIP_READBACK_REJECTED')


def _owner_head(value):
    need(type(value) is str and value in (OWNER_SHA,*PARTIAL_RECEIPT_OWNER_SHAS,PREVIOUS_OWNER_SHA,REVIEWED_PREVIOUS_OWNER_SHA,RETAINED_OWNER_SHA,PRE_STORAGE_REPAIR_SHA))
    return value


def moment(text):
    try:
        need(type(text) is str and len(text)<=64)
        instant=datetime.fromisoformat(text.replace('Z','+00:00'))
        need(instant.utcoffset() is not None)
        return instant
    except (TypeError,ValueError,OverflowError,AttributeError):
        raise ValueError('BOAT_EXACT_ZIP_READBACK_CLOCK_INVALID') from None


def _identity(race_id,prediction):
    """Digest only the immutable original content needed for byte-level parity.

    The digest is never represented as an original AES authenticity proof.
    Source SHA, actual GitHub artifact ID, forecast hash, ordered tickets,
    generated/as-of/cutoff and physically received clock must all agree.
    """
    from hashlib import sha256
    import json
    p=prediction
    values=[race_id,p.get('stage'),p.get('model_id'),
            p.get('model_version'),p.get('artifact_id'),
            p.get('original_json_sha256'),p.get('source_code_commit'),
            p.get('prediction_sha256'),p.get('output_sha256'),
            p.get('ordered_top8'),p.get('as_of'),p.get('generated_at'),
            p.get('server_saved_at'),p.get('cutoff_at')]
    return sha256(json.dumps(values,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _reused_body(race_id,prediction):
    from race_ai.actions_contract import digest
    return digest([race_id,prediction])


def _verified_reused_baseline(get,reader,payload,projection,run,*,saved_at,now,key,day):
    """Bind skipped M2 references to genuine native P1 ZIP/AES, not a boolean."""
    import json
    from race_ai import boat_all_model_recovery as R,boat_all_model_cycle as engine
    from race_ai import boat_private_original_archive as archive
    from race_ai.boat_private_original_vault import _artifact
    from race_ai.boat_source_control import _metadata
    from race_ai.cycle_recovery import artifact_pages
    from race_ai.frozen_day_cycle import read_p1
    from race_ai.actions_contract import digest
    reused=[(row['race_id'],p) for row in projection['records'] for p in
            [row.get('prediction'),*(row.get('comparison_predictions') or [])]
            if p is not None and p.get('dispatch_status')=='ORIGINAL_REUSED']
    if not reused:return set(),set()
    baseline=payload.get('baseline');need(type(baseline) is dict and set(baseline)=={'document_sha256','receipt'})
    proof=baseline.get('receipt');need(type(proof) is dict and proof.get('head_sha') in (OWNER_SHA,*PARTIAL_RECEIPT_OWNER_SHAS))
    ident=proof.get('artifact_id');need(type(ident) is int and ident>0)
    meta_raw=reader.read(f'actions/artifacts/{ident}',128*1024)
    meta=json.loads(meta_raw);origin_ref=meta.get('workflow_run') or {}
    need(type(origin_ref.get('id')) is int and origin_ref['id']>0 and
         str(origin_ref['id'])==str(proof.get('run_id')) and origin_ref.get('head_sha')==proof['head_sha'])
    origin=R._run(reader.read(f'actions/runs/{origin_ref["id"]}',1024*1024),origin_ref['id'],now)
    need(origin.get('head_sha')==proof['head_sha'] and origin.get('head_branch')=='production/boat-p0-p1-20261111' and
         origin.get('event')=='workflow_dispatch' and type(origin.get('run_attempt')) is int and origin['run_attempt']==1 and
         (origin.get('status')=='in_progress' and origin.get('conclusion') is None or
          origin.get('status')=='completed' and origin.get('conclusion') in ('success','failure')))
    listing=artifact_pages(reader,origin['id']);matches=[item for item in listing if item.get('id')==ident]
    need(len(matches)==1 and sum(item.get('name')==meta.get('name') for item in listing)==1 and
         re.fullmatch(r'boat-national-cutoff-'+str(origin['id'])+r'(?:-cycle-(?:0[2-9]|1[0-9]|2[0-4]))?',str(meta.get('name'))))
    R._metadata(meta_raw,matches[0],origin,now,get)
    need(proof.get('artifact_id')==meta.get('id') and proof.get('created_at')==meta.get('created_at') and
         moment(origin['created_at'])<=moment(meta['created_at'])<=moment(saved_at)<=now)
    if origin['status']=='completed':need(moment(meta['created_at'])<=moment(origin['updated_at']))
    raw=get(f'actions/artifacts/{ident}/zip')
    _metadata(raw,meta,name=meta['name'],run_id=origin['id'],head_sha=origin['head_sha'])
    _artifact(raw,meta_raw,key=key,now=now,expected_kind='P1')
    with archive._checked_zip(raw,max_zip_bytes=32*1024*1024) as z:
        need(z.namelist()==[archive.CIPHER_MEMBER])
    document,rows=read_p1(raw,meta)
    need(rows and all(row['race_id'].startswith(day.replace('-','')+'-') and
         moment(row['cutoff_at']).astimezone(JST).date().isoformat()==day for row in rows))
    need(proof.get('payload_sha256')==baseline['document_sha256']==digest(document))
    contexts={item['program']['race_id']:item for item in payload['current_inputs']}
    originals,reconstructed=engine._originals(document,proof,contexts,origin['head_sha'],moment(saved_at))
    need(digest(reconstructed)==digest(baseline))
    by_key={}
    for original in originals:
        key_id=tuple(original.get(k) for k in ('race_id','model_id','model_version'))
        need(key_id not in by_key);by_key[key_id]=original
    slots={}
    for report in payload['dispatch_reports']:
        for slot in report['slots']:
            if slot.get('status')!='ORIGINAL_REUSED':continue
            key_id=tuple(slot.get(k) for k in ('race_id','model_id','model_version'))
            need(key_id not in slots and key_id in by_key and
                 slot.get('reason')=='SAVED_NATIVE_CONTENT_RETAINED_NOT_REISSUED' and
                 digest({k:v for k,v in slot.items() if k not in ('status','reason')})==digest(by_key[key_id]))
            slots[key_id]=slot
    verified=set()
    for rid,prediction in reused:
        need((rid,prediction.get('model_id'),prediction.get('model_version')) in slots and
             prediction.get('source_code_commit')==origin['head_sha'] and prediction.get('artifact_id')==ident and
             prediction.get('receipt_run_id')==str(origin['id']) and
             prediction.get('original_json_sha256')==digest(document) and
             prediction.get('server_saved_at')==prediction.get('persisted_at')==meta['created_at'])
        verified.add(_reused_body(rid,prediction))
    need(len(verified)==len(slots)==len(reused))
    return verified,{ident}


def _canonical_p0(get,run,listing):
    """Keep both cutoff verification and conflict diagnostics on one origin."""
    import importlib.util
    from pathlib import Path
    path=Path(__file__).with_name('boat_owner_evidence_audit.py')
    spec=importlib.util.spec_from_file_location('canonical_p0_evidence_audit',path)
    auditor=importlib.util.module_from_spec(spec);spec.loader.exec_module(auditor)
    return auditor.first_p0_original(get,run,listing)


def _official_cutoffs(get, repo, run, listing, reader, *, day, now, key, p0_original=None):
    """Re-open P0 ZIP and independently verify the original official B source.

    An ALL_MODEL P1 archive cannot certify its own sales cutoff. Every cutoff
    used for acceptance is bound to the separately sealed official P0 ledger.
    """
    import json
    from race_ai.actions_contract import digest
    from race_ai.boat_source_control import _metadata
    from race_ai.boat_private_original_vault import _artifact, REPO_ID
    from race_ai.frozen_day_cycle import read_p0
    from race_ai.boat_program_source import load_program_source
    _owner_head(run.get('head_sha'))
    item,origin=_canonical_p0(get,run,listing) if p0_original is None else p0_original
    owner_head=_owner_head(origin.get('head_sha'))
    ident=item['id']
    meta_raw=reader.read(f'actions/artifacts/{ident}',128*1024)
    meta=json.loads(meta_raw)
    raw=get(f'actions/artifacts/{ident}/zip')
    _metadata(raw,meta,name=item['name'],run_id=origin['id'],head_sha=owner_head)
    _artifact(raw,meta_raw,key=key,now=now,expected_kind='P0')
    doc,p0=read_p0(raw,meta,expected_day=day)
    receipt=dict(repository_id=REPO_ID,repository='haji84/RACE-AI',
        run_id=str(origin['id']),head_sha=owner_head,
        artifact_id=ident,created_at=meta['created_at'],
        payload_sha256=digest(doc),independently_verified=True)
    verified=load_program_source(day,doc,receipt,repo,key=key,as_of=now.isoformat())
    if verified is None:raise OfficialProgramUnavailable()
    schedule=doc.get('schedule')
    need(type(schedule) is list and 0<len(schedule)<=288)
    ledger={}
    for item in schedule:
        need(type(item) is dict)
        rid=item.get('race_id')
        need(type(rid) is str and RACE.fullmatch(rid) and
             rid.startswith(day.replace('-','')) and rid not in ledger)
        cutoff=moment(item.get('cutoff_at'))
        need(cutoff.astimezone(JST).date().isoformat()==day)
        ledger[rid]=cutoff
    return ledger


def _scan(projection, *, day, artifact_id, physical_saved_at, expected, clock,
          source_original_index,official_cutoffs,expected_owner_sha=None,verified_reused_predictions=None):
    owner_head=_owner_head(OWNER_SHA if expected_owner_sha is None else expected_owner_sha)
    need(type(projection) is dict and type(projection.get('records')) is list and
         type(official_cutoffs) is dict and official_cutoffs)
    outputs=[];unqualified=Counter();missing_from_view=0;reused_baseline=0
    saved=moment(physical_saved_at)
    for row in projection['records']:
        if row.get('sport')!='boat' or row.get('event_date_jst')!=day:continue
        rid=row.get('race_id')
        need(type(rid) is str and RACE.fullmatch(rid) and rid[:8]==day.replace('-',''))
        verified_cutoff=official_cutoffs.get(rid)
        need(isinstance(verified_cutoff,datetime) and verified_cutoff.utcoffset() is not None)
        try:official=moment(row.get('cutoff_at'))
        except ValueError:
            official=None
        predictions=[row.get('prediction'),*(row.get('comparison_predictions') or [])]
        need(len(predictions)<=128)
        for p in predictions:
            if p is None or p.get('stage')!='P1':continue
            need(type(p) is dict and p.get('external_receipt_verified') is True)
            # The sealed ALL_MODEL packet can also reference exact baseline A/B
            # P1 originals. Their independent source ZIP must be verified via
            # its own P1 pathway; this ZIP authenticates only its new predictions.
            if p.get('artifact_id')!=artifact_id:
                need(p.get('dispatch_status')=='ORIGINAL_REUSED' and
                     (p.get('source_code_commit')==owner_head if verified_reused_predictions is None else
                      _reused_body(rid,p) in verified_reused_predictions))
                reused_baseline+=1
                continue
            need(p.get('source_code_commit')==owner_head and p.get('dispatch_status')=='GENERATED_UNATTESTED' and
                 p.get('server_saved_at')==physical_saved_at and
                 type(p.get('original_json_sha256')) is str and
                 SHA.fullmatch(p['original_json_sha256']) is not None)
            mid=p.get('model_id')
            need(type(mid) is str and MODEL.fullmatch(mid))
            if mid not in expected:
                unqualified['MODEL_NOT_IN_ACTIVE_CATALOG']+=1
                continue
            fp=_identity(rid,p)
            available=source_original_index.get(fp,0)
            if available>0:
                source_original_index[fp]=available-1
                matched=True
            else:
                matched=False
                missing_from_view+=1
            if official is None:
                unqualified['OFFICIAL_RACE_CUTOFF_UNAVAILABLE']+=1
                outputs.append((rid,mid,False,matched,False))
                continue
            if not p.get('cutoff_at'):
                unqualified['ORIGINAL_CUTOFF_MISSING']+=1
                outputs.append((rid,mid,False,matched,False))
                continue
            try:
                cutoff=moment(p['cutoff_at'])
                asof=moment(p['as_of'])
                generated=moment(p['generated_at'])
            except (KeyError,ValueError,TypeError):
                unqualified['ORIGINAL_CLOCK_MISSING_OR_INVALID']+=1
                outputs.append((rid,mid,False,matched,False))
                continue
            if cutoff!=official:
                unqualified['RACE_ORIGINAL_CUTOFF_CONFLICT']+=1
                outputs.append((rid,mid,False,matched,False))
                continue
            ordered=asof<=saved or (saved.microsecond==0 and
                                    saved<=asof<saved+timedelta(seconds=1))
            generated_order=generated<=saved or (saved.microsecond==0 and
                                    saved<=generated<saved+timedelta(seconds=1))
            eligible=(p.get('eligible_pre_cutoff') is True and
                      asof<cutoff and generated<cutoff and saved<cutoff and
                      saved<=clock and ordered and generated_order)
            if not eligible:
                unqualified['NOT_PHYSICALLY_PRE_CUTOFF']+=1
            if official!=verified_cutoff:
                unqualified['INDEPENDENT_OFFICIAL_CUTOFF_CONFLICT']+=1
            official_eligible=eligible and official==verified_cutoff
            outputs.append((rid,mid,eligible,matched,official_eligible))
    return outputs,unqualified,missing_from_view,reused_baseline


def _scan_unqualified_originals(projection,*,day,artifact_id,physical_saved_at,
                               expected,source_original_index,expected_owner_sha,verified_reused_predictions=None,
                               qualification_blocker='OFFICIAL_PROGRAM_SOURCE_UNAVAILABLE'):
    """Count exact authenticated output bodies without qualifying any deadline.

    Called only after a frozen scope and real ZIP/AES/model replay, when the
    official-B index is absent or the native prefix has an unexplained missing
    model archive. It supplies no physical/official eligible slots.
    """
    owner=_owner_head(expected_owner_sha)
    need(qualification_blocker in ('OFFICIAL_PROGRAM_SOURCE_UNAVAILABLE','ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED'))
    need(type(projection) is dict and type(projection.get('records')) is list)
    rows=[];holds=Counter();missing=0;reused=0
    for row in projection['records']:
        if row.get('sport')!='boat':continue
        rid=row.get('race_id')
        need(row.get('event_date_jst')==day and type(rid) is str and RACE.fullmatch(rid)
             and rid[:8]==day.replace('-',''))
        predictions=[row.get('prediction'),*(row.get('comparison_predictions') or [])]
        need(len(predictions)<=128)
        for prediction in predictions:
            if prediction is None or prediction.get('stage')!='P1':continue
            need(type(prediction) is dict and prediction.get('external_receipt_verified') is True)
            if prediction.get('artifact_id')!=artifact_id:
                need(prediction.get('dispatch_status')=='ORIGINAL_REUSED' and
                     (prediction.get('source_code_commit')==owner if verified_reused_predictions is None else
                      _reused_body(rid,prediction) in verified_reused_predictions));reused+=1;continue
            need(prediction.get('source_code_commit')==owner and prediction.get('dispatch_status')=='GENERATED_UNATTESTED'
                 and prediction.get('server_saved_at')==physical_saved_at
                 and type(prediction.get('original_json_sha256')) is str
                 and SHA.fullmatch(prediction['original_json_sha256']))
            model=prediction.get('model_id');need(type(model) is str and MODEL.fullmatch(model))
            if model not in expected:holds['MODEL_NOT_IN_ACTIVE_CATALOG']+=1
            identity=_identity(rid,prediction);matched=source_original_index.get(identity,0)>0
            if matched:source_original_index[identity]-=1
            else:missing+=1
            holds[qualification_blocker]+=1
            rows.append((rid,model,False,matched,False))
    return rows,holds,missing,reused



def cutoff_source_disagreement(projection, payload, rows, *, artifact_id,
                               official_cutoffs, first_p0_saved_at, p1_saved_at):
    """Classify a P1/P0 cutoff gap using the actual authenticated P1 input bytes.

    This is a source-free, read-only diagnosis, NEVER permission to accept a
    conflicting forecast. Later official racecard+exhibition agreement does
    NOT alone prove a legitimate schedule revision. Aggregate fields only:
    no race ID, model ID, exact clock, source URL/SHA, ticket or plaintext.
    """
    need(type(projection) is dict and type(projection.get('records')) is list and
         type(payload) is dict and type(payload.get('current_inputs')) is list and
         type(rows) is list and type(official_cutoffs) is dict)
    first_saved=moment(first_p0_saved_at); last_saved=moment(p1_saved_at)
    need(first_saved<=last_saved)
    scoped=[(rid,mid) for rid,mid,eligible,matched,officially_valid in rows
            if eligible and not officially_valid]
    if not scoped:
        return dict(conflicting_model_slots=0,conflicting_races=0,
                    source_relation_slots={},p1_minus_first_p0_cutoff_seconds_slots={},
                    racelist_captured_after_first_p0_saved_slots=0)
    current={}
    for record in payload['current_inputs']:
        need(type(record) is dict and type(record.get('program')) is dict)
        rid=record['program'].get('race_id')
        need(type(rid) is str and RACE.fullmatch(rid) and rid not in current)
        current[rid]=record
    projected={}
    for record in projection['records']:
        rid=record.get('race_id')
        need(type(rid) is str and RACE.fullmatch(rid) and rid not in projected)
        projected[rid]=record
    relation=Counter(); offsets=Counter(); later=0
    for rid,mid in scoped:
        need(rid in projected and rid in official_cutoffs)
        saved_row=projected[rid]
        # _scan independently establishes these exact physical P1 slots.
        own=[p for p in [saved_row.get('prediction'),*(saved_row.get('comparison_predictions') or [])]
             if p is not None and p.get('stage')=='P1' and
             p.get('artifact_id')==artifact_id and p.get('model_id')==mid]
        need(len(own)==1)
        view_cutoff=moment(saved_row['cutoff_at'])
        p0_cutoff=official_cutoffs[rid]
        need(view_cutoff!=p0_cutoff)
        delta=(view_cutoff-p0_cutoff).total_seconds()
        key=(str(int(delta)) if delta.is_integer() else 'FRACTIONAL_SECONDS')
        offsets[key]+=1
        context=current.get(rid)
        if context is None:
            relation['P1_SOURCE_CONTEXT_MISSING']+=1
            continue
        try:
            program=context['program'];preview=context['beforeinfo']
            before_context=preview['context']
            # The original dispatch validated the pair; independently compare
            # its captured SOURCE fields rather than the P1 model's own cutoff.
            source_bound=(program.get('body_identity_verified') is True and
                program.get('status')=='OFFICIAL_BODY_IDENTITY_VERIFIED' and
                preview.get('body_identity_verified') is True and
                preview.get('status')=='AVAILABLE' and
                program.get('race_id')==rid and preview.get('race_id')==rid and
                type(program.get('source_sha256')) is str and
                SHA.fullmatch(program['source_sha256']) is not None and
                type(preview.get('source_sha256')) is str and
                SHA.fullmatch(preview['source_sha256']) is not None and
                program.get('source',{}).get('sha256')==program['source_sha256'] and
                before_context.get('source',{}).get('sha256')==preview['source_sha256'])
            program_cutoff=moment(program['closed_at'])
            before_cutoff=moment(preview['closed_at'])
            context_cutoff=moment(before_context['source_cutoff_at'])
            program_at=moment(program['captured_at'])
            preview_at=moment(preview['captured_at'])
            asof=moment(context['as_of'])
            source_bound=source_bound and program_at<=preview_at<=asof<=last_saved
        except (KeyError,TypeError,ValueError,AttributeError):
            source_bound=False
        if not source_bound:
            relation['P1_SOURCE_PROVENANCE_UNVERIFIED']+=1
        elif program_cutoff==before_cutoff==context_cutoff==view_cutoff:
            relation['P1_RACELIST_AND_EXHIBITION_AGREE_BUT_FIRST_P0_DIFFERS']+=1
            later+=int(program_at>first_saved)
        elif program_cutoff==before_cutoff==context_cutoff==p0_cutoff:
            relation['P1_VIEW_DIFFERS_FROM_BOTH_SOURCE_CUTOFFS']+=1
        elif program_cutoff!=before_cutoff or before_cutoff!=context_cutoff:
            relation['P1_RACELIST_AND_EXHIBITION_DISAGREE']+=1
        else:
            relation['P1_VIEW_AND_VERIFIED_INPUT_CUTOFF_DISAGREE']+=1
    need(sum(relation.values())==len(scoped))
    return dict(conflicting_model_slots=len(scoped),
        conflicting_races=len({rid for rid,_ in scoped}),
        source_relation_slots=dict(sorted(relation.items())),
        p1_minus_first_p0_cutoff_seconds_slots=dict(sorted(offsets.items())),
        racelist_captured_after_first_p0_saved_slots=later)

def audit(*,get,repo,run_id,day,expected_models,original_view,now,
          maximum_artifacts=64,owner_key=None,active_scope=None,expected_owner_sha=None,allow_completed_receipts=False):
    """Read all original ZIPs, ignoring any already-cached coverage shortcut.

    Caller must supply authentic saved day, pinned production source checkout
    and Actions-only private key. The read path is strictly GitHub artifacts.
    """
    from race_ai import boat_all_model_recovery as R
    from race_ai.cycle_recovery import artifact_pages
    from race_ai.boat_pdca_state import state_key
    need(callable(get) and type(run_id) is int and run_id>0
         and type(day) is str and date.fromisoformat(day).isoformat()==day
         and isinstance(now,datetime) and now.utcoffset() is not None
         and type(expected_models) in (list,tuple) and
         0<len(expected_models)<=128 and len(set(expected_models))==len(expected_models)
         and all(type(v) is str and MODEL.fullmatch(v) for v in expected_models)
         and type(maximum_artifacts) is int and 1<=maximum_artifacts<=128)
    need(type(original_view) is dict and type(original_view.get('records')) is list)
    expected=set(expected_models)
    key=state_key('production',owner_key)
    reader=R._MetadataReader(get)
    run=R._run(reader.read(f'actions/runs/{run_id}',1024*1024),run_id,now)
    owner_head=_owner_head(run.get('head_sha'))
    if owner_head in PARTIAL_RECEIPT_OWNER_SHAS:need(active_scope is not None and expected_owner_sha==owner_head)
    need(type(allow_completed_receipts) is bool and (not allow_completed_receipts or
         active_scope is not None and expected_owner_sha in PARTIAL_RECEIPT_OWNER_SHAS))
    if expected_owner_sha is not None:
        need(expected_owner_sha in (OWNER_SHA,*PARTIAL_RECEIPT_OWNER_SHAS) and owner_head==expected_owner_sha)
    else:need(owner_head not in PARTIAL_RECEIPT_OWNER_SHAS)
    need(run.get('head_branch')=='production/boat-p0-p1-20261111' and
         run.get('event')=='workflow_dispatch' and
         (run.get('status')=='completed' if active_scope is None else
          run.get('status')=='in_progress' or allow_completed_receipts and run.get('status')=='completed'))
    day_from_run=moment(run['created_at']).astimezone(JST).date().isoformat()
    need(day_from_run==day)
    listed=artifact_pages(reader,run_id)
    selected_rounds=None
    if active_scope is not None:
        from scripts.boat_owner_active_snapshot_audit import validate_active_scope
        selected_rounds=validate_active_scope(active_scope,run,listed,now,get,
            expected_owner_sha=OWNER_SHA if expected_owner_sha is None else expected_owner_sha,
            allow_completed_receipts=allow_completed_receipts)
    model_scope=(active_scope['all_model_archive_scope'] if owner_head in PARTIAL_RECEIPT_OWNER_SHAS else None)
    missing_model_rounds=model_scope['missing_rounds'] if model_scope else []
    targets=[];unique_ids=set();unique_rounds=set()
    for item in listed:
        record=R._listed(item,run_id,now)
        if record is None:continue
        artifact_id,round_no=record
        if selected_rounds is not None and round_no not in selected_rounds:continue
        need(artifact_id not in unique_ids and round_no not in unique_rounds)
        unique_ids.add(artifact_id);unique_rounds.add(round_no)
        targets.append((round_no,artifact_id,item))
    need(len(targets)<=maximum_artifacts and (targets or missing_model_rounds))
    if selected_rounds is not None:need(unique_rounds==set(selected_rounds))
    targets.sort()
    try:
        official_cutoffs=_official_cutoffs(get,repo,run,listed,reader,day=day,now=now,key=key,
            **({'p0_original':active_scope['p0_original']} if active_scope is not None else {}))
    except OfficialProgramUnavailable:
        if active_scope is None:raise
        # Only explicit absence enters authenticity-only reporting. Corruption,
        # wrong keys, source refusals and all other failures still propagate.
        official_cutoffs=None
    day_rows={r['race_id'] for r in original_view['records']
              if r.get('sport')=='boat' and r.get('event_date_jst')==day}
    if official_cutoffs is not None:need(day_rows==set(official_cutoffs))
    source_index=Counter()
    for row in original_view['records']:
        if row.get('sport')!='boat' or row.get('event_date_jst')!=day:continue
        for p in [row.get('prediction'),*(row.get('comparison_predictions') or [])]:
            if p is not None and p.get('stage')=='P1':
                source_index[_identity(row['race_id'],p)]+=1
    original_copy=Counter(source_index)
    physical_forecasts=0;matched=0;absent=0;eligible_slots=set();official_slots=set()
    duplicates=0;invalid=Counter();by_model=Counter();official_by_model=Counter()
    round_counts=[];baseline_reuses=0;cutoff_diagnostics=[];verified_native_ids=set()
    from race_ai.repeated_cycle import artifact_name
    native_rounds=active_scope['rounds'] if active_scope is not None else (selected_rounds or [])
    selected_native_names={artifact_name('boat-national-cutoff',run_id,n) for n in native_rounds if n>0}
    selected_native_ids={item['id'] for item in listed if item.get('name') in selected_native_names}
    all_archive_sha_verified=0;all_aes_authenticated=0
    for round_no,artifact_id,listed_item in targets:
        meta_raw=reader.read(f'actions/artifacts/{artifact_id}',128*1024)
        meta,archived=R._metadata(meta_raw,listed_item,run,now,get)
        if active_scope is not None:
            if round_no==0:
                first=next(s for s in active_scope['job']['steps']
                           if s.get('name')=='Deadline-ordered five-model round 01')
                need(moment(run['created_at'])<=moment(meta['created_at'])<=moment(first['started_at']))
            else:
                step=next(s for s in active_scope['job']['steps']
                          if s.get('name')==f'Deadline-ordered five-model round {round_no:02}')
                need(moment(step['started_at'])<=moment(meta['created_at'])<=moment(step['completed_at']))
        # GitHub metadata's physical created_at, ZIP digest and exact ciphertext
        # are all checked by the *existing* pinned source _project(). This is
        # never a cached HMAC-only coverage acknowledgment.
        raw=get(f'actions/artifacts/{artifact_id}/zip')
        projected,summary,receipt=R._project(raw,meta,run,round_no,key)
        need(receipt.get('independently_verified') is True and
             receipt.get('created_at')==meta['created_at'] and
             receipt.get('artifact_id')==artifact_id and
             receipt.get('head_sha')==owner_head)
        verified_reused=None
        if owner_head in PARTIAL_RECEIPT_OWNER_SHAS:
            from race_ai import boat_all_model_store as store
            with R._checked_zip(raw,max_zip_bytes=R.MAX_ZIP_BYTES,max_expanded=store.MAX_WIRE) as z:
                native_payload=store.open_forecasts(z.read('forecasts.enc'),key=key)
            verified_reused,native_ids=_verified_reused_baseline(get,reader,native_payload,projected,run,
                saved_at=meta['created_at'],now=now,key=key,day=day)
            verified_native_ids.update(native_ids)
        all_archive_sha_verified+=1;all_aes_authenticated+=1
        if official_cutoffs is None or missing_model_rounds:
            rows,holds,missing,reused=_scan_unqualified_originals(projected,day=day,artifact_id=artifact_id,
                physical_saved_at=meta['created_at'],expected=expected,source_original_index=source_index,
                expected_owner_sha=owner_head,verified_reused_predictions=verified_reused,
                qualification_blocker='ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED' if missing_model_rounds else
                                      'OFFICIAL_PROGRAM_SOURCE_UNAVAILABLE')
        else:
            rows,holds,missing,reused=_scan(projected,day=day,artifact_id=artifact_id,
                                physical_saved_at=meta['created_at'],
                                expected=expected,clock=now,
                                source_original_index=source_index,
                                official_cutoffs=official_cutoffs,
                                expected_owner_sha=owner_head,verified_reused_predictions=verified_reused)
        for rid,mid,eligible,equal,officially_valid in rows:
            physical_forecasts+=1;matched+=int(equal);absent+=int(not equal)
            slot=(rid,mid)
            if eligible:
                if slot in eligible_slots:duplicates+=1
                else:eligible_slots.add(slot);by_model[mid]+=1
            if officially_valid and slot not in official_slots:
                official_slots.add(slot);official_by_model[mid]+=1
        # Re-open only conflicting already verified ZIPs to distinguish the
        # sealed P1 racecard/exhibition deadline from the first official P0 B
        # schedule. The 9 conflicting model slots remain HOLD; no re-scoring.
        if holds.get('INDEPENDENT_OFFICIAL_CUTOFF_CONFLICT',0):
            p0,_=_canonical_p0(get,run,listed) if active_scope is None else active_scope['p0_original']
            with R._checked_zip(raw,max_zip_bytes=R.MAX_ZIP_BYTES,
                                max_expanded=R.store.MAX_WIRE) as archive:
                need(archive.namelist()==['forecasts.enc'])
                native_payload=R.store.open_forecasts(archive.read('forecasts.enc'),key=key)
            diagnostic=cutoff_source_disagreement(projected,native_payload,rows,
                artifact_id=artifact_id,official_cutoffs=official_cutoffs,
                first_p0_saved_at=p0['created_at'],p1_saved_at=meta['created_at'])
            need(diagnostic['conflicting_model_slots']==
                 holds['INDEPENDENT_OFFICIAL_CUTOFF_CONFLICT'])
            cutoff_diagnostics.append(dict(round=round_no,**diagnostic))
        invalid.update(holds);baseline_reuses+=reused
        round_counts.append(dict(round=round_no,source_archive_zip_sha_verified=True,
                                 aes_decrypted_and_projected=True,
                                 generated_forecasts_reported=summary['generated_forecasts'],
                                 forecast_p1_rows=len(rows),reused_baseline_p1_rows=reused,
                                 physically_pre_cutoff=sum(row[2] for row in rows),
                                 independently_official_cutoff_verified=sum(row[4] for row in rows),
                                 saved_view_originals_matched=sum(row[3] for row in rows)))
    need(all_archive_sha_verified==all_aes_authenticated==len(targets))
    need(matched+absent==physical_forecasts and
         all(original_copy[key]>=source_index.get(key,0) for key in source_index))
    # Difference is diagnostic only. Missing, duplicated and late original
    # predictions never become a successful user-visible completion claim.
    official_total=len(expected)*len(official_cutoffs) if official_cutoffs is not None else None
    round_coverage=[dict(round=row['round'],state='AES_ARCHIVE_AUTHENTICATED',
                        generated_forecasts=row['generated_forecasts_reported']) for row in round_counts]
    round_coverage.extend(dict(round=number,state='ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED',generated_forecasts=None)
                          for number in missing_model_rounds)
    return dict(schema=SCHEMA,status=('HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED' if missing_model_rounds else
                'AES_ZIP_REPLAY_VERIFIED_P1_COVERAGE_INCOMPLETE' if official_cutoffs is not None else
                'AES_ZIP_REPLAY_VERIFIED_OFFICIAL_PROGRAM_UNAVAILABLE'),
        day_jst=day,owner_run_id=run_id,owner_source_commit=owner_head,
        actual_listed_archives=len(targets),github_zip_sha256_independently_verified=all_archive_sha_verified,
        aes_originals_independently_decrypted=all_aes_authenticated,
        original_content_projection_verified=all_aes_authenticated,
        p1_forecast_rows_reopened=physical_forecasts,
        referenced_existing_baseline_p1_rows_not_recounted=baseline_reuses,
        referenced_native_p1_archives_independently_verified=len(verified_native_ids),
        additional_native_p1_archives_verified=len(verified_native_ids-selected_native_ids),
        physical_pre_cutoff_distinct_model_slots=len(eligible_slots),
        official_program_source_authenticated=official_cutoffs is not None,
        official_cutoff_qualification=official_cutoffs is not None and bool(official_slots) and not invalid,
        cutoff_qualification_blocker=('OFFICIAL_PROGRAM_SOURCE_UNAVAILABLE' if official_cutoffs is None else
                                      'ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED' if missing_model_rounds else None),
        authentic_official_P0_schedule_races=len(official_cutoffs) if official_cutoffs is not None else None,
        official_schedule_crosschecked_pre_cutoff_model_slots=len(official_slots),
        original_predictions_matched_saved_AES_view=matched,
        original_predictions_missing_from_saved_AES_view=absent,
        duplicate_eligible_model_slots=duplicates,
        unqualified_original_reasons=dict(sorted(invalid.items())),
        scheduled_view_model_slot_upper_bound=official_total,
        per_model_physically_pre_cutoff=dict(sorted(by_model.items())),
        per_model_official_schedule_crosschecked=dict(sorted(official_by_model.items())),
        round_evidence=round_counts,
        all_model_round_coverage=sorted(round_coverage,key=lambda row:row['round']),
        missing_all_model_rounds=missing_model_rounds,
        excluded_all_model_rounds=model_scope['excluded_rounds'] if model_scope else [],
        source_cutoff_conflict_diagnostics=cutoff_diagnostics,
        previously_archived_coverages_skipped_without_zip_read=0,
        full_day_coverage=False,successor_dispatch_allowed=False,latest_live_counters_audited=False,
        active_completed_round_scope=selected_rounds,
        racing_provider_gets=0,prediction_generation_performed=False,
        production_predictions_modified=False,website_end_to_end_proven=False)


# Fixed historical artifact bytes, never a caller-selected decryption target.
# Tests substitute only this byte-pin tuple for invented encrypted fixtures.
_FIXED_BOOTSTRAP_P0_BYTE_PINS=(
    ('original_zip_sha256','3dd76e2edba393e51221215703e82756de2ae804ba4b5e063d4e91f44437c995'),
    ('original_zip_bytes',18706128),
    ('metadata_sha256','993c20d3d073d0004f44836a72ef5e30a5b10a8500c8ff81503e4d7bac0fe4a1'),
    ('metadata_bytes',723),
    ('cipher_sha256','e6980993b7d29f9898a50d3cd406c4abca71e75e7f4cc2b89859cfe30fa57026'),
    ('plain_sha256','5f87d119d7c5b30103f1e05896c0dd3a7a3a531b0c68784eb8bd2147e742b347'),
    ('plain_bytes',18699962),
    ('vault_batch_sha256','1254b9a3953121cb8749a22476abfb2b715d18bb997f9b948b4f89583238a552'),
    ('vault_entry_sha256','b43336fa76294275800872755f5fd8cacb217bc31d7789fd3a2290890d580a39'))


def audit_fixed_bootstrap_p0(*,get,repo,now):
    """Count one closed, immutable P0 artifact; never audit the active worker.

    Existing vault and native projectors own all decryption and validation.
    The result contains only aggregate counts or a static HOLD with null counts.
    """
    report=dict(schema='RACE_AI_FIXED_BOOTSTRAP_P0_COUNTS_V1',
        status='HOLD_FIXED_BOOTSTRAP_P0_COUNTS',authenticated_original=False,
        failure_stage='PRECONDITION',counts_only=True,owner_run_id=44170869325,
        owner_source_commit='bb49215034b779ea1493b35dd91e5c3ebfc04032',
        artifact_id=14367093570,round_no=0,day_jst='2026-11-18',
        vault_source_commit='d853f5d6db9089d91748add90560a0b9037b2a1f',
        receipt_scope='ARCHIVED_GITHUB_ARTIFACT_RESPONSE',
        current_artifact_status='NOT_QUERIED',github_artifact_receipt_created=False,
        contexts=None,generated_forecasts=None,reused_forecasts=None,
        projected_forecasts=None,applicable_slots=None,
        non_generated_applicable_slots=None,waiting_exhibition_slots=None,
        retained_original_slots=None,dispatch_status_counts=None,
        official_source_requests=0,full_day_coverage=False,
        all_models_operational=False,qualifying_g8_proven=False,efficacy_proven=False,
        promotion_allowed=False,dispatch_authorized=False,
        website_end_to_end_proven=False,source_originals_modified=False)
    stage='PRECONDITION'
    try:
        import io
        from contextlib import redirect_stdout,redirect_stderr
        from hashlib import sha256
        from race_ai import boat_all_model_recovery as R,boat_private_original_vault as V
        # No dependency diagnostic, source record or exception message may leave.
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            need(callable(get) and type(now) is datetime and now.utcoffset() is not None)
            pins=dict(_FIXED_BOOTSTRAP_P0_BYTE_PINS)
            stage='RUN'
            run=R._run(get('actions/runs/44170869325'),44170869325,now)
            need(run['head_sha']=='bb49215034b779ea1493b35dd91e5c3ebfc04032'
                 and type(run.get('workflow_id')) is int and run['workflow_id']==405276784
                 and run.get('head_branch')=='production/boat-p0-p1-20261111'
                 and run.get('event')=='workflow_dispatch'
                 and run.get('status') in ('in_progress','completed'))
            stage='VAULT_LOOKUP'
            locator=V.lookup_original(14367093570,repo,
                source_commit='d853f5d6db9089d91748add90560a0b9037b2a1f')
            need(type(locator) is dict and locator.get('artifact_id')==14367093570
                 and locator.get('kind')=='ALL_MODEL'
                 and locator.get('ref')=='state/boat-private-originals'
                 and locator.get('source_commit')=='d853f5d6db9089d91748add90560a0b9037b2a1f'
                 and locator.get('batch_sha256')==pins['vault_batch_sha256']
                 and locator.get('entry_sha256')==pins['vault_entry_sha256'])
            stage='VAULT_RESTORE'
            restored=V.restore_original(locator,repo)
            stage='PIN_BINDING'
            raw,metadata_raw,meta=(restored[name] for name in ('raw_zip','metadata_raw','metadata'))
            need(type(raw) is bytes and len(raw)==pins['original_zip_bytes']
                 and sha256(raw).hexdigest()==pins['original_zip_sha256']
                 and type(metadata_raw) is bytes and len(metadata_raw)==pins['metadata_bytes']
                 and sha256(metadata_raw).hexdigest()==pins['metadata_sha256'])
            origin=meta.get('workflow_run',{})
            need(meta.get('id')==14367093570
                 and meta.get('name')=='boat-all-model-forecasts-44170869325-r0'
                 and meta.get('created_at')=='2026-11-17T20:38:49Z'
                 and meta.get('expired') is False
                 and meta.get('size_in_bytes')==pins['original_zip_bytes']
                 and meta.get('digest')=='sha256:'+pins['original_zip_sha256']
                 and origin.get('id')==44170869325
                 and origin.get('head_sha')=='bb49215034b779ea1493b35dd91e5c3ebfc04032'
                 and origin.get('repository_id')==1416489937
                 and origin.get('head_repository_id')==1416489937)
            provenance=restored['provenance']
            need(provenance.get('receipt_scope')=='ARCHIVED_GITHUB_ARTIFACT_RESPONSE'
                 and provenance.get('current_artifact_status')=='NOT_QUERIED'
                 and provenance.get('github_artifact_receipt_created') is False
                 and provenance.get('independent_git_readback_verified') is True
                 and provenance.get('source_commit')=='d853f5d6db9089d91748add90560a0b9037b2a1f'
                 and provenance.get('entry_sha256')==pins['vault_entry_sha256']
                 and moment(meta['created_at'])<=moment(provenance['archived_at'])<=now)
            with R._checked_zip(raw,max_zip_bytes=R.MAX_ZIP_BYTES,
                                max_expanded=R.store.MAX_WIRE) as archive:
                need(archive.namelist()==['forecasts.enc'])
                cipher=archive.read('forecasts.enc')
            header=R.store.forecast_header(cipher)
            need(sha256(cipher).hexdigest()==pins['cipher_sha256']
                 and header==dict(schema='RACE_AI_BOAT_ALL_MODEL_FORECAST_V1',
                    purpose='boat-all-model-forecasts',repository_id='1416489937',
                    run_id='44170869325',round_no=0,encoding='json-utf8',
                    plain_size=pins['plain_bytes'],plain_sha256=pins['plain_sha256']))
            stage='PROJECT'
            projected,summary,receipt=R._project(raw,meta,run,0,None)
            stage='SCOPE'
            rows=projected.get('records')
            need(projected.get('event_date_jst')=='2026-11-18'
                 and type(rows) is list and 0<len(rows)<=288
                 and all(type(row) is dict and row.get('sport')=='boat'
                         and row.get('event_date_jst')=='2026-11-18'
                         and row.get('scheduled_stages')==['P0'] for row in rows))
            stage='COUNTS'
            need(all(type(summary.get(name)) is int and summary[name]>=0
                     for name in ('contexts','generated_forecasts','reused_baseline_forecasts'))
                 and summary['contexts']==len(rows)
                 and len({row['race_id'] for row in rows})==len(rows))
            slots=[slot for row in rows for slot in row['dispatch_slots']]
            states={'NOT_APPLICABLE','INPUT_MISSING','TRAINED_ARTIFACT_MISSING',
                    'DEADLINE_PASSED','RULE_FILTERED','UNCONNECTED_NATIVE_RUNTIME',
                    'SOURCE_NOT_AUTHORIZED','INPUT_REJECTED','EXECUTION_FAILED',
                    'GENERATED_UNATTESTED','ORIGINAL_REUSED'}
            saved={'GENERATED_UNATTESTED','ORIGINAL_REUSED'}
            need(0<len(slots)<=288*128 and all(type(s) is dict
                 and type(s.get('status')) is str and s['status'] in states
                 and type(s.get('applicable')) is bool and s.get('stage')=='P0'
                 and s['applicable']==(s['status']!='NOT_APPLICABLE') for s in slots))
            counts=dict(Counter(s['status'] for s in slots))
            # Projectors can add missing placeholders; do not call those actual slots.
            need(counts==projected['dispatch_status_counts']
                 and summary['generated_forecasts']==counts.get('GENERATED_UNATTESTED',0)
                 and summary['reused_baseline_forecasts']==counts.get('ORIGINAL_REUSED',0))
            applicable=[s for s in slots if s['applicable']]
            predictions=[p for row in rows for p in
                ([row['prediction']] if row['prediction'] is not None else [])+row['comparison_predictions']]
            projected_count=sum(s.get('projection_status')=='PROJECTED' for s in slots)
            need(projected_count==len(predictions) and
                 projected_count<=summary['generated_forecasts']+summary['reused_baseline_forecasts']
                 and all(p.get('stage')=='P0' for p in predictions))
            report.update(status='FIXED_BOOTSTRAP_P0_COUNTS_VERIFIED',
                authenticated_original=True,failure_stage=None,
                contexts=summary['contexts'],generated_forecasts=summary['generated_forecasts'],
                reused_forecasts=summary['reused_baseline_forecasts'],
                projected_forecasts=projected_count,applicable_slots=len(applicable),
                non_generated_applicable_slots=sum(s['status'] not in saved for s in applicable),
                waiting_exhibition_slots=sum(s['status']=='RULE_FILTERED' and
                    s.get('reason')=='WAITING_EXHIBITION' for s in applicable),
                retained_original_slots=sum(s['status']=='RULE_FILTERED' and
                    s.get('reason')=='SAVED_ORIGINAL_RETAINED_IN_OWNER_FEED' for s in applicable),
                dispatch_status_counts=dict(sorted(counts.items())))
    except Exception:
        report['failure_stage']=stage
    return report
