"""Explicit append-only observations of a newer official published inventory.

V1 captures remain immutable. New menu/index bytes are encrypted, signed to
an exact parent manifest and replayed before publication or dataset extension.
Only dates first listed by the latest inventory are eligible for delta GETs.
"""
import base64
from datetime import date
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from .actions_contract import stamp
from .boat_history_catalog import HistoryMonth,published_days,published_months
from .boat_venue_history import JST
from .teiai_history import need
from .source_retry_policy import SourceWait,wait_active
from scripts import boat_venue_history as cli
from scripts.boat_all_racers import _read,_write,_codec

SCHEMA='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V2'
PROOF_SCHEMA='RACE_AI_OFFICIAL_DATED_HISTORY_INVENTORY_V1'
LIMIT=8*1024*1024
ANCESTRAL_FIELDS=frozenset({'full_archive_validation'})
VALIDATION_FIELDS=frozenset('checked_at disputed_payout_races numeric_finish_rows parsed_source_days parser_revision past_day_states requested_end requested_start source_set_sha256 st_centisecond_sum st_centisecond_sum2 st_ok_rows typed_row_count unknown_actual_course_rows unreported_venue_days'.split())


def _bytes(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def validate_ancestral_metadata(state):
    """Recognize the existing report, without extending its coverage claims."""
    core={'schema','months','menu_sha256','captured_at','not_after','heads'}
    if state['schema']==SCHEMA:core|={'inventory_captured_at','inventory_lineage'}
    need(set(state)<=core|ANCESTRAL_FIELDS,'HISTORY_INVENTORY_ANCESTRAL_FIELDS_INVALID')
    if 'full_archive_validation' not in state:return
    report=state['full_archive_validation']
    need(type(report) is dict and set(report)==VALIDATION_FIELDS,'HISTORY_INVENTORY_ANCESTRAL_METADATA_INVALID')
    counters=VALIDATION_FIELDS-{'checked_at','past_day_states','requested_start','requested_end','source_set_sha256'}
    need(all(type(report[k]) is int and report[k]>=0 for k in counters) and report['parser_revision']>=1,
         'HISTORY_INVENTORY_ANCESTRAL_METADATA_INVALID')
    states=report['past_day_states']
    need(type(states) is dict and len(states)<=32 and all(type(k) is str and re.fullmatch('[A-Z_]{1,40}',k) and type(v) is int and v>=0 for k,v in states.items()),'HISTORY_INVENTORY_ANCESTRAL_METADATA_INVALID')
    need(type(report['source_set_sha256']) is str and re.fullmatch('[a-f0-9]{64}',report['source_set_sha256']),
         'HISTORY_INVENTORY_ANCESTRAL_METADATA_INVALID')
    try:start=date.fromisoformat(report['requested_start']);end=date.fromisoformat(report['requested_end'])
    except (TypeError,ValueError):raise ValueError('HISTORY_INVENTORY_ANCESTRAL_METADATA_INVALID') from None
    need(start.isoformat()==report['requested_start'] and end.isoformat()==report['requested_end'] and start<=end and report['requested_end']<=state['not_after'] and
         end<=stamp(report['checked_at']).astimezone(JST).date() and stamp(report['checked_at'])<=stamp(cli._now()),
         'HISTORY_INVENTORY_ANCESTRAL_METADATA_INVALID')

def _ancestral(state):return {k:state[k] for k in ANCESTRAL_FIELDS if k in state}

def _signed(raw):
    from .boat_venue_history_handoff import _signed as verify
    return verify(raw)
def _current(root):
    versions=sorted(Path(root).glob('progress-*.json'))
    raw=_read(versions[-1] if versions else Path(root)/'collection.json',1000000)
    return raw,_signed(raw)['state']
def _copy(source,target,limit):
    body=_read(source,limit);target=Path(target);target.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    if target.exists():need(_read(target,limit)==body,'HISTORY_DELTA_IMMUTABLE_FILE_CHANGED')
    else:_write(target,body)
def _head(folder,report):
    return dict(kind='ENCRYPTED',folder=folder,ciphertext_sha256=report['ciphertext_sha256'],attempt=int(folder.rsplit('-',1)[1]),generation=report['scope']['generation'],month_complete=report['catalog']['month_complete'])
def _target(root,month):
    attempts=[int(p.name.split('-')[1]) for p in (root/month).glob('attempt-*') if re.fullmatch('attempt-[0-9]{6}',p.name)]
    return f'{month}/attempt-{max(attempts,default=0)+1:06d}'


def inventory_files(state):
    need(state.get('schema')==SCHEMA and type(state.get('inventory_lineage')) is list and state['inventory_lineage'],'HISTORY_INVENTORY_LINEAGE_REQUIRED')
    found=[]
    for item in state['inventory_lineage']:
        folder=item.get('folder','')
        need(re.fullmatch(r'dated-inventory/[a-f0-9]{64}',folder),'HISTORY_INVENTORY_PATH_INVALID')
        found.extend([(folder+'/parent.json',1000000),(folder+'/inventory.checkpoint',12*1024*1024),(folder+'/summary.json',64000)])
    need(len(found)==len({p for p,_ in found}),'HISTORY_INVENTORY_DUPLICATE_GENERATION')
    return found


def _open_inventory(root,item):
    folder=Path(root)/item['folder'];report=json.loads(_read(folder/'summary.json',64000))
    need(report=={k:item[k] for k in ('scope','ciphertext_sha256','sqlite_sha256')},'HISTORY_INVENTORY_RECEIPT_MISMATCH')
    cipher=_read(folder/'inventory.checkpoint',12*1024*1024)
    need(_sha(cipher)==item['ciphertext_sha256'] and item['scope']==cli._scope(),'HISTORY_INVENTORY_CIPHER_HASH_INVALID')
    with tempfile.TemporaryDirectory(prefix='race-ai-dated-inventory-') as temp:
        t=Path(temp);_write(t/'scope.json',_bytes(item['scope']))
        _codec('unseal',folder/'inventory.checkpoint',t/'inventory.sqlite',t/'scope.json',cipher_sha=item['ciphertext_sha256'])
        plain=_read(t/'inventory.sqlite',LIMIT)
    need(_sha(plain)==item['sqlite_sha256'],'HISTORY_INVENTORY_SQLITE_HASH_INVALID')
    db=sqlite3.connect(':memory:');db.deserialize(plain);db.execute('PRAGMA trusted_schema=OFF')
    try:
        need(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],'HISTORY_INVENTORY_DB_INVALID')
        rows=db.execute('SELECT document FROM inventory').fetchall();need(len(rows)==1,'HISTORY_INVENTORY_DB_INVALID')
        proof=json.loads(rows[0][0])
    finally:db.close()
    return proof


