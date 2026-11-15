"""Local private BOAT state operations. No source GET, upload, key creation or live-worker change."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.boat_pdca_state import PdcaState,restore_state,need
from race_ai.boat_history_store import wire,instant
from scripts.boat_history_compare import read_json


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('init');p.add_argument('--mode',choices=['production'],required=True)
    p=commands.add_parser('ingest');p.add_argument('--history-db',type=Path);p.add_argument('--captures',type=Path);p.add_argument('--racer-db',type=Path)
    p.add_argument('--pairs-dir',type=Path)
    p=commands.add_parser('checkpoint');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--generation',type=int,required=True);p.add_argument('--previous-cipher-sha256')
    p=commands.add_parser('restore');p.add_argument('--cipher',type=Path,required=True)
    p.add_argument('--expected-sha256',required=True);p.add_argument('--expected-scope',type=Path,required=True)
    p=commands.add_parser('materialize');p.add_argument('--output',type=Path,required=True)
    p=commands.add_parser('score');p.add_argument('--pair-sha256',required=True);p.add_argument('--observations',type=Path,required=True)
    commands.add_parser('status')
    for p in commands.choices.values():p.add_argument('--state',required=True,type=Path)
    args=parser.parse_args(argv);state=None
    try:
        if args.command=='init':state=PdcaState.create(args.state,mode=args.mode)
        elif args.command=='restore':
            state=restore_state(args.cipher,args.state,expected_sha256=args.expected_sha256,expected_scope=read_json(args.expected_scope))
        else:state=PdcaState(args.state)
        if args.command=='ingest':
            if args.history_db:state.retain_history(args.history_db,captures=args.captures)
            if args.racer_db:state.retain_racers(args.racer_db)
            if args.pairs_dir:
                need(args.pairs_dir.is_dir() and not args.pairs_dir.is_symlink(),'EXISTING_PAIRS_DIRECTORY_REQUIRED')
                for p in sorted(args.pairs_dir.glob('*-P[01].json')):state.retain_pair(p)
        elif args.command=='checkpoint':
            proof=state.checkpoint(args.output,generation=args.generation,previous_cipher_sha256=args.previous_cipher_sha256)
            print(wire(proof));return 0
        elif args.command=='materialize':state.materialize(args.output)
        elif args.command=='score':
            observations=read_json(args.observations)
            if isinstance(observations,dict):observations=[observations]
            need(isinstance(observations,list) and len(observations)<=20000,'BOUNDED_RESULT_REVISIONS_REQUIRED')
            for obs in sorted(observations,key=lambda o:instant(o['captured_at'])):
                state.score(args.pair_sha256,obs,datetime.now(timezone.utc))
        print(wire(dict(status='PRIVATE_STATE_VERIFIED',**state.inventory(),real_data_operation_verified=False)))
        return 0
    except (ValueError,OSError,KeyError):
        print(wire(dict(status='PRIVATE_STATE_NOT_VERIFIED',action=args.command,plaintext_published=False)))
        return 2
    finally:
        if state is not None:state.close()


if __name__=='__main__':raise SystemExit(main())
