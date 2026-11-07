"""Publish a durable count-only handoff mirror from completed Actions runs."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from race_ai import boat_source_control_mirror as M,boat_private_original_vault as V
from scripts.boat_private_original_vault import _environment,_parent,_private_path,_write,_gh


def _get(endpoint):
    listing=f'actions/workflows/{M.R.WORKFLOW}/runs?per_page=16&status=completed'
    if endpoint!=listing:return _gh(endpoint)
    result=subprocess.run(['gh','api','repos/haji84/RACE-AI/'+endpoint],capture_output=True,timeout=60)
    M._need(result.returncode==0,'GITHUB_READ_DENIED_OR_UNAVAILABLE')
    M._need(0<len(result.stdout)<=2*1024*1024,'RECENT_RUN_RESPONSE_BOUND_INVALID')
    return result.stdout


def main(argv=None,*,get=None,transport=None,readback_transport=None,now=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('publish','latest-closed'):
        command=commands.add_parser(name)
        command.add_argument('--repo-root',default=str(ROOT));command.add_argument('--output',required=True)
        command.add_argument('--expected-parent',default='current')
        if name=='publish':command.add_argument('--run-id',type=int,required=True)
    args=parser.parse_args(argv)
    try:
        repo=_environment(args.repo_root);output=_private_path(args.output,repo,exists=False)
        git=V._transport(repo,transport);parent=_parent(git,args.expected_parent)
        kwargs=dict(get=get or _get,expected_parent=parent,transport=git,readback_transport=readback_transport,
                    now=now or datetime.now(timezone.utc))
        report=M.publish_control(args.run_id,repo,**kwargs) if args.command=='publish' else M.publish_latest_closed(repo,**kwargs)
        _write(output,V._wire(report)+b'\n');print(V._wire(report).decode());return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'(?:CONTROL_MIRROR|SAFE_SOURCE_CONTROL|VAULT)_[A-Z0-9_]{1,100}',str(exc)) else 'CONTROL_MIRROR_OPERATION_FAILED'
        print(V._wire(dict(status='SOURCE_CONTROL_MIRROR_HOLD',reason=reason,source_requests=0)).decode());return 2


if __name__=='__main__':raise SystemExit(main())
