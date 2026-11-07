"""Daily public descriptive aggregates; raw official sources stay encrypted."""
from collections import Counter
from datetime import date,datetime,timedelta,timezone
import base64,gzip,hashlib,json,os,re,sqlite3
from .official_k_archive import parse_archive
from .official_archive_probe import official_url
from .boat_pdca_state import state_key,inflate

JST=timezone(timedelta(hours=9))
SCHEMA='RACE_AI_RACER_DAILY_V1'
CHECKPOINT='RACE_AI_RACER_DAILY_CHECKPOINT_V1'
PUBLIC_PATH='data/racer-daily.json'
PUBLIC_URL='https://raw.githubusercontent.com/haji84/RACE-AI/gh-pages/'+PUBLIC_PATH
STATUS_PATH='data/racer-live-status.json'
STATUS_URL='https://raw.githubusercontent.com/haji84/RACE-AI/gh-pages/'+STATUS_PATH
API_FILE='racer-daily.js'
MAX_DB=16*1024*1024
MAX_PUBLIC=4*1024*1024
def wire(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(v).hexdigest()
def need(ok,code):
    if not ok:raise ValueError(code)
def clock(v):
    d=v if isinstance(v,datetime) else datetime.fromisoformat(v.replace('Z','+00:00'))
    need(d.utcoffset() is not None,'DAILY_AWARE_CLOCK_REQUIRED');return d.astimezone(timezone.utc)
def day_value(v):
    d=date.fromisoformat(v);need(d.isoformat()==v,'DAILY_CANONICAL_DAY_REQUIRED');return d

def stats(rows):
    absent=sum(r['st_status']=='ABSENT' for r in rows)
    starts=[r for r in rows if r['st_status']!='ABSENT'];n=len(starts)
    finishes=Counter(r['finish'] for r in starts if type(r['finish']) is int and r['finish'] in range(1,7))
    st=[r['st'] for r in starts if r['st_status']=='OK' and r['st'] is not None]
    wins=finishes[1];two=sum(finishes[k] for k in (1,2));three=sum(finishes[k] for k in (1,2,3))
    return dict(starts=n,wins=wins,seconds=finishes[2],thirds=finishes[3],
        win_percent=wins/n*100 if n else None,top2_percent=two/n*100 if n else None,
        top3_percent=three/n*100 if n else None,average_st=round(sum(st)/len(st),4) if st else None,
        st_samples=len(st),confirmed_absences=absent,
        dispositions=dict(Counter(r['result_code'] or 'UNKNOWN' for r in starts if r['finish'] is None)),
        unknown_course_starts=sum(r['course'] is None for r in starts))

class DailyStore:
    def __init__(self,*,clock=None):
        self.clock=clock or (lambda:datetime.now(timezone.utc));self.db=sqlite3.connect(':memory:')
        self.db.executescript('''PRAGMA trusted_schema=OFF;PRAGMA user_version=1;
          CREATE TABLE archives(sha TEXT PRIMARY KEY,raw BLOB NOT NULL);
          CREATE TABLE observations(id INTEGER PRIMARY KEY,day TEXT NOT NULL,sha TEXT NOT NULL,captured_at TEXT NOT NULL);
          CREATE INDEX by_day ON observations(day,id);
          CREATE TABLE waits(day TEXT PRIMARY KEY,retry_at TEXT NOT NULL);''')
    def close(self):self.db.close()
    @property
    def revisions(self):return self.db.execute('SELECT count(*) FROM observations').fetchone()[0]
    def latest(self):
        return {d:dict(day=d,sha256=h,captured_at=c,raw=raw) for d,h,c,raw in self.db.execute(
            'SELECT o.day,o.sha,o.captured_at,a.raw FROM observations o JOIN archives a ON a.sha=o.sha '
            'WHERE o.id=(SELECT max(i.id) FROM observations i WHERE i.day=o.day) ORDER BY o.day')}
    def record(self,day,raw,*,captured_at):
        d=day_value(day);captured=clock(captured_at);now=clock(self.clock())
        need(d<now.astimezone(JST).date() and d<=captured.astimezone(JST).date() and captured<=now,'DAILY_SOURCE_CLOCK_INVALID')
        need(type(raw) is bytes and 0<len(raw)<=16000000,'DAILY_ARCHIVE_SIZE_INVALID')
        h=sha(raw);last=self.db.execute('SELECT sha,captured_at FROM observations WHERE day=? ORDER BY id DESC LIMIT 1',(day,)).fetchone()
        if last and last[0]==h:return False
        need(not last or captured>clock(last[1]),'DAILY_REVISION_CLOCK_REGRESSION')
        parsed=parse_archive(raw,day=day) # Admit a whole source atomically, including supported special results.
        need(not any(r['result_code']=='00' and r['finish'] is None for r in parsed['rows']),'DAILY_UNKNOWN_FINISH_NOT_ADMITTED')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO archives VALUES (?,?)',(h,raw))
            self.db.execute('INSERT INTO observations(day,sha,captured_at) VALUES (?,?,?)',(day,h,captured.isoformat()))
        return True
    def serialize(self):
        self.db.commit();raw=self.db.serialize();need(len(raw)<=MAX_DB,'DAILY_SNAPSHOT_SIZE_LIMIT');return raw
    def waiting(self,day,now):
        row=self.db.execute('SELECT retry_at FROM waits WHERE day=?',(day,)).fetchone()
        return bool(row and clock(row[0])>clock(now))
    def wait_until(self,day,retry_at):
        clock(retry_at)
        with self.db:self.db.execute('INSERT OR REPLACE INTO waits VALUES (?,?)',(day,retry_at))
    def compact(self,keep_from):
        day_value(keep_from)
        with self.db:
            self.db.execute('DELETE FROM observations WHERE day<?',(keep_from,))
            self.db.execute('DELETE FROM observations WHERE id NOT IN (SELECT max(id) FROM observations GROUP BY day)')
            self.db.execute('DELETE FROM archives WHERE sha NOT IN (SELECT sha FROM observations)')
            self.db.execute("DELETE FROM waits WHERE day!='*' AND day<?",(keep_from,))
        self.db.execute('VACUUM')
    @classmethod
    def restore(cls,raw,*,expected_sha256,clock=None):
        need(type(raw) is bytes and 0<len(raw)<=MAX_DB and sha(raw)==expected_sha256,'DAILY_SNAPSHOT_HASH_INVALID')
        need(raw.startswith(b'SQLite format 3\0'),'DAILY_SNAPSHOT_HEADER_INVALID')
        store=cls(clock=clock)
        try:
            store.db.deserialize(raw);store.db.execute('PRAGMA trusted_schema=OFF')
            need(store.db.execute('PRAGMA integrity_check').fetchone()==('ok',),'DAILY_SNAPSHOT_INTEGRITY_INVALID')
            need(store.db.execute('PRAGMA user_version').fetchone()==(1,),'DAILY_SNAPSHOT_SCHEMA_INVALID')
            objects=store.db.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','trigger','view')").fetchall()
            base={('table','archives'),('table','observations')}
            need(set(objects) in (base,base|{('table','waits')}),'DAILY_SNAPSHOT_OBJECTS_INVALID')
            store.db.execute('CREATE TABLE IF NOT EXISTS waits(day TEXT PRIMARY KEY,retry_at TEXT NOT NULL)')
            for h,body in store.db.execute('SELECT sha,raw FROM archives'):need(sha(body)==h,'DAILY_RETAINED_ARCHIVE_HASH_INVALID')
            need(store.db.execute('SELECT count(*) FROM observations o LEFT JOIN archives a ON a.sha=o.sha WHERE a.sha IS NULL').fetchone()==(0,),'DAILY_RETAINED_ARCHIVE_MISSING')
            return store
        except Exception:
            store.close();raise
    def catalogue(self,roster,*,as_of,days=90,extra_rows=(),live=None):
        now=clock(as_of);need(now<=clock(self.clock()) and type(days) is int and 1<=days<=180,'DAILY_CATALOGUE_CLOCK_OR_WINDOW_INVALID')
        end=now.astimezone(JST).date()-timedelta(days=1);start=end-timedelta(days=days-1)
        rows=[];receipts=[];partial=[];latest=self.latest();seen=set();people=[]
        for day,item in latest.items():
            if not start<=day_value(day)<=end or clock(item['captured_at'])>now:continue
            parsed=parse_archive(item['raw'],day=day);rows.extend(parsed['rows'])
            receipts.append(dict(day=day,url=official_url(day_value(day),'K'),sha256=item['sha256'],captured_at=item['captured_at']))
            if parsed['unreported_venues'] or parsed['unpublished_venues']:
                partial.append(dict(day=day,venues=sorted(set(parsed['unreported_venues']+parsed['unpublished_venues']))))
        if live is not None:
            need(type(live) is dict and live.get('day')==now.astimezone(JST).date().isoformat(),'DAILY_INTRADAY_CONTEXT_INVALID')
            # K is canonical per race. A missing/partial day does not erase SP
            # facts for races absent from that day's actual parsed archive.
            canonical={r['race_id'] for r in rows};groups={}
            for row in extra_rows:
                rid=row.get('race_id');need(type(rid) is str and re.fullmatch(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',rid),'DAILY_INTRADAY_RACE_INVALID')
                d=datetime.strptime(rid[:8],'%Y%m%d').date();at=clock(row['captured_at'])
                need(at<=now and d<=at.astimezone(JST).date() and d<=now.astimezone(JST).date(),'DAILY_INTRADAY_CLOCK_INVALID')
                if d<start:continue
                groups.setdefault((rid,at),{})[row['racer_id']]=row
            selected={}
            for (rid,at),group in groups.items():
                need(len(group)==6 and len({r['lane'] for r in group.values()})==6 and all(r['result_code'] not in ('','00') for r in group.values()),'DAILY_INTRADAY_INCOMPLETE_RACE')
                if rid in canonical:continue
                if rid not in selected or at>selected[rid][0]:selected[rid]=(at,list(group.values()))
            for _,group in selected.values():rows.extend(group)
            rows.sort(key=lambda r:(r['race_id'],r['racer_id']))
        for person in roster:
            reg=person['registration'];need(re.fullmatch('[0-9]{4}',reg) and reg not in seen and type(person['name']) is str,'DAILY_ROSTER_INVALID');seen.add(reg)
            own=[r for r in rows if r['racer_id']==reg]
            entry=dict(registration=reg,name=person['name'],summary=stats(own),
                courses=[dict(course=c,**stats([r for r in own if r['course']==c])) for c in range(1,7)],
                last_race_day=max((r['race_id'][:8] for r in own),default=None))
            if live is not None:
                today=[r for r in own if r['race_id'][:8]==live['day'].replace('-','')]
                entry.update(today_stats=stats(today),today_races=[{k:r[k] for k in ('race_id','lane','course','finish','result_code','st','st_status','captured_at')} for r in sorted(today,key=lambda r:r['race_id'])])
            people.append(entry)
        present={r['day'] for r in receipts};missing=[(start+timedelta(days=i)).isoformat() for i in range(days) if (start+timedelta(days=i)).isoformat() not in present]
        last_capture=max((r['captured_at'] for r in receipts),default=None)
        result=dict(schema=SCHEMA,status='READY' if receipts else 'UNAVAILABLE',generated_at=now.isoformat(),last_source_at=last_capture,
            period=dict(start=start.isoformat(),end=end.isoformat(),days=days),
            coverage=dict(parsed_days=len(receipts),missing_days_count=len(missing),missing_days=missing,partial_days=partial,complete=not missing and not partial),
            cohort_top2_percent=[stats([r for r in rows if r['course']==c])['top2_percent'] for c in range(1,7)],
            source=dict(url='https://www1.mbrace.or.jp/od2/K/dmenu.html',sha256=sha(wire(receipts).encode()),receipts=receipts),
            people=people,unknown_registration_count=len({r['racer_id'] for r in rows}-seen),
            denominator='confirmed_starts_including_non_numeric_results; confirmed_absences_excluded; ST_OK_samples_only',
            model_inputs_changed=False)
        if live is not None:
            captures=[r['captured_at'] for r in rows if r.get('captured_at')]
            result.update(schema='RACE_AI_RACER_DAILY_V2',today=live,status='READY' if receipts or captures else 'UNAVAILABLE',
                          last_source_at=max([*captures,*([last_capture] if last_capture else [])],default=None))
        need(len(wire(result).encode())<=MAX_PUBLIC,'DAILY_PUBLIC_SIZE_LIMIT');return result

def seal(raw,*,generation,previous,key=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    need(type(generation) is int and generation>=1 and (previous is None if generation==1 else type(previous) is str and re.fullmatch('[a-f0-9]{64}',previous)),'DAILY_GENERATION_INVALID')
    need(type(raw) is bytes and raw.startswith(b'SQLite format 3\0') and len(raw)<=MAX_DB,'DAILY_SNAPSHOT_INVALID')
    header=dict(schema=CHECKPOINT,repository_id='1416489937',generation=generation,previous_cipher_sha256=previous,sqlite_sha256=sha(raw))
    nonce=os.urandom(12);cipher=AESGCM(state_key('production',key)).encrypt(nonce,gzip.compress(raw,mtime=0),wire(header).encode())
    envelope=(wire(dict(header=header,nonce=base64.b64encode(nonce).decode(),ciphertext=base64.b64encode(cipher).decode()))+'\n').encode()
    head=dict(header,cipher_sha256=sha(envelope));return envelope,head

def unseal(raw,head,*,key=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        need(type(raw) is bytes and 0<len(raw)<=MAX_DB*2 and sha(raw)==head['cipher_sha256'],'DAILY_CIPHER_HASH_INVALID')
        expected={k:v for k,v in head.items() if k!='cipher_sha256'};envelope=json.loads(raw)
        need(set(expected)=={'schema','repository_id','generation','previous_cipher_sha256','sqlite_sha256'} and expected['schema']==CHECKPOINT and expected['repository_id']=='1416489937','DAILY_CIPHER_SCOPE_INVALID')
        need(envelope['header']==expected and set(envelope)=={'header','nonce','ciphertext'},'DAILY_CIPHER_SCOPE_INVALID')
        nonce=base64.b64decode(envelope['nonce'],validate=True);need(len(nonce)==12,'DAILY_NONCE_INVALID')
        packed=AESGCM(state_key('production',key)).decrypt(nonce,base64.b64decode(envelope['ciphertext'],validate=True),wire(expected).encode())
        plain=inflate(packed);need(len(plain)<=MAX_DB and sha(plain)==head['sqlite_sha256'],'DAILY_PLAIN_HASH_INVALID');return plain
    except Exception:raise ValueError('DAILY_CHECKPOINT_AUTHENTICATION_FAILED') from None
