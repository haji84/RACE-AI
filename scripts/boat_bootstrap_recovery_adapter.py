"""Bind one genuine historical bootstrap to a trusted current caller's proof.

The frozen validator and original run identities remain unchanged. This module
has no transport, owner key, forecast engine, writer or dispatch operation.
"""
from copy import deepcopy
import re
from scripts import boat_failed_recovery_contract as frozen
from scripts.boat_failed_recovery_contract import need

OUTER_SCHEMA='RACE_AI_SAVED_BOOTSTRAP_CURRENT_CALLER_PROOF_V1'

# Immutable physical issuance, not an alias for an arbitrary release or day.
BOOTSTRAP_MODEL_ORIGINALS = {
    44409798061: ('fbc743be548bfd123e46cdbfe290515a59e5e0d3', '2026-11-19', 14475644448),
}


def bootstrap_model_artifact(run_id, head_sha, day_jst):
    scope = BOOTSTRAP_MODEL_ORIGINALS.get(run_id)
    if scope is None:return None
    need((head_sha,day_jst)==scope[:2], 'BOOTSTRAP_MODEL_SCOPE_CHANGED')
    return scope[2]


def _exact_instance(run,now=None):
    try:
        scope=BOOTSTRAP_MODEL_ORIGINALS.get(run['id'])
        if scope is None:return False
        if not (type(run['id']) is int and run.get('head_sha')==scope[0] and
                run.get('head_branch')==frozen.OWNER_BRANCH and run.get('event')=='workflow_dispatch' and
                run.get('name')=='BOAT nationwide cutoff-ordered A/B research (no Vercel)' and
                type(run.get('workflow_id')) is int and run['workflow_id']==405276784 and
                run.get('status')=='completed' and run.get('conclusion')=='failure' and
                type(run.get('run_attempt')) is int and run['run_attempt']==1):return False
        for key in ('repository','head_repository'):
            value=run.get(key)
            if not (type(value) is dict and type(value.get('id')) is int and value['id']==1416489937
                    and value.get('full_name')=='haji84/RACE-AI'):return False
        created=frozen.ts(run['created_at'])
        return (created.astimezone(frozen.JST).date().isoformat()==scope[1] and
                (now is None or created<=now and now.astimezone(frozen.JST).date().isoformat()==scope[1]))
    except (KeyError,TypeError,ValueError,AttributeError):return False


def current_recovery_origin(run,expected_head,now=None):
    if type(run) is not dict:return False
    return (frozen.reviewed_recovery_origin(run.get('head_sha'),expected_head) or
        type(expected_head) is str and re.fullmatch('[a-f0-9]{40}',expected_head) is not None and
        _exact_instance(run,now))


def _native_proof(runs,repairs,controls,head,now):
    latest=max(runs,key=lambda r:frozen.ts(r['created_at']))
    repaired={r['run_id']:r['control'] for r in repairs}
    return dict(schema=frozen.PROOF_SCHEMA,head_sha=head,
        day_jst=now.astimezone(frozen.JST).date().isoformat(),verified_at=now.isoformat(),
        history_sha256=frozen.history_digest(runs),latest_control=deepcopy(repaired.get(latest['id'],controls[latest['id']])),
        repairs=deepcopy(repairs))


def build_current_recovery_proof(runs,repairs,controls,*,now,expected_head):
    incidents=[r for r in runs if _exact_instance(r,now)]
    if not incidents:return _native_proof(runs,repairs,controls,expected_head,now)
    need(len(incidents)==1,'BOOTSTRAP_ADAPTER_INSTANCE_CHANGED')
    incident=incidents[0];historical=[r for r in repairs if r['run_id']==incident['id']]
    others=[r for r in runs if r['id']!=incident['id']]
    current=[r for r in repairs if r['run_id']!=incident['id']]
    # This is an authentic old-source validation object from its inception.
    # It is not a current-source proof with its head or history relabeled.
    old=_native_proof([incident],historical,controls,incident['head_sha'],now)
    proof=_native_proof(runs,repairs,controls,expected_head,now)
    proof.update(schema=OUTER_SCHEMA,historical_proof=old,current_proof=None,current_control=None,
        controls={str(r['id']):deepcopy(controls[r['id']]) for r in runs})
    if current:proof['current_proof']=_native_proof(others,current,controls,expected_head,now)
    elif others:
        latest=max(others,key=lambda r:frozen.ts(r['created_at']))
        proof['current_control']=deepcopy(controls[latest['id']])
    return proof


