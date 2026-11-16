"""Source-free recovery before the existing main launcher admits a successor.

Run only from trusted Actions checkouts, never from PR data or a forecast job
rerun. No official-source fetch, inference, scorer, clock rewrite or counter
reset. A failure produces no permission; a later trusted main launcher retries
this recovery phase rather than re-running the failed prediction job.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MAIN_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/boat-racer-daily.yml@refs/heads/main'
RELEASE_PREFIX='boat-owner-release: single-real-session-20261111'


def trusted_main_invocation(event, document, *, workflow_ref, ref, sha, expected_source_head):
    """Match existing main job events; never relabel a callback as a schedule."""
    from scripts.boat_failed_recovery_contract import need,reviewed_recovery_origin
    need(workflow_ref==MAIN_WORKFLOW_REF and ref=='refs/heads/main' and
         type(sha) is str and re.fullmatch('[a-f0-9]{40}',sha) and
         type(document) is dict,'TRUSTED_MAIN_EVENT_REQUIRED')
    repository=document.get('repository')
    need(type(repository) is dict and type(repository.get('id')) is int and
         repository['id']==1416489937 and repository.get('full_name')=='haji84/RACE-AI',
         'TRUSTED_MAIN_REPOSITORY_REQUIRED')
    if event=='schedule':
        need(document.get('schedule') in ('30 20 * * *','20 21 * * *',
             '2-59/5 22-23 * * *','2-59/5 0-14 * * *'),'TRUSTED_MAIN_SCHEDULE_REQUIRED')
    elif event=='workflow_run':
        run=document.get('workflow_run');need(type(run) is dict,'TRUSTED_CALLBACK_REQUIRED')
        head=run.get('head_repository')
        need(type(run.get('id')) is int and run['id']>0 and
             type(run.get('workflow_id')) is int and run['workflow_id']==405276784 and
             run.get('name')=='BOAT nationwide cutoff-ordered A/B research (no Vercel)' and
             run.get('head_branch')=='production/boat-p0-p1-20261111' and
             run.get('event')=='workflow_dispatch' and run.get('status')=='completed' and
             run.get('conclusion') in ('failure','success') and
             type(run.get('run_attempt')) is int and run['run_attempt']==1 and
             reviewed_recovery_origin(run.get('head_sha'),expected_source_head) and
             type(head) is dict and type(head.get('id')) is int and head['id']==1416489937 and
             head.get('full_name')=='haji84/RACE-AI','TRUSTED_CALLBACK_REQUIRED')
    elif event=='push':
        commit=document.get('head_commit')
        need(document.get('ref')==ref and document.get('after')==sha and
             type(commit) is dict and commit.get('id')==sha and
             type(commit.get('message')) is str and commit['message'].startswith(RELEASE_PREFIX),
             'TRUSTED_RELEASE_PUSH_REQUIRED')
    else:
        need(False,'TRUSTED_MAIN_EVENT_REQUIRED')
    return True


def _invocation_context(expected_head):
    from scripts.boat_failed_recovery_contract import need
    path=Path(os.environ.get('GITHUB_EVENT_PATH',''))
    need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=1024*1024,
         'TRUSTED_MAIN_EVENT_FILE_REQUIRED')
    try:document=json.loads(path.read_text(encoding='utf8'))
    except (ValueError,UnicodeError):need(False,'TRUSTED_MAIN_EVENT_FILE_REQUIRED')
    return trusted_main_invocation(os.environ.get('GITHUB_EVENT_NAME'),document,
        workflow_ref=os.environ.get('GITHUB_WORKFLOW_REF'),ref=os.environ.get('GITHUB_REF'),
        sha=os.environ.get('GITHUB_SHA'),expected_source_head=expected_head)


def _packages():
    import race_ai
    for folder in ('pr64-reference', 'pr72-reference'):
        path = ROOT/folder/'race_ai'
        if not path.is_dir():
            raise ValueError('RECOVERY_PINNED_ADAPTER_MISSING')
        if str(path) not in race_ai.__path__:
            race_ai.__path__.append(str(path))


def retain_verified_pair(checked, run, repo, *, now, transport=None, readback_transport=None):
    from scripts import boat_private_original_vault as cli
    V = cli.V
    git = V._transport(repo, transport)
    replies = {f'actions/runs/{run["id"]}': json.dumps(run).encode()}
    for original in checked['originals']:
        ident = original['metadata']['id']
        replies[f'actions/artifacts/{ident}'] = original['metadata_raw']
        replies[f'actions/artifacts/{ident}/zip'] = original['raw_zip']
    # Already authenticated bytes only. An unexpected read is a hard failure,
    # never a request to a racing site or a different archive.
    saved = cli._capture(checked['original_artifact_ids'], repo, cli._parent(git, 'current'),
                         git, readback_transport, lambda route:replies[route], now,
                         allow_refresh=True)
    if saved.get('independent_git_readback_verified') is not True:
        raise ValueError('RECOVERY_VAULT_READBACK_UNVERIFIED')
    return saved


def recover_restored_pending(state, get, repo, *, now=None):
    from race_ai.boat_pending_round_recovery import reconcile_restored_state
    now = now or datetime.now(timezone.utc)
    control=state.get('source_control')
    if (not control or control.get('prepared_round') is None
            or control.get('day_jst')!=state.get('day_jst')):
        return state
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,
                                 stderr=subprocess.DEVNULL,timeout=10).decode().strip()
    restored, pending = reconcile_restored_state(state, get, now=now,expected_head=head)
    if pending is not None:
        saved = retain_verified_pair(pending['verified'], pending['run'], repo, now=now)
        restored['pending_round_recovery_vault_commit'] = saved['source_commit']
    return restored


def today_owners(history, *, now, expected_head):
    from race_ai.boat_pending_round_recovery import JST, need
    from race_ai.frozen_day_cycle import ts
    from race_ai.boat_owner_source_identity import OWNER_BRANCH
    from scripts.boat_failed_recovery_contract import reviewed_recovery_origin
    rows, total = history.get('workflow_runs'), history.get('total_count')
    need(type(rows) is list and type(total) is int and 0 <= len(rows) <= 100 and total >= len(rows),
         'HISTORY_INCOMPLETE')
    need(all(type(r) is dict and ts(r['created_at']) <= now for r in rows), 'HISTORY_CLOCK')
    need(all(ts(rows[i]['created_at']) >= ts(rows[i+1]['created_at']) for i in range(len(rows)-1)),
         'HISTORY_ORDER')
    day = now.astimezone(JST).date()
    need(total == len(rows) or len(rows) == 100 and ts(rows[-1]['created_at']).astimezone(JST).date() < day,
         'HISTORY_WINDOW_INCOMPLETE')
    owners = [r for r in rows if r.get('event') == 'workflow_dispatch' and r.get('head_branch') == OWNER_BRANCH
              and r.get('name') == 'BOAT nationwide cutoff-ordered A/B research (no Vercel)']
    need(not any(r.get('status') != 'completed' for r in owners), 'ACTIVE_OWNER')
    today = [r for r in owners if ts(r['created_at']).astimezone(JST).date() == day]
    need(1 <= len(today) <= 24 and len({r['id'] for r in today}) == len(today), 'HISTORY_BOUND')
    need(all(reviewed_recovery_origin(r.get('head_sha'),expected_head) and
             r.get('conclusion') in ('failure','success') for r in today),
         'HISTORY_OWNER_RELEASE')
    need(any(r['conclusion'] == 'failure' for r in today), 'NO_FAILED_OWNER')
    return today


def recover_history(runs, *, get, load_control, replay_day, retain, now, expected_head):
    from race_ai.boat_pending_round_recovery import (PROOF_SCHEMA, JST, need,
        verify_recoverable_pending, verify_no_pending_failed_owner, history_digest, verify_dispatch_proof)
    from race_ai.boat_owner_source_identity import authenticated_live_owner_run
    from scripts.boat_failed_recovery_contract import reviewed_recovery_origin
    snapshots = []
    controls = {}
    for row in runs:
        actual = json.loads(get(f'actions/runs/{row["id"]}'))
        need(authenticated_live_owner_run(actual) and history_digest([actual]) == history_digest([row])
             and actual.get('run_attempt',1) == 1 and
             reviewed_recovery_origin(actual['head_sha'],expected_head), 'RUN_CHANGED')
        snapshots.append(actual)
        controls[actual['id']] = load_control(actual)
    # Existing readers replay every saved day original, including original
    # timing, training/result provenance and duplicate detection, before writes.
    state = replay_day()
    need(state.get('complete') is True and any(r.get('stage') == 'P0' for r in state.get('rows',[])),
         'DAY_REPLAY_INCOMPLETE')
    latest = max(snapshots, key=lambda r:r['created_at'])
    latest_control = deepcopy(controls[latest['id']])
    repairs = []
    for run in snapshots:
        if run['conclusion'] != 'failure':
            continue
        control = controls[run['id']]
        if control.get('prepared_round') is None:
            # A failed owner can stop during P0 retention BEFORE round 01.
            # The old pending-round-only recovery rejected this genuine state.
            # Authenticate absent P1/RESULT artifacts, source budget == 0,
            # and the already replayed P0 before allowing a successor gate.
            checked = verify_no_pending_failed_owner(get, run, control, now=now)
            repairs.append(dict(run_id=run['id'], original_control=deepcopy(control),
                control=checked['control'], vault_commit=None,
                original_artifact_ids=[]))
        else:
            checked = verify_recoverable_pending(get, run, control, now=now,replayed_state=state,
                                                 expected_head=expected_head)
            saved = retain(checked, run)
            need(saved.get('independent_git_readback_verified') is True and
                 re.fullmatch('[a-f0-9]{40}',str(saved.get('source_commit'))),
                 'VAULT_READBACK_MISSING')
            repairs.append(dict(run_id=run['id'], original_control=deepcopy(control),
                control=checked['control'], vault_commit=saved['source_commit'],
                original_artifact_ids=checked['original_artifact_ids']))
        if run['id'] == latest['id']:
            latest_control = checked['control']
        repairs[-1]['original_head_sha']=run['head_sha']
    proof = dict(schema=PROOF_SCHEMA, head_sha=expected_head, day_jst=now.astimezone(JST).date().isoformat(),
                 verified_at=now.isoformat(), history_sha256=history_digest(runs),
                 latest_control=latest_control, repairs=repairs)
    need(verify_dispatch_proof(proof,runs,controls[latest['id']],expected_head,now) is not None,
         'FINAL_PROOF_REJECTED')
    return proof


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--history', type=Path, required=True)
    p.add_argument('--expected-head', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        _packages()
        from race_ai.boat_pending_round_recovery import need, read_final_control, JST, history_digest
        from race_ai.cycle_recovery import recover
        from scripts import boat_private_original_vault as vault
        from scripts.github_existing_cycle import gh
        _invocation_context(args.expected_head)
        repo = vault._environment(ROOT)
        actual_head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,timeout=10).decode().strip()
        need(actual_head == args.expected_head, 'CHECKOUT_RELEASE_CHANGED')
        need(args.history.is_file() and not args.history.is_symlink() and args.history.stat().st_size <= 1024*1024,
             'HISTORY_FILE_INVALID')
        output = vault._private_path(args.output, repo, exists=False)
        now = datetime.now(timezone.utc)
        supplied = json.loads(args.history.read_text())
        runs = today_owners(supplied,now=now,expected_head=args.expected_head)
        fresh = json.loads(gh('actions/workflows/405276784/runs?branch=production%2Fboat-p0-p1-20261111&per_page=100'))
        need(history_digest(today_owners(fresh,now=now,expected_head=args.expected_head)) == history_digest(runs),
             'OWNER_CHANGED_BEFORE_RECOVERY')
        with tempfile.TemporaryDirectory(prefix='boat-sourcefree-recovery-',dir=os.environ['RUNNER_TEMP']) as folder:
            def replay():
                return recover(gh,now.astimezone(JST).date().isoformat(),
                    current_run=int(os.environ['GITHUB_RUN_ID']),out=Path(folder)/'originals',clock=lambda:now)
            proof = recover_history(runs,get=gh,load_control=lambda r:read_final_control(gh,r),
                replay_day=replay,retain=lambda c,r:retain_verified_pair(c,r,repo,now=now),
                now=now,expected_head=args.expected_head)
        # Fresh history is independently rechecked by the main gate as well.
        vault._write(output,json.dumps(proof,sort_keys=True).encode()+b'\n')
        print(json.dumps(dict(status='FAILED_OWNER_ORIGINALS_RECOVERED',
            recovered_runs=len(proof['repairs']),official_source_requests=0,new_forecasts=0,
            original_forecasts_changed=False,successor_not_yet_dispatched=True)))
        return 0
    except Exception as exc:
        # Never log raw decoded owner payloads, subprocess output or keys.
        reason = str(exc) if re.fullmatch(r'(?:ROUND_RECOVERY_|VAULT_|SAFE_SOURCE_CONTROL_)[A-Z0-9_]{1,100}',str(exc)) else 'RECOVERY_VERIFICATION_OR_STORAGE_UNAVAILABLE'
        print(json.dumps(dict(status='HOLD_FAILED_OWNER_RECOVERY',reason=reason,official_source_requests=0,
                              new_forecasts=0,successor_dispatch_allowed=False)))
        return 2

if __name__=='__main__':
    raise SystemExit(main())
