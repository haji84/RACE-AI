"""Reconcile a genuinely saved pending round without prediction or source GET.

This is not permission to ignore a failed owner. Callers independently obtain
its final control, then read original GitHub bytes and decrypt them here. Only a
P1/RESULT pair bound to that exact checkpoint can complete the pending round.
The failed run and its original archives remain unchanged.
"""
from copy import deepcopy
from datetime import timezone, timedelta
import json
import re

from .actions_contract import digest
from .boat_owner_source_identity import authenticated_live_owner_run, OWNER_BRANCH
from .boat_private_original_archive import open_original_zip
from .boat_private_original_vault import _artifact, MAX_METADATA, MAX_ORIGINAL
from .boat_source_control import _metadata
from .frozen_day_cycle import read_p1, ts
from .repeated_cycle import artifact_name

SCHEMA = 'RACE_AI_PENDING_ROUND_RECOVERY_V1'
JST = timezone(timedelta(hours=9))


def need(ok, reason):
    if not ok:
        raise ValueError('ROUND_RECOVERY_' + reason)


def _counts(control):
    names = ('completed_round', 'prepared_round', 'previous_session_requests',
             'lifetime_requests', 'lifetime_completed_rounds', 'day_start_lifetime_requests')
    need(all(type(control.get(n)) is int and control[n] >= 0 for n in names), 'COUNTERS_INVALID')
    need(1 <= control['prepared_round'] <= 24 and
         control['prepared_round'] == control['completed_round'] + 1, 'ROUND_ORDER_INVALID')
    total, base, used = (control[n] for n in ('lifetime_requests', 'day_start_lifetime_requests',
                                            'previous_session_requests'))
    need(base <= total and used <= total-base and
         control['lifetime_completed_rounds'] >= control['completed_round'], 'BUDGET_INVALID')
    need(control.get('source_wait') is None and control.get('previous_halted_reason') is None
         and control.get('previous_stop_reason') is None, 'SOURCE_HOLD')


