"""Small public operational counters, bound to actual closed Actions receipts.

Only the existing safe summary whitelist, receipt projections and encrypted
locators are published. This is count evidence for coordination, never forecast
data or permission to make source requests. Publication requires owner Actions;
a host may verify the public record against actual run metadata and a pinned
GitHub commit without receiving the owner key or downloading private ZIPs.
"""
from copy import deepcopy
from datetime import datetime,timezone
import hmac
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import boat_private_original_vault as V,boat_original_recovery as R,boat_source_control as safe
from .boat_pdca_state import state_key
from scripts.boat_private_original_vault import _environment

SCHEMA='RACE_AI_BOAT_SOURCE_CONTROL_MIRROR_V1'
LATEST_SCHEMA='RACE_AI_BOAT_SOURCE_CONTROL_MIRROR_LATEST_V1'
PREFIX='state/boat-source-control/v1/'
LATEST=PREFIX+'latest.json'
MAX_RECORD=32768
AUTHORITY='COUNTS_ONLY_NOT_FORECAST_DATA_OR_SOURCE_AUTHORIZATION'
RECEIPT_FIELDS={'id','name','digest','size_in_bytes','created_at','expires_at','expired_as_captured',
                'repository_id','head_repository_id','run_id','head_sha'}
STATE_FIELDS={'schema','repository','repository_id','workflow_id','head_branch','run_id','run_attempt','source_head',
              'day_jst','run_created_at','run_updated_at','run_status','run_conclusion','summary',
              'source_control_receipt','continuity_receipt','vault','authority'}


class MissingControlPair(ValueError):
    """A completed run has not published both exact companion artifacts."""


def _need(ok,reason):
    if not ok:raise ValueError('CONTROL_MIRROR_'+reason)


def _key(key):
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=V.REPO_ID.encode(),
        info=SCHEMA.encode()+b'\0public-count-mirror').derive(state_key('production',key))


def _encode(state,key):
    raw=V._wire(state)
    return V._wire(dict(state=state,sha256=V._sha(raw),mac=hmac.digest(_key(key),raw,'sha256').hex()))+b'\n'


def _decode(raw,key=None):
    body=V._json(raw,MAX_RECORD)
    _need(type(body) is dict and set(body)=={'state','sha256','mac'} and type(body['state']) is dict,
          'ENVELOPE_INVALID')
    V._hex(body['sha256']);V._hex(body['mac'])
    _need(V._sha(V._wire(body['state']))==body['sha256'],'RECORD_HASH_INVALID')
    _need(V._wire(body)+b'\n'==raw,'RECORD_NONCANONICAL')
    if key is not None:
        _need(hmac.compare_digest(body['mac'],hmac.digest(_key(key),V._wire(body['state']),'sha256').hex()),
              'HMAC_INVALID')
    return body['state']


def _first_attempt(run):
    # SCHEMA1 companions and artifact metadata bind run/head, not attempt.
    # A rerun can retain an older normal-stop pair. Only an actual first run
    # attempt establishes unambiguous provenance without a new native schema.
    _need(type(run.get('run_attempt')) is int and run['run_attempt']==1,
          'ATTEMPT_PROVENANCE_UNAVAILABLE')
    return 1


def _run(run,clock=None):
    _need(type(run) is dict,'RUN_INVALID');V._id(run.get('id'));V._hex(run.get('head_sha'),V._HEAD)
    _need(run.get('workflow_id')==R.WORKFLOW and run.get('head_branch')==R.BRANCH
          and run.get('status')=='completed' and run.get('conclusion') in
          ('success','failure','neutral','cancelled','skipped','timed_out','action_required','stale','startup_failure'),
          'COMPLETED_OWNED_RUN_REQUIRED')
    _need(all(type(run.get(name)) is dict and type(run[name].get('id')) is int and run[name]['id']==1416489937
          and run[name].get('full_name')=='haji84/RACE-AI' for name in ('repository','head_repository')),
          'RUN_REPOSITORY_INVALID')
    _first_attempt(run)
    created=V._time(run.get('created_at'));updated=V._time(run.get('updated_at'))
    _need(created<=updated and (clock is None or updated<=clock),'RUN_CLOCK_INVALID')
    return run


def _path(day,run):
    V._id(run)
    _need(type(day) is str and re.fullmatch(r'\d{4}-\d\d-\d\d',day),'DAY_INVALID')
    return PREFIX+day+'/'+str(run)+'.json'


