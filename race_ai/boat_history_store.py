"""Private append-only B/K facts; descriptive profiles, never a betting model."""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import unicodedata

from .boat_entry_observations import build_entry_history_from_archives, extract_daily_lzh
from .boat_racer_tendencies import profile_before
from .boat_k_day_methods import HEADER
from .core import _blocks, SourceError
from .teiai_official_reconciliation import parse_k_rows as parse_k

JST=timezone(timedelta(hours=9))
PARSER_REVISION=4


def wire(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def instant(value):
    stamp=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.utcoffset() is None:raise ValueError('HISTORY_AWARE_CLOCK_REQUIRED')
    return stamp.astimezone(timezone.utc)


def allocations(raw):
    """Read observed motor/boat columns, including tight 100.00 boundaries.

    Never repair statistics or reinterpret an unsupported longer identifier.
    The B/K join independently verifies day, roster and printed cutoff.
    """
    text=unicodedata.normalize('NFKC',raw.decode('cp932'))
    pattern=re.compile(r'^\s*([1-6])\s+(\d{4})(.+?)(\d{2})(\D{2})(\d{2})([AB][12])\s+'
        r'(\d+\.\d{2})\s*(\d+\.\d{2})\s*(\d+\.\d{2})\s*(\d+\.\d{2})\s+'
        r'(\d{1,2})\s*(\d{1,3}\.\d{2})\s*(\d{1,3})\s*(\d{1,3}\.\d{2})(?:\s|$)')
    result={}
    for venue,block in _blocks(text,'B'):
        race=None
        for line in block.splitlines():
            header=HEADER.match(line)
            if header:race=int(header[1]);continue
            if not re.match(r'^\s*[1-6]\s+\d{4}',line):continue
            m=pattern.match(line)
            if m is None or race is None:raise ValueError('HISTORY_B_ALLOCATION_LAYOUT_UNSUPPORTED')
            lane,reg,name,age,branch,weight,grade,national,national2,local,local2,motor,motor2,boat,boat2=m.groups()
            rates=[float(x) for x in (national,national2,local,local2,motor2,boat2)]
            if any(not 0<=x<=100 for x in rates) or rates[0]>10 or rates[2]>10 or not 1<=int(motor)<=99 or not 1<=int(boat)<=999:
                raise ValueError('HISTORY_B_ALLOCATION_OUT_OF_RANGE')
            key=(venue,race,int(lane))
            if key in result:raise ValueError('HISTORY_B_ALLOCATION_DUPLICATE')
            result[key]=dict(racer_id=reg,name=name.strip(),age=int(age),branch=branch,weight_kg=int(weight),grade=grade,motor_no=int(motor),boat_no=int(boat),
                national_win_rate=float(national),local_win_rate=float(local),motor_top2_rate=float(motor2))
    return result


def day_payload(day,b_archive,k_archive,b_source,k_source):
    history=build_entry_history_from_archives(b_archive,k_archive,day=day,b_source=b_source,k_source=k_source)
    b=extract_daily_lzh(b_archive,f'B{day:%y%m%d}.TXT')
    k=extract_daily_lzh(k_archive,f'K{day:%y%m%d}.TXT')
    details=allocations(b)
    normal={r['race_id']:r for r in history['records']}
    facts=[]
    motor_pattern=re.compile(r'^\s*\S+\s+([1-6])\s+(\d{4})\s+.+?\s+(\d{1,2})\s+(\d{1,3})\s+\d+\.\d{2}\s+[1-6]\s+(?:[FL]?0?\.\d{2}|F|L|--)(?:\s|$)')
    text=unicodedata.normalize('NFKC',k.decode('cp932'))
    available=max(instant(s['captured_at']) for s in (b_source,k_source)).isoformat()
    for venue,block in _blocks(text,'K'):
        headers=list(HEADER.finditer(block));pre=block[:headers[0].start()] if headers else ''
        for i,h in enumerate(headers):
            number=int(h[1]);rid=f'{day:%Y%m%d}-{venue:02d}-{number:02d}'
            segment=block[h.start():(headers[i+1].start() if i+1<len(headers) else len(block))]
            packet=(f'STARTK\n{venue:02d}KBGN\n'+pre+'\n'+segment+f'\n{venue:02d}KEND\n').encode('cp932')
            try:parsed=parse_k(packet,day.isoformat())
            except (SourceError,ValueError):continue
            if rid not in history['race_proofs']:raise ValueError('HISTORY_K_RACE_NOT_IN_B')
            motors={}
            for line in segment.splitlines():
                m=motor_pattern.match(line)
                if m:
                    lane,reg,motor,boat=m.groups()
                    if int(lane) in motors:raise ValueError('HISTORY_K_MOTOR_AMBIGUOUS')
                    motors[int(lane)]=(reg,int(motor),int(boat))
            for row in parsed:
                detail=details.get((venue,number,row['lane']))
                if detail is None or detail['racer_id']!=row['racer_id']:raise ValueError('HISTORY_B_K_RACER_MISMATCH')
                actual=motors.get(row['lane'])
                if actual is not None and actual[0]!=row['racer_id']:raise ValueError('HISTORY_K_MOTOR_RACER_MISMATCH')
                facts.append(dict(row,venue=f'{venue:02d}',day=day.isoformat(),cutoff_at=history['race_proofs'][rid]['cutoff_at'],
                    normal_result=rid in normal,winner_method=normal.get(rid,{}).get('winner_method'),
                    motor_no=actual[1] if actual else None,program_motor_no=detail['motor_no'],
                    grade=detail['grade'],program=detail,available_at=available,source_sha256=k_source['source_sha256']))
    expected={(rid,int(frame)) for rid,p in history['race_proofs'].items() for frame in p['frame_racer_ids']}
    if {(r['race_id'],r['lane']) for r in facts}-expected:raise ValueError('HISTORY_UNEXPECTED_START')
    observed={(r['race_id'],r['lane']) for r in facts}
    for row in facts:
        row['participation']='CONFIRMED_ABSENCE' if row['st_status']=='ABSENT' else 'CONFIRMED_START'
    # B establishes a scheduled opportunity, never proof of an actual start.
    # Missing or unreadable K membership must not pull older good races into
    # a recent window. Confirmed K absences remain separate above.
    for rid,lane in sorted(expected-observed):
        proof=history['race_proofs'][rid];venue=int(rid[9:11]);number=int(rid[-2:])
        detail=details[(venue,number,lane)]
        facts.append(dict(race_id=rid,lane=lane,racer_id=proof['frame_racer_ids'][str(lane)],
            course=None,st=None,st_status='MISSING',finish=None,race_at=None,venue=f'{venue:02d}',
            day=day.isoformat(),cutoff_at=proof['cutoff_at'],normal_result=False,winner_method=None,
            motor_no=None,program_motor_no=detail['motor_no'],grade=detail['grade'],program=detail,
            available_at=available,source_sha256=k_source['source_sha256'],participation='UNRESOLVED',
            unresolved_reason=history['excluded_races'].get(rid,'K_RESULT_UNREADABLE')))
    return dict(day=day.isoformat(),facts=facts,history=history,available_at=available,parser_revision=PARSER_REVISION)


def aggregate(rows):
    normal=[r for r in rows if r['normal_result'] and r['finish'] in range(1,7)]
    st=[r['st'] for r in rows if r['st_status']=='OK' and r['st'] is not None]
    counts=Counter(r['st_status'] for r in rows)
    unresolved=sum(r.get('participation')=='UNRESOLVED' for r in rows)
    return dict(opportunities=len(rows),starts=len(rows)-unresolved-counts['ABSENT'],
        unresolved_opportunities=unresolved,confirmed_absences=counts['ABSENT'],
        normal_starts=len(normal),wins=sum(r['finish']==1 for r in normal),
        top2=sum(r['finish']<=2 for r in normal),top3=sum(r['finish']<=3 for r in normal),
        win_rate=sum(r['finish']==1 for r in normal)/len(normal) if normal else None,
        top2_rate=sum(r['finish']<=2 for r in normal)/len(normal) if normal else None,
        top3_rate=sum(r['finish']<=3 for r in normal)/len(normal) if normal else None,
        mean_finish=sum(r['finish'] for r in normal)/len(normal) if rows and len(normal)==len(rows) else None,
        mean_st=math.fsum(st)/len(st) if st and not unresolved else None,st_stddev=statistics.pstdev(st) if st and not unresolved else None,
        st_samples=len(st),st_dispositions={k:counts[k] for k in ('OK','F','L','MISSING','ABSENT')})


class HistoryStore:
    def __init__(self,path):
        supplied=Path(path).absolute()
        if supplied.is_symlink():raise ValueError('HISTORY_PRIVATE_FILE_REQUIRED')
        self.path=supplied.parent.resolve()/supplied.name
        if not self.path.parent.is_dir() or self.path.parent.stat().st_mode&0o077:
            raise ValueError('HISTORY_PRIVATE_PARENT_REQUIRED')
        if any((p/'.git').exists() for p in self.path.parents):raise ValueError('HISTORY_MUST_STAY_OUTSIDE_GIT')
        created=not self.path.exists()
        if created:
            fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600);os.close(fd)
        elif self.path.stat().st_mode&0o077:raise ValueError('HISTORY_PRIVATE_FILE_REQUIRED')
        self.db=sqlite3.connect(self.path);self.db.row_factory=sqlite3.Row
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if not created and version!=1:
            self.db.close();raise ValueError('HISTORY_DATABASE_SCHEMA_REQUIRED_NO_RESET')
        self.db.execute('CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY,day TEXT NOT NULL,available_at TEXT NOT NULL,b_sha TEXT NOT NULL,k_sha TEXT NOT NULL,payload TEXT NOT NULL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS import_day_clock ON imports(day,available_at)')
        self.db.execute('PRAGMA user_version=1');self.db.commit();self._cache=None

    def close(self):self.db.close()

    def ingest_day(self,day,b_archive,k_archive,b_source,k_source):
        day=day if type(day) is date else date.fromisoformat(day)
        payload=day_payload(day,b_archive,k_archive,b_source,k_source)
        ident=hashlib.sha256((day.isoformat()+b_source['source_sha256']+k_source['source_sha256']+f':parser:{PARSER_REVISION}').encode()).hexdigest()
        reused=self.db.execute('SELECT 1 FROM imports WHERE id=?',(ident,)).fetchone() is not None
        if not reused:
            with self.db:self.db.execute('INSERT INTO imports VALUES (?,?,?,?,?,?)',(ident,day.isoformat(),payload['available_at'],b_source['source_sha256'],k_source['source_sha256'],wire(payload)))
            self._cache=None
        return dict(day=day.isoformat(),import_id=ident,reused=reused,normal_races=len(payload['history']['records']),
            excluded_races=len(payload['history']['excluded_races']),fact_rows=len(payload['facts']))

    def _selected(self,as_of):
        clock=instant(as_of);cache_key=clock.isoformat()
        if self._cache is not None and self._cache[0]==cache_key:return self._cache[1]
        by_day=defaultdict(list)
        for r in self.db.execute('SELECT * FROM imports WHERE available_at<? AND day<? ORDER BY day,available_at',(cache_key,clock.astimezone(JST).date().isoformat())):
            by_day[r['day']].append(r)
        result=[]
        for entries in by_day.values():
            latest=entries[-1]['available_at'];selected=[r for r in entries if r['available_at']==latest]
            if len({(r['b_sha'],r['k_sha']) for r in selected})!=1:raise ValueError('HISTORY_REVISION_CAPTURE_CONFLICT')
            interpretations=[json.loads(r['payload']) for r in selected]
            result.append(max(interpretations,key=lambda p:p.get('parser_revision',1)))
        self._cache=(cache_key,result)
        return result

    def visible_days(self,as_of):
        return deepcopy(self._selected(as_of))

    def history_rows(self,racer_ids,as_of):
        selected=set(racer_ids)
        if not selected or any(not re.fullmatch(r'[0-9]{4}',x) for x in selected):raise ValueError('HISTORY_RACER_IDS_REQUIRED')
        rows=[deepcopy(r) for d in self._selected(as_of) for r in d['facts'] if r['racer_id'] in selected and instant(r['cutoff_at'])<instant(as_of)]
        return sorted(rows,key=lambda r:(instant(r['cutoff_at']),r['race_id'],r['lane']))

    def racer_profile(self,racer_id,as_of):
        rows=self.history_rows([racer_id],as_of)
        days=self._selected(as_of)
        records=[r for d in days for r in d['history']['records'] if any(p['racer_id']==racer_id for p in r['entries'])]
        tendencies=profile_before(records,as_of=instant(as_of).isoformat(),racer_id=racer_id)
        last=rows[-1] if rows else None
        last_program=None
        if last is not None and 'program' in last:
            source=next(d['history']['source_proofs']['B'] for d in days if d['day']==last['day'])
            last_program=dict(last['program'],program_day=last['day'],source_url=source['source_url'],
                source_sha256=source['source_sha256'],captured_at=source['captured_at'])
        return dict(schema='RACE_AI_PRIVATE_RACER_HISTORY_V1',racer_id=racer_id,as_of=instant(as_of).isoformat(),
            last_program=last_program,
            **aggregate(rows),recent_10=aggregate(rows[-10:]),recent_30=aggregate(rows[-30:]),
            by_actual_course={str(c):aggregate([r for r in rows if r['course']==c]) for c in range(1,7)},
            tendencies=tendencies,source_publication_time_verified=False,
            source_days=sorted({r['day'] for r in rows}),source_window_is_complete_career=False)

    def motor_profile(self,venue,motor_no,as_of,epoch_start=None):
        if not re.fullmatch(r'0[1-9]|1[0-9]|2[0-4]',venue) or type(motor_no) is not int or not 1<=motor_no<=99:
            raise ValueError('HISTORY_MOTOR_IDENTITY_INVALID')
        start=date.fromisoformat(epoch_start).isoformat() if epoch_start is not None else None
        rows=[r for d in self._selected(as_of) for r in d['facts'] if r['venue']==venue and r['motor_no']==motor_no and (start is None or r['day']>=start)]
        return dict(schema='RACE_AI_PRIVATE_MOTOR_WINDOW_V1',venue=venue,motor_no=motor_no,
            as_of=instant(as_of).isoformat(),**aggregate(rows),motor_epoch_verified=False,
            epoch_start=start,usable_as_lifetime_motor_record=False,identity_scope='VENUE_NUMBER_OBSERVED_WINDOW',
            source_days=sorted({r['day'] for r in rows}))

    def inventory(self):
        return dict(day_revisions=self.db.execute('SELECT count(*) FROM imports').fetchone()[0],
            distinct_days=self.db.execute('SELECT count(DISTINCT day) FROM imports').fetchone()[0],
            range=list(self.db.execute('SELECT min(day),max(day) FROM imports').fetchone()))

    def source_proofs(self,as_of,days):
        wanted=set(days)
        return {d['day']:deepcopy(d['history']['source_proofs']) for d in self._selected(as_of) if d['day'] in wanted}