def verify_pending_round(get, run, control, *, now):
    """Authenticate original payloads before deriving a separate repaired control.

    `control` must come from the existing independent final-control reader. Raw
    bytes in this return value are private and must never be logged/published.
    A caller must retain/read back both originals before using this for dispatch.
    """
    from .cycle_recovery import artifact_pages
    need(now.utcoffset() is not None and type(run) is dict and type(control) is dict,
         'INPUT_INVALID')
    need(authenticated_live_owner_run(run) and run.get('head_branch') == OWNER_BRANCH and
         run.get('event') == 'workflow_dispatch' and run.get('status') == 'completed' and
         run.get('conclusion') == 'failure' and type(run.get('run_attempt', 1)) is int and
         run.get('run_attempt', 1) == 1, 'RUN_INVALID')
    ident = run.get('id')
    need(type(ident) is int and ident > 0 and control.get('previous_run_id') == ident and
         type(run.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}', run['head_sha']),
         'RUN_CONTROL_IDENTITY')
    need(control.get('day_jst') == now.astimezone(JST).date().isoformat(), 'DAY_CHANGED')
    _counts(control)
    start, end = ts(run['created_at']), ts(run['updated_at'])
    need(start <= end <= now, 'RUN_CLOCK_INVALID')
    for name in ('receipt', 'source_control_receipt'):
        receipt = control.get(name)
        need(type(receipt) is dict and type(receipt.get('id')) is int and receipt['id'] > 0
             and re.fullmatch('sha256:[a-f0-9]{64}', str(receipt.get('digest')))
             and start <= ts(receipt['created_at']) <= end, 'CONTROL_RECEIPT_INVALID')
    round_no = control['prepared_round']
    listing = artifact_pages(get, ident)
    selected = []
    for kind, prefix in (('P1', 'boat-national-cutoff'), ('RESULT', 'race-existing-cycle')):
        name = artifact_name(prefix, ident, round_no)
        matches = [m for m in listing if m.get('name') == name]
        need(len(matches) == 1, 'MISSING_OR_DUPLICATE_' + kind)
        artifact_id = matches[0]['id']
        metadata_raw = get(f'actions/artifacts/{artifact_id}')
        need(type(metadata_raw) is bytes and 0 < len(metadata_raw) <= MAX_METADATA, 'METADATA_BOUND')
        metadata = json.loads(metadata_raw)
        need(metadata.get('id') == artifact_id, 'ARTIFACT_ID_CHANGED')
        raw = get(f'actions/artifacts/{artifact_id}/zip')
        _metadata(raw, metadata, name=name, run_id=ident, head_sha=run['head_sha'])
        _artifact(raw, metadata_raw, key=None, now=now, expected_kind=kind)
        need(start <= ts(metadata['created_at']) <= ts(control['receipt']['created_at']),
             'ORIGINAL_CLOCK_INVALID')
        selected.append(dict(raw_zip=raw, metadata_raw=metadata_raw, metadata=metadata))
    p1, result = selected
    need(ts(p1['metadata']['created_at']) <= ts(result['metadata']['created_at']), 'PAIR_CLOCK_INVALID')
    _, rows = read_p1(p1['raw_zip'], p1['metadata'])
    need(all(r['race_id'].startswith(control['day_jst'].replace('-', '')+'-') for r in rows),
         'FOREIGN_RACE_DAY')
    with open_original_zip(result['raw_zip'], result['metadata'], expected_kind='RESULT',
                           max_plain_zip_bytes=32*1024*1024) as bundle:
        need('status.json' in bundle.namelist() and 'current-p1-original.zip' in bundle.namelist(),
             'RESULT_LINK_MISSING')
        need(bundle.getinfo('status.json').file_size <= 16*1024*1024, 'RESULT_REPORT_BOUND')
        report = json.loads(bundle.read('status.json'))
        need(bundle.read('current-p1-original.zip') == p1['raw_zip'], 'NESTED_P1_CHANGED')
    need(report.get('report_sha256') == digest({k:v for k,v in report.items() if k != 'report_sha256'}),
         'RESULT_REPORT_HASH')
    need(report.get('round_no') == round_no and str(report.get('run_id')) == str(ident) and
         report.get('code_sha') == run['head_sha'] and report.get('day_jst') == control['day_jst'],
         'RESULT_SCOPE_INVALID')
    references = [r for r in report.get('first_forecast_artifacts', []) if r.get('id') == p1['metadata']['id']]
    need(len(references) == 1 and all(references[0].get(k) == p1['metadata'].get(k)
         for k in ('id', 'name', 'digest', 'created_at', 'workflow_run')), 'RESULT_P1_RECEIPT_MISMATCH')
    state = report.get('bounded_repeat_session')
    need(type(state) is dict and state.get('day_jst') == control['day_jst'] and state.get('run_id') == ident,
         'RESULT_SESSION_MISSING')
    for field, original in (('requests_used', 'previous_session_requests'),
                            ('completed_round', 'completed_round'), ('prepared_round', 'prepared_round'),
                            ('lifetime_requests', 'lifetime_requests'),
                            ('lifetime_completed_rounds', 'lifetime_completed_rounds'),
                            ('day_start_lifetime_requests', 'day_start_lifetime_requests')):
        need(type(state.get(field)) is int and state[field] == control[original], 'RESULT_COUNTER_MISMATCH')
    need(state.get('source_wait') is None and state.get('halted_reason') is None, 'RESULT_SOURCE_HOLD')
    repaired = deepcopy(control)
    repaired.update(completed_round=round_no, prepared_round=None,
                    lifetime_completed_rounds=control['lifetime_completed_rounds'] + 1)
    repaired['recovery'] = dict(schema=SCHEMA, previous_run_id=ident, round_no=round_no,
        verified_at=now.isoformat(), original_control_receipt=deepcopy(control['receipt']),
        p1_receipt={k:deepcopy(p1['metadata'][k]) for k in ('id','digest','created_at')},
        result_receipt={k:deepcopy(result['metadata'][k]) for k in ('id','digest','created_at')})
    return dict(schema=SCHEMA, control=repaired, originals=selected,
                original_artifact_ids=[v['metadata']['id'] for v in selected],
                replayed_p1_rows=len(rows), new_forecasts=0, official_source_requests=0)

IDLE_SCHEMA = 'RACE_AI_NO_PENDING_FAILED_OWNER_V1'


