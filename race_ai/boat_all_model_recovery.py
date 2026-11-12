"""Recover missed saved-model rounds from exact authenticated Actions artifacts.

Only explicitly named runs on the existing workflow and branch are read. No
source request, prediction creation, Git publication, or current-receipt rewrite
occurs here. The caller owns its cache-first transport and owner-key context.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import hmac
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import boat_all_model_cycle as engine, boat_all_model_store as store
from .boat_owner_source_identity import authenticated_live_owner_run
from .actions_contract import digest
from .boat_history_store import wire
from .boat_pdca_recipient import _json
from .boat_pdca_state import state_key
from .boat_private_original_archive import _checked_zip
from .boat_saved_model_view import SavedModelViewError, saved_prediction_identity
from .boat_saved_view_intake import append_views, _native_key
from .cycle_recovery import artifact_pages
from .saved_view_feed import forecast_inventory, forecast_anchor

SCHEMA='RACE_AI_BOAT_SAVED_MODEL_RECOVERY_COUNTS_V1'
REPO='haji84/RACE-AI'
REPO_ID=1416489937
WORKFLOW=405276784
BRANCH='feat/four-sport-forecast-audit-view-20261022'
MAX_RUNS=16
MAX_ARTIFACTS=128
MAX_PAGES=128
MAX_ZIP_BYTES=40*1024*1024
MAX_TOTAL_ZIP_BYTES=64*1024*1024
MAX_METADATA_BYTES=64*1024*1024
MAX_VIEW_BYTES=64*1024*1024
COVERAGE_SCHEMA='RACE_AI_BOAT_SAVED_MODEL_ARCHIVE_COVERAGE_V1'
EVIDENCE_FIELD='saved_model_archive_evidence'
MAX_DAY_ARCHIVES=1024
MAX_DAY_FORECASTS=32768
MAX_DAY_COVERAGE_LINKS=65536
MAX_DAY_EVIDENCE_BYTES=16*1024*1024
MAX_ROW_EVIDENCE_BYTES=4*1024*1024
_HEAD=re.compile(r'[a-f0-9]{40}\Z')
_SHA=re.compile(r'[a-f0-9]{64}\Z')


def _need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_RECOVERY_'+reason)


def _now():
    return datetime.now(timezone.utc)


def _observed_clock():
    clock=_now()
    _need(type(clock) is datetime and clock.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    return clock


def _time(value):
    try:
        _need(type(value) is str and 0<len(value)<=64,'CLOCK_INVALID')
        clock=datetime.fromisoformat(value.replace('Z','+00:00'))
        _need(clock.utcoffset() is not None,'CLOCK_INVALID')
        return clock
    except (ValueError,TypeError,OverflowError):
        raise ValueError('ALL_MODEL_RECOVERY_CLOCK_INVALID') from None


def _ident(value):
    _need(type(value) is int and 0<value<10**20,'RUN_OR_ARTIFACT_ID_INVALID')
    return value


def _day(value):
    try:_need(type(value) is str and date.fromisoformat(value).isoformat()==value,'DAY_INVALID')
    except (TypeError,ValueError):raise ValueError('ALL_MODEL_RECOVERY_DAY_INVALID') from None
    return value


def _predictions(view):
    return [p for row in view['records'] for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None]


def _declared_capability(get,name):
    # Do not trust dynamic __getattr__ proxies as archive attestations.
    value=vars(get).get(name) if hasattr(get,'__dict__') else None
    declared=getattr(type(get),name,None)
    if value is None and callable(declared):value=lambda *args:declared(get,*args)
    return value if callable(value) else None


class _Deferred(Exception):
    pass


class _MetadataReader:
    """Exact bounded JSON reads, without an availability-inventory capability."""
    def __init__(self,get):
        self.get=get;self.used=0

    def read(self,path,limit):
        if self.used+limit>MAX_METADATA_BYTES:raise _Deferred()
        raw=self.get(path)
        _need(type(raw) is bytes and 0<len(raw)<=limit,'RESPONSE_BOUND_INVALID')
        self.used+=len(raw)
        return raw

    def __call__(self,path):
        match=re.fullmatch(r'actions/runs/([1-9][0-9]{0,19})/artifacts\?per_page=100(?:&page=([1-9][0-9]{0,2}))?',path)
        _need(match is not None,'PAGINATION_ENDPOINT_INVALID')
        if int(match[2] or '1')>MAX_PAGES:raise _Deferred()
        raw=self.read(path,4*1024*1024);value=_json(raw,4*1024*1024)
        _need(type(value) is dict and type(value.get('total_count')) is int
              and value['total_count']>=0,'PAGINATION_RESPONSE_INVALID')
        if value['total_count']>100*MAX_PAGES:raise _Deferred()
        return raw


def _run(raw,ident,clock):
    value=_json(raw,1024*1024)
    _need(type(value) is dict and type(value.get('id')) is int and value['id']==ident
          and authenticated_live_owner_run(value)
          and type(value.get('head_sha')) is str and _HEAD.fullmatch(value['head_sha']),
          'WORKFLOW_IDENTITY_INVALID')
    _need(all(type(value.get(name)) is dict and type(value[name].get('id')) is int
          and value[name]['id']==REPO_ID and value[name].get('full_name')==REPO
          for name in ('repository','head_repository')),'WORKFLOW_REPOSITORY_INVALID')
    _need(_time(value.get('created_at'))<=_time(value.get('updated_at'))<=clock,'WORKFLOW_CLOCK_INVALID')
    return value


def _listed(row,run,clock):
    ident=_ident(row.get('id'));name=row.get('name')
    _need(type(name) is str and 0<len(name)<=256,'ARTIFACT_NAME_INVALID')
    match=re.fullmatch(r'boat-all-model-forecasts-'+str(run)+r'-r(0|[1-9][0-9]{0,5})',name)
    if match is None:return None
    _need(type(row.get('size_in_bytes')) is int and 0<row['size_in_bytes']<=MAX_ZIP_BYTES
          and type(row.get('digest')) is str and re.fullmatch(r'sha256:[a-f0-9]{64}',row['digest'])
          and type(row.get('expired')) is bool,'LISTED_ARTIFACT_INVALID')
    _need(_time(row.get('created_at'))<=clock,'ARTIFACT_CLOCK_INVALID')
    return ident,int(match[1])


def _coverage_key(key):
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=str(REPO_ID).encode(),
                info=COVERAGE_SCHEMA.encode()+b'\0completed-day-coverage').derive(key)


def _signed_coverage(state,key):
    return dict(state=state,mac=hmac.digest(key,wire(state).encode(),'sha256').hex())


def _scope_inventory(view,day):
    found={}
    for row in view['records']:
        if row['event_date_jst']!=day:continue
        for p in [row.get('prediction'),*row.get('comparison_predictions',[])]:
            if p is None:continue
            ident=digest([row['race_id'],saved_prediction_identity(p)]);body=digest(p)
            _need(ident not in found or found[ident]==body,'CONFLICTING_SCOPED_ORIGINAL')
            found[ident]=body
    _need(len(found)<=MAX_DAY_FORECASTS,'DAY_FORECAST_BOUND_INVALID')
    return found


def _artifact_original_ids(view,day,artifact):
    return {digest([row['race_id'],saved_prediction_identity(p)]) for row in view['records']
            if row['event_date_jst']==day for p in [row.get('prediction'),*row.get('comparison_predictions',[])]
            if p is not None and p.get('artifact_id')==artifact}


def _coverage_bound(entries,*,new=False):
    inventory={};links=0
    for entry in entries.values():
        scoped=entry['state']['scoped_inventory'];links+=len(scoped)
        for ident,body in scoped.items():
            _need(ident not in inventory or inventory[ident]==body,'CONFLICTING_COVERAGE_ORIGINAL')
            inventory[ident]=body
    bounded=(len(entries)<=MAX_DAY_ARCHIVES and len(inventory)<=MAX_DAY_FORECASTS
             and links<=MAX_DAY_COVERAGE_LINKS and len(wire(entries).encode())<=MAX_DAY_EVIDENCE_BYTES)
    if not bounded and new:raise _Deferred()
    _need(bounded,'COVERAGE_DAY_BOUND_INVALID')


def _read_coverage(view,key,clock):
    """Authenticate all retained day attestations before any transport read."""
    found={};current={};all_current=forecast_inventory(view)
    for row in view['records']:
        if EVIDENCE_FIELD not in row:continue
        day=_day(row['event_date_jst']);entries=row[EVIDENCE_FIELD]
        _need(type(entries) is dict and len(entries)<=MAX_DAY_ARCHIVES
              and len(wire(entries).encode())<=MAX_ROW_EVIDENCE_BYTES,'COVERAGE_ROW_BOUND_INVALID')
        if day not in current:current[day]=_scope_inventory(view,day)
        inventory=current[day]
        target=found.setdefault(day,{})
        for ident,entry in entries.items():
            _need(type(ident) is str and re.fullmatch(r'[1-9][0-9]{0,19}',ident)
                  and type(entry) is dict and set(entry)=={'state','mac'}
                  and type(entry['state']) is dict and type(entry['mac']) is str and _SHA.fullmatch(entry['mac']),
                  'COVERAGE_ENVELOPE_INVALID')
            state=entry['state']
            _need(hmac.compare_digest(entry['mac'],_signed_coverage(state,key)['mac']),'COVERAGE_AUTHENTICATION_FAILED')
            _need(set(state)=={'schema','repository_id','day','run_id','head_sha','round_no','artifact',
                  'receipt','scoped_inventory','scope_complete','verified_at'} and state['schema']==COVERAGE_SCHEMA
                  and state['repository_id']==REPO_ID and state['day']==day and state['scope_complete'] is True,
                  'COVERAGE_SCOPE_INVALID')
            run=_ident(state['run_id'])
            _need(type(state['head_sha']) is str and _HEAD.fullmatch(state['head_sha'])
                  and type(state['round_no']) is int and 0<=state['round_no']<=999999
                  and _time(state['verified_at'])<=clock,'COVERAGE_IDENTITY_INVALID')
            artifact=state['artifact'];receipt=state['receipt'];scoped=state['scoped_inventory']
            _need(type(artifact) is dict and set(artifact)=={'id','name','digest','size_in_bytes','created_at','metadata_sha256'}
                  and type(artifact['id']) is int and artifact['id']==int(ident)
                  and artifact['name']==f'boat-all-model-forecasts-{run}-r{state["round_no"]}'
                  and type(artifact['digest']) is str and re.fullmatch(r'sha256:[a-f0-9]{64}',artifact['digest'])
                  and type(artifact['size_in_bytes']) is int and 0<artifact['size_in_bytes']<=MAX_ZIP_BYTES
                  and type(artifact['metadata_sha256']) is str and _SHA.fullmatch(artifact['metadata_sha256']),
                  'COVERAGE_ARTIFACT_INVALID')
            _time(artifact['created_at'])
            _need(type(receipt) is dict and set(receipt)=={'repository_id','repository','run_id','head_sha','artifact_id',
                  'created_at','payload_sha256','independently_verified'} and receipt['repository_id']==str(REPO_ID)
                  and receipt['repository']==REPO and receipt['run_id']==str(run) and receipt['head_sha']==state['head_sha']
                  and receipt['artifact_id']==artifact['id'] and receipt['created_at']==artifact['created_at']
                  and receipt['independently_verified'] is True and type(receipt['payload_sha256']) is str
                  and _SHA.fullmatch(receipt['payload_sha256']),'COVERAGE_RECEIPT_INVALID')
            _need(type(scoped) is dict and len(scoped)<=MAX_DAY_FORECASTS and all(type(k) is str and _SHA.fullmatch(k)
                  and type(v) is str and _SHA.fullmatch(v) for k,v in scoped.items()),'COVERAGE_INVENTORY_INVALID')
            for original,body in scoped.items():
                _need(original not in all_current or original in inventory,'COVERAGE_ORIGINAL_DAY_CONFLICT')
                _need(original not in inventory or inventory[original]==body,'COVERED_ORIGINAL_CHANGED')
            _need(_artifact_original_ids(view,day,artifact['id'])<=set(scoped),
                  'COVERAGE_EXISTING_ARTIFACT_CONFLICT')
            _need(ident not in target or target[ident]==entry,'CONFLICTING_COVERAGE_ATTESTATION')
            target[ident]=entry
    for entries in found.values():_coverage_bound(entries)
    return found


def _coverage_complete(coverage,view,run,listed,days):
    complete=True;nonempty=False
    for day in days:
        entry=coverage.get(day,{}).get(str(listed['id']))
        if entry is None:complete=False;continue
        state=entry['state'];artifact=state['artifact']
        _need(state['run_id']==run['id'] and state['head_sha']==run['head_sha'] and all(
              artifact[field]==listed[field] for field in ('id','name','digest','size_in_bytes','created_at')),
              'COVERAGE_LISTING_CONFLICT')
        inventory=_scope_inventory(view,day)
        _need(_artifact_original_ids(view,day,listed['id'])<=set(state['scoped_inventory']),
              'COVERAGE_EXISTING_ARTIFACT_CONFLICT')
        complete=complete and all(inventory.get(ident)==body for ident,body in state['scoped_inventory'].items())
        nonempty=nonempty or bool(state['scoped_inventory'])
    return complete,nonempty


def _preserved_scope(projected,view,day,artifact):
    """Bind every verified projected native original to its preserved dictionary."""
    expected={_native_key(row['race_id'],p) for row in projected['records'] if row['event_date_jst']==day
              for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None}
    _need(None not in expected,'PROJECTED_ORIGINAL_BINDING_REQUIRED')
    found=set();inventory={}
    for row in view['records']:
        if row['event_date_jst']!=day:continue
        for p in [row.get('prediction'),*row.get('comparison_predictions',[])]:
            if p is None:continue
            key=_native_key(row['race_id'],p)
            if p.get('artifact_id')==artifact:_need(key in expected,'ARCHIVE_EXISTING_ORIGINAL_CONFLICT')
            if key in expected:
                found.add(key);inventory[digest([row['race_id'],saved_prediction_identity(p)])]=digest(p)
    _need(found==expected,'ARCHIVE_SCOPED_ORIGINAL_MISSING')
    return inventory


def _attestation(projected,view,day,meta,meta_raw,run,round_no,receipt,key,previous):
    inventory=_preserved_scope(projected,view,day,meta['id'])
    artifact={field:meta[field] for field in ('id','name','digest','size_in_bytes','created_at')}
    artifact['metadata_sha256']=sha256(meta_raw).hexdigest()
    if previous is not None:
        state=previous['state']
        _need(state['run_id']==run['id'] and state['head_sha']==run['head_sha'] and state['round_no']==round_no
              and state['receipt']==receipt and state['scoped_inventory']==inventory
              and all(state['artifact'][name]==artifact[name] for name in artifact if name!='metadata_sha256'),
              'COVERED_ORIGINAL_RESTORE_CONFLICT')
        return previous
    state=dict(schema=COVERAGE_SCHEMA,repository_id=REPO_ID,day=day,run_id=run['id'],head_sha=run['head_sha'],
        round_no=round_no,artifact=artifact,receipt=receipt,scoped_inventory=inventory,
        scope_complete=True,verified_at=_observed_clock().isoformat())
    return _signed_coverage(state,key)


def _check_history_row_bounds(view):
    """Every indivisible race row must fit its actual V5 day envelope."""
    from .saved_view_history import MAX_CHUNK_PLAIN
    anchor=forecast_anchor(view);overheads={}
    for row in view['records']:
        day=_day(row['event_date_jst'])
        if day not in overheads:
            base={name:value for name,value in view.items() if name!='records'}
            base.update(event_date_jst=day,forecast_base_sha256=anchor)
            overheads[day]=len(wire(dict(base,records=[])).encode())
        if overheads[day]+len(wire(row).encode())>MAX_CHUNK_PLAIN:raise _Deferred()


def _write_coverage(view,coverage,updates):
    from .saved_view_history import MAX_CHUNK_PLAIN
    output=deepcopy(view);anchor=forecast_anchor(view);output['forecast_base_sha256']=anchor
    combined={day:dict(entries) for day,entries in coverage.items()}
    for day,entries in updates.items():
        combined.setdefault(day,{}).update(entries);_coverage_bound(combined[day],new=True)
        if len(wire(combined[day]).encode())>MAX_ROW_EVIDENCE_BYTES:raise _Deferred()
        rows=sorted((row for row in output['records'] if row['event_date_jst']==day),key=lambda row:row['race_id'])
        if not rows:raise _Deferred()
        for row in rows:row.pop(EVIDENCE_FIELD,None)
        base={name:value for name,value in output.items() if name!='records'}
        base.update(event_date_jst=day,forecast_base_sha256=anchor)
        overhead=len(wire(dict(base,records=[])).encode())
        for row in rows:
            candidate=dict(row,**{EVIDENCE_FIELD:combined[day]})
            if overhead+len(wire(candidate).encode())+1<=MAX_CHUNK_PLAIN:
                row[EVIDENCE_FIELD]=deepcopy(combined[day]);break
        else:raise _Deferred()
    if len(wire(output).encode())>MAX_VIEW_BYTES:raise _Deferred()
    _check_history_row_bounds(output)
    return output,combined


def _metadata(raw,listed,run,clock,get):
    meta=_json(raw,128*1024)
    _need(type(meta) is dict and all(meta.get(name)==listed.get(name) for name in
        ('id','name','digest','size_in_bytes','created_at')),'ARTIFACT_LISTING_CONFLICT')
    workflow=meta.get('workflow_run')
    _need(type(workflow) is dict and type(workflow.get('id')) is int and workflow['id']==run['id']
          and workflow.get('head_sha')==run['head_sha']
          and all(type(workflow.get(name)) is int and workflow[name]==REPO_ID
                  for name in ('repository_id','head_repository_id')),'ARTIFACT_RUN_HEAD_INVALID')
    # A vault reader restores and authenticates the exact ZIP while serving its
    # exact captured metadata. Check that explicit proof only after the read.
    capability=_declared_capability(get,'is_archived')
    archived=capability is not None and capability(meta['id']) is True
    created,expires=_time(meta.get('created_at')),_time(meta.get('expires_at'))
    _need(meta.get('expired') is False and created<=clock and created<expires
          and (archived or clock<expires),'ARTIFACT_EXPIRED_OR_CLOCK_INVALID')
    return meta,archived


def _project(raw,meta,run,round_no,key,*,name_alias_sources=None):
    _need(type(raw) is bytes and len(raw)==meta['size_in_bytes'] and len(raw)<=MAX_ZIP_BYTES
          and meta['digest']=='sha256:'+sha256(raw).hexdigest(),'ARTIFACT_ZIP_HASH_INVALID')
    with _checked_zip(raw,max_zip_bytes=MAX_ZIP_BYTES,max_expanded=store.MAX_WIRE) as archive:
        _need(archive.namelist()==['forecasts.enc'],'ARTIFACT_ZIP_MEMBERS_INVALID')
        cipher=archive.read('forecasts.enc')
    header=store.forecast_header(cipher)
    _need(header['run_id']==str(run['id']) and header['round_no']==round_no,'ARTIFACT_HEADER_RUN_ROUND_INVALID')
    payload=store.open_forecasts(cipher,key=key)
    _need(str(payload.get('run_id'))==str(run['id']) and payload.get('source_code_commit')==run['head_sha']
          and payload.get('stage') in ('P0','P1'),'PAYLOAD_RUN_HEAD_INVALID')
    receipt=dict(repository_id=str(REPO_ID),repository=REPO,run_id=str(run['id']),head_sha=run['head_sha'],
                 artifact_id=meta['id'],created_at=meta['created_at'],payload_sha256=digest(payload),independently_verified=True)
    projected=engine.project_round(payload,receipt)
    if name_alias_sources is not None and payload.get('stage')=='P1':
        from .boat_name_aliases import build_program_name_aliases,attach_name_aliases
        aliases=build_program_name_aliases(name_alias_sources,payload,receipt,now=_observed_clock())
        projected=attach_name_aliases(projected,aliases)
    summary=payload.get('summary')
    _need(type(summary) is dict and all(type(summary.get(name)) is int and summary[name]>=0
          for name in ('contexts','generated_forecasts','reused_baseline_forecasts')),'SUMMARY_INVALID')
    _need(summary['generated_forecasts']==sum(slot['status']=='GENERATED_UNATTESTED'
          for report in payload['dispatch_reports'] for slot in report['slots'])
          and summary['reused_baseline_forecasts']==sum(slot['status']=='ORIGINAL_REUSED'
          for report in payload['dispatch_reports'] for slot in report['slots']),'SUMMARY_CONFLICT')
    return projected,summary,receipt


def _new_predictions(before,view):
    return [p for row in view['records'] for p in [row.get('prediction'),*row.get('comparison_predictions',[])]
            if p is not None and digest([row['race_id'],saved_prediction_identity(p)]) not in before]


def recover_saved_models(view,get,*,run_ids,day=None,key=None,max_artifacts=MAX_ARTIFACTS,name_alias_sources=None):
    """Append missed physical originals from a bounded set of named runs.

    Complete exact listings precede selection. Listed ZIP sizes reserve the
    budget before metadata access, since cache-first metadata may itself restore
    the ZIP. Count, byte, and view bounds defer work; source denial and integrity
    conflicts stop without changing the caller's view or choosing a fallback.
    """
    key=state_key('production',key)
    mac_key=_coverage_key(key)
    _need(type(run_ids) in (tuple,list,set,frozenset) and len(run_ids)<=MAX_RUNS,'RUN_SCOPE_INVALID')
    runs=sorted({_ident(ident) for ident in run_ids})
    _need(len(runs)<=MAX_RUNS and type(max_artifacts) is int and 1<=max_artifacts<=MAX_ARTIFACTS,'WORK_BOUND_INVALID')
    clock=_observed_clock()
    before=forecast_inventory(view)
    _need(len(wire(view).encode())<=MAX_VIEW_BYTES,'EXISTING_VIEW_BOUND_INVALID')
    days={_day(day)} if day is not None else {_day(row['event_date_jst']) for row in view['records']}
    coverage=_read_coverage(view,mac_key,clock)
    output=view;reader=_MetadataReader(get);seen=set();reserved=0;attempted=0
    counts=dict(schema=SCHEMA,runs_requested=len(runs),runs_scanned=0,listed_artifacts=0,matched_model_artifacts=0,
        already_projected_artifacts=0,archives_verified=0,archived_artifacts=0,empty_prediction_archives=0,
        zero_generated_archives=0,generated_forecasts_reported=0,reused_forecasts_reported=0,
        projected_forecasts=0,out_of_scope_records=0,deferred_artifacts=0,deferred_runs=0,
        coverage_reused_artifacts=0,coverage_scopes_written=0,empty_scope_acknowledgments=0,
        unrepresented_scoped_forecasts=0)
    for ident in runs:
        try:
            run_raw=reader.read(f'actions/runs/{ident}',1024*1024)
            run=_run(run_raw,ident,_observed_clock())
            rows=artifact_pages(reader,ident)
        except _Deferred:
            counts['deferred_runs']+=1;continue
        counts['runs_scanned']+=1;counts['listed_artifacts']+=len(rows)
        clock=_observed_clock();selected=[]
        for row in rows:
            _need(type(row) is dict,'ARTIFACT_LISTING_INVALID')
            match=_listed(row,ident,clock)
            if match is None:continue
            artifact,round_no=match
            _need(artifact not in seen,'DUPLICATE_ARTIFACT_ACROSS_RUNS');seen.add(artifact)
            counts['matched_model_artifacts']+=1
            complete,nonempty=_coverage_complete(coverage,output,run,row,days)
            if complete:
                counts['coverage_reused_artifacts']+=1
                counts['already_projected_artifacts']+=int(nonempty)
                continue
            selected.append((round_no,artifact,row))
        for round_no,artifact,listed in sorted(selected):
            size=listed['size_in_bytes']
            if attempted>=max_artifacts or reserved+size>MAX_TOTAL_ZIP_BYTES:
                counts['deferred_artifacts']+=1;continue
            try:
                # Reserve before get(metadata): an archived response can hydrate
                # its ciphertext-backed exact ZIP as part of that operation.
                if reader.used+128*1024>MAX_METADATA_BYTES:raise _Deferred()
                attempted+=1;reserved+=size
                meta_raw=reader.read(f'actions/artifacts/{artifact}',128*1024)
                meta,archived=_metadata(meta_raw,listed,run,_observed_clock(),get)
            except _Deferred:
                counts['deferred_artifacts']+=1;continue
            projected,summary,receipt=_project(get(f'actions/artifacts/{artifact}/zip'),meta,run,round_no,key,
                **(dict(name_alias_sources=name_alias_sources) if name_alias_sources is not None else {}))
            counts['archives_verified']+=1;counts['archived_artifacts']+=int(archived)
            all_predictions=_predictions(projected)
            counts['empty_prediction_archives']+=int(not all_predictions)
            counts['zero_generated_archives']+=int(summary['generated_forecasts']==0)
            counts['generated_forecasts_reported']+=summary['generated_forecasts']
            counts['reused_forecasts_reported']+=summary['reused_baseline_forecasts']
            counts['projected_forecasts']+=len(all_predictions)
            chosen=[row for row in projected['records'] if row['event_date_jst'] in days]
            counts['out_of_scope_records']+=len(projected['records'])-len(chosen)
            merged=output
            try:
                if chosen:
                    addition=dict(projected,records=chosen)
                    selected_days={row['event_date_jst'] for row in chosen}
                    addition['event_date_jst']=next(iter(selected_days)) if len(selected_days)==1 else None
                    merged=append_views(output,[addition])
            except SavedModelViewError as exc:
                if str(exc) not in ('saved model view rejected: JSON size','saved model view rejected: union JSON size',
                                    'saved model view rejected: per-race saved prediction limit',
                                    'saved model view rejected: total saved prediction limit'):raise
                counts['deferred_artifacts']+=1;continue
            if len(wire(merged).encode())>MAX_VIEW_BYTES:
                counts['deferred_artifacts']+=1;continue
            unsupported=[row for row in chosen if any(slot.get('projection_status')=='UNREPRESENTABLE'
                          for slot in row.get('dispatch_slots',[]))]
            if unsupported:
                _need(all(str(artifact) not in coverage.get(row['event_date_jst'],{}) for row in unsupported),
                      'COVERED_ORIGINAL_RESTORE_CONFLICT')
                # Missing projection support is not a verified zero-generation
                # scope. Preserve representable originals, but do not attest
                # that every saved forecast in this archive is represented.
                counts['unrepresented_scoped_forecasts']+=sum(slot.get('projection_status')=='UNREPRESENTABLE'
                    for row in unsupported for slot in row.get('dispatch_slots',[]))
                try:_check_history_row_bounds(merged)
                except _Deferred:
                    counts['deferred_artifacts']+=1;continue
                output=merged;counts['deferred_artifacts']+=1
                continue
            available_days={row['event_date_jst'] for row in merged['records']}
            if not days<=available_days:
                # A real same-day row is required for a routed acknowledgment.
                # Do not invent a race just to host an empty/out-of-scope entry.
                counts['deferred_artifacts']+=1;continue
            updates={scope:{str(artifact):_attestation(projected,merged,scope,meta,meta_raw,run,round_no,
                       receipt,mac_key,coverage.get(scope,{}).get(str(artifact)))} for scope in days}
            try:merged,updated=_write_coverage(merged,coverage,updates)
            except _Deferred:
                counts['deferred_artifacts']+=1;continue
            output=merged;coverage=updated
            counts['coverage_scopes_written']+=len(updates)
            counts['empty_scope_acknowledgments']+=sum(not entry['state']['scoped_inventory']
                for entries in updates.values() for entry in entries.values())
    after=forecast_inventory(output)
    _need(all(after.get(ident)==body for ident,body in before.items()),'EXISTING_ORIGINAL_CHANGED')
    appended=_new_predictions(before,output)
    counts.update(status='SAVED_MODEL_RECOVERY_DEFERRED' if counts['deferred_artifacts'] or counts['deferred_runs'] else 'SAVED_MODEL_RECOVERY_COMPLETE',
        appended_forecasts=len(appended),appended_p0_forecasts=sum(p.get('stage')=='P0' for p in appended),
        appended_p1_forecasts=sum(p.get('stage')=='P1' for p in appended),
        appended_eligible_pre_cutoff_forecasts=sum(p.get('eligible_pre_cutoff') is True for p in appended),
        originals_unchanged=True,zip_bytes_reserved=reserved,metadata_response_bytes=reader.used,
        max_artifacts=max_artifacts,max_zip_bytes=MAX_TOTAL_ZIP_BYTES,max_metadata_bytes=MAX_METADATA_BYTES,
        official_source_requests=0,plaintext_published=False)
    return output,counts
