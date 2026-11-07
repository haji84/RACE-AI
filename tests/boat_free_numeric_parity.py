"""Synthetic parity only. Does not attest real source or live day completion."""
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.boat_ab_shadow import build_pair

for case in range(6):
    source={'race_id':'20301103-17-05','cutoff_at':'2030-11-03T13:30:00+09:00','captured_at':'2030-11-03T13:15:00+09:00','program_source_sha256':'a'*64,'beforeinfo_source_sha256':'b'*64,'boats':[{'lane':n,'racer_id':str(4100+n),'national_win_rate':None if case==5 and n==2 else 5+n*.17+case*.07,'exhibition_time_seconds':6.7+n*.01+case*.02,'motor_two_place_rate_percent':20+n*5+case} for n in range(1,7)]}
    now='2030-11-03T13:16:00+09:00'
    expected=build_pair(source,now)
    code="import {buildPair} from './workers/boat_free_model.mjs';let s='';for await(const c of process.stdin)s+=c;const p=JSON.parse(s);console.log(JSON.stringify(buildPair(p.source,p.now)));"
    child=subprocess.run(['node','--input-type=module','-e',code],input=json.dumps({'source':source,'now':now}),cwd=ROOT,text=True,capture_output=True,check=True)
    actual=json.loads(child.stdout)
    for a,b in zip(expected['models'],actual['models']):
        assert a['model_id']==b['model_id']
        assert [x['ticket'] for x in a['top8']]==[x['ticket'] for x in b['top8']]
        assert [x['ticket'] for x in a['full_120']]==[x['ticket'] for x in b['full_120']]
        assert max(abs(x['score']-y['score']) for x,y in zip(a['full_120'],b['full_120']))<1e-12
print(json.dumps({'status':'CANONICAL_PYTHON_JS_PARITY_PASS','synthetic_cases':6,'models_per_case':2,'outcomes_per_model':120,'tolerance':1e-12,'live_evidence':False}))
