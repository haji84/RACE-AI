"""Encrypted all-racer x 24-venue lookup using observed official history.

Uses the existing venue definitions, monthly parser and owner checkpoint codec.
Compressed JSON lives inside bounded SQLite partitions, never public plaintext.
Acquisition/import clocks remain later than historical races: no retrospective
claim that these newly collected features existed before their actual capture.
"""
from datetime import datetime,timezone
import gzip,hashlib,hmac,io,json,re,sqlite3,tempfile
from pathlib import Path

from .boat_venue_history import VenueHistory,NAMES
from .boat_venue_history_handoff import _signed,GitStateRepository,TRANSFER_REF,PREFIX
from .teiai_history import need,racer_number
from .actions_contract import stamp
from scripts.boat_venue_history import restore_month,_manifest_mac,_scope
from scripts.boat_all_racers import _read,_write,_codec,_key_ready,_now

SCHEMA='RACE_AI_ENCRYPTED_VENUE_DATASET_V1'
INPUT='RACE_AI_BOAT_VENUE_DATASET_INPUT_V1'

def _bytes(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _unzip(raw,limit):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:body=f.read(limit+1)
    need(len(body)<=limit,'VENUE_PROFILE_SIZE_LIMIT');return json.loads(body)

def _seal(db,path,metadata):
    raw=db.serialize();need(len(raw)<=8*1024*1024,'VENUE_DATASET_PARTITION_SIZE_LIMIT');scope=_scope()
    with tempfile.TemporaryDirectory(prefix='boat-venue-part-') as t:
        t=Path(t);_write(t/'part.sqlite',raw);_write(t/'scope.json',_bytes(scope))
        _codec('seal',t/'part.sqlite',path,t/'scope.json')
    return dict(metadata,path=path.name,scope=scope,sqlite_sha256=_sha(raw),ciphertext_sha256=_sha(_read(path,12*1024*1024)))

def _open(root,part,*,key=None):
    path=Path(root)/part['path'];raw=_read(path,12*1024*1024)
    need(_sha(raw)==part['ciphertext_sha256'] and part['scope']==_scope(),'VENUE_DATASET_CIPHER_HASH_INVALID')
    with tempfile.TemporaryDirectory(prefix='boat-venue-part-read-') as t:
        t=Path(t);_write(t/'scope.json',_bytes(part['scope']))
        _codec('unseal',path,t/'part.sqlite',t/'scope.json',cipher_sha=part['ciphertext_sha256'],
            **(dict(key=key) if key is not None else {}))
        plain=_read(t/'part.sqlite',8*1024*1024)
    need(_sha(plain)==part['sqlite_sha256'],'VENUE_DATASET_SQLITE_HASH_INVALID')
    db=sqlite3.connect(':memory:');db.deserialize(plain);db.execute('PRAGMA trusted_schema=OFF')
    need(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],'VENUE_DATASET_SQLITE_CORRUPT')
    return db

def _manifest(root):
    need(_key_ready(),'OWNER_STATE_KEY_REQUIRED');raw=_read(Path(root)/'dataset.json',1000000);record=json.loads(raw)
    s=record['state'];need(record.keys()=={'state','mac'} and hmac.compare_digest(record['mac'],_manifest_mac(s)) and
        s['schema']==SCHEMA,'VENUE_DATASET_AUTHENTICATION_FAILED')
    need(len(s['parts'])==len({p['path'] for p in s['parts']}) and all(re.fullmatch(r'venue-(0[1-9]|1[0-9]|2[0-4])-part-[0-9]{4}\.enc',p['path']) for p in s['parts']) and
         s['sources']['path']=='sources.enc','VENUE_DATASET_PART_PATH_INVALID')
    return raw,s

