"""Bounded daily refresh on the existing encrypted transfer ref."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib,hmac,json,re,tempfile
from .boat_pdca_github_handoff import GitStateRepository,TRANSFER_REF
from .racer_daily import DailyStore,wire,sha,need,clock,JST,seal,unseal
from .boat_pdca_state import state_key
from .source_retry_policy import SourceWait

PREFIX='state/boat-racer-daily/v1/'
LATEST=PREFIX+'latest.json'

def _mac(doc,key):return hmac.new(state_key('production',key),b'RACE_AI_RACER_DAILY_HEAD_V1\n'+wire(doc).encode(),hashlib.sha256).hexdigest()
def _head(raw,key):
    doc=json.loads(raw);unsigned={k:v for k,v in doc.items() if k!='mac'}
    need(set(doc)=={'schema','as_of','head','cipher_path','catalogue_sha256','mac'} and doc['schema']=='RACE_AI_RACER_DAILY_HEAD_V1' and hmac.compare_digest(_mac(unsigned,key),doc['mac']),'DAILY_HEAD_AUTHENTICATION_FAILED')
    clock(doc['as_of']);h=doc['head'];g=h['generation']
    need(type(g) is int and 1<=g<=999999 and doc['cipher_path']==PREFIX+f'g{g:06d}/'+h['cipher_sha256']+'.enc','DAILY_HEAD_PATH_INVALID')
    need(re.fullmatch('[a-f0-9]{64}',h['cipher_sha256']) and re.fullmatch('[a-f0-9]{64}',doc['catalogue_sha256']),'DAILY_HEAD_HASH_INVALID')
    return doc

def load_daily(repo,*,initialize=False,key=None,transport=None,now=None):
    state_key('production',key);now=clock(now or datetime.now(timezone.utc));git=transport or GitStateRepository(repo,ref=TRANSFER_REF)
    need(git.ref==TRANSFER_REF,'DAILY_TRANSFER_REF_REQUIRED');parent=git.head();need(parent is not None,'DAILY_EXISTING_TRANSFER_REQUIRED');git.fetch(parent)
    previous=None;raw=None
    if git.exists(parent,LATEST):
        raw=git.read(parent,LATEST,16000);doc=_head(raw,key);previous=doc['head']
        need(clock(doc['as_of'])<=now,'DAILY_STATE_CLOCK_REGRESSION')
        paths=git._run(['ls-tree','-r','--name-only',parent,'--',PREFIX]).decode().splitlines()
        gens=[int(m[1]) for path in paths if (m:=re.fullmatch(re.escape(PREFIX)+r'g([0-9]{6})/[a-f0-9]{64}\.enc',path))]
        need(gens and max(gens)==previous['generation'],'DAILY_STATE_ROLLBACK_REJECTED')
        plain=unseal(git.read(parent,doc['cipher_path'],32*1024*1024),previous,key=key)
        store=DailyStore.restore(plain,expected_sha256=previous['sqlite_sha256'],clock=lambda:now)
    else:
        need(initialize is True,'DAILY_INITIALIZATION_REQUIRED')
        need(not git._run(['ls-tree','-r','--name-only',parent,'--',PREFIX]).strip() and not git._run(['log','-1','--format=%H',parent,'--',LATEST]).strip(),'DAILY_MISSING_STATE_MUST_NOT_RESET')
        store=DailyStore(clock=lambda:now)
    return dict(git=git,parent=parent,previous=previous,previous_raw=raw,store=store)

def save_daily(loaded,catalogue,*,key=None):
    need(catalogue['status']=='READY','DAILY_SUCCESSFUL_SOURCE_REQUIRED')
    prior=loaded['previous'];g=prior['generation']+1 if prior else 1
    raw=loaded['store'].serialize();cipher,head=seal(raw,generation=g,previous=prior['cipher_sha256'] if prior else None,key=key)
    path=PREFIX+f'g{g:06d}/'+head['cipher_sha256']+'.enc'
    doc=dict(schema='RACE_AI_RACER_DAILY_HEAD_V1',as_of=catalogue['generated_at'],head=head,cipher_path=path,catalogue_sha256=sha(wire(catalogue).encode()))
    doc['mac']=_mac(doc,key);files={path:cipher,LATEST:(wire(doc)+'\n').encode()};git=loaded['git']
    for attempt in range(4):
        parent=git.head();need(parent is not None,'DAILY_TRANSFER_DISAPPEARED');git.fetch(parent)
        current=git.read(parent,LATEST,16000) if git.exists(parent,LATEST) else None
        need(current==loaded['previous_raw'],'DAILY_CONCURRENT_WRITER_REJECTED')
        commit=git.commit(files,parent)
        try:git.push(commit,parent);break
        except ValueError:
            if attempt==3:raise
    need(git.read(commit,path,32*1024*1024)==cipher and git.read(commit,LATEST,16000)==files[LATEST],'DAILY_REMOTE_STATE_MISMATCH')
    return dict(status='DAILY_ENCRYPTED_STATE_RETAINED',source_commit=commit,cipher_path=path,cipher_sha256=head['cipher_sha256'],generation=g,plaintext_published=False)

def collect_recent(store,*,now,fetch=None,max_requests=7):
    from scripts.boat_venue_history import _http
    from .official_archive_probe import official_url
    from .racer_daily import day_value
    now=clock(now);need(type(max_requests) is int and 1<=max_requests<=7,'DAILY_REQUEST_LIMIT_INVALID')
    if store.waiting('*',now):return dict(status='SOURCE_WAIT',requests=0,new_files=0)
    end=now.astimezone(JST).date()-timedelta(days=1);latest=store.latest()
    dates=[end-timedelta(days=i) for i in range(3)]
    dates += [end-timedelta(days=i) for i in range(3,90) if (end-timedelta(days=i)).isoformat() not in latest]
    requests=changed=0;missing=0;status='NO_CHANGES'
    for d in dates:
        day=d.isoformat()
        if requests>=max_requests:break
        if store.waiting(day,now):continue
        requests+=1
        try:
            raw,captured=(fetch(day) if fetch else _http(official_url(d,'K')))
            changed+=store.record(day,raw,captured_at=captured)
        except SourceWait as exc:
            if getattr(exc,'plan',{}).get('http_status')==404:
                delay=timedelta(hours=1 if d>=end-timedelta(days=2) else 24)
                store.wait_until(day,max(clock(exc.retry_at),now+delay).isoformat());missing+=1;continue
            retry=max(clock(exc.retry_at),now+timedelta(hours=1)).isoformat() if exc.retry_at else '9999-12-31T23:59:59+00:00'
            store.wait_until('*',retry);status='SOURCE_WAIT';break
        except ValueError as exc:
            if str(exc)=='DAILY_UNKNOWN_FINISH_NOT_ADMITTED':
                store.wait_until(day,(now+timedelta(hours=6)).isoformat());missing+=1;continue
            store.wait_until('*',(now+timedelta(hours=6)).isoformat());status='SOURCE_HOLD';break
    if status=='NO_CHANGES' and changed:status='COLLECTED'
    return dict(status=status,requests=requests,new_files=changed,unavailable_days=missing)

def seed_recent_months(repo,store,*,now,pointer,transport=None):
    """Restore only the four relevant authenticated monthly heads; no provider GET."""
    from .boat_venue_history_handoff import _signed,PREFIX as MONTH_PREFIX
    from scripts.boat_venue_history import restore_month
    from scripts.boat_all_racers import _write
    state_key('production');git=transport or GitStateRepository(repo,ref=TRANSFER_REF)
    need(pointer['status']=='READY' and re.fullmatch('[a-f0-9]{40}',pointer['source_commit']) and pointer['manifest_path']==MONTH_PREFIX+'manifests/'+pointer['manifest_sha256']+'.json','DAILY_SEED_POINTER_INVALID')
    commit=pointer['source_commit'];git.fetch(commit);raw=git.read(commit,pointer['manifest_path'],1000000)
    need(sha(raw)==pointer['manifest_sha256'],'DAILY_SEED_MANIFEST_HASH_INVALID');manifest=_signed(raw)['state']
    end=clock(now).astimezone(JST).date()-timedelta(days=1);start=end-timedelta(days=89)
    months={ (start+timedelta(days=i)).strftime('%Y%m') for i in range(90)};count=0
    for month in sorted(months):
        entry=manifest['heads'].get(month)
        if not entry:continue
        with tempfile.TemporaryDirectory(prefix='race-ai-daily-seed-') as temp:
            folder=Path(temp)
            for name,limit in [('history.checkpoint',12*1024*1024),('summary.json',64000)]:
                _write(folder/name,git.read(commit,MONTH_PREFIX+entry['folder']+'/'+name,limit))
            catalog,report=restore_month(folder,expected_month=month)
            try:
                need(report['ciphertext_sha256']==entry['ciphertext_sha256'] and report['scope']['generation']==entry['generation'],'DAILY_SEED_HEAD_MISMATCH')
                for source in catalog.archives():
                    if start.isoformat()<=source['day']<=end.isoformat():
                        try:count+=store.record(source['day'],source['raw'],captured_at=source['captured_at'])
                        except ValueError as exc:
                            if str(exc)!='DAILY_UNKNOWN_FINISH_NOT_ADMITTED':raise
            finally:catalog.db.close()
    need(count>0,'DAILY_AUTHENTICATED_SEED_REQUIRED');return count

def publish_daily_catalogue(repo,catalogue,*,transport=None):
    """Update one derived JSON blob. Inherit every UI, manifest and cipher byte."""
    import subprocess
    from .racer_daily import PUBLIC_PATH,API_FILE,MAX_PUBLIC
    from .saved_pages import PagesRepository,_tree
    raw=(wire(catalogue)+'\n').encode();need(len(raw)<=MAX_PUBLIC and catalogue.get('status')=='READY','DAILY_PUBLIC_CATALOGUE_INVALID')
    expected={'schema','status','generated_at','last_source_at','period','coverage','cohort_top2_percent','source','people','unknown_registration_count','denominator','model_inputs_changed'}
    need(set(catalogue)==expected,'DAILY_PUBLIC_FIELDS_REJECTED')
    need(set(catalogue['source'])=={'url','sha256','receipts'} and all(set(r)=={'day','url','sha256','captured_at'} for r in catalogue['source']['receipts']),'DAILY_PRIVATE_FIELDS_REJECTED')
    need(set(catalogue['period'])=={'start','end','days'} and set(catalogue['coverage'])=={'parsed_days','missing_days_count','missing_days','partial_days','complete'} and all(set(d)=={'day','venues'} for d in catalogue['coverage']['partial_days']),'DAILY_PRIVATE_FIELDS_REJECTED')
    need(catalogue['denominator']=='confirmed_starts_including_non_numeric_results; confirmed_absences_excluded; ST_OK_samples_only','DAILY_DENOMINATOR_INVALID')
    fields={'starts','wins','seconds','thirds','win_percent','top2_percent','top3_percent','average_st','st_samples','confirmed_absences','dispositions','unknown_course_starts'}
    for person in catalogue['people']:
        need(set(person)=={'registration','name','summary','courses','last_race_day'} and set(person['summary'])==fields,'DAILY_PRIVATE_FIELDS_REJECTED')
        need(all(set(c)==fields|{'course'} for c in person['courses']),'DAILY_PRIVATE_FIELDS_REJECTED')
    code="let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{try{if(!require('./web/racer-daily.js').parse(JSON.parse(s)))process.exit(1);}catch{process.exit(1);}});"
    result=subprocess.run(['node','-e',code],cwd=Path(__file__).resolve().parents[1],input=raw,capture_output=True,timeout=30)
    need(result.returncode==0,'DAILY_PUBLIC_SCHEMA_REJECTED')
    git=transport or PagesRepository(repo);need(git.ref=='gh-pages','DAILY_PAGES_REF_REQUIRED')
    for attempt in range(4):
        parent=git.head();need(parent is not None,'DAILY_EXISTING_PAGES_REQUIRED');git.fetch(parent);paths=_tree(git,parent)
        manifest=git.read(parent,'site-build.json',32768);meta=json.loads(manifest)
        need(API_FILE in meta['files'] and API_FILE in paths and API_FILE.encode() in git.read(parent,'index.html',100000),'DAILY_UI_NOT_PUBLISHED')
        if PUBLIC_PATH in paths:
            previous=json.loads(git.read(parent,PUBLIC_PATH,MAX_PUBLIC))
            need(clock(previous['generated_at'])<=clock(catalogue['generated_at']),'DAILY_PUBLIC_ROLLBACK_REJECTED')
            if previous['generated_at']==catalogue['generated_at']:
                need(wire(previous)==wire(catalogue),'DAILY_PUBLIC_REVISION_AMBIGUOUS')
                return dict(status='DAILY_PUBLIC_UNCHANGED',pages_commit=parent,public_sha256=sha(raw),path=PUBLIC_PATH)
        before=git._run(['ls-tree','-r',parent,'--','views']);commit=git.commit({PUBLIC_PATH:raw},parent)
        need(git.read(commit,'site-build.json',32768)==manifest and git._run(['ls-tree','-r',commit,'--','views'])==before,'DAILY_PAGES_ORIGINALS_CHANGED')
        changed=git._run(['diff-tree','--no-commit-id','--name-only','-r',parent,commit]).decode().splitlines()
        need(changed==[PUBLIC_PATH],'DAILY_PUBLICATION_SCOPE_REJECTED')
        try:git.push(commit,parent);break
        except ValueError:
            if attempt==3:raise
    need(git.read(commit,PUBLIC_PATH,MAX_PUBLIC)==raw,'DAILY_PUBLIC_READBACK_MISMATCH')
    return dict(status='DAILY_PUBLIC_PUBLISHED',pages_commit=commit,parent_commit=parent,public_sha256=sha(raw),path=PUBLIC_PATH,
                unchanged_cipher_count=len(before.splitlines()),presentation_and_ciphertext_unchanged=True,raw_sources_published=False)