def _models_ok(models,repair,run,expected_head,now):
    scope=BOOTSTRAP_MODEL_ORIGINALS[run['id']]
    need(type(models) is dict and models.get('head_sha')==expected_head and
         models.get('run_id')==run['id'] and models.get('source_head_sha')==scope[0] and
         models.get('day_jst')==scope[1] and type(models.get('new_forecasts')) is int and models['new_forecasts']==0 and
         type(models.get('forecasts')) is int and models['forecasts']>0 and
         type(models.get('baseline_forecasts')) is int and models['baseline_forecasts']>0,
         'BOOTSTRAP_CURRENT_MODEL_PROOF_REQUIRED')
    need(0<=(now-frozen.ts(models['verified_at'])).total_seconds()<=600,'BOOTSTRAP_CURRENT_MODEL_PROOF_STALE')
    for expected,restored in (('forecast_inventory_sha256','restored_inventory_sha256'),
            ('baseline_inventory_sha256','restored_baseline_inventory_sha256'),
            ('issued_models_sha256','included_issued_models_sha256')):
        need(type(models.get(expected)) is str and re.fullmatch('[a-f0-9]{64}',models[expected]) and
             models.get(restored)==models[expected],'BOOTSTRAP_CURRENT_MODEL_INVENTORY_CHANGED')
    for key in ('vault_commit','view_commit'):
        need(type(models.get(key)) is str and re.fullmatch('[a-f0-9]{40}',models[key]),
             'BOOTSTRAP_CURRENT_MODEL_READBACK_REQUIRED')
    receipt=models.get('artifact_receipt');evidence=repair['control']['recovery']
    need(type(receipt) is dict and receipt.get('id')==scope[2] and
         type(receipt.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}',receipt['digest']) and
         frozen.ts(evidence['p0_receipt']['created_at'])<=frozen.ts(receipt['created_at'])<=
         frozen.ts(repair['original_control']['receipt']['created_at']),'BOOTSTRAP_CURRENT_MODEL_RECEIPT_CHANGED')


def _successful_control(runs,control,now):
    latest=max(runs,key=lambda r:frozen.ts(r['created_at']))
    need(control.get('previous_run_id')==latest['id'] and
         control.get('day_jst')==now.astimezone(frozen.JST).date().isoformat() and
         control.get('prepared_round') is None and control.get('source_wait') is None and
         control.get('previous_halted_reason') is None and control.get('previous_stop_reason') in
         ('BOUNDED_SESSION_END','MAX_ROUNDS_REACHED','WORKER_HANDOFF'),'BOOTSTRAP_CURRENT_SOURCE_HOLD')
    names=('lifetime_requests','day_start_lifetime_requests','previous_session_requests','completed_round','lifetime_completed_rounds')
    need(all(type(control.get(k)) is int and control[k]>=0 for k in names) and
         control['previous_session_requests']<=control['lifetime_requests']-control['day_start_lifetime_requests'] and
         control['lifetime_completed_rounds']>=control['completed_round'],'BOOTSTRAP_CURRENT_COUNTER_INVALID')
    for key in ('receipt','source_control_receipt'):
        receipt=control.get(key)
        need(type(receipt) is dict and type(receipt.get('id')) is int and receipt['id']>0 and
             type(receipt.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}',receipt['digest']) and
             frozen.ts(latest['created_at'])<=frozen.ts(receipt['created_at'])<=now,
             'BOOTSTRAP_CURRENT_RECEIPT_CHANGED')
    return deepcopy(control)


def _control_ledger(proof,runs,repairs,fresh_control,now):
    controls=proof.get('controls');by_id={r['run_id']:r for r in repairs}
    need(type(controls) is dict and set(controls)=={str(r['id']) for r in runs},
         'BOOTSTRAP_CURRENT_CONTROL_LEDGER_CHANGED')
    ordered=sorted(runs,key=lambda r:(frozen.ts(r['created_at']),r['id']))
    previous=None
    for run in ordered:
        raw=controls[str(run['id'])]
        need(type(raw) is dict and raw.get('previous_run_id')==run['id'] and
             raw.get('day_jst')==proof['day_jst'],'BOOTSTRAP_CURRENT_CONTROL_IDENTITY_CHANGED')
        if run['conclusion']=='success':effective=_successful_control([run],raw,now)
        else:
            repair=by_id[run['id']]
            need(repair['original_control']==raw,'BOOTSTRAP_CURRENT_ORIGINAL_CONTROL_CHANGED')
            effective=repair['control']
        if previous is not None:
            need(effective['day_start_lifetime_requests']==previous['day_start_lifetime_requests'] and
                 effective['lifetime_requests']-effective['previous_session_requests']>=previous['lifetime_requests'] and
                 effective['lifetime_completed_rounds']-effective['completed_round']>=previous['lifetime_completed_rounds'],
                 'BOOTSTRAP_CURRENT_CONTROL_INHERITANCE_CHANGED')
        previous=effective
    need(controls[str(ordered[-1]['id'])]==fresh_control,'BOOTSTRAP_CURRENT_LATEST_CONTROL_CHANGED')


