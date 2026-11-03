"""Reuse frozen artifacts and observe later official results in the same workflow.

The forecast process and outcome process never share result inputs. This runner
is not a scheduler, does not publish raw pages or change model coefficients.
"""
from datetime import datetime,timezone,timedelta,date
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
from urllib import request,error
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
race_ai.__path__.append(str(ROOT/'pr64-reference'/'race_ai'))
from race_ai.frozen_day_cycle import read_p0,read_p1,evaluate,need,ts
JST=timezone(timedelta(hours=9));REPO='haji84/RACE-AI'

def gh(path):
    result=subprocess.run(['gh','api',f'repos/{REPO}/'+path],check=True,capture_output=True,timeout=50)
    return result.stdout

def original(day):
    index=ROOT/'docs/evidence'/day/'p0-first-receipt.json'
    if not index.is_file():raise ValueError('FIRST_RECEIPT_REGISTRY_MISSING_NO_BLIND_REGENERATION')
    known=json.loads(index.read_text());ident=known['artifact_id']
    receipt=json.loads(gh(f'actions/artifacts/{ident}'));raw=gh(f'actions/artifacts/{ident}/zip')
    need(receipt['created_at']==known['server_created_at'] and receipt['digest']=='sha256:'+known['zip_sha256'],'original receipt changed')
    doc,rows=read_p0(raw,receipt,expected_day=day)
    need(rows[0]['original_json_sha256']==known['json_sha256'],'original body changed')
    return doc,rows,receipt,raw

def restore(day):
    import zipfile,io
    doc,rows,meta,raw=original(day);folder=ROOT/'boat_all_day_output';folder.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:body=z.read('forecasts.json')
    with (folder/'forecasts.json').open('xb') as f:f.write(body)
    (folder/'first-receipt.json').write_text(json.dumps(meta,ensure_ascii=False))
    print(json.dumps(dict(state='ORIGINAL_REUSED_NO_REGENERATION',races=doc['race_count'],forecasts=len(rows),artifact_id=meta['id'])))

def audit(day,p1_id):
    doc,rows,p0_meta,p0_zip=original(day);sources=[p0_meta];p1_doc=None
    out=ROOT/'existing_cycle_output';out.mkdir(exist_ok=True)
    (out/'first-p0-original.zip').write_bytes(p0_zip)
    if p1_id:
        meta=json.loads(gh(f'actions/artifacts/{p1_id}'));raw=gh(f'actions/artifacts/{p1_id}/zip')
        p1_doc,p1rows=read_p1(raw,meta);rows+=p1rows;sources.append(meta)
        (out/'current-p1-original.zip').write_bytes(raw)
    from race_ai.official_race_updates import endpoint,parse_update,MAX_BYTES
    from race_ai.tokuyama_day_worker import NoRedirects
    by_race={x['race_id']:x for x in rows};observations=[];failures=[];requests_used=0
    now=datetime.now(timezone.utc)
    due=sorted((x for x in by_race.values() if ts(x['cutoff_at'])+timedelta(seconds=90)<now),key=lambda x:(x['cutoff_at'],x['race_id']))
    blocked=False
    for row in due[:24]:
        if blocked:failures.append(dict(race_id=row['race_id'],state='SOURCE_RATE_LIMIT_STOP'));continue
        rid=row['race_id'];d=date.fromisoformat(day);venue=rid[9:11];n=int(rid[-2:]);url=endpoint(d,venue,n,'raceresult')
        try:
            req=request.Request(url,headers={'User-Agent':'RACE-AI-owner-existing-result-audit/1.0','Accept':'text/html'})
            requests_used+=1
            with request.build_opener(NoRedirects()).open(req,timeout=12) as response:
                raw=response.read(MAX_BYTES+1)
                need(response.status==200 and response.geturl()==url and 0<len(raw)<=MAX_BYTES,'official response rejected')
            at=datetime.now(timezone.utc).isoformat()
            observation=parse_update(raw,kind='raceresult',day=d,venue=venue,race_no=n,source_url=url,captured_at=at,entries=None)
            observation.update(source_url=url,source_sha256=hashlib.sha256(raw).hexdigest())
            observations.append(observation);time.sleep(.35)
        except Exception as exc:
            if isinstance(exc,error.HTTPError) and 400<=exc.code<500:blocked=True
            failures.append(dict(race_id=rid,state='SOURCE_OR_PARSE_UNAVAILABLE',reason=type(exc).__name__+': '+str(exc)[:120]))
    report=evaluate(rows,observations)
    report.update(day_jst=day,updated_at=datetime.now(timezone.utc).isoformat(),run_id=os.environ.get('GITHUB_RUN_ID'),
        code_sha=os.environ.get('GITHUB_SHA'),first_forecast_artifacts=sources,source_request_count=requests_used,
        schedule=doc['schedule'],scheduled_boat_races=len(doc['schedule']),no_p0_forecast=doc['skipped'],
        result_source_failures=failures,raw_sources_published=False,continuous_operation_proven=False,
        all_models_operational=False,other_sports_status='LIVE_INPUT_INTEGRATION_NOT_YET_VERIFIED',
        archive_retention_days=7,permanent_private_retention_proven=False)
    report['report_sha256']=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    (out/'status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (out/'official-result-observations.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2))
    import csv
    with (out/'forecasts.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['race_id','phase','model','cutoff','first_saved_at','top8','artifact_id'])
        for r in rows:writer.writerow([r['race_id'],r['stage'],r['model_id'],r['cutoff_at'],r['server_saved_at'],' / '.join('-'.join(map(str,t)) for t in r['top8']),r['artifact_id']])
    lines=['# Existing-model actual execution status',f'Day: {day}; run: '+str(report['run_id']),
        f'Frozen forecast rows: {len(rows)}; races: {report["distinct_races"]}; scored: {report["scored_forecasts"]}.',
        'Research only. No wagering, model auto-promotion, retrospective forecast edits or all-model completion claim.',
        '| Phase | Model | Forecasts | Scored | Hit | ROI |','|---|---|---:|---:|---:|---:|']
    for x in report['scoreboard']:
        lines.append(f'|{x["stage"]}|{x["model_id"]}|{x["forecast_count"]}|{x["scored"]}|{x["hits"]}|{x["roi"] if x["roi"] is not None else "pending"}|')
    lines+=['','Unmet: all four sports/all models, perpetual private storage, continuous per-deadline coverage.']
    text='\n'.join(lines)+'\n';(out/'STATUS.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(text)
    print(json.dumps({k:report[k] for k in ('day_jst','forecast_count','distinct_races','scored_forecasts','source_request_count','auto_promoted')},ensure_ascii=False))

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['restore','audit']);p.add_argument('--p1-artifact',type=int);a=p.parse_args()
    day=datetime.now(timezone.utc).astimezone(JST).date().isoformat()
    if a.command=='restore':restore(day)
    else:audit(day,a.p1_artifact)
if __name__=='__main__':main()