def verify_no_pending_failed_owner(get, run, control, *, now):
    """Attest a failed pre-round P0 stage, without pretending a round was repaired.

    Requires actual independently decrypted final-control readback by the caller,
    a complete source-free replay of the first P0, zero failed-session requests
    and absence of P1/RESULT artifacts. Anything uncertain remains hard HOLD.
    No source GET, forecast regeneration, archive write or counter adjustment.
    """
    from .cycle_recovery import artifact_pages
    need(type(now) is type(ts(run['created_at'])) and now.utcoffset() is not None
         and type(run) is dict and type(control) is dict,
         'IDLE_INPUT_INVALID')
    need(authenticated_live_owner_run(run) and run.get('head_branch')==OWNER_BRANCH
         and run.get('event')=='workflow_dispatch' and
         run.get('status')=='completed' and run.get('conclusion')=='failure'
         and run.get('run_attempt',1)==1,
         'IDLE_OWNER_RUN_INVALID')
    ident=run.get('id')
    need(type(ident) is int and ident>0 and control.get('previous_run_id')==ident and
         control.get('day_jst')==now.astimezone(JST).date().isoformat(),
         'IDLE_OWNER_SCOPE_INVALID')
    names=('completed_round','previous_session_requests','lifetime_requests',
           'lifetime_completed_rounds','day_start_lifetime_requests')
    need(all(type(control.get(k)) is int and control[k]>=0 for k in names)
         and control.get('prepared_round') is None
         and control['completed_round']==0 and control['previous_session_requests']==0
         # Earlier owners can have spent requests on this same day. Only
         # this failed session must be source-free; retain the inherited total.
         and control['day_start_lifetime_requests']<=control['lifetime_requests']
         and control.get('source_wait') is None
         and control.get('previous_halted_reason') is None
         and control.get('previous_stop_reason') is None,
         'IDLE_CONTROL_OR_SOURCE_HOLD')
    start,end=ts(run['created_at']),ts(run['updated_at'])
    need(start<=end<=now,'IDLE_RUN_CLOCK_INVALID')
    for k in ('receipt','source_control_receipt'):
        receipt=control.get(k)
        need(type(receipt) is dict and type(receipt.get('id')) is int
             and receipt['id']>0 and
             re.fullmatch('sha256:[a-f0-9]{64}',str(receipt.get('digest')))
             and start<=ts(receipt['created_at'])<=end,
             'IDLE_CHECKPOINT_RECEIPT_INVALID')
    listing=artifact_pages(get,ident)
    need(type(listing) is list and 2<=len(listing)<=128
         and all(type(a) is dict and type(a.get('name')) is str
                 and type(a.get('id')) is int and a['id']>0
                 for a in listing),
         'IDLE_ARTIFACT_LISTING_INVALID')
    names=[a['name'] for a in listing]
    for kind in ('race-cycle-continuity','race-source-control'):
        need(names.count(kind+'-'+str(ident))==1,'IDLE_CHECKPOINT_INVENTORY_INVALID')
    need(len(set(names))==len(names),'IDLE_DUPLICATE_ARTIFACT')
    forbidden=re.compile(r'(?:race-existing-cycle|boat-national-cutoff)-'+str(ident)+
                         r'(?:-cycle-[0-9]+)?\Z')
    need(not any(forbidden.fullmatch(name) for name in names),
         'IDLE_P1_OR_RESULT_ARTIFACT_PRESENT')
    evidence=dict(schema=IDLE_SCHEMA, previous_run_id=ident, round_no=None,
                  verified_at=now.isoformat(), original_control_receipt=deepcopy(control['receipt']),
                  source_attempts=0, no_p1_or_result_artifacts_verified=True,
                  no_future_forecast_generated=True, originals_rewritten=False)
    repaired=deepcopy(control)
    repaired['recovery']=evidence
    return dict(schema=IDLE_SCHEMA,control=repaired,originals=[],
                original_artifact_ids=[],replayed_p1_rows=0,
                new_forecasts=0,official_source_requests=0)


from scripts.boat_failed_recovery_contract import (PROOF_SCHEMA, ORPHAN_SCHEMA,
                                                  history_digest, verify_dispatch_proof)


