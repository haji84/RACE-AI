"""Official all-racer fan book, 2014-2+ fixed BYTE layout (CP932).

No API crawl or model. Recorded age/class/rates describe this term, never the
present or an earlier forecast. Zero-course samples remain absent metrics.
"""
from datetime import date
import hashlib
from pathlib import Path
import re
import race_ai
from .teiai_history import need

REFERENCE=str(Path(__file__).resolve().parents[1]/'pr64-reference'/'race_ai')
if REFERENCE not in race_ai.__path__:race_ai.__path__.append(REFERENCE)
from .official_lzh_extract import _extract_portable
from .official_archive_probe import inspect_lzh

LAYOUT_URL='https://www.boatrace.jp/owpc/pc/extra/data/layout.html'
RECORD_BYTES=416
HEAD=(('racer_id',4),('name',16),('kana',15),('branch',4),('class',2),('era',1),('birth',6),
      ('sex',1),('age',2),('height',3),('weight',2),('blood',2),('win_rate',4),('top2',4),
      ('wins',3),('seconds',3),('starts',3),('finals',2),('victories',2),('st',3))
DISPOSITIONS=('F','L0','L1','K0','K1','S0','S1','S2')


def term_info(term):
    need(type(term) is str and re.fullmatch(r'20[0-9]{2}-[12]',term),'TERM_INVALID')
    year,half=map(int,term.split('-'))
    need((year,half)>=(2014,2),'TERM_LAYOUT_NOT_SUPPORTED')
    if half==2:start,end=date(year-1,11,1),date(year,4,30);name=f'fan{year%100:02d}04'
    else:start,end=date(year-1,5,1),date(year-1,10,31);name=f'fan{(year-1)%100:02d}10'
    return dict(term=term,period_start=start.isoformat(),period_end=end.isoformat(),
                entry_name=name+'.txt',source_url='https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu/'+name+'.lzh')


def extract_term(raw,*,term):
    info=term_info(term);inspect_lzh(raw)
    return _extract_portable(raw,info['entry_name'])


def parse_term(raw,*,term):
    info=term_info(term)
    need(type(raw) is bytes and 0<len(raw)<=8_000_000,'TERM_TEXT_SIZE_INVALID')
    result=[];seen=set()
    def num(text):
        need(re.fullmatch(r'[0-9]+',text) is not None,'TERM_NUMERIC_INVALID')
        return int(text)
    for line in raw.splitlines():
        if line==b'':continue
        need(len(line)==RECORD_BYTES,'TERM_RECORD_LENGTH_CHANGED')
        offset=0
        def take(n):
            nonlocal offset
            value=line[offset:offset+n];offset+=n
            try:return value.decode('cp932').strip()
            except UnicodeError as exc:raise ValueError('TERM_CP932_INVALID') from exc
        h={key:take(n) for key,n in HEAD}
        need(re.fullmatch(r'[0-9]{4}',h['racer_id']) and h['racer_id'] not in seen,'TERM_REGISTRATION_DUPLICATE_OR_INVALID')
        seen.add(h['racer_id'])
        need(h['name'] and h['branch'] and h['class'] in ('A1','A2','B1','B2'),'TERM_IDENTITY_OR_CLASS_INVALID')
        course=[]
        for c in range(1,7):
            n,top2,st,rank=(num(take(n)) for n in (3,4,3,3))
            need(top2<=1000 and st<=100 and rank<=600,'TERM_COURSE_VALUE_INVALID')
            course.append(dict(course=c,entry_n=n,official_top2_percent=top2/10 if n else None,
                               mean_st=st/100 if n else None,mean_start_rank=rank/100 if n else None))
        previous=[take(2) for _ in range(3)]
        previous_ability,current_ability=num(take(4)),num(take(4))
        year,half=num(take(4)),num(take(1))
        start,end=take(8),take(8);training=num(take(3))
        need(f'{year}-{half}'==term and start==info['period_start'].replace('-','')
             and end==info['period_end'].replace('-',''),'TERM_PERIOD_MISMATCH')
        for c in course:
            finishes=[num(take(3)) for _ in range(6)]
            dispositions={code:num(take(2)) for code in DISPOSITIONS}
            n=sum(finishes)
            need(n<=c['entry_n'],'TERM_COURSE_DENOMINATOR_CONFLICT')
            c.update(finish_counts=finishes,dispositions=dispositions,numeric_finishes=n,
                     win_rate_numeric=finishes[0]/n if n else None,
                     top2_rate_numeric=sum(finishes[:2])/n if n else None,
                     top3_rate_numeric=sum(finishes[:3])/n if n else None,
                     definition='numeric_finish_only_v1_not_official_entry_denominator')
        no_course={code:num(take(2)) for code in ('L0','L1','K0','K1')}
        birthplace=take(6);need(offset==RECORD_BYTES,'TERM_OFFSET_INVALID')
        base={'S':1925,'H':1988,'R':2018}.get(h['era'])
        need(base is not None and len(h['birth'])==6,'TERM_BIRTH_INVALID')
        birth=date(base+num(h['birth'][:2]),num(h['birth'][2:4]),num(h['birth'][4:])).isoformat()
        win=num(h['win_rate'])/100;top2=num(h['top2'])/10;st=num(h['st'])/100
        need(win<=10 and top2<=100 and st<=1,'TERM_RATE_INVALID')
        starts=num(h['starts'])
        no_samples={k:'NO_PRIOR_SAMPLES' for k in ('national_win_rate','national_top2_percent','mean_st')} if not starts else {}
        result.append(dict(racer_id=h['racer_id'],name=h['name'],kana=h['kana'],branch=h['branch'],
            recorded_class=h['class'],recorded_age=num(h['age']),age_basis='TERM_RECORDED_NOT_CURRENT',
            birth_date=birth,sex_code=num(h['sex']),height_cm=num(h['height']),weight_kg=num(h['weight']),
            blood_type=h['blood'],training_term=training,birthplace=birthplace,
            national_win_rate=win if starts else None,national_top2_percent=top2 if starts else None,mean_st=st if starts else None,
            wins=num(h['wins']),seconds=num(h['seconds']),starts=starts,
            finals=num(h['finals']),victories=num(h['victories']),
            previous_classes=previous,previous_ability=previous_ability/100,current_ability=current_ability/100,
            term=term,period_start=info['period_start'],period_end=info['period_end'],courses=course,
            no_course_dispositions=no_course,record_sha256=hashlib.sha256(line).hexdigest(),
            national_top3_percent=None,local_win_rate=None,local_top2_percent=None,
            missing={**no_samples,'national_top3_percent':'NOT_PROVIDED','local_win_rate':'NOT_PROVIDED','local_top2_percent':'NOT_PROVIDED'},
            publication_at=None,formal_backtest_eligible=False))
    need(result and len(result)<=10000,'TERM_EMPTY_OR_TOO_MANY_RACERS')
    return result
