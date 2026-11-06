"""Build/publish an encrypted view; private owner URL is never printed."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.saved_pages import build_site,publish_site
from race_ai.boat_history_store import wire
from scripts.boat_history_collect import private_root,save


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--state',type=Path,required=True)
    b.add_argument('--public-dir',type=Path,required=True);b.add_argument('--private-dir',type=Path,required=True)
    b.add_argument('--source-sha',required=True)
    b.add_argument('--viewer-from',type=Path)
    p=sub.add_parser('publish');p.add_argument('--repo',type=Path,default=ROOT)
    p.add_argument('--public-dir',type=Path,required=True);p.add_argument('--private-dir',type=Path,required=True)
    p.add_argument('--manifest-sha',required=True);p.add_argument('--initialize',action='store_true');p.add_argument('--expected-parent')
    args=parser.parse_args(argv)
    try:
        if args.command=='build':report=build_site(args.state,args.public_dir,args.private_dir,expected_source_sha256=args.source_sha,viewer_from=args.viewer_from)
        else:report=publish_site(args.repo,args.public_dir,expected_manifest_sha256=args.manifest_sha,initialize=args.initialize,expected_parent=args.expected_parent)
        root=private_root(args.private_dir);save(root/(args.command+'-status.json'),(wire(report)+'\n').encode())
        print(wire(report));return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch('(?:PAGES_|STATE_)[A-Z0-9_]{1,90}',str(exc)) else 'PAGES_OPERATION_FAILED'
        print(wire(dict(status='PAGES_OPERATION_REJECTED',reason=reason,plaintext_published=False)));return 2


if __name__=='__main__':raise SystemExit(main())