def verify_orphan_p1(get, run, control, *, now, replayed_state, expected_head, listing=None):
    """Retain an authentic incomplete round without manufacturing its RESULT.

    Unlike pair completion, this authenticates counters against the encrypted
    final checkpoint. Only the prepared marker is cleared. The original
    request/round counts, receipts, forecasts and timestamps remain unchanged.
    Returned native bytes are private; callers retain/read them back before
    using the derived control for a new worker.
    """
    from .cycle_recovery import artifact_pages
    from . import boat_source_control as public
    from . import boat_private_original_archive as archive
    from .first_receipt_continuity import first_receipt_rows
    from scripts.boat_failed_recovery_contract import reviewed_recovery_origin
    need(now.utcoffset() is not None and authenticated_live_owner_run(run) and
         run.get('head_branch')==OWNER_BRANCH and run.get('event')=='workflow_dispatch' and
         run.get('status')=='completed' and run.get('conclusion')=='failure' and
         type(run.get('run_attempt')) is int and run['run_attempt']==1,
         'ORPHAN_OWNER_REJECTED')
    need(reviewed_recovery_origin(run.get('head_sha'),expected_head),'ORPHAN_SOURCE_NOT_REVIEWED')
    ident=run['id'];_counts(control)
    need(control.get('previous_run_id')==ident and
         control.get('day_jst')==now.astimezone(JST).date().isoformat(),
         'ORPHAN_SCOPE_REJECTED')
    start,end=ts(run['created_at']),ts(run['updated_at'])
    need(start<=end<=now,'ORPHAN_RUN_CLOCK_INVALID')
    items=artifact_pages(get,ident) if listing is None else listing
    need(type(items) is list and 3<=len(items)<=1024 and all(
        type(a) is dict and type(a.get('id')) is int and a['id']>0 and
        type(a.get('name')) is str for a in items) and
        len({a['id'] for a in items})==len(items) and
        len({a['name'] for a in items})==len(items),'ORPHAN_INVENTORY_INVALID')
    round_no=control['prepared_round']
    p1_name=artifact_name('boat-national-cutoff',ident,round_no)
    result_name=artifact_name('race-existing-cycle',ident,round_no)
    need(not any(a['name']==result_name for a in items),'ORPHAN_RESULT_PRESENT')
    # Unknown/current-round native outputs cannot be silently abandoned. The
    # first supported case has only its baseline P1 and final checkpoint pair.
    suffixes=(f'boat-all-model-forecasts-{ident}-r{round_no}',
              f'boat-venue-research-p1-{ident}-{round_no}',
              f'all-existing-model-pairs-{ident}-{round_no}',
              artifact_name('boat-p0-existing',ident,round_no))
    need(not any(a['name'] in suffixes for a in items),'ORPHAN_ADDITIONAL_ORIGINALS_UNSUPPORTED')
    for prefix in ('boat-national-cutoff','race-existing-cycle'):
        pattern=re.compile(re.escape(prefix+'-'+str(ident))+r'-cycle-([0-9]+)\Z')
        need(not any((match:=pattern.fullmatch(a['name'])) and
             int(match[1])==round_no and a['name'] not in (p1_name,result_name)
             for a in items),'ORPHAN_ROUND_NAME_INVALID')
    packets=[]
    for name,limit in ((p1_name,MAX_ORIGINAL),
                       (f'race-cycle-continuity-{ident}',public.MAX_CONTINUITY_ZIP),
                       (f'race-source-control-{ident}',public.MAX_SUMMARY_ZIP)):
        found=[a for a in items if a['name']==name]
        need(len(found)==1,'ORPHAN_ORIGINAL_MISSING_OR_DUPLICATE')
        selected=found[0];meta_raw=get(f'actions/artifacts/{selected["id"]}')
        need(type(meta_raw) is bytes and len(meta_raw)<=MAX_METADATA,'ORPHAN_METADATA_BOUND')
        meta=json.loads(meta_raw)
        need(meta.get('id')==selected['id'] and all(meta.get(k)==selected.get(k) for k in
             ('id','name','digest','created_at','size_in_bytes','expired')),
             'ORPHAN_LISTING_CHANGED')
        raw=get(f'actions/artifacts/{selected["id"]}/zip')
        need(type(raw) is bytes and 0<len(raw)<=limit,'ORPHAN_ORIGINAL_BOUND')
        public._metadata(raw,meta,name=name,run_id=ident,head_sha=run['head_sha'])
        need(start<=ts(meta['created_at'])<=end and now<ts(meta['expires_at']),
             'ORPHAN_ORIGINAL_CLOCK_INVALID')
        packets.append(dict(raw_zip=raw,metadata_raw=meta_raw,metadata=meta))
    p1,checkpoint,summary=packets
    bound=public.read_summary(summary['raw_zip'],summary['metadata'],
        checkpoint['raw_zip'],checkpoint['metadata'],run_id=ident,head_sha=run['head_sha'])
    need(bound==control,'ORPHAN_PUBLIC_CONTROL_CHANGED')
    with archive._checked_zip(checkpoint['raw_zip'],max_zip_bytes=public.MAX_CONTINUITY_ZIP) as z:
        need(z.namelist()==[archive.CIPHER_MEMBER],'ORPHAN_CHECKPOINT_CIPHER_REQUIRED')
        derived=public.build_summary(z.read(archive.CIPHER_MEMBER),run_id=ident,head_sha=run['head_sha'])
    with archive._checked_zip(summary['raw_zip'],max_zip_bytes=public.MAX_SUMMARY_ZIP,
                              max_expanded=public.MAX_SUMMARY) as z:
        need(z.namelist()==[public.MEMBER] and public._json(z.read(public.MEMBER))==derived,
             'ORPHAN_CHECKPOINT_AES_PUBLIC_DISAGREE')
    _artifact(p1['raw_zip'],p1['metadata_raw'],key=None,now=now,expected_kind='P1')
    document,rows=read_p1(p1['raw_zip'],p1['metadata'])
    need(ts(p1['metadata']['created_at'])<=ts(control['receipt']['created_at']) and
         all(r['race_id'].startswith(control['day_jst'].replace('-','')+'-') for r in rows),
         'ORPHAN_P1_CLOCK_OR_DAY_INVALID')
    need(type(replayed_state) is dict and replayed_state.get('complete') is True and
         replayed_state.get('day_jst')==control['day_jst'] and
         type(replayed_state.get('rows')) is list and type(replayed_state.get('receipts')) is list,
         'ORPHAN_DAY_REPLAY_REQUIRED')
    before,_=first_receipt_rows(replayed_state['rows'])
    union,_=first_receipt_rows(replayed_state['rows']+rows)
    need(before==union and any(m.get('id')==p1['metadata']['id'] and all(
         m.get(k)==p1['metadata'].get(k) for k in ('digest','created_at','workflow_run'))
         for m in replayed_state['receipts']),'ORPHAN_FIRST_RECEIPT_UNION_MISSING')
    proof=lambda m:{k:deepcopy(m[k]) for k in ('id','digest','created_at')}
    fixed=deepcopy(control)
    fixed.update(prepared_round=None,recovery=dict(schema=ORPHAN_SCHEMA,
        previous_run_id=ident,round_no=round_no,verified_at=now.isoformat(),
        original_control_receipt=deepcopy(control['receipt']),original_control=deepcopy(control),
        p1_receipt=proof(p1['metadata']),continuity_receipt=proof(checkpoint['metadata']),
        source_control_receipt=proof(summary['metadata']),checkpoint_AES_authenticated=True,
        public_control_matches_AES=True,missing_result_inventory_verified=True,
        first_receipt_union_verified=True,completed_round_advanced=False,originals_rewritten=False))
    return dict(schema=ORPHAN_SCHEMA,control=fixed,originals=packets,
        original_artifact_ids=[p['metadata']['id'] for p in packets],
        replayed_p1_rows=len(rows),new_forecasts=0,official_source_requests=0)


