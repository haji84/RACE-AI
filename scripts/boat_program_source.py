"""Retain the current first-P0's already-captured official B inside Actions."""
import argparse
from datetime import datetime,timezone
import os
from pathlib import Path
import re
import stat
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from race_ai import boat_program_source as P
from race_ai import boat_private_original_vault as V
from race_ai.actions_contract import digest
from scripts.boat_private_original_vault import _environment,_private_path,_write,_parent


def _local(path,limit):
    V._need(not any(p.is_symlink() for p in (path,*path.parents)),'LOCAL_FIRST_P0_SYMLINK_REJECTED')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as stream:
        before=os.fstat(stream.fileno())
        V._need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<=limit,
                'LOCAL_FIRST_P0_BOUND_INVALID')
        raw=stream.read(limit+1);after=os.fstat(stream.fileno())
    V._need(len(raw)==before.st_size and len(raw)<=limit and
        (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
        (after.st_size,after.st_mtime_ns,after.st_ctime_ns),'LOCAL_FIRST_P0_CHANGED')
    return raw


def _first_p0(repo,git,parent):
    body=_local(repo/'boat_all_day_output/forecasts.json',32*1024*1024)
    metadata=V._json(_local(repo/'boat_all_day_output/first-receipt.json',V.MAX_METADATA),V.MAX_METADATA)
    V._need(type(metadata) is dict,'LOCAL_FIRST_P0_METADATA_INVALID')
    locator=V.lookup_original(metadata.get('id'),repo,source_commit=parent,transport=git)
    V._need(locator is not None and locator['kind']=='P0','VERIFIED_FIRST_P0_VAULT_REQUIRED')
    restored=V.restore_original(locator,repo,transport=git)
    V._need(metadata==restored['metadata'],'LOCAL_FIRST_P0_RECEIPT_CONFLICT')
    with V.native.open_original_zip(restored['raw_zip'],restored['metadata'],expected_kind='P0',
                                   max_plain_zip_bytes=32*1024*1024) as original:
        V._need(original.namelist()==['forecasts.json'] and original.read('forecasts.json')==body,
                'LOCAL_FIRST_P0_DOCUMENT_CONFLICT')
    document=V._json(body,32*1024*1024);run=metadata['workflow_run']
    receipt=dict(repository_id=V.REPO_ID,repository='haji84/RACE-AI',run_id=str(run['id']),head_sha=run['head_sha'],
        artifact_id=metadata['id'],created_at=metadata['created_at'],payload_sha256=digest(document),independently_verified=True)
    return document,receipt


def main(argv=None,*,transport=None,readback_transport=None,now=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    retain=commands.add_parser('retain')
    retain.add_argument('--day',required=True);retain.add_argument('--repo-root',default=str(ROOT))
    retain.add_argument('--output',required=True);retain.add_argument('--expected-parent',default='current')
    args=parser.parse_args(argv)
    try:
        repo=_environment(args.repo_root);output=_private_path(args.output,repo,exists=False)
        git=V._transport(repo,transport);parent=_parent(git,args.expected_parent)
        document,receipt=_first_p0(repo,git,parent)
        report=P.retain_program_source(args.day,document,receipt,repo,expected_parent=parent,
            transport=git,readback_transport=readback_transport,now=now or datetime.now(timezone.utc))
        _write(output,V._wire(report)+b'\n');print(V._wire(report).decode())
        return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'(?:PROGRAM_SOURCE|VAULT)_[A-Z0-9_]{1,100}',str(exc)) else 'PROGRAM_SOURCE_RETAIN_REJECTED'
        print(V._wire(dict(status='OFFICIAL_B_PROGRAM_SOURCE_REJECTED',reason=reason,source_requests=0)).decode())
        return 2


if __name__=='__main__':raise SystemExit(main())
