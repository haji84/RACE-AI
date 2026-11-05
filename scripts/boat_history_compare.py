"""Prepare/read/score private fixed-eight history pairs; no live worker change."""
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.actions_contract import digest
from race_ai.boat_history_store import HistoryStore,wire,instant
from race_ai.boat_history_comparison import prepare_pair,freeze_pair,load_pair,score_pair
from race_ai.frozen_day_cycle import official_id,read_p0,sealed
from race_ai.observed_weight_learning import source_snapshot
from scripts.boat_history_collect import private_root,save


def clock():return datetime.now(timezone.utc)


def read_json(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>32*1024*1024:raise ValueError('COMPARISON_PRIVATE_BOUNDED_INPUT_REQUIRED')
    return json.loads(path.read_text())


def prepare(args):
    now=clock();root=private_root(args.private_dir)
    if not args.history_db.is_file() or args.history_db.is_symlink():raise ValueError('EXISTING_PRIVATE_HISTORY_DATABASE_REQUIRED')
    if args.snapshot:
        supplied=read_json(args.snapshot)
        snapshots=supplied if isinstance(supplied,list) else [supplied]
        source_sha=digest(supplied)
    else:
        if not(args.p0_zip and args.receipt and args.event_day):raise ValueError('VERIFIED_P0_ZIP_RECEIPT_AND_DAY_REQUIRED')
        path=Path(args.p0_zip)
        if path.is_symlink() or path.stat().st_size>32*1024*1024:raise ValueError('BOUNDED_P0_REQUIRED')
        doc,_=read_p0(path.read_bytes(),read_json(args.receipt),expected_day=args.event_day)
        snapshots=[]
        for suite in doc['predictions']:
            sealed(suite,'suite_sha256');snapshots.append(source_snapshot(suite))
        source_sha=digest(doc)
    ids=[official_id(s['race_id']) for s in snapshots]
    if len(ids)!=len(set(ids)) or not 1<=len(ids)<=288:raise ValueError('DISTINCT_DECLARED_RACE_COHORT_REQUIRED')
    protocol_path=root/'protocol.json'
    if protocol_path.exists():
        protocol=read_json(protocol_path)
        if protocol['input_sha256']!=source_sha or protocol['scheduled_race_ids']!=ids:raise ValueError('PROTOCOL_COHORT_CANNOT_BE_REPLACED')
    else:
        protocol=dict(schema='RACE_AI_PROSPECTIVE_HISTORY_PROTOCOL_V1',created_at=now.isoformat(),input_sha256=source_sha,
            scheduled_race_ids=ids,policy='SAME_ASOF_FIXED8_RECENT_HISTORY_ONLY_EXISTING_WEIGHTS',
            missing_races_retained=True,result_selection='LATEST_VISIBLE_SHARED_OFFICIAL_OBSERVATION',
            model_promotion=False,independent_freeze_receipt_verified=False)
        save(protocol_path,(wire(protocol)+'\n').encode())
    store=HistoryStore(args.history_db);outcomes=[];reused=0
    try:
        for snapshot,rid in zip(snapshots,ids):
            path=root/f'{rid}-{snapshot["stage"]}.json'
            if path.exists():
                pair=load_pair(path)
                expected=dict(snapshot,as_of=pair['generated_at'])
                if digest(expected)!=digest(pair['baseline']['snapshot']):raise ValueError('FIRST_PAIR_INPUT_CANNOT_BE_REPLACED')
                reused+=1
            elif now>=instant(snapshot['sales_cutoff_at']):
                outcomes.append(dict(race_id=rid,state='NO_FORECAST_CUTOFF_PASSED'));continue
            else:
                pair=prepare_pair(snapshot,store,now);freeze_pair(pair,path)
            outcomes.append(dict(race_id=rid,state='PREPARED_PRIVATE_RESEARCH',pair_sha256=pair['pair_sha256'],
                coverage=pair['history_coverage'],generated_at=pair['generated_at'],cutoff_at=pair['cutoff_at']))
    finally:store.close()
    result=dict(scheduled=len(ids),prepared=sum(r['state']=='PREPARED_PRIVATE_RESEARCH' for r in outcomes),
        reused=reused,rows=outcomes,accuracy_improvement_proven=False,independent_pre_cutoff_receipt_verified=False)
    save(root/'preparation-report.json',(wire(result)+'\n').encode(),replace=True)
    print(wire({k:v for k,v in result.items() if k!='rows'}))


def score(args):
    pair=load_pair(args.pair);supplied=read_json(args.observations)
    observations=supplied if isinstance(supplied,list) else [supplied]
    now=clock()
    selected=[o for o in observations if o['race_id']==pair['race_id'] and instant(o['captured_at'])<=now]
    if not selected:
        result=dict(race_id=pair['race_id'],state='RESULT_PENDING',accuracy_improvement_proven=False)
    else:
        latest=max(instant(o['captured_at']) for o in selected)
        last=[o for o in selected if instant(o['captured_at'])==latest]
        if any(o!=last[0] for o in last[1:]):raise ValueError('RESULT_CAPTURE_CONFLICT')
        result=score_pair(pair,last[0],now)
    if args.private_dir:
        root=private_root(args.private_dir);save(root/(pair['race_id']+'-comparison.json'),(wire(result)+'\n').encode(),replace=True)
    print(wire(result))


def main():
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    a=commands.add_parser('prepare');group=a.add_mutually_exclusive_group(required=True)
    group.add_argument('--snapshot',type=Path);group.add_argument('--p0-zip',type=Path)
    a.add_argument('--receipt',type=Path);a.add_argument('--event-day')
    a.add_argument('--history-db',required=True,type=Path);a.add_argument('--private-dir',required=True,type=Path)
    a.set_defaults(action=prepare)
    b=commands.add_parser('score');b.add_argument('--pair',required=True,type=Path)
    b.add_argument('--observations',required=True,type=Path);b.add_argument('--private-dir',type=Path);b.set_defaults(action=score)
    args=p.parse_args();args.action(args)


if __name__=='__main__':main()
