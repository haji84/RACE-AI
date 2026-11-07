"""Official public result facts with explicit entry courses; no HTTP or forecasts."""
from datetime import datetime,timedelta
import hashlib,json,re,unicodedata
from urllib.parse import urlsplit,parse_qs
from .racer_daily import need,clock,wire,sha,JST

RESULT_ROOT='https://www.boatrace.jp/owsp/sp/spdata'
MAX_RESULT=256*1024

def result_url(day,venue,number):
    from datetime import date
    d=date.fromisoformat(day)
    need(d.isoformat()==day and re.fullmatch(r'0[1-9]|1[0-9]|2[0-4]',venue) and type(number) is int and 1<=number<=12,'INTRADAY_SOURCE_IDENTITY_INVALID')
    return RESULT_ROOT+f'?type=raceresult&hd={d:%Y%m%d}&jcd={venue}&rno={number}'

def identity(url):
    u=urlsplit(url);q=parse_qs(u.query,keep_blank_values=True)
    need(u.scheme=='https' and u.netloc=='www.boatrace.jp' and u.path=='/owsp/sp/spdata' and not u.fragment and
         set(q)=={'type','hd','jcd','rno'} and all(len(v)==1 for v in q.values()) and q['type']==['raceresult'],'INTRADAY_SOURCE_URL_INVALID')
    day=q['hd'][0];venue=q['jcd'][0];number=q['rno'][0]
    need(re.fullmatch('[0-9]{8}',day) and re.fullmatch(r'[1-9]|1[0-2]',number),'INTRADAY_SOURCE_URL_INVALID')
    stamp=datetime.strptime(day,'%Y%m%d').date().isoformat();result_url(stamp,venue,int(number))
    return stamp,venue,int(number)

def _integer(value,low,high):
    need(type(value) is int or type(value) is str and re.fullmatch('[0-9]+',value),'INTRADAY_SOURCE_NUMBER_INVALID')
    n=int(value);need(low<=n<=high,'INTRADAY_SOURCE_NUMBER_INVALID');return n

def _stamp(value):return unicodedata.normalize('NFKC',str(value)).strip()

def _json(raw):
    def unique(pairs):
        out={}
        for k,v in pairs:need(k not in out,'INTRADAY_SOURCE_DUPLICATE_FIELD');out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:need(False,'INTRADAY_SOURCE_NONFINITE'))

def row_facts(rows,*,dispositions=True):
    """Comparable K/SP facts; transport clocks and non-OK ST values are not form."""
    def code(r):
        if r['finish'] is not None:return str(r['finish'])
        if r['st_status']=='ABSENT':return 'ABSENT'
        if not dispositions:return 'CONFIRMED_NON_NUMERIC'
        return re.sub(r'^(F|L)[0-9]*$',r'\1',r['result_code'])
    return sha(wire(sorted([[r['race_id'],r['racer_id'],r['lane'],r['course'],r['finish'],code(r),r['st_status'],r['st'] if r['st_status']=='OK' else None] for r in rows])).encode())

def _st(token):
    token=_stamp(token)
    if token in ('','-','--','―','—','.'):return None,'MISSING'
    if token=='S':return None,'S'
    prefix=token[0] if token.startswith(('F','L')) else ''
    number=token[1:] if prefix else token
    if not number and prefix:return None,prefix
    need(re.fullmatch(r'(?:[0-2]?(?:\.[0-9]{1,3})|[0-2])',number),'INTRADAY_SOURCE_ST_INVALID')
    value=float(number);need(0<=value<=2,'INTRADAY_SOURCE_ST_INVALID')
    return (None if prefix else value),prefix or 'OK'