def build_dataset(root,output,*,roster=(),end):
    need(_key_ready(),'OWNER_STATE_KEY_REQUIRED');root=Path(root);raw=_read(root/'collection.json',1000000);s=_signed(raw)['state']
    out=Path(output);out.mkdir(parents=True,mode=0o700,exist_ok=True);need(not any(out.iterdir()),'VENUE_DATASET_OUTPUT_EXISTS_DO_NOT_RESET')
    start=s['months'][0][:4]+'-'+s['months'][0][4:]+'-01'
    if s['schema']=='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V2':
        from .boat_history_dated_inventory import validate_inventory
        from .boat_venue_history import JST
        dated=validate_inventory(root,s,manifest_raw=raw)
        need(stamp(dated['inventory_captured_at']).astimezone(JST).date().isoformat()>=end and
             end<=s['not_after'],'VENUE_DATASET_END_INVALID')
    else:
        need(stamp(s['captured_at']).date().isoformat()>=end and end<=s['not_after'],'VENUE_DATASET_END_INVALID')
    engine=VenueHistory(start=start,end=end,roster=roster,clock=lambda:stamp(_now()));gaps=[]
    for m,h in sorted(s['heads'].items()):
        c,r=restore_month(root/h['folder'],expected_month=m)
        need(r['ciphertext_sha256']==h['ciphertext_sha256'],'VENUE_DATASET_SOURCE_HEAD_MISMATCH')
        for day,_,_,state,reason,_ in c._heads():
            if day<=end and state not in ('PARSED','PARTIAL_SOURCE'):gaps.append(dict(day=day,state=state,reason=reason))
        for source in c.archives():
            if source['day']<=end:engine.add_archive(source['raw'],day=source['day'],captured_at=source['captured_at'],allow_partial=True)
        c.db.close()
    as_of=_now();summary=engine.summary(as_of=as_of);parts=[];ids=sorted(engine.ids)
    for venue in sorted(NAMES):
        for number,offset in enumerate(range(0,len(ids),1000),1):
            subset=ids[offset:offset+1000];db=sqlite3.connect(':memory:')
            db.execute('CREATE TABLE profiles(racer_id TEXT PRIMARY KEY,document BLOB NOT NULL)')
            for pid in subset:
                profile=engine.profile(pid,venue,as_of=as_of)
                db.execute('INSERT INTO profiles VALUES (?,?)',(pid,gzip.compress(_bytes(profile),mtime=0)))
            db.commit();part=_seal(db,out/f'venue-{venue}-part-{number:04d}.enc',dict(venue_code=venue,rows=len(subset)))
            parts.append(part);db.close()
    sources=sqlite3.connect(':memory:');sources.execute('CREATE TABLE sources(document BLOB NOT NULL)')
    sources.execute('INSERT INTO sources VALUES (?)',(gzip.compress(_bytes(dict(sources=engine.sources,source_gaps=gaps)),mtime=0),));sources.commit()
    source_part=_seal(sources,out/'sources.enc',dict(days=len(engine.sources)));sources.close()
    state=dict(schema=SCHEMA,source_manifest_sha256=_sha(raw),created_at=as_of,available_at=as_of,
        requested_start=start,requested_end=end,summary=summary,parts=parts,sources=source_part,
        acquisition_complete=len(s['heads'])==len(s['months']) and not gaps and summary['coverage']['source_window_complete'],
        formal_backtest_eligible=False,production_promoted=False)
    _write(out/'dataset.json',_bytes(dict(state=state,mac=_manifest_mac(state))))
    return dict(summary,status='ENCRYPTED_VENUE_DATASET_CREATED',partitions=len(parts),available_at=as_of,
                source_gaps=len(gaps),plaintext_published=False)

def verify_dataset(root):
    _,s=_manifest(root);by_venue={v:set() for v in NAMES};count=0
    for part in s['parts']:
        db=_open(root,part);rows=db.execute('SELECT racer_id,document FROM profiles').fetchall();db.close()
        need(len(rows)==part['rows'],'VENUE_DATASET_ROW_COUNT_MISMATCH')
        for pid,raw in rows:
            profile=_unzip(raw,128000);racer_number(pid);venue=part['venue_code']
            need(pid not in by_venue[venue] and profile['racer_id']==pid and profile['venue_code']==venue and
                 profile['as_of']==s['available_at'] and profile['formal_backtest_eligible'] is False and
                 set(profile['by_actual_course'])==set('123456'),'VENUE_DATASET_PROFILE_CONTRACT')
            by_venue[venue].add(pid);count+=1
    need(all(ids==by_venue['01'] for ids in by_venue.values()) and count==s['summary']['grid_cells'],'VENUE_DATASET_GRID_INCOMPLETE')
    db=_open(root,s['sources']);values=db.execute('SELECT document FROM sources').fetchall();db.close()
    need(len(values)==1,'VENUE_DATASET_SOURCES_INVALID');provenance=_unzip(values[0][0],8*1024*1024)
    from .actions_contract import digest
    need(digest(provenance['sources'])==s['summary']['coverage']['source_set_sha256'],'VENUE_DATASET_SOURCE_SET_MISMATCH')
    return dict(status='ENCRYPTED_ALL_VENUE_GRID_READBACK_VERIFIED',verified_cells=count,
        known_racers=len(by_venue['01']),venues=24,source_days=len(provenance['sources']),
        acquisition_complete=s['acquisition_complete'],formal_backtest_eligible=False,plaintext_published=False)

