"""Actual PR71 + encrypted SQLite between runners. Input races are SYNTHETIC ONLY."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import subprocess

from scripts.keirin_github_sqlite_snapshot import backup_sqlite,validate_snapshot
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_private_spool import KeirinPrivateSpool
from tests.test_keirin_pr71_model_adapter import make_sources,RID,run_suite,verify_suite

SCOPE={'schema':'RACE_AI_GITHUB_SQLITE_V1','repository_id':'1416489937',
       'mode':'synthetic','generation':1,'previous_cipher_sha256':None}

def _write(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,sort_keys=True)

def _tick(store,inbox,stamp):
    engine=KeirinPrivateSpool(store,clock=lambda:datetime.fromisoformat(stamp),
        model_suite=run_suite,model_verifier=verify_suite)
    return engine.tick(inbox)

def produce(work,output):
    work=Path(work);output=Path(output)
    work.mkdir(parents=True,exist_ok=False);output.mkdir(parents=True,exist_ok=False)
    inbox=work/'inbox';(inbox/'pre').mkdir(parents=True)
    snapshot,_,_=make_sources();_write(inbox/'pre'/'01.json',snapshot)
    stamp='2030-01-15T09:21:00+09:00'
    db=work/'owner.sqlite3'
    with PrivateKeirinStore(db,clock=lambda:datetime.fromisoformat(stamp)) as store:
        report=_tick(store,inbox,stamp)
        if report['private_forecasts_saved_this_tick']!=1:raise ValueError('MODEL_FIXTURE_NOT_SAVED')
        original=store.get_persisted_forecast(RID)
        if len(original['forecast']['top8'])!=8:raise ValueError('MODEL_TOP8_INVALID')
    backup=work/'snapshot.sqlite3';backup_sqlite(db,backup)
    _write(output/'scope.json',SCOPE)
    subprocess.run(['node','scripts/keirin_github_checkpoint.mjs','seal',str(backup),
        str(output/'state.enc'),str(output/'scope.json')],check=True)
    cipher_sha=sha256((output/'state.enc').read_bytes()).hexdigest()
    _write(output/'fixture-proof.json',{'synthetic_only':True,
        'cipher_sha256':cipher_sha,'snapshot_sha256':sha256(backup.read_bytes()).hexdigest(),
        'forecast_sha256':original['sha256'],'producer_sha':os.environ.get('GITHUB_SHA'),
        'producer_run_id':os.environ.get('GITHUB_RUN_ID')})
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('cipher_sha256='+cipher_sha+'\n')
    print(json.dumps({'state':'SYNTHETIC_REAL_MODEL_ENCRYPTED','real_races':0,
        'private_forecasts_uploaded':False,'cipher_sha256':cipher_sha}))

def consume(artifact,work):
    artifact=Path(artifact);work=Path(work);work.mkdir(parents=True,exist_ok=False)
    proof=json.loads((artifact/'fixture-proof.json').read_text())
    if proof.get('synthetic_only') is not True:raise ValueError('FIXTURE_ONLY')
    expected=os.environ.get('RACE_AI_EXPECTED_CIPHER_SHA256') or proof['cipher_sha256']
    if expected!=proof['cipher_sha256']:raise ValueError('PROOF_SHA_MISMATCH')
    expected_run=os.environ.get('EXPECTED_PRODUCER_RUN_ID')
    expected_commit=os.environ.get('EXPECTED_PRODUCER_SHA')
    if expected_run and str(proof['producer_run_id'])!=expected_run:raise ValueError('PRODUCER_RUN_MISMATCH')
    if expected_commit and proof['producer_sha']!=expected_commit:raise ValueError('PRODUCER_SHA_MISMATCH')
    if json.loads((artifact/'scope.json').read_text())!=SCOPE:raise ValueError('SCOPE_MISMATCH')
    db=work/'restored.sqlite3';env={**os.environ,'RACE_AI_EXPECTED_CIPHER_SHA256':expected}
    subprocess.run(['node','scripts/keirin_github_checkpoint.mjs','unseal',str(artifact/'state.enc'),
        str(db),str(artifact/'scope.json')],check=True,env=env)
    if sha256(db.read_bytes()).hexdigest()!=proof['snapshot_sha256']:raise ValueError('SQLITE_BYTE_MISMATCH')
    validate_snapshot(db)
    stamp='2030-01-15T10:40:00+09:00'
    inbox=work/'inbox';(inbox/'pre').mkdir(parents=True);(inbox/'results').mkdir()
    with PrivateKeirinStore(db,clock=lambda:datetime.fromisoformat(stamp)) as store:
        original=store.get_persisted_forecast(RID)
        if original['sha256']!=proof['forecast_sha256']:raise ValueError('ORIGINAL_CHANGED')
        winning=original['forecast']['top8'][0]
        _write(inbox/'results'/'01.json',{
            'schema':'RACE_AI_PRIVATE_KEIRIN_RESULT_OBSERVATION_V1','observation':{
              'race_id':RID,'observed_at':'2030-01-15T10:04:00+09:00','source_sha256':'a'*64,
              'status':'FINAL_NORMAL','refund_status':'NONE','winning_triples':[winning],
              'payouts_100yen':[{'triple':winning,'yen':2680}]}})
        snapshot,_,_=make_sources();snapshot=deepcopy(snapshot)
        next_id='keirin:2030-01-15:fictional-venue:2'
        snapshot.update(race_id=next_id,as_of='2030-01-15T10:30:00+09:00',official_cutoff_at='2030-01-15T11:50:00+09:00')
        snapshot['facts']['pr71_evidenced_snapshot']['race'].update(
            race_id=next_id,as_of=snapshot['as_of'],sales_cutoff_at=snapshot['official_cutoff_at'])
        _write(inbox/'pre'/'02.json',snapshot)
        report=_tick(store,inbox,stamp)
        if report['reference_hits_this_tick']!=1 or report['private_forecasts_saved_this_tick']!=1:
            raise ValueError('RESTORED_NEXT_CYCLE_FAILED')
        if store.get_persisted_forecast(RID)['sha256']!=proof['forecast_sha256']:raise ValueError('ORIGINAL_OVERWRITTEN')
        repeated=_tick(store,inbox,stamp)
        if repeated['private_forecasts_saved_this_tick'] or repeated['reference_hits_this_tick']:raise ValueError('REPLAY_RECOUNT')
    print(json.dumps({'state':'GITHUB_ENCRYPTED_HANDOFF_RESTORED_AND_NEXT_MODEL_SAVED',
        'original_forecast_preserved':True,'replayed_without_recount':True,
        'input_kind':'SYNTHETIC_ONLY','real_races':0,'formal_hit_at_8':None}))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('produce','consume'))
    parser.add_argument('--work',required=True);parser.add_argument('--artifact',required=True);args=parser.parse_args()
    try:
        if args.mode=='produce':produce(args.work,args.artifact)
        else:consume(args.artifact,args.work)
        return 0
    except Exception:
        print(json.dumps({'state':'GITHUB_ONLY_FIXTURE_HANDOFF_FAILED','real_races':0}));return 2
if __name__=='__main__':raise SystemExit(main())
