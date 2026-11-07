"""Strict opt-in for one future BOAT native case in the existing push writer.

Pure validation only. Source collection, workflow creation and key lookup do
not exist here. An ordinary push has no request and keeps its existing flow.
"""
from copy import deepcopy
from datetime import timedelta, timezone
from hashlib import sha256
import re

from .actions_contract import digest, stamp
from .permissioned_source_delivery import read_json_bytes

SCHEMA = 'RACE_AI_BOAT_PROSPECTIVE_FORWARD_REQUEST_V1'
ACTIVATION = 'RACE_AI_BOAT_GRID_FORWARD_V1'
REQUEST_PATH = 'audit/state/boat-venue-future-forward-request.json'
GRID_PATH = 'audit/state/boat-venue-future-grid-input.json'
TRIGGER = 'docs/evidence/boat-nationwide-pilot-trigger.txt'
BRANCH = 'feat/four-sport-forecast-audit-view-20261022'
JST = timezone(timedelta(hours=9))


def need(ok, reason):
    if not ok: raise ValueError('BOAT_FORWARD_' + reason)


def activation(trigger, subject):
    if not subject.startswith('boat-grid-forward:'): return None
    lines = trigger.splitlines()
    need(lines and lines[-1].startswith(ACTIVATION+' '), 'ACTIVATION_REQUIRED')
    value = read_json_bytes(lines[-1][len(ACTIVATION)+1:].encode())
    need(type(value) is dict and set(value) == {'tested_head_sha', 'tested_run_id', 'request_sha256'} and
         type(value['tested_run_id']) is int and value['tested_run_id'] > 0 and
         re.fullmatch('[a-f0-9]{40}', value['tested_head_sha']) and
         re.fullmatch('[a-f0-9]{64}', value['request_sha256']) and
         subject == 'boat-grid-forward: '+value['request_sha256'], 'ACTIVATION_SCOPE')
    return value


def validate_request(value, *, now, grid_raw, runtime_raw):
    need(type(value) is dict and set(value) == {'schema','day_jst','max_cases','grid_input_path',
         'grid_input_sha256','runtime_pointer_sha256','target','predecessor'} and value['schema'] == SCHEMA and
         type(value['max_cases']) is int and value['max_cases'] == 1 and value['grid_input_path'] == GRID_PATH and
         value['grid_input_sha256'] == sha256(grid_raw).hexdigest() and
         value['runtime_pointer_sha256'] == sha256(runtime_raw).hexdigest(), 'REQUEST')
    need(now.utcoffset() is not None and value['day_jst'] == now.astimezone(JST).date().isoformat(), 'PHYSICAL_DAY')
    target = value['target']
    need(type(target) is dict and set(target) == {'race_id','cutoff_at','roster_sha256','active_count'} and
         type(target['race_id']) is str and re.fullmatch(value['day_jst'].replace('-','')+
         r'-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])', target['race_id']) and
         type(target['active_count']) is int and 3 <= target['active_count'] <= 6 and
         re.fullmatch('[a-f0-9]{64}', target['roster_sha256']) and
         type(target['cutoff_at']) is str and
         re.fullmatch(value['day_jst']+r'T[0-9]{2}:[0-9]{2}:[0-9]{2}\+09:00',target['cutoff_at']) and
         stamp(target['cutoff_at']).astimezone(JST).date().isoformat() == value['day_jst'] and
         now+timedelta(seconds=600) < stamp(target['cutoff_at']), 'EXACT_FUTURE_TARGET')
    previous = value['predecessor']
    need(type(previous) is dict and set(previous) == {'run_id','receipt','lifetime_requests','lifetime_completed_rounds'} and
         type(previous['run_id']) is int and previous['run_id'] > 0 and
         all(type(previous[k]) is int and previous[k] >= 0 for k in ('lifetime_requests','lifetime_completed_rounds')),
         'PREDECESSOR')
    receipt = previous['receipt']
    need(type(receipt) is dict and set(receipt) == {'id','digest','created_at'} and
         type(receipt['id']) is int and receipt['id'] > 0 and
         re.fullmatch('sha256:[a-f0-9]{64}', receipt['digest']) and stamp(receipt['created_at']) <= now,
         'PREDECESSOR_RECEIPT')
    return deepcopy(value)


def no_other_workers(get, current_run):
    from .saved_view_run import display_only_run
    for status in ('in_progress','queued','pending','waiting'):
        data = get(f'actions/workflows/405276784/runs?status={status}&per_page=100')
        need(type(data) is dict and type(data.get('workflow_runs')) is list and
             type(data.get('total_count')) is int and data['total_count'] == len(data['workflow_runs']) <= 100,
             'ACTIVE_RUN_PAGE')
        for run in data['workflow_runs']:
            need(run.get('workflow_id') == 405276784 and run.get('head_branch') == BRANCH, 'ACTIVE_RUN_IDENTITY')
            need(run['id'] == current_run or display_only_run(run), 'EXISTING_WORKER_MUST_BE_HONORED')