def _raw(document):
    need(type(document) is dict and set(document)=={'source_url','captured_at','raw_base64','sha256'},'HISTORY_INVENTORY_SOURCE_INVALID')
    try:raw=base64.b64decode(document['raw_base64'],validate=True)
    except (ValueError,TypeError):raise ValueError('HISTORY_INVENTORY_SOURCE_INVALID') from None
    need(0<len(raw)<=200000 and base64.b64encode(raw).decode()==document['raw_base64'] and _sha(raw)==document['sha256'],'HISTORY_INVENTORY_SOURCE_HASH_INVALID')
    stamp(document['captured_at']);return raw


def _rows(db,table):
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
    return db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall() if exists else []


def _unchanged(parent,current):
    need(_rows(parent.db,'meta')==_rows(current.db,'meta'),'HISTORY_INVENTORY_OLD_META_CHANGED')
    for table in ('archives','observations','parse_events','waits','inventory_observations'):
        old=_rows(parent.db,table);new=_rows(current.db,table)
        if table=='archives':need(set(old)<=set(new),'HISTORY_INVENTORY_OLD_SOURCE_CHANGED')
        else:need(new[:len(old)]==old,'HISTORY_INVENTORY_OLD_OBSERVATION_CHANGED')


def validate_inventory(root,state,*,manifest_raw=None):
    """Authenticate the full parent/listing chain and retained original facts."""
    root=Path(root);inventory_files(state)
    if manifest_raw is not None:need(_signed(manifest_raw)['state']==state,'HISTORY_INVENTORY_MANIFEST_MISMATCH')
    entries=state['inventory_lineage'];ancestors=[];expected={};proofs=[];source_clocks={}
    now=stamp(cli._now())
    for number,item in enumerate(entries):
        parentraw=_read(root/item['folder']/'parent.json',1000000)
        need(_sha(parentraw)==item['parent_manifest_sha256'],'HISTORY_INVENTORY_PARENT_HASH_INVALID')
        parent=_signed(parentraw)['state'];ancestors.append(_sha(parentraw))
        validate_ancestral_metadata(parent)
        need(_ancestral(state)==_ancestral(parent),'HISTORY_INVENTORY_ANCESTRAL_METADATA_CHANGED')
        need(parent.get('inventory_lineage',[])==entries[:number],'HISTORY_INVENTORY_PARENT_LINEAGE_INVALID')
        proof=_open_inventory(root,item);proofs.append(proof)
        need(item['folder']=='dated-inventory/'+_sha(_bytes(proof)),'HISTORY_INVENTORY_CONTENT_ADDRESS_INVALID')
        need(set(proof)=={'schema','parent_manifest_sha256','not_after','inventory_captured_at','menu','indices','added_days'} and proof['schema']==PROOF_SCHEMA and proof['parent_manifest_sha256']==_sha(parentraw),'HISTORY_INVENTORY_PROOF_INVALID')
        need(proof['not_after']==item['not_after'] and proof['not_after']>=parent['not_after'] and proof['inventory_captured_at']==item['inventory_captured_at'],'HISTORY_INVENTORY_SCOPE_REGRESSION')
        menu=_raw(proof['menu']);months=published_months(menu)
        need(proof['menu']['source_url']==cli.MENU and set(parent['months'])<=set(months),'HISTORY_INVENTORY_MONTH_REGRESSION')
        lower=stamp(parent.get('inventory_captured_at',parent['captured_at']))
        docs=[proof['menu']]+list(proof['indices'].values())
        need(all(lower<=stamp(d['captured_at'])<=now and proof['not_after']<=stamp(d['captured_at']).astimezone(JST).date().isoformat() for d in docs),'HISTORY_INVENTORY_CLOCK_INVALID')
        need(item['inventory_captured_at']==max((d['captured_at'] for d in docs),key=stamp),'HISTORY_INVENTORY_CLOCK_INVALID')
        need(set(proof['indices'])==set(item['month_indices'])==set(proof['added_days']),'HISTORY_INVENTORY_INDEX_SCOPE_INVALID')
        for month,document in proof['indices'].items():
            raw=_raw(document)
            need(month in months and document['source_url']==f'https://www1.mbrace.or.jp/od2/K/{month}/mday.html' and item['month_indices'][month]==dict(sha256=_sha(raw),captured_at=document['captured_at']),'HISTORY_INVENTORY_INDEX_SCOPE_INVALID')
            days=set(published_days(raw,month=month,not_after=item['not_after']))
            if month in parent['heads']:
                old,receipt=cli.restore_month(root/parent['heads'][month]['folder'],expected_month=month)
                try:
                    need(receipt['ciphertext_sha256']==parent['heads'][month]['ciphertext_sha256'],'HISTORY_INVENTORY_PARENT_HEAD_INVALID')
                    olddays={d for (d,) in old.db.execute('SELECT day FROM expected')}
                    current,report=cli.restore_month(root/state['heads'][month]['folder'],expected_month=month)
                    try:
                        need(report['ciphertext_sha256']==state['heads'][month]['ciphertext_sha256'],'HISTORY_INVENTORY_HEAD_INVALID')
                        _unchanged(old,current)
                        event=current.db.execute('SELECT 1 FROM inventory_observations WHERE index_raw=? AND not_after=? AND captured_at=? AND parent_sqlite_sha256=?',(raw,item['not_after'],document['captured_at'],receipt['sqlite_sha256'])).fetchone()
                        need(event,'HISTORY_INVENTORY_MONTH_EVENT_MISSING')
                    finally:current.db.close()
                finally:old.db.close()
            else:olddays=set()
            need(olddays<=days and proof['added_days'][month]==sorted(days-olddays),'HISTORY_INVENTORY_LISTING_REGRESSION')
            expected.setdefault(month,set()).update(days)
            for day in proof['added_days'][month]:source_clocks[(month,day)]=stamp(document['captured_at'])
        if number==len(entries)-1:
            need(state['months']==months and state['menu_sha256']==_sha(menu) and state['captured_at']==parent['captured_at'] and state['not_after']==item['not_after'] and state['inventory_captured_at']==item['inventory_captured_at'],'HISTORY_INVENTORY_STATE_BINDING_INVALID')
    for month,days in expected.items():
        catalog,_=cli.restore_month(root/state['heads'][month]['folder'],expected_month=month)
        try:
            need({d for (d,) in catalog.db.execute('SELECT day FROM expected')}==days,'HISTORY_INVENTORY_UNOBSERVED_DATE')
            for day,captured in catalog.db.execute('SELECT day,captured_at FROM observations'):
                if (month,day) in source_clocks:
                    need(source_clocks[(month,day)]<=stamp(captured)<=now,'HISTORY_INVENTORY_DAILY_SOURCE_CLOCK_INVALID')
        finally:catalog.db.close()
    return dict(inventory_captured_at=state['inventory_captured_at'],parent_manifest_sha256=entries[-1]['parent_manifest_sha256'],ancestor_manifest_sha256=ancestors)