def verify_current_recovery_proof(proof,runs,fresh_control,expected_head,now):
    if type(proof) is dict and proof.get('schema')==frozen.PROOF_SCHEMA:
        return frozen.verify_dispatch_proof(proof,runs,fresh_control,expected_head,now)
    try:
        need(type(proof) is dict and proof.get('schema')==OUTER_SCHEMA and
             type(expected_head) is str and re.fullmatch('[a-f0-9]{40}',expected_head) and
             proof.get('head_sha')==expected_head and proof.get('day_jst')==
             now.astimezone(frozen.JST).date().isoformat(),'BOOTSTRAP_CURRENT_PROOF_SCOPE')
        need(0<=(now-frozen.ts(proof['verified_at'])).total_seconds()<=600 and
             type(runs) is list and 1<=len(runs)<=24 and len({r['id'] for r in runs})==len(runs) and
             proof.get('history_sha256')==frozen.history_digest(runs),'BOOTSTRAP_CURRENT_HISTORY_CHANGED')
        need(all(current_recovery_origin(r,expected_head,now) and r.get('head_branch')==frozen.OWNER_BRANCH and
             r.get('event')=='workflow_dispatch' and r.get('status')=='completed' and
             r.get('conclusion') in ('success','failure') and frozen.ts(r['created_at'])<=now
             for r in runs),'BOOTSTRAP_CURRENT_HISTORY_UNVERIFIED')
        incidents=[r for r in runs if _exact_instance(r,now)]
        need(len(incidents)==1,'BOOTSTRAP_CURRENT_INSTANCE_MISSING')
        incident=incidents[0]
        need(expected_head!=incident['head_sha'],'BOOTSTRAP_CURRENT_CHECKOUT_REQUIRED')
        repairs=proof.get('repairs');failed={r['id'] for r in runs if r['conclusion']=='failure'}
        need(type(repairs) is list and len(repairs)==len(failed) and
             {r['run_id'] for r in repairs}==failed,'BOOTSTRAP_CURRENT_REPAIRS_CHANGED')
        repair=next(r for r in repairs if r['run_id']==incident['id'])
        historical=proof['historical_proof']
        need(repair.get('original_head_sha')==incident['head_sha'] and
             historical.get('repairs')==[repair],'BOOTSTRAP_HISTORICAL_PROOF_CHANGED')
        original=frozen.verify_dispatch_proof(historical,[incident],repair['original_control'],incident['head_sha'],now)
        need(original is not None,'BOOTSTRAP_HISTORICAL_ORIGINAL_UNVERIFIED')
        _models_ok(repair.get('bootstrap_models'),repair,incident,expected_head,now)
        others=[r for r in runs if r['id']!=incident['id']]
        other_repairs=[r for r in repairs if r['run_id']!=incident['id']]
        need(all(frozen.ts(incident['created_at'])<=frozen.ts(r['created_at']) for r in others),
             'BOOTSTRAP_CURRENT_EPOCH_CHANGED')
        if other_repairs:
            current=proof.get('current_proof')
            need(type(current) is dict and current.get('repairs')==other_repairs,
                 'BOOTSTRAP_CURRENT_REPAIR_PROOF_MISSING')
            final=frozen.verify_dispatch_proof(current,others,fresh_control,expected_head,now)
            need(final is not None and proof.get('current_control') is None,'BOOTSTRAP_CURRENT_REPAIR_UNVERIFIED')
        elif others:
            need(proof.get('current_proof') is None and proof.get('current_control')==fresh_control and
                 all(r['conclusion']=='success' for r in others),'BOOTSTRAP_CURRENT_SUCCESS_UNVERIFIED')
            final=_successful_control(others,fresh_control,now)
        else:
            need(proof.get('current_proof') is None and proof.get('current_control') is None and
                 fresh_control==repair['original_control'],'BOOTSTRAP_CURRENT_FRESH_CONTROL_CHANGED')
            final=original
        need(proof.get('latest_control')==final and
             final['day_start_lifetime_requests']==original['day_start_lifetime_requests'] and
             final['lifetime_requests']>=original['lifetime_requests'] and
             final['lifetime_completed_rounds']>=original['lifetime_completed_rounds'],
             'BOOTSTRAP_CURRENT_INHERITED_COUNTER_CHANGED')
        _control_ledger(proof,runs,repairs,fresh_control,now)
        return deepcopy(final)
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError):return None
