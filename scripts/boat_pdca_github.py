"""Explicit owner-key encrypted publication/readback; never manages GitHub secrets."""
import argparse
import base64
import json
import os
import re
from pathlib import Path
import stat
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.boat_pdca_github_handoff import publish_checkpoint,readback
from race_ai.boat_pdca_state import state_key,need
from race_ai.boat_history_store import wire
from scripts.boat_history_collect import private_root,save


def owner_key_file(path):
    if path is None:return None
    path=Path(path).absolute()
    need(path.is_file() and not path.is_symlink(),'OWNER_PRIVATE_KEY_FILE_REQUIRED')
    private_root(path.parent)
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        info=os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and not info.st_mode&0o077 and info.st_size<=128,'OWNER_PRIVATE_KEY_FILE_REQUIRED')
        raw=os.read(fd,129).strip()
    finally:os.close(fd)
    try:key=base64.b64decode(raw,validate=True)
    except ValueError:raise ValueError('OWNER_STATE_KEY_REQUIRED') from None
    return state_key('production',key)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    a=commands.add_parser('publish');a.add_argument('--state',type=Path,required=True)
    a.add_argument('--repo',type=Path,default=ROOT);a.add_argument('--output',type=Path,required=True)
    a.add_argument('--initialize',action='store_true');a.add_argument('--expected-parent')
    b=commands.add_parser('readback');b.add_argument('--input',type=Path,required=True)
    b.add_argument('--private-dir',type=Path,required=True)
    for cmd in commands.choices.values():cmd.add_argument('--owner-key-file',type=Path)
    args=p.parse_args(argv)
    try:
        key=owner_key_file(args.owner_key_file)
        if args.command=='publish':
            report=publish_checkpoint(args.state,args.repo,args.output,initialize=args.initialize,
                expected_parent=args.expected_parent,key=key)
        else:
            need(args.input.is_file() and not args.input.is_symlink() and args.input.stat().st_size<=8192,'BOUNDED_STATE_INPUT_REQUIRED')
            pointer=json.loads(args.input.read_text());report=readback(pointer,args.private_dir,key=key)
            root=private_root(args.private_dir)
            save(root/'production-readback-status.json',(wire(report)+'\n').encode())
        print(wire(report));return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'(?:STATE_|OWNER_|PRODUCTION_|BOUNDED_)[A-Z0-9_]{1,80}',str(exc)) else 'STATE_OPERATION_FAILED'
        status='HOLD_OWNER_STATE_KEY_MISSING' if reason.startswith('OWNER_STATE_KEY_REQUIRED') else 'STATE_GITHUB_HANDOFF_REJECTED'
        print(wire(dict(status=status,reason=reason,action=args.command,plaintext_published=False)))
        return 2


if __name__=='__main__':raise SystemExit(main())