def _document(url,raw,at):
    return dict(source_url=url,raw_base64=base64.b64encode(raw).decode(),sha256=_sha(raw),captured_at=at)


def _save_inventory(out,parentraw,proof):
    identity=_sha(_bytes(proof));folder=f'dated-inventory/{identity}';target=out/folder
    target.mkdir(parents=True,mode=0o700,exist_ok=True)
    need(not any(target.iterdir()),'HISTORY_INVENTORY_OUTPUT_EXISTS_DO_NOT_RESET')
    _write(target/'parent.json',parentraw)
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE inventory(document BLOB NOT NULL)');db.execute('INSERT INTO inventory VALUES (?)',(_bytes(proof),));db.commit();plain=db.serialize();db.close()
    need(len(plain)<=LIMIT,'HISTORY_INVENTORY_SIZE_LIMIT');scope=cli._scope()
    with tempfile.TemporaryDirectory(prefix='race-ai-dated-seal-') as temp:
        t=Path(temp);_write(t/'inventory.sqlite',plain);_write(t/'scope.json',_bytes(scope));_codec('seal',t/'inventory.sqlite',target/'inventory.checkpoint',t/'scope.json')
    item=dict(folder=folder,parent_manifest_sha256=_sha(parentraw),inventory_captured_at=proof['inventory_captured_at'],not_after=proof['not_after'],month_indices={m:dict(sha256=d['sha256'],captured_at=d['captured_at']) for m,d in proof['indices'].items()},ciphertext_sha256=_sha(_read(target/'inventory.checkpoint',12*1024*1024)),sqlite_sha256=_sha(plain),scope=scope)
    _write(target/'summary.json',_bytes({k:item[k] for k in ('scope','ciphertext_sha256','sqlite_sha256')}))
    return item