def verify_recoverable_pending(get, run, control, *, now, replayed_state, expected_head=None):
    from .cycle_recovery import artifact_pages
    items=artifact_pages(get,run['id'])
    result_name=artifact_name('race-existing-cycle',run['id'],control['prepared_round'])
    if any(a.get('name')==result_name for a in items):
        return verify_pending_round(get,run,control,now=now)
    return verify_orphan_p1(get,run,control,now=now,replayed_state=replayed_state,
                            expected_head=expected_head,listing=items)


def read_final_control(get, run):
    """Read the public companion and real encrypted sibling, not a success flag."""
    from .cycle_recovery import artifact_pages
    from .boat_source_control import read_summary
    items = artifact_pages(get, run['id'])
    pair = []
    for prefix in ('race-cycle-continuity', 'race-source-control'):
        selected = [m for m in items if m.get('name') == f'{prefix}-{run["id"]}']
        need(len(selected) == 1, 'CHECKPOINT_MISSING_OR_DUPLICATE')
        ident = selected[0]['id']
        meta = json.loads(get(f'actions/artifacts/{ident}'))
        need(meta.get('id') == ident, 'CHECKPOINT_ID_CHANGED')
        pair.append((get(f'actions/artifacts/{ident}/zip'),meta))
    return read_summary(*pair[1], *pair[0], run_id=run['id'], head_sha=run['head_sha'])


def reconcile_restored_state(state, get, *, now, expected_head=None):
    """Derive a repaired control from independently decrypted original state.

    No checkpoint/forecast bytes are changed. Restoration must happen before
    the next owner starts a source session; unavailable evidence raises HOLD.
    """
    control = state.get('source_control')
    if not control or control.get('prepared_round') is None:
        return state, None
    # Prior-day originals are not turned into today's inference permission.
    if control.get('day_jst') != state.get('day_jst'):
        return state, None
    run = json.loads(get(f'actions/runs/{control["previous_run_id"]}'))
    public = read_final_control(get, run)
    need(all(public.get(k) == v for k,v in control.items()), 'SEALED_AND_PUBLIC_CONTROL_DISAGREE')
    verified = verify_recoverable_pending(get, run, public, now=now,replayed_state=state,
                                        expected_head=expected_head)
    restored = deepcopy(state)
    restored['source_control'] = verified['control']
    return restored, dict(run=run, verified=verified)
