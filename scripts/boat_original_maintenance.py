"""Bounded Actions-only backfill of exact native originals and closed API bytes.

This command never requests an official race source, starts a worker, changes a
reader or publishes plaintext. GitHub responses are selected cache-first and
memoized as exact bytes. A partial pass is explicitly deferred for another run.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from race_ai import boat_private_original_vault as V
from race_ai import boat_original_recovery as R
from scripts import boat_private_original_vault as VCLI

MAX_RUNS = 16
MAX_ARTIFACTS = 128
MAX_TARGET_DESCRIPTORS = 128
MAX_RUN_PROBES = 128
MAX_DESCRIPTOR_LOOKUPS = 512
MAX_METADATA_BYTES = 64*1024*1024
PROGRESS_PATH = 'state/boat-original-maintenance/v1/progress.json'
RUN_CONFIG_PATH = 'audit/state/boat-model-recovery-input.json'


class _BudgetLimit(Exception):
    """A bounded deferred pass, never an HTTP denial or integrity fallback."""


class _ByteBudget:
    def __init__(self,maximum):self.maximum=maximum;self.used=0
    @property
    def remaining(self):return self.maximum-self.used
    def reserve(self,amount):
        _need(type(amount) is int and amount>=0,'BYTE_COST_INVALID')
        if amount>self.remaining:raise _BudgetLimit()
        self.used+=amount


def _need(ok, reason):
    if not ok: raise ValueError('ORIGINAL_MAINTENANCE_'+reason)


def _ident(value):
    if type(value) is str and re.fullmatch(r'[1-9][0-9]{0,19}',value): value=int(value)
    return V._id(value)


def targets_from_view(view, artifact_ids=()):
    _need(type(view) is dict and type(view.get('records')) is list and len(view['records'])<=5000,
          'VIEW_INVALID')
    artifacts={_ident(i) for i in artifact_ids};runs=set()
    for row in view['records']:
        _need(type(row) is dict and type(row.get('comparison_predictions',[])) is list,'ROW_INVALID')
        for p in [row.get('prediction'),*row.get('comparison_predictions',[])]:
            if p is None: continue
            _need(type(p) is dict,'PREDICTION_REFERENCE_INVALID')
            if p.get('artifact_id') is not None:artifacts.add(_ident(p['artifact_id']))
            if p.get('receipt_run_id') is not None:runs.add(_ident(p['receipt_run_id']))
            reference=p.get('native_source_reference')
            if type(reference) is dict and reference.get('run_id') is not None:runs.add(_ident(reference['run_id']))
        for evidence in row.get('saved_prediction_evidence',{}).values():
            artifact=evidence.get('artifact',{})
            if artifact.get('id') is not None:artifacts.add(_ident(artifact['id']))
            if artifact.get('run_id') is not None:runs.add(_ident(artifact['run_id']))
    _need(len(artifacts)<=32768 and len(runs)<=32768,'TARGET_BOUND_INVALID')
    return sorted(artifacts),runs


def read_artifact_pages(run, get):
    """Return complete actual page responses; changing/incomplete lists stop."""
    _ident(run);pages=[];rows=[];seen=set();total=None
    for number in range(1,R.MAX_PAGES+1):
        endpoint=f'actions/runs/{run}/artifacts?per_page=100'+('' if number==1 else f'&page={number}')
        raw=get(endpoint);value=V._json(raw,4*1024*1024)
        _need(type(value) is dict and type(value.get('total_count')) is int and
              0<=value['total_count']<=100*R.MAX_PAGES and type(value.get('artifacts')) is list,
              'ARTIFACT_PAGE_INVALID')
        if total is None:total=value['total_count']
        _need(value['total_count']==total and len(value['artifacts'])==min(100,max(0,total-(number-1)*100)),
              'PAGINATION_CHANGED_OR_INCOMPLETE')
        for item in value['artifacts']:
            ident=_ident(item.get('id'))
            _need(ident not in seen and type(item.get('name')) is str,'ARTIFACT_PAGE_DUPLICATE')
            seen.add(ident);rows.append(item)
        pages.append((endpoint,raw))
        if len(pages)==max(1,(total+99)//100):return pages,rows
    raise ValueError('ORIGINAL_MAINTENANCE_PAGINATION_BOUND_EXCEEDED')


def select_native_batch(rows, run, lookup, limit=MAX_ARTIFACTS,*,byte_limit=None,byte_cost=None,after=0):
    """Select new originals, skipping retained IDs rather than counting them.

    Source control's exact continuity is included in the same capture call even
    when that sibling is already retained. It never consumes a phantom new-ID
    count, but it does consume one bounded capture slot.
    """
    _need(type(limit) is int and 0<=limit<=MAX_ARTIFACTS,'BATCH_LIMIT_INVALID')
    native=[];seen=set()
    for row in rows:
        ident=_ident(row.get('id'));_need(ident not in seen,'DUPLICATE_LISTED_ID');seen.add(ident)
        kind=R._native_kind(row.get('name'),run)
        if kind is not None:native.append((ident,kind))
    cached={}
    def is_cached(ident):
        if ident not in cached:cached[ident]=bool(lookup(ident))
        return cached[ident]
    continuity=[ident for ident,kind in native if kind=='CONTINUITY']
    selected=[];deferred=0;new=0;reserved=0;visited=0;lookup_limited=False
    # Pair the control before ordinary rows so a nearly full batch cannot leave
    # a newly selected control without its mandatory continuity companion.
    ordered=sorted(native,key=lambda item:(item[1]!='SOURCE_CONTROL',item[0]))
    start=next((index+1 for index,item in enumerate(ordered) if item[0]==after),0)
    ordered=ordered[start:]+ordered[:start]
    for index,(ident,kind) in enumerate(ordered):
        if selected and len(selected)>=limit:
            deferred+=sum(i not in selected for i,_ in ordered[index:]);break
        try:
            if ident in selected or is_cached(ident):visited+=1;continue
            needed=[ident]
            if kind=='SOURCE_CONTROL':
                _need(len(continuity)==1,'SOURCE_CONTROL_CONTINUITY_REQUIRED')
                sibling=continuity[0];is_cached(sibling)
                needed=([sibling] if sibling not in selected else [])+[ident]
            if len(selected)+len(needed)>limit:
                deferred+=1;visited+=1;continue
            cost=sum(byte_cost(i) for i in needed) if byte_cost is not None else 0
            if byte_limit is not None and reserved+cost>byte_limit:
                deferred+=1;visited+=1;continue
            selected.extend(needed);new+=sum(not cached[i] for i in needed);reserved+=cost;visited+=1
        except _BudgetLimit:
            # Preserve a useful initial slice. Unchecked IDs remain deferred;
            # they are never treated as authenticated retained originals.
            lookup_limited=True
            deferred+=sum(i not in selected for i,_ in ordered[index:]);break
    return dict(selected=selected,new_originals=new,deferred=deferred,
                already_retained=sum(cached.values()),native_ids=[i for i,_ in native],reserved_bytes=reserved,
                cursor_after=ordered[visited-1][0] if 0<visited<len(ordered) else 0,lookup_limited=lookup_limited)


def _window(values,after,limit):
    ordered=sorted(set(values))
    start=next((i for i,value in enumerate(ordered) if value>after),len(ordered))
    if start==len(ordered):start=0
    selected=ordered[start:start+limit]
    finished=start+len(selected)==len(ordered)
    return selected,(0 if finished else selected[-1]),finished


def _progress(git,parent,mac_key):
    default=dict(schema='RACE_AI_ORIGINAL_MAINTENANCE_PROGRESS_V1',repository_id=V.REPO_ID,
                 target_after=0,run_after=0,pending_runs=[],pending_targets={},artifact_after={},
                 targets_sha256='',target_cycle_complete=False,target_cycle_dirty=False)
    if not git.exists(parent,PROGRESS_PATH):return default
    value=V._unsigned(V._read(git,parent,PROGRESS_PATH,1024*1024),mac_key)
    legacy={'schema','repository_id','target_after','run_after','pending_runs'}
    _need(type(value) is dict and set(value) in (set(default),legacy),'PROGRESS_INVALID')
    value=dict(default,**value)
    _need(value['schema']==default['schema'] and
          value['repository_id']==V.REPO_ID and all(type(value[k]) is int and 0<=value[k]<10**20 for k in ('target_after','run_after')) and
          type(value['pending_runs']) is list and len(value['pending_runs'])<=32768 and
          all(type(run) is int for run in value['pending_runs']) and
          value['pending_runs']==sorted(set(value['pending_runs'])) and
          type(value['target_cycle_complete']) is bool and type(value['target_cycle_dirty']) is bool and
          not (value['target_cycle_complete'] and value['target_cycle_dirty']) and type(value['targets_sha256']) is str and
          (value['targets_sha256']=='' or re.fullmatch(r'[0-9a-f]{64}',value['targets_sha256'])) and
          type(value['pending_targets']) is dict and type(value['artifact_after']) is dict and
          len(value['artifact_after'])<=32768,'PROGRESS_INVALID')
    for run in value['pending_runs']:_ident(run)
    required=[]
    for run,ids in value['pending_targets'].items():
        _need(str(_ident(run))==run and type(ids) is list and all(type(i) is int for i in ids) and
              ids==sorted(set(ids)),'PROGRESS_INVALID')
        for ident in ids:_ident(ident)
        required.extend(ids)
        _need(int(run) in value['pending_runs'],'PROGRESS_INVALID')
    _need(len(required)<=32768 and len(required)==len(set(required)),'PROGRESS_INVALID')
    for run,after in value['artifact_after'].items():
        _need(str(_ident(run))==run and type(after) is int and 0<=after<10**20 and
              int(run) in value['pending_runs'],'PROGRESS_INVALID')
    return value


def _save_progress(git,parent,before,after,mac_key,readback):
    if before==after:return parent
    _need(git.head()==parent,'PROGRESS_CONCURRENT_UPDATE')
    raw=V._signed(after,mac_key);_need(len(raw)<=1024*1024,'PROGRESS_BOUND_EXCEEDED')
    commit=git.commit({PROGRESS_PATH:raw},parent);git.push(commit,parent)
    with V._independent_reader(git,readback) as reader:
        reader.fetch(commit);_need(V._read(reader,commit,PROGRESS_PATH,1024*1024)==raw,'PROGRESS_READBACK_FAILED')
    return commit


def _restore_cost(entry):
    """Reserve both encrypted bytes and returned plaintext before any read."""
    return entry['cipher_size']+sum(item['size'] for item in entry['header']['files'].values())


def _strict_live_gh(endpoint):
    _need(type(endpoint) is str and re.fullmatch(
        r'actions/(?:artifacts/[1-9][0-9]{0,19}(?:/zip)?|runs/[1-9][0-9]{0,19}(?:/artifacts\?per_page=100(?:&page=[1-9][0-9]{0,2})?)?)',endpoint),
        'GITHUB_ENDPOINT_INVALID')
    from scripts.github_existing_cycle import _live_gh as strict_live_gh
    return strict_live_gh(endpoint)


def backfill(view, repo, *, artifact_ids=(), run_ids=(), github_get=None, transport=None,
             readback_transport=None, now=None):
    """Retain up to 128 capture IDs and scan up to 16 unfinished runs.

    Previously authenticated closures are skipped without consuming new-work
    slots. No denied GET is caught or used to choose an alternate archive.
    The caller supplies an Actions owner context; CLI enforces it before I/O.
    """
    repo=VCLI._environment(repo)
    clock=now or datetime.now(timezone.utc)
    _need(type(clock) is datetime and clock.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    git=V._transport(repo,transport);parent=git.head();_need(parent is not None,'TRANSFER_REF_REQUIRED')
    git.fetch(parent);mac_key=V._keys(None)[1]
    progress=_progress(git,parent,mac_key)
    live=github_get or _strict_live_gh
    reader=R.ArtifactRecovery(live,repo,transport=git)
    cache={};lookups={};descriptors={};live_runs=set();allowed_zips=set();metadata_bytes=0
    lookup_count=0;budget=_ByteBudget(V.MAX_BATCH_PLAIN)
    targets,runs=targets_from_view(view,artifact_ids)
    _need(type(run_ids) in (tuple,list,set) and len(run_ids)<=MAX_RUNS,'RUN_INPUT_INVALID')
    runs.update(_ident(run) for run in run_ids)
    targets_sha256=V._sha(V._wire(targets))
    same_targets=progress['targets_sha256']==targets_sha256
    target_start=progress['target_after']
    target_cycle_dirty=progress['target_cycle_dirty'] or (not same_targets and target_start>0)
    if same_targets and progress['target_cycle_complete']:
        target_batch=[];target_after=0;target_cycle_complete=True
    else:
        target_batch,target_after,target_cycle_complete=_window(targets,target_start,MAX_TARGET_DESCRIPTORS)
        if target_cycle_dirty:target_cycle_complete=False
    pending=set(progress['pending_runs'])|runs
    target_runs={int(run):set(ids) for run,ids in progress['pending_targets'].items()}
    artifact_after={int(run):after for run,after in progress['artifact_after'].items()}
    def lookup(ident):
        nonlocal lookup_count
        if ident not in lookups:
            if lookup_count>=MAX_DESCRIPTOR_LOOKUPS:raise _BudgetLimit()
            lookup_count+=1
            lookups[ident]=V.lookup_original(ident,repo,source_commit=parent,transport=git)
        return lookups[ident]
    def descriptor(ident):
        locator=lookup(ident)
        if locator is None:return None
        if ident not in descriptors:
            reference={key:locator[key] for key in ('batch_path','batch_sha256','entry_sha256','artifact_id','kind') if key in locator}
            descriptors[ident]=V._batch_entry(git,parent,reference,mac_key)
        return descriptors[ident]
    def get(endpoint):
        nonlocal metadata_bytes
        if endpoint not in cache:
            zip_match=re.fullmatch(r'actions/artifacts/([1-9][0-9]*)/zip',endpoint)
            if zip_match:_need(int(zip_match[1]) in allowed_zips,'ZIP_NOT_PREFLIGHTED')
            run_match=re.match(r'actions/runs/([1-9][0-9]*)',endpoint)
            raw=live(endpoint) if run_match and int(run_match[1]) in live_runs else reader(endpoint)
            _need(type(raw) is bytes,'ACTUAL_RESPONSE_BYTES_REQUIRED')
            if not zip_match:
                if metadata_bytes+len(raw)>MAX_METADATA_BYTES:raise _BudgetLimit()
                metadata_bytes+=len(raw)
            cache[endpoint]=raw
        return cache[endpoint]
    def metadata(ident):
        raw=get(f'actions/artifacts/{ident}');value=V._json(raw,V.MAX_METADATA)
        _need(value.get('id')==ident and type(value.get('size_in_bytes')) is int and
              0<value['size_in_bytes']<=V.MAX_ORIGINAL and value.get('expired') is False,
              'TARGET_ARTIFACT_IDENTITY_INVALID')
        V._kind(value);return value,raw
    checked=0;cached_targets=0
    for ident in target_batch:
        try:
            entry=descriptor(ident)
            if entry is not None:
                run=_ident(entry['header']['summary']['run_id']);cached_targets+=1
            else:
                value,_=metadata(ident);run=_ident(value['workflow_run']['id'])
            target_runs.setdefault(run,set()).add(ident);pending.add(run);checked+=1
        except _BudgetLimit:
            target_after=target_batch[checked-1] if checked else target_start
            target_cycle_complete=False;break
    if checked==len(target_batch) and target_after==0:target_cycle_dirty=False
    selected=[];scanned=[];cached_closed=0;active=0;byte_deferred=0;descriptor_deferred=0;probed=0
    _need(len(pending)<=32768,'PENDING_RUN_BOUND_EXCEEDED')
    _need(sum(len(ids) for ids in target_runs.values())<=32768,'PENDING_TARGET_BOUND_EXCEEDED')
    candidates=sorted(pending)
    run_batch,run_after,run_cycle_complete=_window(candidates,progress['run_after'],MAX_RUN_PROBES)
    for run in run_batch:
        probed+=1
        closed_descriptor=reader.closed_run_descriptor(run)
        closed_state=closed_descriptor['state'] if closed_descriptor is not None else None
        included={item['artifact_id'] for item in closed_state['originals']} if closed_state else set()
        additional_targets=target_runs.get(run,set())-included if closed_state else set()
        if closed_descriptor is not None and not additional_targets:
            response_cost=closed_descriptor['capture_cipher_bytes']+closed_descriptor['capture_plain_bytes']
            try:
                budget.reserve(response_cost)
                _need(reader.has_closed_run(run),'CLOSED_DESCRIPTOR_CHANGED')
                # The response bundle was verified; no native ZIP availability
                # is claimed and the response cache need not accumulate here.
                reader.closures.pop(run,None);pending.discard(run);target_runs.pop(run,None)
                artifact_after.pop(run,None);cached_closed+=1
            except _BudgetLimit:
                byte_deferred+=1
                run_after=run if response_cost>budget.maximum else (run_batch[probed-2] if probed>1 else progress['run_after'])
                break
            continue
        if len(scanned)>=MAX_RUNS:
            run_after=run_batch[probed-2] if probed>1 else progress['run_after']
            break
        if closed_descriptor is not None:
            # A missing explicit/view target identifies a newer attempt before
            # any live request. A denial cannot trigger another selection.
            live_runs.add(run)
        try:
            raw=get(f'actions/runs/{run}');info=V._json(raw,1024*1024)
            _need(type(info) is dict and info.get('id')==run,'RUN_IDENTITY_INVALID')
            VCLI._live_run(raw,dict(workflow_run=dict(id=run,head_sha=info.get('head_sha'))))
            pages,rows=read_artifact_pages(run,get)
            by_id={item['id']:item for item in rows}
            continuity=[item['id'] for item in rows if R._native_kind(item['name'],run)=='CONTINUITY']
            def capture_cost(ident):
                entry=descriptor(ident)
                if entry is not None:return _restore_cost(entry)
                value,metadata_raw=metadata(ident)
                _need(value['workflow_run']['id']==run and R._native_kind(value['name'],run)==R._native_kind(by_id[ident]['name'],run),
                      'LISTED_ARTIFACT_IDENTITY_INVALID')
                cost=2*(value['size_in_bytes']+len(metadata_raw))
                if V._kind(value)=='SOURCE_CONTROL':
                    _need(len(continuity)==1,'SOURCE_CONTROL_CONTINUITY_REQUIRED')
                    companion=descriptor(continuity[0])
                    if companion is not None:cost+=2*sum(item['size'] for item in companion['header']['files'].values())
                    else:
                        sibling,sibling_raw=metadata(continuity[0]);cost+=2*(sibling['size_in_bytes']+len(sibling_raw))
                return cost
            plan=select_native_batch(rows,run,lookup,MAX_ARTIFACTS-len(selected),
                                     byte_limit=budget.remaining,byte_cost=capture_cost,after=artifact_after.get(run,0))
            budget.reserve(plan['reserved_bytes']);selected.extend(plan['selected'])
            artifact_after[run]=plan['cursor_after']
            if plan['lookup_limited']:descriptor_deferred+=1
            scanned.append(dict(run=run,raw=raw,info=info,pages=pages,plan=plan))
            if info.get('status')!='completed':active+=1
            if len(selected)>=MAX_ARTIFACTS or (plan['lookup_limited'] and lookup_count>=MAX_DESCRIPTOR_LOOKUPS):
                run_after=run;break
        except _BudgetLimit:
            descriptor_deferred+=1;run_after=run
            if lookup_count>=MAX_DESCRIPTOR_LOOKUPS or metadata_bytes>=MAX_METADATA_BYTES:break
    missing_before={ident for ident in selected if not lookup(ident)}
    if selected:
        allowed_zips.update(selected)
        captured=VCLI._capture(selected,repo,parent,git,readback_transport,get,clock)
        parent=captured['source_commit']
        for locator in captured['locators']:
            lookups[locator['artifact_id']]=locator;descriptors.pop(locator['artifact_id'],None)
        # _capture already authenticated exact bytes and independently read back
        # their encrypted retention. Release ZIP buffers before closure checks.
        for endpoint in list(cache):
            if endpoint.endswith('/zip'):del cache[endpoint]
        reader.artifacts.cache.clear()
    closed=0;deferred_artifacts=0;incomplete_closed=0
    for item in scanned:
        try:
            remaining=[];unchecked=0
            for index,ident in enumerate(item['plan']['native_ids']):
                try:
                    if lookup(ident) is None:remaining.append(ident)
                except _BudgetLimit:
                    unchecked=len(item['plan']['native_ids'])-index;break
            deferred_artifacts+=len(remaining)+unchecked
            if item['info'].get('status')!='completed':continue
            if remaining or unchecked:
                incomplete_closed+=1
                if unchecked:descriptor_deferred+=1
                continue
            required=target_runs.get(item['run'],set())
            if not required<=set(item['plan']['native_ids']):
                incomplete_closed+=1;continue
            # Full ZIP validation is sequential in the existing closure helper;
            # reserve its whole aggregate workload before the first ZIP read.
            restore_bytes=sum(_restore_cost(descriptor(ident)) for ident in item['plan']['native_ids'])
            budget.reserve(restore_bytes)
            retained=R.retain_closed_run_responses(item['raw'],item['pages'],repo,expected_parent=parent,
                        transport=git,readback_transport=readback_transport,now=clock)
            parent=retained['source_commit'];closed+=1;pending.discard(item['run'])
            target_runs.pop(item['run'],None);artifact_after.pop(item['run'],None)
        except _BudgetLimit:byte_deferred+=1;incomplete_closed+=1
    remaining_targets=sum(len(ids) for ids in target_runs.values())
    next_progress=dict(progress,target_after=target_after,run_after=run_after,pending_runs=sorted(pending),
        pending_targets={str(run):sorted(ids) for run,ids in target_runs.items()},
        artifact_after={str(run):after for run,after in artifact_after.items() if run in pending},
        targets_sha256=targets_sha256,target_cycle_complete=target_cycle_complete,target_cycle_dirty=target_cycle_dirty)
    parent=_save_progress(git,parent,progress,next_progress,mac_key,readback_transport)
    complete=target_cycle_complete and not pending and not remaining_targets
    return dict(schema='RACE_AI_BOAT_ORIGINAL_MAINTENANCE_COUNTS_V1',
        status='BOAT_ORIGINAL_MAINTENANCE_COMPLETE' if complete else 'BOAT_ORIGINAL_MAINTENANCE_DEFERRED',
        scope='BOUNDED_DESCRIPTOR_BACKFILL_AND_CLOSED_RESPONSE_VERIFICATION',source_commit=parent,
        target_artifacts=len(targets),target_descriptors_checked=checked,target_cycle_complete=target_cycle_complete,
        descriptor_only_cached_targets=cached_targets,descriptor_lookups=lookup_count,known_runs=len(candidates),
        runs_scanned=len(scanned),run_probes=probed,cached_closed_runs=cached_closed,
        selected_capture_ids=len(selected),newly_retained_originals=len(missing_before),
        closed_runs_retained=closed,active_runs=active,deferred_runs=max(0,len(candidates)-cached_closed-len(scanned)),pending_run_work=len(pending),
        byte_deferred_runs=byte_deferred,descriptor_deferred_runs=descriptor_deferred,
        deferred_native_artifacts=deferred_artifacts,deferred_target_artifacts=remaining_targets,
        pending_required_artifact_ids=remaining_targets,
        max_new_runs=MAX_RUNS,max_capture_ids=MAX_ARTIFACTS,max_target_descriptors=MAX_TARGET_DESCRIPTORS,
        max_descriptor_lookups=MAX_DESCRIPTOR_LOOKUPS,max_run_probes=MAX_RUN_PROBES,
        reserved_io_bytes=budget.used,max_io_bytes=budget.maximum,metadata_response_bytes=metadata_bytes,
        full_current_view_readback_verified=False,complete=complete,
        official_source_requests=0,plaintext_published=False)



def _owner_view(repo):
    from race_ai import saved_view_feed as F
    from race_ai.saved_pages import _read
    config=V._json(_read(Path(repo)/'audit/state/boat-saved-view-input.json',8192),8192)
    _need(config.get('schema')=='RACE_AI_SAVED_VIEW_INPUT_V1','VIEW_CONFIG_INVALID')
    raw=base64.b64decode(config['bootstrap'],validate=True)
    _need(V._sha(raw)==config['bootstrap_sha256'],'BOOTSTRAP_HASH_INVALID')
    bootstrap=F.open_bootstrap(raw)
    return F.current_view(F.FeedRepository(repo),bootstrap)[3]


def _configured_run_ids(repo,path):
    """Read only the explicitly requested public checkout configuration."""
    _need(path==RUN_CONFIG_PATH,'RUN_CONFIG_PATH_INVALID')
    root=Path(repo).resolve();source=root/path
    _need(source.resolve().is_relative_to(root) and
          all(not parent.is_symlink() for parent in (source,*source.parents) if parent!=root.parent),
          'RUN_CONFIG_PATH_INVALID')
    from race_ai.saved_pages import _read
    config=V._json(_read(source,8192),8192)
    _need(type(config) is dict and set(config)=={'schema','run_ids'} and
          config['schema']=='RACE_AI_BOAT_MODEL_RECOVERY_INPUT_V1' and
          type(config['run_ids']) is list and len(config['run_ids'])<=MAX_RUNS and
          all(type(run) is int for run in config['run_ids']) and
          len(config['run_ids'])==len(set(config['run_ids'])),'RUN_CONFIG_INVALID')
    return [_ident(run) for run in config['run_ids']]


def main(argv=None, *, transport=None,readback_transport=None,github_get=None,view_loader=None,now=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True);command=sub.add_parser('backfill')
    command.add_argument('--repo-root',default=str(ROOT));command.add_argument('--output',required=True)
    command.add_argument('--artifactID','--artifact-id','--artifact',dest='artifact_ids',action='append',type=int,default=[])
    command.add_argument('--run-id',dest='run_ids',action='append',type=int,default=[])
    command.add_argument('--run-config')
    args=parser.parse_args(argv)
    try:
        repo=VCLI._environment(args.repo_root)
        output=VCLI._private_path(args.output,repo,exists=False)
        run_ids=set(args.run_ids)
        if args.run_config is not None:run_ids.update(_configured_run_ids(repo,args.run_config))
        _need(len(run_ids)<=MAX_RUNS,'RUN_INPUT_INVALID')
        for run in run_ids:_ident(run)
        owner=(view_loader or _owner_view)(repo)
        report=backfill(owner,repo,artifact_ids=args.artifact_ids,run_ids=run_ids,github_get=github_get,
                        transport=transport,readback_transport=readback_transport,now=now)
        VCLI._write(output,V._wire(report)+b'\n');print(V._wire(report).decode());return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,(ValueError,RuntimeError)) and re.fullmatch(
            r'(?:VAULT|ORIGINAL_RECOVERY|ORIGINAL_MAINTENANCE|GITHUB)_[A-Z0-9_]{1,100}',str(exc)) else 'ORIGINAL_MAINTENANCE_OPERATION_FAILED'
        print(V._wire(dict(status='BOAT_ORIGINAL_MAINTENANCE_REJECTED',reason=reason,complete=False,plaintext_published=False)).decode());return 2


if __name__=='__main__':raise SystemExit(main())