def _wait_report(out,plan,gets):
    report=dict(status='HOLD_SOURCE_WAIT',source_wait=plan,upstream_gets=gets,all_available_period_complete=False,plaintext_published=False)
    body=dict(report,hold_mac=cli._manifest_mac(report))
    files=sorted(out.glob('dated-wait-*.json'));_write(out/f'dated-wait-{len(files)+1:06d}.json',_bytes(body));return report


def extend_collection(source,output,*,not_after=None,max_files=31):
    """Create a dated child, then collect only newly listed dates.

    Repeating an interrupted output respects its authenticated wait. Completed
    inventory generations resume via collect_delta without observing it again.
    """
    if not cli._key_ready():return dict(status='HOLD_OWNER_STATE_KEY_MISSING',upstream_gets=0,all_available_period_complete=False)
    need(type(max_files) is int and 1<=max_files<=31,'HISTORY_BATCH_LIMIT_INVALID')
    source=Path(source);out=Path(output)
    need(source.resolve()!=out.resolve() and source.resolve() not in out.resolve().parents,'HISTORY_DELTA_SEPARATE_OUTPUT_REQUIRED')
    parentraw,parent=_current(source)
    validate_ancestral_metadata(parent)
    if parent['schema']==SCHEMA:validate_inventory(source,parent,manifest_raw=parentraw)
    need(stamp(parent.get('inventory_captured_at',parent['captured_at']))<=stamp(cli._now()),'HISTORY_INVENTORY_PARENT_CLOCK_INVALID')
    end=not_after or stamp(cli._now()).astimezone(JST).date().isoformat()
    need(date.fromisoformat(end).isoformat()==end and parent['not_after']<=end<=stamp(cli._now()).astimezone(JST).date().isoformat(),'HISTORY_INVENTORY_SCOPE_REGRESSION')
    request=dict(schema='RACE_AI_DATED_HISTORY_EXTENSION_REQUEST_V1',parent_manifest_sha256=_sha(parentraw),not_after=end)
    out.mkdir(parents=True,mode=0o700,exist_ok=True)
    if (out/'dated-request.json').exists():
        record=json.loads(_read(out/'dated-request.json',64000));need(record==dict(state=request,mac=cli._manifest_mac(request)),'HISTORY_DELTA_REQUEST_MISMATCH')
        if (out/'collection.json').exists():
            _,current=_current(out)
            if current['schema']==SCHEMA and current['inventory_lineage'][-1]['parent_manifest_sha256']==_sha(parentraw):return collect_delta(out,max_files=max_files)
        waits=sorted(out.glob('dated-wait-*.json'))
        if waits:
            prior=cli._verify_hold(json.loads(_read(waits[-1],64000)))
            if wait_active(prior['source_wait'],cli._now()):return dict(prior,upstream_gets=0)
        # Before a committed V2 pointer, an existing request may have already
        # acquired its listings. Preserve it and stop instead of fetching again.
        need(bool(waits),'HISTORY_DELTA_UNCOMMITTED_INVENTORY_HOLD')
    else:
        need(not any(out.iterdir()),'HISTORY_DELTA_OUTPUT_EXISTS_DO_NOT_RESET')
        _write(out/'dated-request.json',_bytes(dict(state=request,mac=cli._manifest_mac(request))))
    from .boat_venue_history_handoff import _chain
    active=None
    for month,head in sorted(parent['heads'].items()):
        chain=_chain(source,month,head)
        for folder,_ in chain:
            for name,limit in [('history.checkpoint',12*1024*1024),('summary.json',64000)]:_copy(folder/name,out/folder.relative_to(source)/name,limit)
        catalog,_=cli.restore_month(source/head['folder'],expected_month=month)
        try:active=active or catalog.active_wait(cli._now())
        finally:catalog.db.close()
    if parent['schema']==SCHEMA:
        for path,limit in inventory_files(parent):_copy(source/path,out/path,limit)
    if not (out/'collection.json').exists():_write(out/'collection.json',parentraw)
    if active:return _wait_report(out,active,0)
    gets=0;epoch=stamp(cli._now())
    def fetch(url):
        nonlocal gets
        need(stamp(cli._now())>=epoch,'HISTORY_INVENTORY_CLOCK_REGRESSION_BEFORE_SOURCE')
        attempted=True
        try:return cli._http(url)
        except SourceWait as exc:
            attempted=getattr(exc,'upstream_attempted',True);raise
        finally:gets+=int(attempted)
    try:
        menu,menu_at=fetch(cli.MENU);months=published_months(menu)
        need(set(parent['months'])<=set(months),'HISTORY_INVENTORY_MONTH_REGRESSION')
        low=parent['not_after'][:7].replace('-','');high=end[:7].replace('-','')
        need(all(m>=low for m in set(months)-set(parent['months'])),'HISTORY_NEW_HISTORICAL_MONTH_REQUIRES_REVIEW')
        targets=[m for m in months if low<=m<=high]
        need(1<=len(targets)<=24,'HISTORY_INVENTORY_MONTH_BATCH_LIMIT')
        docs={}
        for month in targets:
            raw,at=fetch(f'https://www1.mbrace.or.jp/od2/K/{month}/mday.html')
            docs[month]=_document(f'https://www1.mbrace.or.jp/od2/K/{month}/mday.html',raw,at)
    except SourceWait as exc:return _wait_report(out,exc.plan,gets)
    documents=[_document(cli.MENU,menu,menu_at)]+list(docs.values())
    lower=stamp(parent.get('inventory_captured_at',parent['captured_at']))
    need(all(lower<=stamp(d['captured_at'])<=stamp(cli._now()) and end<=stamp(d['captured_at']).astimezone(JST).date().isoformat() for d in documents),'HISTORY_INVENTORY_CLOCK_INVALID')
    added={};prepared={};heads=dict(parent['heads'])
    for month,document in docs.items():
        if month in parent['heads']:
            catalog,old=cli.restore_month(source/parent['heads'][month]['folder'],expected_month=month)
            added[month]=catalog.extend_inventory(_raw(document),not_after=end,captured_at=document['captured_at'],parent_sqlite_sha256=old['sqlite_sha256'])
            scope=cli._scope(old['scope']['generation']+1,old['ciphertext_sha256'])
        else:
            catalog=HistoryMonth(month=month,index_raw=_raw(document),not_after=end)
            added[month]=catalog.pending();scope=cli._scope()
        prepared[month]=(catalog,scope)
    proof=dict(schema=PROOF_SCHEMA,parent_manifest_sha256=_sha(parentraw),not_after=end,inventory_captured_at=max((d['captured_at'] for d in documents),key=stamp),menu=documents[0],indices=docs,added_days=added)
    item=_save_inventory(out,parentraw,proof)
    for month,(catalog,scope) in prepared.items():
        relative=_target(out,month);report=cli.seal_catalog(out/relative,catalog,scope);catalog.db.close();heads[month]=_head(relative,report)
    state=dict(parent,schema=SCHEMA,months=months,menu_sha256=_sha(menu),not_after=end,heads=heads,inventory_captured_at=item['inventory_captured_at'],inventory_lineage=parent.get('inventory_lineage',[])+[item])
    cli._store_progress(out,state)
    validate_inventory(out,state,manifest_raw=_read(out/'collection.json',1000000))
    report=collect_delta(out,max_files=max_files)
    report['upstream_gets']+=gets
    return report