def _validate_receipt(receipt,role,run):
    _need(type(receipt) is dict and set(receipt)==RECEIPT_FIELDS,'RECEIPT_FIELDS_INVALID')
    V._id(receipt['id']);V._hex(receipt['head_sha'],V._HEAD)
    expected=('race-source-control-' if role=='source_control' else 'race-cycle-continuity-')+str(run['id'])
    limit=safe.MAX_SUMMARY_ZIP if role=='source_control' else safe.MAX_CONTINUITY_ZIP
    _need(receipt['name']==expected and receipt['expired_as_captured'] is False
          and type(receipt['size_in_bytes']) is int and 0<receipt['size_in_bytes']<=limit
          and type(receipt['digest']) is str and re.fullmatch(r'sha256:[a-f0-9]{64}',receipt['digest'])
          and type(receipt['run_id']) is int and receipt['run_id']==run['id'] and receipt['head_sha']==run['head_sha']
          and all(type(receipt[name]) is int and receipt[name]==1416489937
                  for name in ('repository_id','head_repository_id')),'RECEIPT_IDENTITY_INVALID')
    created=V._time(receipt['created_at']);expires=V._time(receipt['expires_at'])
    _need(V._time(run['created_at'])<=created<=V._time(run['updated_at']) and created<expires,
          'RECEIPT_CLOCK_INVALID')


def _project_receipt(metadata):
    workflow=metadata['workflow_run']
    return dict(**{name:metadata[name] for name in ('id','name','digest','size_in_bytes','created_at','expires_at')},
        expired_as_captured=metadata['expired'],repository_id=workflow['repository_id'],
        head_repository_id=workflow['head_repository_id'],run_id=workflow['id'],head_sha=workflow['head_sha'])


def _validate_state(state,run):
    _need(type(state) is dict and set(state)==STATE_FIELDS and state['schema']==SCHEMA
          and state['repository']=='haji84/RACE-AI' and type(state['repository_id']) is int
          and state['repository_id']==1416489937 and state['workflow_id']==R.WORKFLOW
          and state['head_branch']==R.BRANCH and state['authority']==AUTHORITY,'STATE_FIELDS_INVALID')
    _run(run)
    _need(type(state['run_attempt']) is int and state['run_attempt']==1,'ATTEMPT_PROVENANCE_UNAVAILABLE')
    expected={'run_id':run['id'],'run_attempt':run.get('run_attempt',1),'source_head':run['head_sha'],
              'run_created_at':run['created_at'],'run_updated_at':run['updated_at'],
              'run_status':run['status'],'run_conclusion':run['conclusion']}
    _need(all(state[name]==value for name,value in expected.items()),'STATE_RUN_CONFLICT')
    safe.validate_summary(state['summary'])
    summary=state['summary']
    _need(summary['run_id']==run['id'] and summary['head_sha']==run['head_sha']
          and state['day_jst']==summary['day_jst'],'SUMMARY_RUN_CONFLICT')
    _validate_receipt(state['source_control_receipt'],'source_control',run)
    _validate_receipt(state['continuity_receipt'],'continuity',run)
    _need(state['source_control_receipt']['id']!=state['continuity_receipt']['id']
          and V._time(state['continuity_receipt']['created_at'])<=V._time(state['source_control_receipt']['created_at']),
          'PAIR_CLOCK_OR_ID_CONFLICT')
    _need(type(state['vault']) is dict and set(state['vault'])=={'source_control','continuity'},'VAULT_FIELDS_INVALID')
    for role,kind in (('source_control','SOURCE_CONTROL'),('continuity','CONTINUITY')):
        locator=V._validate_locator(state['vault'][role])
        _need(locator['kind']==kind and locator['artifact_id']==state[role+'_receipt']['id'],'VAULT_RECEIPT_CONFLICT')
    return state


def verify_record(raw,*,run,key=None,source_commit=None):
    """Verify public shape/run identity; keyless hosts must supply a GitHub pin.

    The caller authenticates ``run`` and ``source_commit`` through GitHub. A host
    without the owner key never claims HMAC verification or private-cipher
    decryption. Actual source-pair validation was done by the Actions publisher.
    """
    if key is None:V._hex(source_commit,V._HEAD)
    state=_validate_state(_decode(raw,key),run)
    return dict(state=state,hmac_verified=key is not None,cipher_binding_verified_by_reader=False,
                source_commit=source_commit,forecast_data=False,source_authorization_granted=False)


