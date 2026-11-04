"""Restore authenticated first receipts across existing Actions runs.

No source requests, new models, forecast regeneration or production promotion.
The caller supplies authenticated GitHub API reads. Incomplete history stops
new forecasts; it is never silently treated as an empty database.
"""
from datetime import datetime,timedelta,timezone
import hashlib,io,json,zipfile
from .frozen_day_cycle import need,ts,read_p1,read_p0
from .first_receipt_continuity import first_receipt_rows,latest_result_observations
BRANCH='feat/four-sport-forecast-audit-view-20261022'
WORKFLOW=405276784
JST=timezone(timedelta(hours=9))

def day_runs(get,day,*,current_run):
    start=datetime.fromisoformat(day+'T00:00:00+09:00');end=start+timedelta(days=1)
    selected=[];complete=False
    for page in range(1,11):
        response=json.loads(get(f'actions/workflows/{WORKFLOW}/runs?per_page=100&page={page}'))
        runs=response['workflow_runs'];need(isinstance(runs,list),'invalid run page')
        for run in runs:
            at=ts(run['created_at'])
            if not start<=at<end or run['id']==current_run or run['head_branch']!=BRANCH:continue
            if run['event']!='push':continue
            # Queued successors are not prior executions. An earlier in-flight
            # writer is unresolved and cannot safely be assumed to have no receipt.
            if run['id']>current_run:continue
            need(run['status']=='completed','UNRESOLVED_PREVIOUS_RUN')
            selected.append(run)
        if len(runs)<100 or any(ts(x['created_at'])<start for x in runs):
            complete=True;break
    need(complete,'RUN_HISTORY_PAGINATION_INCOMPLETE')
    need(len({x['id'] for x in selected})==len(selected),'duplicate run page')
    return sorted(selected,key=lambda x:(ts(x['created_at']),x['id']))

def result_archive(raw,meta,day):
    need(isinstance(raw,bytes) and len(raw)<=32*1024*1024,'bounded result archive')
    run=meta['workflow_run']['id']
    need(meta.get('expired') is False and meta.get('name')==f'race-existing-cycle-{run}' and
         meta['workflow_run'].get('head_repository_id')==1416489937,'foreign/expired cycle archive')
    need(meta.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest(),'cycle archive hash mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        member='official-result-observations.json'
        need(len(z.namelist())==len(set(z.namelist())) and member in z.namelist(),'cycle member missing/duplicate')
        need(z.getinfo(member).file_size<=16*1024*1024,'oversized result journal')
        items=json.loads(z.read(member))
    need(isinstance(items,list) and len(items)<=20000,'bounded observation journal')
    for row in items:
        need(row['race_id'].startswith(day.replace('-','')+'-'),'foreign result day')
        ts(row['captured_at'])
    return items

def recover(get,day,*,current_run,out):
    """Read every same-day P1 original and every saved result journal, no writes upstream."""
    rows=[];observations=[];receipts=[];scanned=[];index_entries=[]
    out.mkdir(parents=True,exist_ok=True)
    for run in day_runs(get,day,current_run=current_run):
        data=json.loads(get(f'actions/runs/{run["id"]}/artifacts?per_page=100'))
        artifacts=data['artifacts']
        need(data.get('total_count',len(artifacts))==len(artifacts),'ARTIFACT_PAGE_INCOMPLETE')
        scanned.append(run['id'])
        for listed in artifacts:
            prefix=('boat-p0-existing-' if listed['name']==f'boat-p0-existing-{run["id"]}' else
                    'boat-national-cutoff-' if listed['name']==f'boat-national-cutoff-{run["id"]}' else
                    'race-existing-cycle-' if listed['name']==f'race-existing-cycle-{run["id"]}' else None)
            if prefix is None:continue
            ident=listed['id'];meta=json.loads(get(f'actions/artifacts/{ident}'))
            need(meta['workflow_run']['id']==run['id'],'artifact/run identity mismatch')
            raw=get(f'actions/artifacts/{ident}/zip')
            if prefix in ('boat-national-cutoff-','boat-p0-existing-'):
                doc,items=(read_p1(raw,meta) if prefix=='boat-national-cutoff-' else read_p0(raw,meta,expected_day=day))
                need(all(x['race_id'].startswith(day.replace('-','')+'-') for x in items),'foreign forecast day')
                rows+=items
                if prefix=='boat-national-cutoff-':
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        body_sha=hashlib.sha256(archive.read('national.json')).hexdigest()
                    for pair in doc.get('paired_forecasts',[]):
                        index_entries.append(dict(race_id=pair['race_id'],cutoff_at=pair['cutoff_at'],run_id=run['id'],artifact_id=ident,server_created_at=meta['created_at'],zip_sha256=hashlib.sha256(raw).hexdigest(),json_sha256=body_sha,bundle_sha256=pair['bundle_sha256']))
                # Preserve original bytes, not reconstructed predictions.
                (out/f'original-{ident}.zip').write_bytes(raw)
                receipts.append(meta)
            else:observations+=result_archive(raw,meta,day)
    unique,excluded=first_receipt_rows(rows)
    _,journal=latest_result_observations(observations)
    state=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst=day,rows=unique,
               excluded_repeats=excluded,receipts=receipts,observations=journal,
               scanned_runs=scanned,index_entries=index_entries,complete=True)
    state['state_sha256']=hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    (out/'continuity.json').write_text(json.dumps(state,ensure_ascii=False))
    return state

def load_state(path,day):
    data=json.loads(path.read_text());digest=data.pop('state_sha256')
    need(digest==hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'recovered state hash mismatch')
    need(data.get('schema')=='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1' and data.get('complete') is True and data.get('day_jst')==day,'recovery missing or wrong day')
    return data

def due_rows(rows,observations,now,*,limit=24):
    """Poll pending first, at most every five minutes; revisit settled after six hours."""
    latest,_=latest_result_observations(observations)
    by_result={x['race_id']:x for x in latest};by_race={x['race_id']:x for x in rows};due=[]
    for row in by_race.values():
        if ts(row['cutoff_at'])+timedelta(seconds=90)>=now:continue
        old=by_result.get(row['race_id']);settled=False
        if old:
            data=old.get('data') or {}
            settled=(data.get('confirmed') is True and data.get('status') in ('settled','cancelled','no_contest'))
            interval=timedelta(hours=6) if settled else timedelta(minutes=5)
            if ts(old['captured_at'])+interval>now:continue
        due.append((settled,ts(old['captured_at']) if old else ts(row['cutoff_at']),row['race_id'],row))
    return [item[3] for item in sorted(due,key=lambda x:x[:3])[:limit]]
