"""Private venue-grid build, immutable encrypted publication and exact readback."""
import argparse,json
from pathlib import Path
from race_ai.boat_venue_dataset import build_dataset,verify_dataset,publish_dataset,readback_dataset

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',default='.')
    s=p.add_subparsers(dest='action',required=True)
    x=s.add_parser('build');x.add_argument('--collection-dir',required=True);x.add_argument('--out-dir',required=True);x.add_argument('--end',required=True);x.add_argument('--roster-db')
    x=s.add_parser('verify');x.add_argument('--folder',required=True)
    x=s.add_parser('publish');x.add_argument('--folder',required=True);x.add_argument('--pointer-out',required=True)
    x=s.add_parser('readback');x.add_argument('--input',required=True);x.add_argument('--out-dir',required=True)
    a=p.parse_args(argv)
    if a.action=='build':
        roster=[]
        if a.roster_db:
            from race_ai.boat_racer_database import RacerDatabase
            from race_ai.boat_pdca_state import sqlite_snapshot,sha
            raw=sqlite_snapshot(a.roster_db);db=RacerDatabase.restore(raw,expected_sha256=sha(raw))
            roster=[r[0] for r in db.db.execute('SELECT DISTINCT racer_id FROM racers')];db.db.close()
        r=build_dataset(a.collection_dir,a.out_dir,roster=roster,end=a.end)
    elif a.action=='verify':r=verify_dataset(a.folder)
    elif a.action=='publish':
        r=publish_dataset(a.folder,a.repo);Path(a.pointer_out).write_text(json.dumps(r,sort_keys=True)+'\n')
    else:r=readback_dataset(json.loads(Path(a.input).read_text()),a.out_dir,a.repo)
    print(json.dumps(r,sort_keys=True));return r
if __name__=='__main__':main()