def _recover_month(root,state,month):
    """Adopt a fully authenticated child sealed before its pointer write."""
    head=state['heads'][month];candidates=[]
    for folder in sorted((root/month).glob('attempt-*')):
        if not re.fullmatch('attempt-[0-9]{6}',folder.name) or int(folder.name.split('-')[1])<=head['attempt']:continue
        # An unfinished attempt has an unknown acquisition outcome: stop rather
        # than replace it with a repeated request or invent zero prior GETs.
        need((folder/'summary.json').is_file() and (folder/'history.checkpoint').is_file(),'HISTORY_DELTA_INCOMPLETE_CHECKPOINT_HOLD')
        report=json.loads(_read(folder/'summary.json',64000))
        if report.get('scope',{}).get('previous_cipher_sha256')!=head['ciphertext_sha256']:continue
        catalog,report=cli.restore_month(folder,expected_month=month);catalog.db.close()
        need(report['scope']==cli._scope(head['generation']+1,head['ciphertext_sha256']),'HISTORY_DELTA_ORPHAN_PARENT_MISMATCH')
        candidates.append((folder,report))
    need(len(candidates)<=1,'HISTORY_DELTA_CONFLICTING_ORPHAN_CHECKPOINTS')
    if not candidates:return False
    folder,report=candidates[0];new=dict(state,heads=dict(state['heads']))
    new['heads'][month]=_head(folder.relative_to(root).as_posix(),report)
    validate_inventory(root,new)
    cli._store_progress(root,new);state.update(new);return True


