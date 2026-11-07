"""艇愛 public API format boundary. No HTTP, storage, rights or truth attestation.

CSV has no registration number; requested identity is a claim until official
row reconciliation. Grades are provider-inferred. Winner method is never
propagated from another racer by guessing.
"""
import csv
import io
import math
import re
from datetime import date

from .permissioned_source_delivery import read_json_bytes
from .boat_k_day_methods import METHOD

BASE = 'https://boatrace-db.jp'
RIGHTS = BASE + '/about/data/#api'
MAX_BYTES = 8_000_000
COLUMNS = ('日付','場','R','レース','開催','グレード(推定)','艇番','コース','ST','ST記号',
           '着','結果記号','決まり手','展示','モーター','ボート','タイム')
VENUES = {name: f'{i:02d}' for i,name in enumerate(
    ('桐生','戸田','江戸川','平和島','多摩川','浜名湖','蒲郡','常滑','津','三国','びわこ','住之江',
     '尼崎','鳴門','丸亀','児島','宮島','徳山','下関','若松','芦屋','福岡','唐津','大村'),1)}
CODES = {f'{i:02d}' for i in range(1,7)} | {'','00','F','L0','L1','K0','K1','S0','S1','S2'}


def need(ok, message):
    if not ok: raise ValueError(message)


def racer_number(value):
    need(type(value) is str and re.fullmatch(r'[0-9]{4}',value), 'TEIAI_REGISTRATION_INVALID')
    return value


def race_key(day, venue, number):
    d=date.fromisoformat(day)
    need(d.isoformat()==day and type(venue) is int and venue in range(1,25)
         and type(number) is int and number in range(1,13), 'TEIAI_RACE_ID_INVALID')
    return f'{d:%Y%m%d}-{venue:02d}-{number:02d}'


def race_parts(value):
    need(type(value) is str and re.fullmatch(r'[0-9]{8}-[0-9]{2}-[0-9]{2}',value), 'TEIAI_RACE_ID_INVALID')
    d=date.fromisoformat(value[:4]+'-'+value[4:6]+'-'+value[6:8])
    need(race_key(d.isoformat(),int(value[9:11]),int(value[12:]))==value,'TEIAI_RACE_ID_INVALID')
    return d,int(value[9:11]),int(value[12:])


def _number(value, low, high, *, integer=False):
    if value is None or value=='':return None
    need(type(value) in (str,int,float) and type(value) is not bool,'TEIAI_NUMBER_INVALID')
    if integer:
        need(re.fullmatch(r'[0-9]+',str(value)) is not None,'TEIAI_INTEGER_INVALID')
    try: n=int(value) if integer else float(value)
    except (ValueError,OverflowError):raise ValueError('TEIAI_NUMBER_INVALID') from None
    need(math.isfinite(n) and low<=n<=high,'TEIAI_NUMBER_OUT_OF_RANGE')
    return n


def _raw(raw):
    need(type(raw) is bytes and 0<len(raw)<=MAX_BYTES,'TEIAI_RESPONSE_SIZE_INVALID')
    return raw


def _row(*,rid,racer,lane,course,st,st_flag,finish,code,method,exhibit,motor,boat,grade):
    need(type(code) is str and code in CODES and st_flag in ('','F','L'),'TEIAI_DISPOSITION_UNKNOWN')
    lane=_number(lane,1,6,integer=True); course=_number(course,1,6,integer=True)
    finish=_number(finish,1,6,integer=True)
    need(lane is not None,'TEIAI_FRAME_MISSING')
    need((code in {f'{i:02}' for i in range(1,7)} and finish==int(code))
         or (code not in {f'{i:02}' for i in range(1,7)} and finish is None),'TEIAI_FINISH_CODE_CONFLICT')
    raw_st=_number(st,-1 if st_flag=='F' else 0,1)
    st=raw_st if not st_flag else None
    return dict(race_id=rid,racer_id=racer_number(racer),lane=lane,course=course,st=st,
                st_status=st_flag or ('ABSENT' if code in ('K0','K1') else ('OK' if st is not None else 'MISSING')),raw_st=raw_st,finish=finish,
                result_code=code,winner_method=METHOD.get(method) if finish==1 else None,
                own_winning_method_raw=method if finish==1 else None,
                exhibition_time=_number(exhibit,1,20),motor_no=_number(motor,1,999,integer=True),
                boat_no=_number(boat,1,999,integer=True),grade=grade,grade_basis='PROVIDER_INFERRED')


