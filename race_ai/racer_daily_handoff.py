"""Bounded daily refresh on the existing encrypted transfer ref."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib,hmac,json,os,re,tempfile
from .boat_pdca_github_handoff import GitStateRepository,TRANSFER_REF
from .racer_daily import DailyStore,wire,sha,need,clock,JST,seal,unseal
from .boat_pdca_state import state_key
from .source_retry_policy import SourceWait

PREFIX='state/boat-racer-daily/v1/'
LATEST=PREFIX+'latest.json'

class _DailyFilteredFetch:
    """Keep complete ancestry; retrieve only the encrypted blobs actually read.

    Command-scoped promisor settings leave shared repository configuration intact.
    The inherited transport still validates the remote, rejects URL rewrites and
    checks every requested commit, tree and blob before using it.
    """
    def _run(self,args,*,body=None,env=None):
        # The base GitStateRepository already supplies the exact blobless
        # fetch and validated repository identity. Do not add promisor config
        # or a second filter to that transport negotiation. Verified lazy blob
        # reads and missing-ok tree writes below retain their existing scope.
        if args and args[0]=='fetch' and '--filter=blob:none' in args:
            return super()._run(args,body=body,env=env)
        config=dict(os.environ if env is None else env);count=int(config.get('GIT_CONFIG_COUNT','0'))
        for setting,value in [('remote.origin.promisor','true'),('remote.origin.partialclonefilter','blob:none')]:
            config['GIT_CONFIG_KEY_'+str(count)]=setting;config['GIT_CONFIG_VALUE_'+str(count)]=value;count+=1
        config['GIT_CONFIG_COUNT']=str(count)
        if args and args[0]=='fetch':args=[args[0],'--filter=blob:none',*args[1:]]
        # The parent tree is already pinned on the validated remote and new
        # blobs were written locally. Do not materialize every inherited blob
        # merely to rebuild its unchanged tree; push verifies connectivity.
        if args==['write-tree']:args=['write-tree','--missing-ok']
        return super()._run(args,body=body,env=config)

class DailyStateRepository(_DailyFilteredFetch,GitStateRepository):pass

def _mac(doc,key):return hmac.new(state_key('production',key),b'RACE_AI_RACER_DAILY_HEAD_V1\n'+wire(doc).encode(),hashlib.sha256).hexdigest()
def _head(raw,key):
    doc=json.loads(raw);unsigned={k:v for k,v in doc.items() if k!='mac'}
    need(set(doc)=={'schema','as_of','head','cipher_path','catalogue_sha256','mac'} and doc['schema']=='RACE_AI_RACER_DAILY_HEAD_V1' and hmac.compare_digest(_mac(unsigned,key),doc['mac']),'DAILY_HEAD_AUTHENTICATION_FAILED')
    clock(doc['as_of']);h=doc['head'];g=h['generation']
    need(type(g) is int and 1<=g<=999999 and doc['cipher_path']==PREFIX+f'g{g:06d}/'+h['cipher_sha256']+'.enc','DAILY_HEAD_PATH_INVALID')
    need(re.fullmatch('[a-f0-9]{64}',h['cipher_sha256']) and re.fullmatch('[a-f0-9]{64}',doc['catalogue_sha256']),'DAILY_HEAD_HASH_INVALID')
    return doc

def _validate_history(git,parent,current,key):
    commits=git._run(['log','--full-history','--topo-order','--reverse','--format=%H',parent,'--',LATEST]).decode().splitlines()
    need(commits and len(commits)<=999999,'DAILY_STATE_HISTORY_REQUIRED')
    generation=0;previous=None;previous_time=None;last=None;seen=set()
    for commit in commits:
        need(git.exists(commit,LATEST),'DAILY_STATE_HISTORY_DELETION_REJECTED')
        raw=git.read(commit,LATEST,16000);doc=_head(raw,key);head=doc['head'];stamp=clock(doc['as_of'])
        if raw in seen:continue
        seen.add(raw)
        need(head['generation']==generation+1 and head['previous_cipher_sha256']==previous and (previous_time is None or stamp>=previous_time),'DAILY_STATE_HISTORY_ROLLBACK_REJECTED')
        path=doc['cipher_path']
        original=git._run(['ls-tree',commit,'--',path]).strip();retained=git._run(['ls-tree',parent,'--',path]).strip()
        need(original and retained,'DAILY_STATE_HISTORY_CIPHER_MISSING')
        need(original==retained,'DAILY_STATE_HISTORY_CIPHER_CHANGED')
        generation=head['generation'];previous=head['cipher_sha256'];previous_time=stamp;last=raw
    need(last==current,'DAILY_STATE_HISTORY_HEAD_MISMATCH')

def load_daily(repo,*,initialize=False,key=None,transport=None,now=None):
    state_key('production',key);now=clock(now or datetime.now(timezone.utc));git=transport or DailyStateRepository(repo,ref=TRANSFER_REF)
    need(git.ref==TRANSFER_REF,'DAILY_TRANSFER_REF_REQUIRED');parent=git.head();need(parent is not None,'DAILY_EXISTING_TRANSFER_REQUIRED');git.fetch(parent)
    previous=None;raw=None
    if git.exists(parent,LATEST):
        raw=git.read(parent,LATEST,16000);doc=_head(raw,key);previous=doc['head']
        _validate_history(git,parent,raw,key)
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
                retry=max(clock(exc.retry_at),now+delay) if exc.retry_at else now+delay
                store.wait_until(day,retry.isoformat());missing+=1;continue
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
    state_key('production');git=transport or DailyStateRepository(repo,ref=TRANSFER_REF)
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

def publish_daily_catalogue(repo,catalogue,*,transport=None,checked_at=None,state='READY',result_sync=None):
    """Atomically update derived aggregates/status; inherit UI and ciphertext."""
    import subprocess
    from .racer_daily import PUBLIC_PATH,PUBLIC_URL,STATUS_PATH,STATUS_URL,API_FILE,MAX_PUBLIC
    from .saved_pages import PagesRepository,_tree
    raw=(wire(catalogue)+'\n').encode();need(len(raw)<=MAX_PUBLIC and catalogue.get('status')=='READY','DAILY_PUBLIC_CATALOGUE_INVALID')
    expected={'schema','status','generated_at','last_source_at','period','coverage','cohort_top2_percent','source','people','unknown_registration_count','denominator','model_inputs_changed'}
    live=catalogue.get('schema')=='RACE_AI_RACER_DAILY_V2'
    need(set(catalogue)==expected|({'today'} if live else set()),'DAILY_PUBLIC_FIELDS_REJECTED')
    need(set(catalogue['source'])=={'url','sha256','receipts'} and all(set(r)=={'day','url','sha256','captured_at'} for r in catalogue['source']['receipts']),'DAILY_PRIVATE_FIELDS_REJECTED')
    need(set(catalogue['period'])=={'start','end','days'} and set(catalogue['coverage'])=={'parsed_days','missing_days_count','missing_days','partial_days','complete'} and all(set(d)=={'day','venues'} for d in catalogue['coverage']['partial_days']),'DAILY_PRIVATE_FIELDS_REJECTED')
    need(catalogue['denominator']=='confirmed_starts_including_non_numeric_results; confirmed_absences_excluded; ST_OK_samples_only','DAILY_DENOMINATOR_INVALID')
    fields={'starts','wins','seconds','thirds','win_percent','top2_percent','top3_percent','average_st','st_samples','confirmed_absences','dispositions','unknown_course_starts'}
    if live:
        need(set(catalogue['today'])=={'day','last_checked_at','latest_result_at','expected_races','confirmed_races','pending_races','schedule_complete','source_state','revision_conflicts','source_receipts'} and all(set(r)=={'url','sha256','captured_at','kind'} for r in catalogue['today']['source_receipts']),'DAILY_PRIVATE_FIELDS_REJECTED')
    for person in catalogue['people']:
        need(set(person)=={'registration','name','summary','courses','last_race_day'}|({'today_stats','today_races'} if live else set()) and set(person['summary'])==fields,'DAILY_PRIVATE_FIELDS_REJECTED')
        need(all(set(c)==fields|{'course'} for c in person['courses']),'DAILY_PRIVATE_FIELDS_REJECTED')
        if live:need(set(person['today_stats'])==fields and all(set(r)=={'race_id','lane','course','finish','result_code','st','st_status','captured_at'} for r in person['today_races']),'DAILY_PRIVATE_FIELDS_REJECTED')
    code="let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{try{if(!require('./web/racer-daily.js').parse(JSON.parse(s)))process.exit(1);}catch{process.exit(1);}});"
    result=subprocess.run(['node','-e',code],cwd=Path(__file__).resolve().parents[1],input=raw,capture_output=True,timeout=30)
    need(result.returncode==0,'DAILY_PUBLIC_SCHEMA_REJECTED')
    checked=clock(checked_at or catalogue['generated_at']);need(checked>=clock(catalogue['generated_at']) and state in ('READY','SOURCE_WAIT','SOURCE_HOLD'),'DAILY_STATUS_INVALID')
    status=dict(schema='RACE_AI_RACER_STATISTICS_STATUS_V1',catalogue_sha256=sha(raw),catalogue_generated_at=catalogue['generated_at'],checked_at=checked.isoformat(),state=state)
    if result_sync is not None:
        need(type(result_sync) is dict and set(result_sync)=={'schema','state','checked_at','races','confirmed','pending','held','changed_races'} and result_sync['schema']=='RACE_AI_RESULT_SYNC_V1' and result_sync['state'] in ('READY','SOURCE_WAIT','HOLD','RETRY') and clock(result_sync['checked_at'])<=checked,'RESULT_PUBLIC_STATUS_INVALID')
        need(all(type(result_sync[k]) is int and 0<=result_sync[k]<=576 for k in ('races','confirmed','pending','held','changed_races')) and result_sync['confirmed']+result_sync['pending']+result_sync['held']==result_sync['races'],'RESULT_PUBLIC_COUNTS_INVALID')
        status['result_sync']=dict(result_sync)
    status_raw=(wire(status)+'\n').encode()
    def receipt(status,commit,**extra):return dict(status=status,pages_commit=commit,public_sha256=sha(raw),path=PUBLIC_PATH,public_url=PUBLIC_URL,status_sha256=sha(status_raw),status_path=STATUS_PATH,status_url=STATUS_URL,**extra)
    class DailyPagesRepository(_DailyFilteredFetch,PagesRepository):pass
    git=transport or DailyPagesRepository(repo);need(git.ref=='gh-pages','DAILY_PAGES_REF_REQUIRED')
    for attempt in range(4):
        parent=git.head();need(parent is not None,'DAILY_EXISTING_PAGES_REQUIRED');git.fetch(parent);paths=_tree(git,parent)
        manifest=git.read(parent,'site-build.json',32768);meta=json.loads(manifest)
        need(API_FILE in meta['files'] and API_FILE in paths and API_FILE.encode() in git.read(parent,'index.html',100000),'DAILY_UI_NOT_PUBLISHED')
        if live:need(b'RACE_AI_RACER_DAILY_V2' in git.read(parent,API_FILE,100000),'DAILY_LIVE_UI_NOT_PUBLISHED')
        if PUBLIC_PATH in paths:
            previous=json.loads(git.read(parent,PUBLIC_PATH,MAX_PUBLIC))
            need(live or previous.get('schema')!='RACE_AI_RACER_DAILY_V2','DAILY_LIVE_CATALOGUE_REQUIRED')
            need(clock(previous['generated_at'])<=clock(catalogue['generated_at']),'DAILY_PUBLIC_ROLLBACK_REJECTED')
            if previous['generated_at']==catalogue['generated_at']:
                need(wire(previous)==wire(catalogue),'DAILY_PUBLIC_REVISION_AMBIGUOUS')
                if STATUS_PATH in paths and git.read(parent,STATUS_PATH,16000)==status_raw:return receipt('DAILY_PUBLIC_UNCHANGED',parent)
        if STATUS_PATH in paths:
            prior_status=json.loads(git.read(parent,STATUS_PATH,16000));need(clock(prior_status['checked_at'])<=checked,'DAILY_STATUS_ROLLBACK_REJECTED')
        before=git._run(['ls-tree','-r',parent,'--','views']);commit=git.commit({PUBLIC_PATH:raw,STATUS_PATH:status_raw},parent)
        need(git.read(commit,'site-build.json',32768)==manifest and git._run(['ls-tree','-r',commit,'--','views'])==before,'DAILY_PAGES_ORIGINALS_CHANGED')
        changed=git._run(['diff-tree','--no-commit-id','--name-only','-r',parent,commit]).decode().splitlines()
        need(changed and set(changed)<={PUBLIC_PATH,STATUS_PATH},'DAILY_PUBLICATION_SCOPE_REJECTED')
        try:git.push(commit,parent);break
        except ValueError:
            if attempt==3:raise
    need(git.read(commit,PUBLIC_PATH,MAX_PUBLIC)==raw and git.read(commit,STATUS_PATH,16000)==status_raw,'DAILY_PUBLIC_READBACK_MISMATCH')
    return receipt('DAILY_PUBLIC_PUBLISHED',commit,parent_commit=parent,changed_paths=changed,
                unchanged_cipher_count=len(before.splitlines()),presentation_and_ciphertext_unchanged=True,raw_sources_published=False)
