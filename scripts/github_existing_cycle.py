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
from race_ai.first_receipt_continuity import first_receipt_rows,latest_result_observations
from race_ai.cycle_recovery import recover,load_state,due_rows
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
    state=recover(gh,day,current_run=int(os.environ['GITHUB_RUN_ID']),out=ROOT/'cycle_recovery_output')
    print(json.dumps(dict(state='ORIGINAL_REUSED_NO_REGENERATION',races=doc['race_count'],forecasts=len(rows),artifact_id=meta['id'])))

def forecast(day):
    from scripts import boat_nationwide_ab_pilot as pilot
    state=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    index=json.loads(pilot.FROZEN_INDEX.read_text())
    first={}
    for row in sorted(index['entries']+state['index_entries'],key=lambda x:(ts(x['server_created_at']),x['artifact_id'])):
        first.setdefault(row['race_id'],row)
    index['entries']=list(first.values())
    target=ROOT/'cycle_recovery_output/freeze-index.json'
    target.write_text(json.dumps(index,ensure_ascii=False))
    # Point the unchanged predictor at the verified union, not yesterday alone.
    pilot.FROZEN_INDEX=target
    pilot.run()

def supplement(day):
    """Fill only previously absent future P0 rows; never edit first morning bytes."""
    _,rows,_,_=original(day)
    recovered=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    from scripts.existing_day_program import collect
    frozen=frozenset(x['race_id'] for x in rows+recovered['rows'] if x['stage']=='P0')
    result=collect(already_frozen=frozen)
    folder=ROOT/'p0_supplement_output';folder.mkdir(exist_ok=True)
    with (folder/'forecasts.json').open('x') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    print(json.dumps(dict(state='MISSING_FUTURE_P0_ONLY',race_count=result['race_count'],original_races_not_regenerated=len(frozen))))

def audit(day,p1_id,p0_supplement=None):
    doc,rows,p0_meta,p0_zip=original(day);sources=[p0_meta];p1_doc=None
    recovered=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
    rows+=recovered['rows'];sources+=recovered['receipts']
    out=ROOT/'existing_cycle_output';out.mkdir(exist_ok=True)
    (out/'first-p0-original.zip').write_bytes(p0_zip)
    if p0_supplement:
        meta=json.loads(gh(f'actions/artifacts/{p0_supplement}'));raw=gh(f'actions/artifacts/{p0_supplement}/zip')
        _,additional=read_p0(raw,meta,expected_day=day);rows+=additional;sources.append(meta)
        (out/'supplement-p0-original.zip').write_bytes(raw)
    if p1_id:
        meta=json.loads(gh(f'actions/artifacts/{p1_id}'));raw=gh(f'actions/artifacts/{p1_id}/zip')
        p1_doc,p1rows=read_p1(raw,meta);rows+=p1rows;sources.append(meta)
        (out/'current-p1-original.zip').write_bytes(raw)
    rows,excluded=first_receipt_rows(rows)
    excluded=recovered['excluded_repeats']+excluded
    from race_ai.official_race_updates import endpoint,parse_update,MAX_BYTES
    from race_ai.tokuyama_day_worker import NoRedirects
    by_race={x['race_id']:x for x in rows};observations=list(recovered['observations']);failures=[];requests_used=0
    now=datetime.now(timezone.utc)
    due=due_rows(rows,observations,now)
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
    latest_observations,observations=latest_result_observations(observations)
    report=evaluate(rows,latest_observations)
    report.update(day_jst=day,updated_at=datetime.now(timezone.utc).isoformat(),run_id=os.environ.get('GITHUB_RUN_ID'),
        code_sha=os.environ.get('GITHUB_SHA'),first_forecast_artifacts=sources,source_request_count=requests_used,
        schedule=doc['schedule'],scheduled_boat_races=len(doc['schedule']),
        original_p0_skips=doc['skipped'],no_p0_forecast=[x for x in doc['skipped'] if x['race_id'] not in {r['race_id'] for r in rows if r['stage']=='P0'}],
        result_source_failures=failures,excluded_repeat_forecasts=excluded,
        restored_run_ids=recovered['scanned_runs'],result_observation_versions=len(observations),raw_sources_published=False,continuous_operation_proven=False,
        all_models_operational=False,other_sports_status='LIVE_INPUT_INTEGRATION_NOT_YET_VERIFIED',
        archive_retention_days=7,permanent_private_retention_proven=False)
    from race_ai.existing_model_coverage import coverage
    schedule_counts={'boat':len(doc['schedule'])}
    if day=='2026-11-04':
        schedule_counts.update(keirin=75,autorace=20,horse=59)
        report['nonboat_discovery_receipt']={'artifact_id':13283229052,'zip_sha256':'86ffb2b44fdbb2119a0401533cd9f182eca0d918ab555c48870d01ef422e0e9d','state':'154_CAPTURED_CARDS_NOT_154_FORECASTS'}
    report['model_coverage']=coverage(rows,schedule_counts)
    report['next_action']='VALIDATE_IMPROVEMENT_ON_NEW_RACES_ONLY'
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
    (out/'model_coverage.json').write_text(json.dumps(report['model_coverage'],ensure_ascii=False,indent=2))
    (out/'improvement_candidates.json').write_text(json.dumps(report['improvement_candidates'],ensure_ascii=False,indent=2))
    lines+=['',f'Repeated later predictions excluded: {len(excluded)}; recovered previous runs: {len(recovered["scanned_runs"])}.', 'Unmet: all four sports/all models, perpetual private storage, continuous per-deadline coverage.']
    text='\n'.join(lines)+'\n';(out/'STATUS.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(text)
    print(json.dumps({k:report[k] for k in ('day_jst','forecast_count','distinct_races','scored_forecasts','source_request_count','auto_promoted')},ensure_ascii=False))

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['restore','forecast','audit','supplement']);p.add_argument('--p1-artifact',type=int);p.add_argument('--p0-supplement',type=int);a=p.parse_args()
    day=datetime.now(timezone.utc).astimezone(JST).date().isoformat()
    if a.command=='restore':restore(day)
    elif a.command=='forecast':forecast(day)
    elif a.command=='supplement':supplement(day)
    else:audit(day,a.p1_artifact,a.p0_supplement)
if __name__=='__main__':main()
