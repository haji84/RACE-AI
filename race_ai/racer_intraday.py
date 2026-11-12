"""Bounded official-result queue and encrypted-packet contents, without network I/O."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime,timedelta,date
from pathlib import Path
import base64,json,re,sqlite3
import race_ai
from .racer_daily import clock,wire,sha,need,JST
from .racer_intraday_source import result_url,parse_result,row_facts
from .official_archive_probe import official_url
from .official_k_archive import parse_archive
from .source_retry_policy import SourceWait

REFERENCE=str(Path(__file__).resolve().parents[1]/'pr64-reference/race_ai')
if REFERENCE not in race_ai.__path__:race_ai.__path__.append(REFERENCE)
from .official_day_schedule import endpoint as index_url,parse_day_schedule

STATE='RACE_AI_RACER_INTRADAY_STATE_V1'
PACKET='RACE_AI_RACER_INTRADAY_PACKET_V1'
MAX_PACKET=12*1024*1024

def base_races(base):
    out={}
    for item in base.latest().values():
        parsed=parse_archive(item['raw'],day=item['day']);groups=defaultdict(list)
        for r in parsed['rows']:groups[r['race_id']].append(r)
        for rid,rows in groups.items():out[rid]=dict(status='CONFIRMED',rows=rows,statistics_sha256=row_facts(rows,dispositions=False),source_sha256=item['sha256'])
        for rid in parsed['cancelled_races']:out[rid]=dict(status='CANCELLED',rows=[],statistics_sha256=None,source_sha256=item['sha256'])
    return out

def archive_facts(raw,receipt):
    match=re.fullmatch(r'https://www1\.mbrace\.or\.jp/od2/K/([0-9]{6})/k([0-9]{6})\.lzh',receipt['source_url'])
    need(match and sha(raw)==receipt['source_sha256'],'INTRADAY_ARCHIVE_IDENTITY_INVALID')
    day=datetime.strptime(match[2],'%y%m%d').date();need(day.strftime('%Y%m')==match[1],'INTRADAY_ARCHIVE_IDENTITY_INVALID')
    parsed=parse_archive(raw,day=day.isoformat());groups=defaultdict(list);out={}
    for row in parsed['rows']:groups[row['race_id']].append(dict(row,captured_at=receipt['captured_at'],source_url=receipt['source_url'],source_sha256=receipt['source_sha256']))
    for rid,rows in groups.items():
        if len(rows)==6 and not any(r['result_code']=='00' and r['finish'] is None for r in rows):
            out[rid]=dict(status='CONFIRMED',rows=rows,statistics_sha256=row_facts(rows,dispositions=False),source_sha256=receipt['source_sha256'])
    for rid in parsed['cancelled_races']:out[rid]=dict(status='CANCELLED',rows=[],statistics_sha256=None,source_sha256=receipt['source_sha256'])
    return out

def encode_packet(control,captures):
    raw=wire(dict(schema=PACKET,control=control,captures=list(captures.values()))).encode();need(len(raw)<=MAX_PACKET,'INTRADAY_PACKET_BOUND')
    db=sqlite3.connect(':memory:')
    try:
        db.execute('PRAGMA application_id=1380006220');db.execute('CREATE TABLE packet(body BLOB NOT NULL)');db.execute('INSERT INTO packet VALUES (?)',(raw,));db.commit();return db.serialize()
    finally:db.close()

def decode_packet(raw):
    need(type(raw) is bytes and len(raw)<=16*1024*1024 and raw.startswith(b'SQLite format 3\0'),'INTRADAY_PACKET_INVALID')
    db=sqlite3.connect(':memory:')
    try:
        db.deserialize(raw);db.execute('PRAGMA trusted_schema=OFF')
        need(db.execute('PRAGMA application_id').fetchone()==(1380006220,) and db.execute('PRAGMA integrity_check').fetchone()==('ok',),'INTRADAY_PACKET_INTEGRITY')
        need(db.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','trigger','view')").fetchall()==[('table','packet')],'INTRADAY_PACKET_SCHEMA')
        rows=db.execute('SELECT body FROM packet').fetchall();need(len(rows)==1 and len(rows[0][0])<=MAX_PACKET,'INTRADAY_PACKET_BOUND');doc=json.loads(rows[0][0])
        need(set(doc)=={'schema','control','captures'} and doc['schema']==PACKET and doc['control'].get('schema')==STATE and type(doc['captures']) is list,'INTRADAY_PACKET_SCHEMA')
        return doc
    finally:db.close()

def _capture_key(pointer):
    return pointer['packet'],pointer['capture_id'],pointer['captured_at']

class IntradayState:
    def __init__(self,control=None,*,loader=None):
        self.control=deepcopy(control) if control else dict(schema=STATE,day=None,venues=[],meetings={},races={},results={},archives={},waits={},schedule=None,conflicts={},last_checked_at=None,catalogue_at=None,material_sha256=None,archive_next=None)
        need(self.control.get('schema')==STATE,'INTRADAY_STATE_SCHEMA')
        self.loader=loader;self.new_captures={};self.cache={};self.facts_cache={};self.canonical={}
    def rollover(self,now):
        day=clock(now).astimezone(JST).date();c=self.control
        if c['day']!=day.isoformat():
            c.update(day=day.isoformat(),venues=[],meetings={},schedule=None,archive_next=None)
            c['races']={rid:q for rid,q in c['races'].items() if rid[:8]>=(day-timedelta(days=1)).strftime('%Y%m%d') and rid not in self.canonical and rid not in c['results']}
    def remember(self,kind,raw,receipt):
        ident=sha((receipt['source_url']+'\n'+receipt['source_sha256']).encode())
        pointer=dict(packet='@self',capture_id=ident,kind=kind,source_sha256=receipt['source_sha256'],source_url=receipt['source_url'],captured_at=receipt['captured_at'])
        capture=dict(id=ident,kind=kind,receipt=receipt,raw=base64.b64encode(raw).decode());self.new_captures[ident]=capture;self.cache[_capture_key(pointer)]=capture
        return pointer
    def capture(self,pointer):
        ident=pointer['capture_id'];key=_capture_key(pointer)
        if key not in self.cache:
            need(self.loader is not None,'INTRADAY_CAPTURE_LOADER_REQUIRED');self.cache[key]=self.loader(pointer)
        c=self.cache[key];r=c['receipt'];raw=base64.b64decode(c['raw'],validate=True)
        need(c['id']==ident and c['kind']==pointer['kind'] and r['source_url']==pointer['source_url'] and r['source_sha256']==pointer['source_sha256'] and r['captured_at']==pointer['captured_at'] and sha(raw)==r['source_sha256'],'INTRADAY_CAPTURE_BINDING')
        return raw,r
    def facts(self,pointer,now):
        key=_capture_key(pointer)
        if key not in self.facts_cache:
            raw,receipt=self.capture(pointer)
            self.facts_cache[key]=archive_facts(raw,receipt) if pointer['kind']=='K' else parse_result(raw,receipt,now=now)
        return self.facts_cache[key]
    def extra_rows(self,base,*,now):
        now=clock(now);start=(now.astimezone(JST).date()-timedelta(days=90)).strftime('%Y%m%d');known=base_races(base);canonical=dict(known);extra={}
        for day,p in list(self.control['archives'].items()):
            facts=self.facts(p,now)
            for rid,item in facts.items():
                if rid[:8]>=start and rid not in canonical:extra[rid]=item;canonical[rid]=item
            if day.replace('-','')<start or set(facts)<=set(known):del self.control['archives'][day]
        for rid,p in list(self.control['results'].items()):
            if rid[:8]<start:del self.control['results'][rid];continue
            if rid in canonical:
                if p.get('statistics_sha256')!=canonical[rid]['statistics_sha256']:
                    self.control['conflicts'][rid]=dict(sp_sha256=p['source_sha256'],k_sha256=canonical[rid]['source_sha256'])
                del self.control['results'][rid];continue
            item=self.facts(p,now);need(item['status'] in ('CONFIRMED','CANCELLED') and item['race_id']==rid and item['fact_sha256']==p['fact_sha256'],'INTRADAY_CAPTURE_FACTS_MISMATCH')
            extra[rid]=item
        self.control['conflicts']={rid:c for rid,c in self.control['conflicts'].items() if rid[:8]>=start}
        self.canonical=canonical
        return [r for rid,item in extra.items() for r in item['rows']]
    def metadata(self,now):
        now=clock(now);c=self.control;day=now.astimezone(JST).date().isoformat();compact=day.replace('-','')
        complete=bool(c['schedule']) and all(v in c['meetings'] for v in c['venues'])
        expected=sum(1 for rid in c['races'] if rid.startswith(compact)) if complete else None
        confirmed={rid for rid in c['results'] if rid.startswith(compact)}|{rid for rid in self.canonical if rid.startswith(compact)}
        pointers=list(c['results'].values())+list(c['archives'].values());receipts={p['capture_id']:{'url':p['source_url'],'sha256':p['source_sha256'],'captured_at':p['captured_at'],'kind':p['kind']} for p in pointers if clock(p['captured_at']).astimezone(JST).date().isoformat()>=day}
        wait=c['waits'].get('boatrace');state='SOURCE_WAIT' if wait and clock(wait['until'])>now else 'READY'
        captures=[p['captured_at'] for p in pointers if clock(p['captured_at']).astimezone(JST).date().isoformat()>=day]
        return dict(day=day,last_checked_at=c['last_checked_at'] or now.isoformat(),latest_result_at=max(captures,default=None),expected_races=expected,confirmed_races=len(confirmed),pending_races=None if expected is None else max(0,expected-len(confirmed)),schedule_complete=complete,source_state=state,revision_conflicts=len(c['conflicts']),source_receipts=list(receipts.values()))
    def advance(self,base,*,now,fetch,max_requests=12,result_targets=()):
        now=clock(now);need(type(max_requests) is int and 1<=max_requests<=36,'INTRADAY_REQUEST_BOUND');c=self.control;day=now.astimezone(JST).date();text=day.isoformat();requests=changed=0
        self.extra_rows(base,now=now)
        self.rollover(now)
        targets={}
        if result_targets:
            need(len(result_targets)<=576,'SETTLEMENT_TARGET_BOUND');c.setdefault('settlement_captures',{});c.setdefault('settlement_next',{})
            for target in result_targets:
                rid=target['race_id'];need(type(rid) is str and re.fullmatch(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',rid) and type(target['pending']) is bool,'SETTLEMENT_TARGET_IDENTITY')
                cutoff=clock(target['cutoff_at']) if target['cutoff_at'] else None
                if cutoff and cutoff.astimezone(JST).date().strftime('%Y%m%d')==rid[:8] and cutoff+timedelta(minutes=1)<=now:
                    # A cutoff is NOT a finished race. This is only the first
                    # chance to inspect official publication; pending remains pending.
                    c['settlement_next'].setdefault(rid,(cutoff+timedelta(minutes=1)).isoformat())
                    if clock(c['settlement_next'][rid])<=now:targets[rid]=target
        def waiting(key):return key in c['waits'] and clock(c['waits'][key]['until'])>now
        def get(url,host):
            nonlocal requests
            if requests>=max_requests or waiting(host) or waiting(url):return None
            requests+=1
            try:
                raw,at=fetch(url);at=clock(at);need(at<=now+timedelta(minutes=5),'INTRADAY_CAPTURE_CLOCK_INVALID')
                return raw,dict(source_url=url,captured_at=at.isoformat(),http_status=200,source_sha256=sha(raw))
            except SourceWait as exc:
                status=getattr(exc,'plan',{}).get('http_status');key=url if status==404 else host
                delay=timedelta(minutes=5 if host=='boatrace' else 60)
                until=max(clock(exc.retry_at),now+delay).isoformat() if exc.retry_at else (now+delay).isoformat() if status==404 else '9999-12-31T23:59:59+00:00'
                c['waits'][key]=dict(until=until,reason=exc.reason);return None
        def rejected(host):c['waits'][host]=dict(until=(now+timedelta(hours=6)).isoformat(),reason='SOURCE_HOLD')
        if c['schedule'] is None and (not result_targets or now.astimezone(JST).hour>=7):
            response=get(index_url(day),'boatrace')
            if response:
                raw,r=response
                try:
                    plan=parse_day_schedule(raw,day=day,source_url=r['source_url'],observed_at=r['captured_at']);c['venues']=plan['active_venues'];c['schedule']=self.remember('INDEX',raw,r)
                except ValueError:self.remember('REJECTED',raw,r);rejected('boatrace')
        if now.astimezone(JST).hour>=21 and (not c['archive_next'] or clock(c['archive_next'])<=now):
            response=get(official_url(day,'K'),'mbrace');c['archive_next']=(now+timedelta(minutes=30)).isoformat()
            if response:
                raw,r=response
                try:
                    need(len(raw)<=1024*1024,'INTRADAY_ARCHIVE_BOUND');facts=archive_facts(raw,r)
                    if not c['archives'].get(text) or c['archives'][text]['source_sha256']!=r['source_sha256']:
                        c['archives'][text]=self.remember('K',raw,r);self.facts_cache[_capture_key(c['archives'][text])]=facts;changed+=1
                except ValueError:self.remember('REJECTED',raw,r);rejected('mbrace')
            self.extra_rows(base,now=now)
        bootstrap=[f'{day:%Y%m%d}-{v}-01' for v in c['venues'] if v not in c['meetings']]
        due=[rid for rid,q in sorted(c['races'].items(),key=lambda i:(i[0] in c['results'],i[0][:8]!=day.strftime('%Y%m%d'),i[1]['next_check'],i[0])) if q['cutoff_at'] and clock(q['cutoff_at'])+timedelta(minutes=5)<=now and clock(q['next_check'])<=now and rid not in self.canonical]
        picked=set()
        result_due=sorted(targets,key=lambda rid:(not targets[rid]['pending'],rid[:8]!=day.strftime('%Y%m%d'),c['settlement_next'][rid],rid))
        fresh=sorted((rid for rid in result_due if targets[rid]['pending'] and rid.startswith(day.strftime('%Y%m%d'))),
            # Give newly closed races a bounded lead over old pending backlog.
            # Older races retain the same persisted retry queue and still get
            # capacity once the short recent window has passed.
            key=lambda rid:(now-clock(targets[rid]['cutoff_at'])>timedelta(minutes=12),
                            c['settlement_next'][rid],rid))
        old=[rid for rid in result_due if targets[rid]['pending'] and rid not in fresh]
        revisions=[rid for rid in result_due if not targets[rid]['pending']]
        new_stats=[rid for rid in due if rid not in c['results']]
        # Normal runs retain the original 12-GET cap. Only a separately
        # admitted recovery may request up to 36, retaining the SAME total
        # source budget, one GET per race, source WAIT and single writer.
        # After urgent current-day races/venue discovery, allocate half of
        # the guarded catch-up budget to the oldest authenticated saved races
        # so a busy new day does not starve yesterday's retained P0 outcomes.
        today_first=fresh+bootstrap+new_stats
        remaining=max_requests-requests
        protected=len(fresh)+len(bootstrap)
        old_quota=(4 if max_requests<=12 else max_requests//2)
        older_count=min(len(old),old_quota,max(0,remaining-protected))
        if old and older_count and remaining>=8:
            before=max(protected,remaining-older_count)
            order=(today_first[:before]+old[:older_count]+
                   today_first[before:]+old[older_count:]+
                   [rid for rid in due if rid not in new_stats]+revisions)
        else:
            order=today_first+old+[rid for rid in due if rid not in new_stats]+revisions
        for target in order:
            if requests>=max_requests or waiting('boatrace'):break
            venue=target[9:11];number=int(target[-2:])
            if target in picked:continue
            picked.add(target)
            event=date(int(target[:4]),int(target[4:6]),int(target[6:8]))
            response=get(result_url(event.isoformat(),venue,number),'boatrace')
            if not response:continue
            raw,r=response
            try:
                out=parse_result(raw,r,now=clock(r['captured_at']))
                if event==day:
                    header_changed=venue not in c['meetings']
                    for item in out['deadlines']:
                        q=c['races'].setdefault(item['race_id'],dict(cutoff_at=item['cutoff_at'],next_check=(clock(item['cutoff_at'])+timedelta(minutes=5)).isoformat() if item['cutoff_at'] else (now+timedelta(days=1)).isoformat()))
                        if q['cutoff_at']!=item['cutoff_at']:
                            header_changed=True;q['next_check']=(clock(item['cutoff_at'])+timedelta(minutes=5)).isoformat() if item['cutoff_at'] else (now+timedelta(days=1)).isoformat()
                        q['cutoff_at']=item['cutoff_at']
                    if header_changed:c['meetings'][venue]=self.remember('RESULT',raw,r)
                q=c['races'].setdefault(target,dict(cutoff_at=None,next_check=now.isoformat()));q['next_check']=(now+timedelta(minutes=30 if out['status']!='PENDING' else 5)).isoformat()
                if out['status']=='PENDING' and q['cutoff_at']:q['next_check']=max(clock(q['next_check']),clock(q['cutoff_at'])+timedelta(minutes=5)).isoformat()
                if target in targets:
                    from .boat_sp_settlement import parse_settlement,settlement_digest
                    try:
                        settlement=parse_settlement(raw,r,now=clock(r['captured_at']));fingerprint=settlement_digest(settlement);status=settlement['status']
                    except ValueError:fingerprint=sha(raw);status='UNSUPPORTED'
                    previous=c['settlement_captures'].get(target)
                    supersedes=previous and targets[target].get('after') and clock(previous['captured_at'])<clock(targets[target]['after'])
                    if not previous or previous['settlement_sha256']!=fingerprint or supersedes:
                        p=self.remember('RESULT',raw,r);p.update(settlement_sha256=fingerprint,settlement_status=status);c['settlement_captures'][target]=p
                    interval=2 if targets[target]['pending'] or status!='AVAILABLE' else 30
                    c['settlement_next'][target]=(now+timedelta(minutes=interval)).isoformat()
                    if status=='PENDING' and q['cutoff_at']:c['settlement_next'][target]=max(clock(c['settlement_next'][target]),clock(q['cutoff_at'])+timedelta(minutes=1)).isoformat()
                old=c['results'].get(target)
                if target not in self.canonical and out['status']!='PENDING' and (not old or old['fact_sha256']!=out['fact_sha256']):
                    p=self.remember('RESULT',raw,r);p.update(fact_sha256=out['fact_sha256'],statistics_sha256=out.get('statistics_sha256'));c['results'][target]=p;changed+=1
                    self.facts_cache[_capture_key(p)]=out
            except ValueError:self.remember('REJECTED',raw,r);rejected('boatrace')
        c['last_checked_at']=now.isoformat();self.extra_rows(base,now=now)
        return dict(status=self.metadata(now)['source_state'],requests=requests,new_observations=changed)

def build_catalogue(base,state,roster,*,now,base_sha):
    now=clock(now);state.rollover(now);extra=state.extra_rows(base,now=now);meta=state.metadata(now);c=state.control
    material=dict(base=base_sha,roster=sha(wire(roster).encode()),algorithm='intraday-v1',day=meta['day'],results={rid:p['fact_sha256'] for rid,p in c['results'].items()},archives={d:p['source_sha256'] for d,p in c['archives'].items()},
      expected_races=meta['expected_races'],confirmed_races=meta['confirmed_races'],schedule_complete=meta['schedule_complete'],conflicts=c['conflicts'])
    fingerprint=sha(wire(material).encode())
    if c.get('material_sha256')!=fingerprint:
        c.update(material_sha256=fingerprint,catalogue_at=now.isoformat(),catalogue_meta=deepcopy(meta));c['catalogue_meta']['last_checked_at']=now.isoformat()
    return base.catalogue(roster,as_of=c['catalogue_at'],extra_rows=extra,live=deepcopy(c['catalogue_meta']))
