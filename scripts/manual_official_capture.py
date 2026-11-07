"""Explicit one-time official source capture, encryption and private restore.

No schedule or model execution. Collection requires an explicit current JST
day, each URL and its private-use terms manifest. Seal/restore use the existing
configured owner key only when those commands are explicitly invoked; keys
are never accepted in arguments or printed. Collection itself needs no key.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai import manual_official_capture as capture


def _manifest(path):
    path=Path(path).absolute()
    capture._need(not any(parent.is_symlink() for parent in (path,*path.parents)),'TERMS_FILE_SYMLINK_REJECTED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as source:
        info=os.fstat(source.fileno())
        capture._need(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and 0<info.st_size<=capture.MAX_METADATA,
                      'TERMS_FILE_BOUND_INVALID')
        raw=source.read(capture.MAX_METADATA+1)
    capture._need(len(raw)==info.st_size<=capture.MAX_METADATA,'TERMS_FILE_BOUND_INVALID')
    return capture._json(raw)


def main(argv=None,*,clock=None,opener=None,sleeper=None,monotonic=None,key=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    collect=commands.add_parser('collect',help='collect explicit official URLs once into a private cache')
    collect.add_argument('--execution-day',required=True)
    collect.add_argument('--url',action='append',required=True)
    collect.add_argument('--terms-manifest',required=True)
    collect.add_argument('--cache-dir',required=True)
    collect.add_argument('--request-limit',type=int,default=capture.MAX_REQUESTS)
    seal=commands.add_parser('seal',help='encrypt the cache and independently read every encrypted source')
    seal.add_argument('--cache-dir',required=True);seal.add_argument('--sealed-dir',required=True)
    seal.add_argument('--run-id',required=True);seal.add_argument('--round-no',type=int,required=True)
    restore=commands.add_parser('restore',help='restore exact source bytes to a new private directory')
    restore.add_argument('--sealed-dir',required=True);restore.add_argument('--output-dir',required=True)
    restore.add_argument('--expected-index-sha256',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='collect':
            injected={name:value for name,value in (('clock',clock),('opener',opener),('sleeper',sleeper),
                                                     ('monotonic',monotonic)) if value is not None}
            result=capture.collect_once(args.url,execution_day=args.execution_day,
                terms_manifest=_manifest(args.terms_manifest),cache_dir=args.cache_dir,
                request_limit=args.request_limit,**injected)
            status=0 if result['captured_sources']==len(args.url) else 2
        else:
            if key is None:
                from race_ai.boat_pdca_state import state_key
                key=state_key('production')
            if args.command=='seal':
                result=capture.seal_cache(args.cache_dir,args.sealed_dir,key=key,run_id=args.run_id,round_no=args.round_no)
            else:
                result=capture.restore_cache(args.sealed_dir,args.output_dir,key=key,
                                            expected_index_sha256=args.expected_index_sha256)
            status=0
    except (ValueError,OSError,TypeError,KeyError) as exc:
        reason=str(exc)
        if re.fullmatch(r'(?:MANUAL_OFFICIAL|ALL_MODEL_FORECAST)_[A-Z0-9_]{1,120}',reason) is None:
            reason='MANUAL_OFFICIAL_OPERATION_REJECTED'
        result=dict(state='MANUAL_OFFICIAL_CAPTURE_REJECTED',reason=reason,plaintext_published=False)
        status=2
    print(json.dumps(result,sort_keys=True,separators=(',',':')))
    return status


if __name__=='__main__':raise SystemExit(main())