def _artifact_pages(get,run):
    # Read only actual listing bytes. The availability projection would hydrate
    # unrelated P0/P1 archives; a mirror never needs those forecast documents.
    pages=[];rows=[];seen=set();total=None;page=1
    while page<=R.MAX_PAGES:
        endpoint=f'actions/runs/{run}/artifacts?per_page=100'+('' if page==1 else f'&page={page}')
        raw=get(endpoint);value=V._json(raw,4*1024*1024)
        _need(type(value) is dict and type(value.get('artifacts')) is list and len(value['artifacts'])<=100
              and type(value.get('total_count')) is int and 0<=value['total_count']<=100*R.MAX_PAGES,
              'ARTIFACT_PAGE_INVALID')
        count=value['total_count'];_need(total is None or total==count,'ARTIFACT_PAGE_CHANGED');total=count
        for row in value['artifacts']:
            _need(type(row) is dict,'ARTIFACT_ROW_INVALID');ident=V._id(row.get('id'))
            _need(ident not in seen,'ARTIFACT_PAGE_DUPLICATE');seen.add(ident);rows.append(row)
        pages.append((endpoint,raw));_need(len(rows)<=total,'ARTIFACT_PAGE_CHANGED')
        if len(rows)==total:return rows
        _need(len(value['artifacts'])==100,'ARTIFACT_PAGE_INCOMPLETE');page+=1
    raise ValueError('CONTROL_MIRROR_ARTIFACT_PAGE_BOUND_EXCEEDED')


def _pair(reader,run,clock):
    rows=_artifact_pages(reader,run['id']);selected={}
    for role,prefix in (('source_control','race-source-control-'),('continuity','race-cycle-continuity-')):
        candidates=[row for row in rows if row.get('name')==prefix+str(run['id'])]
        _need(len(candidates)<=1,'DUPLICATE_SOURCE_PAIR')
        if not candidates:raise MissingControlPair('CONTROL_MIRROR_SOURCE_PAIR_ABSENT')
        ident=candidates[0]['id'];metadata_raw=reader(f'actions/artifacts/{ident}')
        metadata=V._json(metadata_raw,V.MAX_METADATA)
        _need(type(metadata) is dict and metadata.get('id')==ident and metadata.get('expired') is False,
              'SOURCE_METADATA_INVALID')
        receipt=_project_receipt(metadata);_validate_receipt(receipt,role,run)
        if not reader.is_archived(ident):
            _need(clock<V._time(metadata['expires_at']),'UNRETAINED_ARTIFACT_EXPIRED')
        raw=reader(f'actions/artifacts/{ident}/zip')
        selected[role]=dict(raw=raw,metadata=metadata,metadata_raw=metadata_raw,receipt=receipt)
    control=selected['source_control'];continuity=selected['continuity']
    safe.read_summary(control['raw'],control['metadata'],continuity['raw'],continuity['metadata'],
                      run_id=run['id'],head_sha=run['head_sha'])
    with V.native._checked_zip(control['raw'],max_zip_bytes=safe.MAX_SUMMARY_ZIP,max_expanded=safe.MAX_SUMMARY) as source:
        _need(source.namelist()==[safe.MEMBER],'CONTROL_MEMBER_INVALID')
        summary=safe._json(source.read(safe.MEMBER))
    safe.validate_summary(summary)
    return selected,summary


def _readback_sources(state,reader,key):
    restored={role:V.restore_original(locator,reader.repo,key=key,transport=reader)
              for role,locator in state['vault'].items()}
    for role,value in restored.items():
        _need(_project_receipt(value['metadata'])==state[role+'_receipt'],'REMOTE_SOURCE_RECEIPT_CONFLICT')
    safe.read_summary(restored['source_control']['raw_zip'],restored['source_control']['metadata'],
        restored['continuity']['raw_zip'],restored['continuity']['metadata'],
        run_id=state['run_id'],head_sha=state['source_head'])
    with V.native._checked_zip(restored['source_control']['raw_zip'],max_zip_bytes=safe.MAX_SUMMARY_ZIP,
                              max_expanded=safe.MAX_SUMMARY) as source:
        _need(safe._json(source.read(safe.MEMBER))==state['summary'],'REMOTE_SOURCE_SUMMARY_CONFLICT')


