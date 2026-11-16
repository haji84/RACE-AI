"""Existing owner gate plus a trusted source-free pending-round recovery proof.

No run is relabeled, source request made, scheduler added or state counter reset.
The proof is an internal file from the preceding authenticated recovery step,
not a public API, user workflow input or producer success declaration.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo
from scripts import boat_main_dispatch_gate as base
from scripts.boat_failed_recovery_contract import verify_dispatch_proof


def read_pinned_control(run, *, reader_root=None):
    """Use the exact producer package in a fresh process, not main's namespace.

    Only the opaque public checkpoint is read. No AES key or archive-recovery
    mode enters the child; any unavailable or mismatched reader fails closed.
    """
    try:
        root = Path(reader_root) if reader_root is not None else (
            Path(__file__).resolve().parents[1]/'boat-owner-reader')
        if root.is_symlink() or not root.is_dir():
            raise ValueError('RECOVERY_PINNED_READER_UNAVAILABLE')
        root = root.resolve()
        head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,
                                       stderr=subprocess.DEVNULL,timeout=10).decode().strip()
        if head != base.RELEASE_SHA:
            raise ValueError('RECOVERY_PINNED_READER_HEAD_CHANGED')
        request = json.dumps(run,separators=(',',':'),allow_nan=False).encode()
        if type(run) is not dict or not 0 < len(request) <= base.MAX_JSON_BYTES:
            raise ValueError('RECOVERY_PINNED_READER_INPUT_INVALID')
        environment = dict(os.environ)
        for name in ('RACE_AI_STATE_KEY','RACE_AI_ORIGINAL_VAULT_ENABLED','PYTHONPATH','PYTHONHOME'):
            environment.pop(name,None)
        program = (
            "import json,sys\n"
            "from race_ai.github_continuous_supervisor import GitHubCLI\n"
            "raw=sys.stdin.buffer.read(1048577)\n"
            "assert 0<len(raw)<=1048576\n"
            "result=GitHubCLI().final_control(json.loads(raw))\n"
            "assert type(result) is dict\n"
            "wire=json.dumps(result,sort_keys=True,allow_nan=False).encode()\n"
            "assert 0<len(wire)<=1048576\n"
            "sys.stdout.buffer.write(wire)\n")
        result = subprocess.run([sys.executable,'-S','-c',program],cwd=root,env=environment,
            input=request,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=120,check=False)
        if result.returncode != 0 or not 0 < len(result.stdout) <= base.MAX_JSON_BYTES:
            raise ValueError('RECOVERY_PINNED_CONTROL_UNAVAILABLE')
        control = json.loads(result.stdout)
        if type(control) is not dict:
            raise ValueError('RECOVERY_PINNED_CONTROL_INVALID')
        return control
    except (OSError,subprocess.SubprocessError,UnicodeError,ValueError,TypeError):
        # Child diagnostics may contain URLs; do not echo them into Actions logs.
        raise ValueError('RECOVERY_PINNED_CONTROL_UNAVAILABLE') from None


def _today(history, now):
    day=now.astimezone(ZoneInfo('Asia/Tokyo')).date()
    return [r for r in history.get('workflow_runs',[]) if type(r) is dict and
        r.get('event')=='workflow_dispatch' and r.get('head_branch')==base.RELEASE_REF and
        r.get('name')==base.WORKFLOW and base._stamp(r['created_at']).astimezone(ZoneInfo('Asia/Tokyo')).date()==day]


def _resume_control_ok(control, latest, now, recovered_latest):
    try:
        if (control.get('previous_run_id')!=latest['id'] or
                control.get('day_jst')!=now.astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat() or
                control.get('prepared_round') is not None or control.get('source_wait') is not None or
                control.get('previous_halted_reason') is not None):
            return False
        allowed=(None,) if recovered_latest else ('BOUNDED_SESSION_END','MAX_ROUNDS_REACHED','WORKER_HANDOFF')
        if control.get('previous_stop_reason') not in allowed:return False
        total,baseline,used,rounds=(control.get(k) for k in
            ('lifetime_requests','day_start_lifetime_requests','previous_session_requests','completed_round'))
        if (any(type(x) is not int for x in (total,baseline,used,rounds)) or
                min(total,baseline,used,rounds)<0 or not used<=total-baseline):return False
        for key in ('receipt','source_control_receipt'):
            meta=control.get(key)
            if (type(meta) is not dict or type(meta.get('id')) is not int or meta['id']<=0 or
                    re.fullmatch('sha256:[a-f0-9]{64}',str(meta.get('digest'))) is None or
                    not base._stamp(latest['created_at'])<=base._stamp(meta['created_at'])<=now):return False
        return True
    except (KeyError,TypeError,ValueError,OverflowError):return False


def decide(*, now, release, owner_doc, history, retry_proof=None,
           continuation_proof=None, recovery_proof=None):
    # Preserve every original release, policy, complete-history and active-writer
    # guard. Only its same-day failure HOLD is eligible for a recovery phase.
    result=base.decide(now=now,release=release,owner_doc=owner_doc,history=history,
                       retry_proof=retry_proof,continuation_proof=continuation_proof)
    result['recovery_required']=False
    if result['status']!='HOLD_ALREADY_DISPATCHED_FOR_JST_DAY':return result
    if now.astimezone(ZoneInfo('Asia/Tokyo')).hour<6:return result
    runs=_today(history,now)
    if (not runs or len({r['id'] for r in runs})!=len(runs) or
            any(r.get('head_sha')!=base.RELEASE_SHA or r.get('status')!='completed' or
                r.get('conclusion') not in ('success','failure') for r in runs) or
            not any(r.get('conclusion')=='failure' for r in runs)):return result
    result['recovery_required']=True
    if recovery_proof is None:return result
    fixed=verify_dispatch_proof(recovery_proof,runs,continuation_proof,base.RELEASE_SHA,now)
    if fixed is None:return result
    latest=max(runs,key=lambda r:base._stamp(r['created_at']))
    repaired_ids={r['run_id'] for r in recovery_proof['repairs']}
    if not _resume_control_ok(fixed,latest,now,latest['id'] in repaired_ids):return result
    result.update(status='READY_VERIFIED_RECOVERED_OWNER_CONTINUATION',
                  dispatch_allowed=True,recovery_required=False)
    return result


def trusted_owner_completion(history, now, *, env=None):
    """Verify GitHub's completed-owner event against independent live run history.

    This only enables a source-free gate decision. A genuine AES continuity
    control and release approval remain mandatory before any new owner starts.
    """
    env = os.environ if env is None else env
    if (env.get('GITHUB_ACTIONS')!='true' or
            env.get('GITHUB_EVENT_NAME')!='workflow_run' or
            env.get('GITHUB_REPOSITORY')!=base.REPO or
            env.get('GITHUB_REF')!='refs/heads/main' or
            not isinstance(now,datetime) or now.utcoffset() is None):
        return False
    try:
        name=env.get('GITHUB_EVENT_PATH')
        if type(name) is not str or not name:return False
        path=Path(name)
        if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=base.MAX_JSON_BYTES:
            return False
        payload=json.loads(path.read_text(encoding='utf-8'))
        if type(payload) is not dict or payload.get('action')!='completed':
            return False
        actual=payload.get('workflow_run')
        if type(actual) is not dict or not type(actual.get('id')) is int or actual['id']<=0:
            return False
        if (actual.get('name')!=base.WORKFLOW or
                actual.get('event')!='workflow_dispatch' or
                actual.get('head_branch')!=base.RELEASE_REF or
                actual.get('head_sha')!=base.RELEASE_SHA or
                actual.get('status')!='completed' or
                actual.get('conclusion') not in ('success','failure') or
                (actual.get('head_repository') or {}).get('full_name')!=base.REPO or
                (actual.get('repository') or {}).get('full_name')!=base.REPO):
            return False
        creation=base._stamp(actual.get('created_at'))
        if (creation>now or
                creation.astimezone(ZoneInfo('Asia/Tokyo')).date() !=
                now.astimezone(ZoneInfo('Asia/Tokyo')).date()):
            return False
        items=history.get('workflow_runs')
        total=history.get('total_count')
        if (type(items) is not list or len(items)>100 or type(total) is not int or
                total<len(items)):
            return False
        matches=[row for row in items if type(row) is dict and row.get('id')==actual['id']]
        if len(matches)!=1:return False
        source=matches[0]
        for field in ('id','name','event','head_branch','head_sha',
                      'status','conclusion','created_at'):
            if source.get(field)!=actual.get(field):return False
        today=_today(history,now)
        return (bool(today) and
                max(today,key=lambda row:base._stamp(row['created_at']))['id']==actual['id'])
    except (KeyError,ValueError,TypeError,OSError,UnicodeError,OverflowError):
        return False


def main(argv=None, *, now=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('release','owner-doc','history'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--retry-proof',type=Path)
    p.add_argument('--recovery-proof',type=Path)
    p.add_argument('--verify-source-handoff',action='store_true')
    p.add_argument('--github-output',type=Path)
    args=p.parse_args(argv)
    now=now or datetime.now(timezone.utc)
    history=base._load(args.history)
    triggered=trusted_owner_completion(history,now)
    source_gate_event=(os.environ.get('GITHUB_EVENT_NAME')=='schedule' or triggered)
    control=None
    if args.verify_source_handoff and source_gate_event:
        candidates=_today(history,now)
        if candidates:
            latest=max(candidates,key=lambda r:base._stamp(r['created_at']))
            if latest.get('status')=='completed' and latest.get('conclusion') in ('success','failure'):
                try:
                    control=read_pinned_control(latest)
                except Exception:
                    control=None
    proof=None
    if args.recovery_proof:
        if (os.environ.get('GITHUB_ACTIONS')!='true' or not source_gate_event
                or os.environ.get('GITHUB_REPOSITORY')!='haji84/RACE-AI'):
            raise ValueError('RECOVERY_PROOF_TRUSTED_TRIGGER_REQUIRED')
        proof=base._load(args.recovery_proof)
    result=decide(now=now,release=base._load(args.release),owner_doc=base._load(args.owner_doc),
        history=history,retry_proof=base._load(args.retry_proof) if args.retry_proof else None,
        continuation_proof=control,recovery_proof=proof)
    if args.github_output:
        if args.github_output.is_symlink() or not args.github_output.is_file():
            raise ValueError('BOAT_DISPATCH_OUTPUT_INVALID')
        with args.github_output.open('a',encoding='utf8') as out:
            for key,value in (('ready',result['dispatch_allowed']),('recovery_required',result['recovery_required'])):
                out.write(key+'='+('true' if value else 'false')+'\n')
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=='__main__':raise SystemExit(main())
