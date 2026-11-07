"""Two-runner acceptance fixture. Invented riders/results; never real data."""
import argparse
from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess

from race_ai.boat_pdca_state import PdcaState,restore_state,scope_for,need
from race_ai.boat_history_store import HistoryStore,instant,wire
from race_ai.boat_history_comparison import prepare_pair,freeze_pair
from scripts.boat_history_collect import private_root,save
from tests.test_boat_pdca_state import invented_pair,result
from tests.test_boat_history_comparison import current
from race_ai.boat_racer_database import RacerDatabase
from race_ai.boat_racer_term import term_info
from race_ai.boat_racer_research_profile import assemble_profile
from tests.test_boat_racer_database import term_archive


def produce(work,artifact):
    root=private_root(work);pair,path=invented_pair(root)
    racers=RacerDatabase();racers.import_term(term_archive(),term='2026-2',source_url=term_info('2026-2')['source_url'],
        captured_at=datetime.now().astimezone().isoformat())
    save(root/'racers.sqlite',racers.serialize());racers.db.close()
    state=PdcaState.create(root/'state.sqlite',mode='synthetic')
    try:
        state.retain_history(root/'history.sqlite',synthetic_fixture=True);state.retain_pair(path)
        state.retain_racers(root/'racers.sqlite',synthetic_fixture=True)
        proof=state.checkpoint(artifact,generation=1)
    finally:state.close()
    receipt=dict(proof,first_pair_sha256=pair['pair_sha256'],first_pair_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        producer_run_id=os.environ.get('GITHUB_RUN_ID','LOCAL_SYNTHETIC_TEST'),
        producer_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        real_data_operation_verified=False,accuracy_improvement_proven=False)
    save(Path(artifact)/'handoff-proof.json',(wire(receipt)+'\n').encode())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('cipher_sha256='+proof['cipher_sha256']+'\n')
    return receipt


def consume(work,artifact,expected):
    root=private_root(work);artifact=Path(artifact)
    proof=json.loads((artifact/'handoff-proof.json').read_text())
    need(proof['synthetic_only'] is True and proof['scope']==scope_for('synthetic',1),'SYNTHETIC_HANDOFF_SCOPE')
    if os.environ.get('GITHUB_ACTIONS')=='true':
        need(proof['producer_run_id']==os.environ.get('EXPECTED_PRODUCER_RUN_ID') and
             proof['producer_commit']==os.environ.get('EXPECTED_PRODUCER_SHA'),'SYNTHETIC_PRODUCER_IDENTITY_MISMATCH')
    state=restore_state(artifact/'state.enc',root/'restored.sqlite',expected_sha256=expected,expected_scope=scope_for('synthetic',1))
    try:
        recovered=root/'recovered';state.materialize(recovered)
        raw=(recovered/'racers.sqlite').read_bytes();racers=RacerDatabase.restore(raw,expected_sha256=hashlib.sha256(raw).hexdigest())
        history=HistoryStore(recovered/'history.sqlite')
        try:
            profile=assemble_profile(history,racers,'4001',as_of=datetime.now().astimezone().isoformat(),allow_source=lambda *a:True)
            need(profile['official_term']['racer_id']=='4001' and profile['recent_history']['opportunities']==3,'JOINED_PROFILE_MISMATCH')
        finally:racers.db.close();history.close()
        p=recovered/'pairs'/f"{proof['first_pair_sha256']}.json";pair=json.loads(p.read_text())
        need(hashlib.sha256(p.read_bytes()).hexdigest()==proof['first_pair_file_sha256'],'FIRST_ORIGINAL_BYTES_CHANGED')
        first=result(pair);now='2026-11-06T12:00:00+09:00'
        need(state.score(pair['pair_sha256'],first,now)['reused'] is False,'FIRST_SCORE_NOT_NEW')
        need(state.score(pair['pair_sha256'],first,now)['reused'] is True,'DUPLICATE_SCORE_NOT_REUSED')
        correction=result(pair);correction['captured_at']='2026-11-06T11:20:00+09:00'
        correction['source_sha256']='e'*64;correction['data']['payouts'][0]['payout_per_100_yen']=1500
        state.score(pair['pair_sha256'],correction,now)
        snapshot=current();snapshot.update(scope='SYNTHETIC_ONLY',race_id='boat:2026-11-07:boatrace-jcd-17:1',
            event_date_jst='2026-11-07',as_of='2026-11-07T01:30:00+09:00',sales_cutoff_at='2026-11-07T10:59:00+09:00')
        history=HistoryStore(recovered/'history.sqlite')
        try:next_pair=prepare_pair(snapshot,history,snapshot['as_of'])
        finally:history.close()
        next_path=root/'next.json';freeze_pair(next_pair,next_path,clock=lambda:instant(snapshot['as_of']));state.retain_pair(next_path)
        state.checkpoint(root/'next-encrypted',generation=2,previous_cipher_sha256=expected)
        report=dict(state.inventory(),synthetic_only=True,original_bytes_preserved=True,next_pair_created=True,
            joined_racer_profile_verified=True,
            real_data_operation_verified=False,accuracy_improvement_proven=False,plaintext_published=False)
        need(report['pairs']==2 and report['result_revisions']==2 and report['scorings']==2,'SYNTHETIC_COUNTS_MISMATCH')
        save(root/'consumer-proof.json',(wire(report)+'\n').encode());return report
    finally:state.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['produce','consume'])
    parser.add_argument('--work',required=True,type=Path);parser.add_argument('--artifact',required=True,type=Path)
    parser.add_argument('--expected-cipher-sha256',default=os.environ.get('RACE_AI_EXPECTED_CIPHER_SHA256'))
    args=parser.parse_args()
    report=produce(args.work,args.artifact) if args.action=='produce' else consume(args.work,args.artifact,args.expected_cipher_sha256)
    print(wire(report))


if __name__=='__main__':main()
