"""Read protected factual receipts and independently replay a research comparison.

No official source GETs, source originals, forecast/result writes or credential
backups. A missing/unsupported outcome stays excluded with empty metrics.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from publish_day_feed import get_json,validate_target,canonical_sha
from publish_race_updates import workflow_session
from web.research_contract import _time
from web.evaluation_contract import build_research_evaluation


def verify_evaluation(report,prediction,race_bundle,race,now):
    if not isinstance(report,dict) or _time(report.get('as_of'))>now:raise ValueError('EVALUATION_CLOCK_INVALID')
    rebuilt=build_research_evaluation(prediction,race_bundle,race,_time(report['as_of']))
    if canonical_sha(report)!=canonical_sha(rebuilt):raise ValueError('EVALUATION_REPLAY_MISMATCH')
    return report


def run(race_id,output,*,execute=False):
    if not isinstance(race_id,str) or not re.fullmatch(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',race_id):
        raise ValueError('EVALUATION_RACE_ID_INVALID')
    if not execute:
        print(json.dumps({'result':'DRY_RUN','network_requests':0,'official_source_requests':0}));return
    url=os.environ.get('RACE_AI_EVALUATION_URL','')
    if not url.endswith('/api/evaluation'):raise ValueError('EVALUATION_TARGET_INVALID')
    validate_target(url[:-len('evaluation')]+'publish-day')
    opener,headers=workflow_session(os.environ.get('RACE_AI_EVALUATION_COMMIT_SHA',''))
    base=url.rsplit('/',1)[0]
    feed=get_json(opener,urllib.request.Request(base+'/today',headers=headers),limit=6_000_000)
    matches=[r for v in feed.get('venues',[]) for r in v.get('races',[]) if r.get('race_id')==race_id]
    if len(matches)!=1:raise ValueError('EVALUATION_RACE_ID_INVALID')
    race=matches[0]
    # The target result/forecast receipts must already exist for this verification.
    prediction=get_json(opener,urllib.request.Request(base+'/prediction?race_id='+race_id,headers=headers),limit=256000)
    race_bundle=get_json(opener,urllib.request.Request(base+'/race?race_id='+race_id,headers=headers),limit=256000)
    report=get_json(opener,urllib.request.Request(url+'?race_id='+race_id,headers=headers),limit=256000)
    verify_evaluation(report,prediction,race_bundle,race,datetime.now(timezone.utc))
    raw=json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as handle:handle.write(raw)
    print(json.dumps({'result':'RESEARCH_EVALUATION_API_REPLAY_VERIFIED','race_id':race_id,'status':report['status'],
        'evaluation_as_of':report['as_of'],'sha256':canonical_sha(report),'bytes':len(raw),
        'backup_file_sha256':hashlib.sha256(raw).hexdigest(),'prediction_proof':report['prediction_proof'],
        'result_proof':report['result_proof'],'common_race_ids':report['common_race_ids'],'models':report['models'],
        'validation_status':'UNVALIDATED','purchase_decision':'skip','official_source_requests':0},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--race-id',required=True);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:run(args.race_id,args.output,execute=args.execute)
    except (ValueError,RuntimeError,OSError) as error:
        code=str(error);allowed={'EVALUATION_CLOCK_INVALID','EVALUATION_REPLAY_MISMATCH','EVALUATION_TARGET_INVALID','EVALUATION_RACE_ID_INVALID'}
        stage=code if code in allowed or re.fullmatch(r'DAY_PUBLISH_HTTP_[0-9]{3}',code) else type(error).__name__
        print('SAFE_STOP: research evaluation verification failed '+stage,flush=True);raise SystemExit(2)