def collect_delta(root,*,max_files=31):
    """Resume only dates added by the latest authenticated dated inventory."""
    if not cli._key_ready():return dict(status='HOLD_OWNER_STATE_KEY_MISSING',upstream_gets=0,all_available_period_complete=False)
    need(type(max_files) is int and 1<=max_files<=31,'HISTORY_BATCH_LIMIT_INVALID')
    root=Path(root);raw,state=_current(root);validate_inventory(root,state,manifest_raw=raw)
    if _read(root/'collection.json',1000000)!=raw:
        # Signed versions precede the atomic pointer. Recover the completed
        # version without altering a source observation or requesting it again.
        cli._store_progress(root,state)
    proof=_open_inventory(root,state['inventory_lineage'][-1]);gets=0;remaining=max_files;processed=0;wait=None
    for month in sorted(proof['added_days']):
        while _recover_month(root,state,month):pass
    for month,head in sorted(state['heads'].items()):
        catalog,_=cli.restore_month(root/head['folder'],expected_month=month)
        try:active=catalog.active_wait(cli._now())
        finally:catalog.db.close()
        if active:return dict(status='HOLD_SOURCE_WAIT',upstream_gets=0,source_wait=active,newly_listed_days=sum(map(len,proof['added_days'].values())),all_available_period_complete=False,plaintext_published=False)
    for month,days in sorted(proof['added_days'].items()):
        head=state['heads'][month];catalog,_=cli.restore_month(root/head['folder'],expected_month=month)
        try:
            active=catalog.active_wait(cli._now());pending=[d for d in catalog.pending() if d in days]
        finally:catalog.db.close()
        if active:return dict(status='HOLD_SOURCE_WAIT',upstream_gets=gets,source_wait=active,newly_listed_days=sum(map(len,proof['added_days'].values())),all_available_period_complete=False,plaintext_published=False)
        if not pending or not remaining:continue
        relative=_target(root,month)
        report=cli.capture_month(root/relative,month=month,resume=root/head['folder'],max_files=remaining,only_days=days,minimum_source_at=proof['indices'][month]['captured_at'])
        gets+=report['upstream_gets'];remaining-=min(remaining,len(pending));processed+=1
        state['heads'][month]=_head(relative,report);cli._store_progress(root,state)
        if report.get('source_wait'):wait=report['source_wait'];break
    validate_inventory(root,state,manifest_raw=_read(root/'collection.json',1000000))
    result=dict(status='HOLD_SOURCE_WAIT' if wait else 'DATED_HISTORY_DELTA_CHECKPOINTED',newly_listed_days=sum(map(len,proof['added_days'].values())),upstream_gets=gets,months_processed_this_invocation=processed,inventory_captured_at=state['inventory_captured_at'],not_after=state['not_after'],all_available_period_complete=False,source_gaps_require_separate_review=True,plaintext_published=False)
    if wait:result['source_wait']=wait
    return result