def _latest(state,path,raw,key):
    value=dict(schema=LATEST_SCHEMA,repository='haji84/RACE-AI',repository_id=1416489937,
        run_id=state['run_id'],source_head=state['source_head'],day_jst=state['day_jst'],record_path=path,
        record_sha256=V._sha(raw),server_created_at=state['source_control_receipt']['created_at'],authority=AUTHORITY)
    return _encode(value,key)


def _validate_latest(state):
    _need(type(state) is dict and set(state)=={'schema','repository','repository_id','run_id','source_head','day_jst',
          'record_path','record_sha256','server_created_at','authority'} and state['schema']==LATEST_SCHEMA
          and state['repository']=='haji84/RACE-AI' and state['repository_id']==1416489937 and state['authority']==AUTHORITY,
          'LATEST_FIELDS_INVALID')
    V._id(state['run_id']);V._hex(state['source_head'],V._HEAD);V._hex(state['record_sha256'])
    _need(state['record_path']==_path(state['day_jst'],state['run_id']),'LATEST_PATH_INVALID')
    V._time(state['server_created_at'])
    return state


def _check_latest_record(git,commit,latest,key):
    raw=V._read(git,commit,latest['record_path'],MAX_RECORD)
    _need(V._sha(raw)==latest['record_sha256'],'LATEST_RECORD_HASH_INVALID')
    state=_decode(raw,key)
    run=dict(id=state.get('run_id'),head_sha=state.get('source_head'),workflow_id=state.get('workflow_id'),
        head_branch=state.get('head_branch'),status=state.get('run_status'),conclusion=state.get('run_conclusion'),
        run_attempt=state.get('run_attempt'),created_at=state.get('run_created_at'),updated_at=state.get('run_updated_at'),
        repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
        head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))
    _validate_state(state,run)
    _need(state['run_id']==latest['run_id'] and state['source_head']==latest['source_head']
          and state['day_jst']==latest['day_jst']
          and state['source_control_receipt']['created_at']==latest['server_created_at'],'LATEST_RECORD_IDENTITY_INVALID')