def admit(*, raw, activation, env, get, now, grid_raw, runtime_raw):
    need(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_EVENT_NAME') == 'push' and
         env.get('GITHUB_REPOSITORY') == 'haji84/RACE-AI' and env.get('GITHUB_REPOSITORY_ID') == '1416489937' and
         env.get('GITHUB_REF') == 'refs/heads/'+BRANCH and env.get('GITHUB_RUN_ATTEMPT') == '1' and
         env.get('GITHUB_WORKFLOW_REF') == 'haji84/RACE-AI/.github/workflows/boat-nationwide-ab-one-shot.yml@refs/heads/'+BRANCH and
         env.get('GITHUB_ACTOR') == 'haji84' and re.fullmatch('[a-f0-9]{40}',env.get('GITHUB_SHA','')) and
         re.fullmatch('[1-9][0-9]*',env.get('GITHUB_RUN_ID','')), 'OWNER_PUSH_ATTEMPT_ONE')
    need(type(activation) is dict and sha256(raw).hexdigest() == activation['request_sha256'], 'REQUEST_HASH')
    request = validate_request(read_json_bytes(raw), now=now, grid_raw=grid_raw, runtime_raw=runtime_raw)
    head = activation['tested_head_sha']; run_id = activation['tested_run_id']; current = env['GITHUB_SHA']
    run = get(f'actions/runs/{run_id}/attempts/1')
    need(run.get('id') == run_id and run.get('head_sha') == head and run.get('run_attempt') == 1 and
         run.get('status') == 'completed' and run.get('conclusion') == 'success' and
         run.get('workflow_id') == 392270247 and run.get('path') == '.github/workflows/forecast-audit-ui.yml' and
         run.get('event') == 'pull_request' and run.get('head_branch') == BRANCH and
         any(p.get('number') == 71 for p in run.get('pull_requests',[])) and
         all(run.get(k,{}).get('id') == 173585154 and run[k].get('login') == 'haji84'
             for k in ('actor','triggering_actor')) and
         all(run.get(k,{}).get('id') == 1416489937 and run[k].get('full_name') == 'haji84/RACE-AI'
             for k in ('repository','head_repository')), 'EXACT_FULL_TESTED_HEAD')
    jobs = get(f'actions/runs/{run_id}/attempts/1/jobs?per_page=100')
    need(type(jobs.get('jobs')) is list and jobs.get('total_count') == len(jobs['jobs']) <= 100, 'TEST_JOBS')
    for name in ('Viewer audit contract','Pinned PR64 store and PDCA synthetic E2E'):
        found = [job for job in jobs['jobs'] if job.get('name') == name]
        need(len(found) == 1 and found[0].get('status') == 'completed' and found[0].get('conclusion') == 'success',
             'REQUIRED_HEAVY_TEST')
    compared = get('compare/'+head+'...'+current)
    need(compared.get('status') == 'ahead' and compared.get('total_commits') == 1 and
         compared.get('base_commit',{}).get('sha') == compared.get('merge_base_commit',{}).get('sha') == head and
         len(compared.get('commits',[])) == 1 and compared['commits'][0].get('sha') == current and
         len(compared['commits'][0].get('parents',[])) == 1 and
         compared['commits'][0]['parents'][0].get('sha') == head and
         len(compared.get('files',[])) == 1 and compared['files'][0].get('filename') == TRIGGER and
         compared['files'][0].get('status') == 'modified', 'TRIGGER_ONLY_TESTED_CHILD')
    no_other_workers(get, int(env['GITHUB_RUN_ID']))
    return dict(schema='RACE_AI_BOAT_FORWARD_ADMISSION_V1',request=request,request_sha256=sha256(raw).hexdigest(),
        head_sha=current,run_id=int(env['GITHUB_RUN_ID']),tested_head_sha=head,tested_run_id=run_id)


def check_predecessor(request, control):
    previous = request['predecessor']
    need(type(control) is dict and control.get('previous_run_id') == previous['run_id'] and
         control.get('receipt') == previous['receipt'] and
         all(control.get(k) == previous[k] for k in ('lifetime_requests','lifetime_completed_rounds')) and
         control.get('prepared_round') is None and control.get('source_wait') is None and
         control.get('previous_halted_reason') is None and control.get('previous_stop_reason') in
         (None,'DAY_HANDOFF','DAY_CHANGED','BOUNDED_SESSION_END','MAX_ROUNDS_REACHED',
          'SOURCE_BUDGET_EXHAUSTED','SESSION_SOURCE_BUDGET_EXHAUSTED','ROUND_SOURCE_BUDGET_EXHAUSTED','WORKER_HANDOFF'),
         'AUTHENTICATED_PREDECESSOR_REQUIRED')


def check_case(request, rows, *, now):
    from .boat_venue_future_grid import prospective_requests
    from .all_existing_model_registry import identity
    from .existing_model_dispatch import _race_key
    need(type(rows) is list and len(rows) == len({row['cell_key'] for row in rows}) == 14, 'EXACT_FOURTEEN')
    prospective_requests(rows, now=now)
    target = request['target']; infos = [identity(row['cell_key'][5:],'boat',row['native_payload']) for row in rows]
    for info in infos:
        roster = {str(slot):str(value) for slot,value in info['roster'].items()}
        need(_race_key(info['race_id'],'boat') == _race_key(target['race_id'],'boat') and
             stamp(info['cutoff_at']) == stamp(target['cutoff_at']) and
             len(roster) == target['active_count'] and digest(roster) == target['roster_sha256'], 'EXACT_CASE')
    return dict(native_cell_count=14,unique_races=1,source_as_of=infos[0]['as_of'],
        cutoff_at=target['cutoff_at'],roster_sha256=target['roster_sha256'],native_inputs_sha256=digest(rows))


def check_rows(request, rows, *, now, saved_at):
    proof = check_case(request,rows,now=now)
    need(stamp(saved_at) <= now and stamp(saved_at)+timedelta(seconds=601) < stamp(request['target']['cutoff_at']),
         'ACTUAL_SAVE_SIX_HUNDRED_MARGIN')
    return proof