def parse_result(raw,receipt,*,now):
    need(type(raw) is bytes and 0<len(raw)<=MAX_RESULT and receipt.get('http_status')==200 and sha(raw)==receipt.get('source_sha256'),'INTRADAY_SOURCE_CAPTURE_INVALID')
    captured=clock(receipt['captured_at']);now=clock(now);day,venue,number=identity(receipt['source_url']);compact=day.replace('-','')
    need(captured<=now and day<=captured.astimezone(JST).date().isoformat(),'INTRADAY_SOURCE_CLOCK_INVALID')
    doc=_json(raw);head=doc.get('dataheader');holding=doc.get('holdingheader');race=doc.get('raceheader')
    need(type(head) is dict and head.get('statuscd')==0 and type(holding) is dict and type(race) is dict,'INTRADAY_SOURCE_HEADER_INVALID')
    key=head.get('datakey');need(type(key) is dict and (str(key.get('hd')),str(key.get('jcd')),_integer(key.get('rno'),1,12))==(compact,venue,number),'INTRADAY_SOURCE_BODY_IDENTITY_MISMATCH')
    need((str(holding.get('hd')),str(holding.get('jcd')),_integer(race.get('rno'),1,12))==(compact,venue,number),'INTRADAY_SOURCE_BODY_IDENTITY_MISMATCH')
    links=race.get('rlinklist');need(type(links) is list and len(links)==12,'INTRADAY_SOURCE_SCHEDULE_INCOMPLETE')
    deadlines=[];seen=set()
    for link in links:
        n=_integer(link.get('rno'),1,12);need(n not in seen,'INTRADAY_SOURCE_SCHEDULE_DUPLICATE');seen.add(n)
        value=_stamp(link.get('deadline',''));cutoff=None
        if value not in ('','-','--','中止'):
            need(re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value),'INTRADAY_SOURCE_DEADLINE_INVALID');cutoff=day+'T'+value+':00+09:00'
        deadlines.append(dict(race_id=f'{compact}-{venue}-{n:02d}',cutoff_at=cutoff,result_available=bool(_integer(link.get('resultflag'),0,1))))
    rid=f'{compact}-{venue}-{number:02d}';cutoff=next(v['cutoff_at'] for v in deadlines if v['race_id']==rid)
    out=dict(race_id=rid,status='PENDING',rows=[],deadlines=deadlines,captured_at=captured.isoformat(),source_url=receipt['source_url'],source_sha256=receipt['source_sha256'],fact_sha256=None)
    data=doc.get('maindata')
    if data is None:return out
    need(type(data) is dict and (str(data.get('hd')),str(data.get('jcd')),_integer(data.get('rno'),1,12))==(compact,venue,number),'INTRADAY_SOURCE_BODY_IDENTITY_MISMATCH')
    finishes=data.get('teiinfolist');starts=data.get('stinfolist')
    if _integer(data.get('rstop'),0,1):
        need(finishes==[] and starts==[],'INTRADAY_SOURCE_CANCELLATION_CONFLICT')
        return dict(out,status='CANCELLED',fact_sha256=sha((rid+':CANCELLED').encode()))
    if not finishes:return out
    need(cutoff is not None and captured>=clock(cutoff),'INTRADAY_SOURCE_RESULT_BEFORE_CUTOFF')
    need(type(finishes) is list and len(finishes)==6 and type(starts) is list and len(starts)==6,'INTRADAY_SOURCE_SIX_IDENTITIES_REQUIRED')
    by={};courses=set()
    for s in starts:
        lane=_integer(s.get('teino'),1,6);need(lane not in by,'INTRADAY_SOURCE_START_IDENTITY_CONFLICT')
        course=_integer(s.get('cs'),0,6);display=_integer(s.get('csdisp'),0,6)
        need(display==0 or display==course and course not in courses,'INTRADAY_SOURCE_COURSE_CONFLICT')
        if not display:course=0
        if course:courses.add(course)
        by[lane]=(course or None,*_st(s.get('st','')))
    rows=[];lanes=set();regs=set()
    for f in finishes:
        lane=_integer(f.get('teino'),1,6);reg=str(f.get('registno'));name=_stamp(f.get('racername',''));token=_stamp(f.get('chk',''))
        need(lane not in lanes and re.fullmatch('[0-9]{4}',reg) and reg not in regs and 0<len(name)<=128,'INTRADAY_SOURCE_FINISH_IDENTITY_CONFLICT');lanes.add(lane);regs.add(reg)
        if token in ('','00','0','-','--'):return out
        need(token in {'1','2','3','4','5','6','F','L','欠','転','落','沈','失','妨','不','エ'},'INTRADAY_SOURCE_FINISH_UNSUPPORTED')
        course,st,status=by[lane]
        if token=='欠':need(course is None,'INTRADAY_SOURCE_ABSENCE_CONFLICT');st=None;status='ABSENT'
        rows.append(dict(race_id=rid,racer_id=reg,name=name,lane=lane,course=course,finish=int(token) if token.isdecimal() else None,
          result_code=f'{int(token):02d}' if token.isdecimal() else token,st=st,st_status=status,
          captured_at=captured.isoformat(),source_url=receipt['source_url'],source_sha256=receipt['source_sha256']))
    return dict(out,status='CONFIRMED',rows=sorted(rows,key=lambda r:r['lane']),fact_sha256=row_facts(rows),statistics_sha256=row_facts(rows,dispositions=False))