def publish_control(run_id,repo,*,get,expected_parent,key=None,transport=None,readback_transport=None,now=None):
    """Publish one completed run's count-only record; fetch no forecast ZIPs."""
    _environment(repo);root=state_key('production',key);V._id(run_id)
    clock=now or datetime.now(timezone.utc)
    _need(type(clock) is datetime and clock.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    git=V._transport(repo,transport);V._hex(expected_parent,V._HEAD)
    _need(git.head()==expected_parent,'REF_CONCURRENT_UPDATE');git.fetch(expected_parent)
    reader=R.ArtifactRecovery(get,repo,key=root,transport=git)
    run=_run(V._json(reader(f'actions/runs/{run_id}'),1024*1024),clock)
    _need(run['id']==run_id,'REQUESTED_RUN_CONFLICT')
    pair,summary=_pair(reader,run,clock)
    locators={role:V.lookup_original(data['metadata']['id'],repo,source_commit=expected_parent,key=root,transport=git)
              for role,data in pair.items()}
    missing=[]
    for role,locator in locators.items():
        if locator is None:
            data=pair[role];item=dict(raw_zip=data['raw'],metadata_raw=data['metadata_raw'])
            if role=='source_control':
                item['companion']=(pair['continuity']['raw'],pair['continuity']['metadata_raw'])
            missing.append(item)
    parent=expected_parent
    if missing:
        retained=V.retain_originals(missing,repo,expected_parent=parent,key=root,transport=git,
            readback_transport=readback_transport,now=clock);parent=retained['source_commit']
        by_id={value['artifact_id']:value for value in retained['locators']}
        locators={role:locator or by_id[pair[role]['metadata']['id']] for role,locator in locators.items()}
    state=dict(schema=SCHEMA,repository='haji84/RACE-AI',repository_id=1416489937,workflow_id=R.WORKFLOW,
        head_branch=R.BRANCH,run_id=run_id,run_attempt=run.get('run_attempt',1),source_head=run['head_sha'],
        day_jst=summary['day_jst'],run_created_at=run['created_at'],run_updated_at=run['updated_at'],
        run_status=run['status'],run_conclusion=run['conclusion'],summary=summary,
        source_control_receipt=pair['source_control']['receipt'],continuity_receipt=pair['continuity']['receipt'],
        vault=locators,authority=AUTHORITY)
    _validate_state(state,run);path=_path(state['day_jst'],run_id);files={}
    if git.exists(parent,path):
        raw=V._read(git,parent,path,MAX_RECORD);old=verify_record(raw,run=run,key=root)['state']
        _need({k:v for k,v in state.items() if k!='vault'}=={k:v for k,v in old.items() if k!='vault'},
              'IMMUTABLE_RUN_CONFLICT')
        for role in locators:
            _need({k:v for k,v in locators[role].items() if k!='source_commit'}==
                  {k:v for k,v in old['vault'][role].items() if k!='source_commit'},'IMMUTABLE_VAULT_CONFLICT')
        state=old
    else:
        raw=_encode(state,root);_need(len(raw)<=MAX_RECORD,'RECORD_BOUND_EXCEEDED');files[path]=raw
    latest=_latest(state,path,raw,root);advance=True;expected_latest=latest
    if git.exists(parent,LATEST):
        old_latest_raw=V._read(git,parent,LATEST,MAX_RECORD);old_latest=_validate_latest(_decode(old_latest_raw,root))
        _check_latest_record(git,parent,old_latest,root)
        new_latest=_decode(latest,root)
        if old_latest['run_id']==run_id:
            _need(old_latest==new_latest,'LATEST_SAME_RUN_CONFLICT');advance=False
        else:
            advance=(run_id>old_latest['run_id'] and V._time(new_latest['server_created_at'])>=
                     V._time(old_latest['server_created_at']) and new_latest['day_jst']>=old_latest['day_jst'])
        if not advance:expected_latest=old_latest_raw
    if advance:files[LATEST]=latest
    commit=parent
    if files:commit=git.commit(files,parent);git.push(commit,parent)
    with V._independent_reader(git,readback_transport) as check:
        check.fetch(commit)
        _need(V._read(check,commit,path,MAX_RECORD)==raw,'REMOTE_RECORD_READBACK_MISMATCH')
        verify_record(V._read(check,commit,path,MAX_RECORD),run=run,key=root)
        _readback_sources(state,check,root)
        _need(V._read(check,commit,LATEST,MAX_RECORD)==expected_latest,'REMOTE_LATEST_READBACK_MISMATCH')
        _check_latest_record(check,commit,_validate_latest(_decode(expected_latest,root)),root)
    return dict(status='SOURCE_CONTROL_MIRROR_PUBLISHED' if files else 'SOURCE_CONTROL_MIRROR_UNCHANGED',
        source_run_id=run_id,source_head=run['head_sha'],source_commit=commit,record_path=path,
        record_sha256=V._sha(raw),latest_path=LATEST,latest_advanced=advance,source_requests=0,
        private_payload_published=False,independent_git_readback_verified=True)


def publish_latest_closed(repo,*,get,expected_parent,key=None,transport=None,readback_transport=None,now=None):
    """Inspect at most 16 closed runs; only a genuinely absent pair is skipped."""
    _environment(repo);root=state_key('production',key);git=V._transport(repo,transport)
    V._hex(expected_parent,V._HEAD);_need(git.head()==expected_parent,'REF_CONCURRENT_UPDATE')
    endpoint=f'actions/workflows/{R.WORKFLOW}/runs?per_page=16&status=completed'
    response=V._json(get(endpoint),2*1024*1024);runs=response.get('workflow_runs') if type(response) is dict else None
    _need(type(runs) is list and len(runs)<=16,'RECENT_RUNS_BOUND_INVALID')
    selected=[];seen=set()
    for run in runs:
        _need(type(run) is dict,'RECENT_RUN_INVALID');ident=V._id(run.get('id'))
        _need(ident not in seen and run.get('status')=='completed' and run.get('workflow_id')==R.WORKFLOW,
              'RECENT_RUN_SCOPE_INVALID');seen.add(ident)
        if run.get('head_branch')!=R.BRANCH:continue
        _first_attempt(run)
        V._time(run.get('created_at'));selected.append(run)
    skipped=[];scanned=0
    for run in sorted(selected,key=lambda value:(V._time(value['created_at']),value['id']),reverse=True):
        scanned+=1
        try:
            report=publish_control(run['id'],repo,get=get,expected_parent=expected_parent,key=root,
                transport=git,readback_transport=readback_transport,now=now)
        except MissingControlPair:
            skipped.append(run['id']);continue
        return dict(report,scanned_closed_runs=scanned,skipped_missing_pairs=skipped)
    return dict(status='NO_CLOSED_SOURCE_CONTROL_PAIR',source_requests=0,scanned_closed_runs=scanned,
                skipped_missing_pairs=skipped,private_payload_published=False)