def parse_history_csv(raw, *, racer_id, source_url):
    racer_number(racer_id)
    need(source_url==f'{BASE}/api/racer/{racer_id}/results/','TEIAI_HISTORY_URL_IDENTITY')
    try:
        reader=csv.DictReader(io.StringIO(_raw(raw).decode('utf-8-sig')),strict=True)
        need(tuple(reader.fieldnames or ())==COLUMNS,'TEIAI_CSV_SCHEMA_CHANGED')
        rows={};conflicts={};duplicates=0
        for count,x in enumerate(reader,1):
            need(count<=25000 and set(x)==set(COLUMNS) and all(type(v) is str for v in x.values()),'TEIAI_CSV_ROW_INVALID')
            need(x['場'] in VENUES,'TEIAI_VENUE_UNKNOWN')
            rno=_number(x['R'],1,12,integer=True)
            rid=race_key(x['日付'],int(VENUES[x['場']]),rno)
            row=_row(rid=rid,racer=racer_id,lane=x['艇番'],course=x['コース'],st=x['ST'],st_flag=x['ST記号'],
                     finish=x['着'],code=x['結果記号'],method=x['決まり手'],exhibit=x['展示'],
                     motor=x['モーター'],boat=x['ボート'],grade=x['グレード(推定)'])
            if rid in rows:
                duplicates+=1
                if rows[rid]!=row: conflicts[rid]='CONFLICTING_DUPLICATE'
            else:rows[rid]=row
        need(rows,'TEIAI_EMPTY_HISTORY')
    except (UnicodeError,csv.Error,TypeError) as exc:
        raise ValueError('TEIAI_CSV_INVALID') from exc
    return dict(rows=[rows[k] for k in sorted(rows) if k not in conflicts],duplicate_count=duplicates,
                quarantine=[dict(race_id=k,reason=v) for k,v in sorted(conflicts.items())],
                registration_independently_verified=False)


def parse_racer_json(raw, *, racer_id):
    racer_number(racer_id);x=read_json_bytes(_raw(raw))
    need(type(x) is dict and {'source','racer','stats'}<=set(x) and type(x['racer']) is dict
         and type(x['stats']) is dict and type(x['racer'].get('regno')) is int
         and str(x['racer']['regno'])==racer_id,'TEIAI_RACER_IDENTITY_OR_SCHEMA')
    return x['racer']


def parse_race_json(raw, *, race_id):
    day,venue,rno=race_parts(race_id);x=read_json_bytes(_raw(raw))
    need(type(x) is dict and {'source','race','day','entries','payouts'}<=set(x),'TEIAI_RACE_SCHEMA_CHANGED')
    r=x['race'];d=x['day'];api_id=int(f'{day:%Y%m%d}{venue:02d}{rno:02d}')
    need(type(r) is dict and type(d) is dict and r.get('race_id')==api_id
         and type(r.get('race_id')) is int and r.get('date')==day.isoformat()
         and type(r.get('pid')) is int and r['pid']==venue
         and type(r.get('rno')) is int and r['rno']==rno
         and d.get('date')==day.isoformat() and d.get('pid')==venue,'TEIAI_RACE_IDENTITY_MISMATCH')
    need(type(x['entries']) is list and 0<len(x['entries'])<=6 and type(x['payouts']) is list,'TEIAI_RACE_ENTRIES_INVALID')
    required={'race_id','regno','boat','course','st','st_flag','rank','result_code','exhibit','motor_no','boat_no'}
    rows=[]
    for e in x['entries']:
        need(type(e) is dict and required<=set(e) and e['race_id']==api_id and type(e['regno']) is int,'TEIAI_ENTRY_SCHEMA_OR_IDENTITY')
        rows.append(_row(rid=race_id,racer=str(e['regno']),lane=e['boat'],course=e['course'],st=e['st'],
                         st_flag=e['st_flag'] or '',finish=e['rank'],code=e['result_code'] or '',
                         method=r.get('kimarite'),exhibit=e['exhibit'],motor=e['motor_no'],boat=e['boat_no'],grade=d.get('grade')))
    for key in ('lane','racer_id','course'):
        values=[r[key] for r in rows if r[key] is not None]
        need(len(values)==len(set(values)),'TEIAI_DUPLICATE_ENTRY_'+key)
    payouts=[]
    for p in x['payouts']:
        need(type(p) is dict and {'race_id','bet_type','combo','amount'}<=set(p) and p['race_id']==api_id
             and type(p['bet_type']) is str and type(p['combo']) is str,'TEIAI_PAYOUT_SCHEMA')
        amount=_number(p['amount'],0,100_000_000,integer=True)
        need(amount is not None,'TEIAI_PAYOUT_MISSING')
        payouts.append(dict(bet_type=p['bet_type'],combo=p['combo'],amount=amount))
    need(len({(p['bet_type'],p['combo']) for p in payouts})==len(payouts),'TEIAI_DUPLICATE_PAYOUT')
    return dict(race_id=race_id,rows=rows,winner_method=METHOD.get(r.get('kimarite')),payouts=payouts,
                special_result=len(rows)!=6 or {r['finish'] for r in rows}!=set(range(1,7)),
                deadline=r.get('deadline'),provider_note=r.get('note'))
