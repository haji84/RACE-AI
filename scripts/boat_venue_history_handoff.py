"""Reuse existing Git state for encrypted full-period history publication/readback."""
import argparse,json
from pathlib import Path
from race_ai.boat_venue_history_handoff import publish_collection,readback_collection

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='action',required=True)
    x=s.add_parser('publish');x.add_argument('--source-dir',required=True);x.add_argument('--pointer-out',required=True)
    x=s.add_parser('readback');x.add_argument('--input',required=True);x.add_argument('--out-dir',required=True)
    p.add_argument('--repo',default='.');a=p.parse_args(argv)
    if a.action=='publish':
        r=publish_collection(a.source_dir,a.repo);Path(a.pointer_out).write_text(json.dumps(r,sort_keys=True)+'\n')
    else:r=readback_collection(json.loads(Path(a.input).read_text()),a.out_dir,a.repo)
    print(json.dumps(r,sort_keys=True));return r
if __name__=='__main__':main()