def lookup(root,racer_id,venue_code,*,as_of):
    _,s=_manifest(root);racer_number(racer_id);need(venue_code in NAMES,'VENUE_CODE_INVALID')
    need(stamp(as_of)>=stamp(s['available_at']),'VENUE_DATASET_AFTER_PREDICTION_ASOF')
    for part in s['parts']:
        if part['venue_code']!=venue_code:continue
        db=_open(root,part);row=db.execute('SELECT document FROM profiles WHERE racer_id=?',(racer_id,)).fetchone();db.close()
        if row:
            profile=_unzip(row[0],128000)
            need(profile['racer_id']==racer_id and profile['venue_code']==venue_code and profile['as_of']==s['available_at'],'VENUE_DATASET_PROFILE_CONTRACT')
            return profile
    raise ValueError('VENUE_DATASET_RACER_NOT_PRESENT')

def publish_dataset(root,repo,*,transport=None):
    verify_dataset(root);root=Path(root);raw,s=_manifest(root);identity=_sha(raw);prefix=PREFIX+'datasets/'+identity+'/'
    git=transport or GitStateRepository(repo,ref=TRANSFER_REF);parent=git.head();need(parent is not None,'VENUE_EXISTING_TRANSFER_REF_REQUIRED');git.fetch(parent)
    files={}
    for name,limit in [('dataset.json',1000000)]+[(p['path'],12*1024*1024) for p in s['parts']+[s['sources']]]:
        body=_read(root/name,limit);path=prefix+name
        if git.exists(parent,path):need(git.read(parent,path,limit)==body,'VENUE_DATASET_IMMUTABLE_FILE_CHANGED')
        else:files[path]=body
    commit=parent
    if files:commit=git.commit(files,parent);git.push(commit,parent)
    return dict(schema=INPUT,status='READY',repository_id='1416489937',source_commit=commit,dataset_path=prefix+'dataset.json',dataset_sha256=identity)

def readback_dataset(pointer,root,repo,*,transport=None):
    if not _key_ready():return dict(status='HOLD_OWNER_STATE_KEY_MISSING',verified_cells=0)
    need(pointer.get('schema')==INPUT and pointer.get('repository_id')=='1416489937','VENUE_DATASET_INPUT_INVALID')
    if pointer.get('status')=='WAITING_ENCRYPTED_INPUT':return dict(status='HOLD_ENCRYPTED_INPUT_REQUIRED',verified_cells=0)
    need(pointer.get('schema')==INPUT and pointer.get('repository_id')=='1416489937' and pointer.get('status')=='READY' and
        re.fullmatch('[a-f0-9]{40}',pointer.get('source_commit','')) and re.fullmatch('[a-f0-9]{64}',pointer.get('dataset_sha256','')) and
        pointer.get('dataset_path')==PREFIX+'datasets/'+pointer['dataset_sha256']+'/dataset.json','VENUE_DATASET_INPUT_INVALID')
    from .boat_private_original_vault import VaultGitRepository
    git=transport if transport is not None else VaultGitRepository(repo,ref=TRANSFER_REF)
    c=pointer['source_commit'];git.fetch(c)
    raw=git.read(c,pointer['dataset_path'],1000000);need(_sha(raw)==pointer['dataset_sha256'],'VENUE_DATASET_MANIFEST_HASH_INVALID')
    root=Path(root);root.mkdir(mode=0o700,parents=True,exist_ok=True);need(not any(root.iterdir()),'VENUE_DATASET_OUTPUT_EXISTS_DO_NOT_RESET');_write(root/'dataset.json',raw)
    _,s=_manifest(root);prefix=pointer['dataset_path'].removesuffix('dataset.json')
    for part in s['parts']+[s['sources']]:_write(root/part['path'],git.read(c,prefix+part['path'],12*1024*1024))
    return verify_dataset(root)
