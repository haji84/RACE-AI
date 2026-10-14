"""Strict official observation JSON contract; standard-library imports only.

Runner saved_at and cloud saved_at are different proofs. This module validates
the runner's immutable record; the cloud envelope must validate its own clock.
Offline history may be captured later than race day. Cloud callers can enable
require_same_day=True without relabelling historical observations.
"""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import hashlib
import itertools
import json
import math
import re
import unicodedata

JST=timezone(timedelta(hours=9))
KINDS={'beforeinfo','odds3t','raceresult'}
STORE_FIELDS={'snapshot_id','saved_at','storage_eligible_pre_race'}
REQUIRED={'schema_version','race_id','kind','source_url','source_sha256','captured_at',
          'available_at','upstream_published_at','eligible_pre_race','information_phase',
          'body_identity_verified','status','data'}|STORE_FIELDS
OPTIONAL={'closed_at','missing_reason','rights_review','observed_racers'}
PLACEHOLDER_KINDS={'OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID':'beforeinfo','OFFICIAL_ODDS_ALL_ZERO_PLACEHOLDER':'odds3t'}
MARKETS={'trifecta':(3,False),'trio':(3,True),'exacta':(2,False),'quinella':(2,True),
         'quinella_place':(2,True),'win':(1,False),'place':(1,False)}
ALL_MARKETS=set(MARKETS)
MAX_YEN=9007199254740991
MISSING={'','-','--','―','—','発売なし','欠場'}


def _require(condition,message):
    if not condition: raise ValueError(message)


def _json(value,depth=0):
    _require(depth<=40,'JSON nesting exceeds contract')
    if value is None or type(value) in (bool,int): return
    if type(value) is float:
        _require(math.isfinite(value),'nonfinite JSON number');return
    if isinstance(value,str): value.encode('utf-8');return
    if isinstance(value,list):
        _require(len(value)<=20000,'JSON array exceeds contract')
        for item in value: _json(item,depth+1)
        return
    if isinstance(value,dict):
        _require(len(value)<=1000 and all(isinstance(k,str) for k in value),'invalid JSON object')
        for key,item in value.items(): _json(key,depth+1);_json(item,depth+1)
        return
    raise ValueError('non-JSON value')


def canonical(value):
    """Stable UTF-8 JSON bytes; nonfinite and non-JSON Python values rejected."""
    _json(value)
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def _time(value):
    if isinstance(value,str):
        _require(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])',value) is not None,'invalid observation timestamp')
        value=datetime.fromisoformat(value.replace('Z','+00:00'))
    _require(isinstance(value,datetime) and value.tzinfo is not None and value.utcoffset() is not None,'timestamp needs timezone')
    return value.astimezone(timezone.utc)


def stamp(value):
    return _time(value).isoformat(timespec='microseconds')


def _text(value,maximum=250):
    _require(isinstance(value,str) and 0<len(value)<=maximum,'invalid source text')
    value.encode('utf-8')
    return value


def _name(value):
    value=re.sub(r'\s+','',unicodedata.normalize('NFKC',_text(value)))
    _require(bool(value),'empty racer name')
    return value


def _keys(value,required,optional=()):
    _require(isinstance(value,dict) and set(required)<=set(value)<=set(required)|set(optional),'unsupported object fields')


def _integer(value,low,high):
    _require(type(value) is int and low<=value<=high,'invalid integer value')


def _number(value,low,high):
    if value is None: return
    _require(type(value) in (int,float) and math.isfinite(value) and low<=value<=high,'invalid numeric value')


def _program(race):
    _require(isinstance(race,dict),'program race required')
    match=re.fullmatch(r'([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',race.get('race_id',''))
    _require(match is not None,'invalid program race identity')
    day=datetime.strptime(match[1],'%Y%m%d').date();closed=_time(race['closed_at'])
    _require(closed.astimezone(JST).date()==day,'program cutoff day mismatch')
    boats=race['boats'];_require(isinstance(boats,list) and len(boats)==6,'six program boats required')
    identities={};registrations=set()
    for boat in boats:
        _require(isinstance(boat,dict),'invalid program boat')
        lane=boat['lane'];_integer(lane,1,6)
        registration=boat['racer_registration_id']
        _require(isinstance(registration,str) and re.fullmatch(r'[0-9]{4}',registration) is not None,'invalid program registration')
        _require(lane not in identities and registration not in registrations,'duplicate program identity')
        identities[lane]=dict(lane=lane,racer_registration_id=registration,name=_name(boat['name']))
        registrations.add(registration)
    return day,closed,identities


def program_digest(race):
    """Bind race/cutoff/six identity tuples, ignoring mutable display fields."""
    try:
        _,closed,identities=_program(race)
        value=dict(race_id=race['race_id'],closed_at=stamp(closed),boats=[identities[n] for n in range(1,7)])
        return hashlib.sha256(canonical(value)).hexdigest()
    except (TypeError,KeyError,AttributeError,OverflowError) as exc:
        raise ValueError('invalid program digest input') from exc


def _endpoint(race_id,kind):
    hd,venue,number=race_id.split('-')
    return f'https://www.boatrace.jp/owpc/pc/race/{kind}?rno={int(number)}&jcd={venue}&hd={hd}'


def _metadata(record,race,now,*,summary=False,require_same_day=False):
    _json(record)
    required=REQUIRED-{'data'}|{'payload_omitted'} if summary else REQUIRED
    _keys(record,required,OPTIONAL)
    _require(type(record['schema_version']) is int and record['schema_version']==1,'unsupported observation schema')
    _require(record['race_id']==race['race_id'] and record['kind'] in KINDS,'observation and program race mismatch')
    for key in ('snapshot_id','source_sha256'):
        _require(isinstance(record[key],str) and re.fullmatch(r'[0-9a-f]{64}',record[key]) is not None,'invalid observation hash')
    if summary: _require(record['payload_omitted'] is True,'invalid observation summary')
    else:
        digest=hashlib.sha256(canonical({k:v for k,v in record.items() if k not in STORE_FIELDS})).hexdigest()
        _require(digest==record['snapshot_id'],'stored observation content hash conflict')
    day,closed,identities=_program(race);kind=record['kind']
    _require(record['source_url']==_endpoint(race['race_id'],kind),'source endpoint race mismatch')
    captured,available,saved=(_time(record[k]) for k in ('captured_at','available_at','saved_at'))
    _require(available==captured<=saved<=_time(now),'observation outside capture/save/as-of boundary')
    _require(captured.astimezone(JST).date()>=day,'observation predates race day')
    if require_same_day:
        _require(captured.astimezone(JST).date()==day and saved.astimezone(JST).date()==day,'cloud observation crosses race day')
    _require(record['upstream_published_at'] is None,'unsupported upstream publication evidence')
    _require(type(record['body_identity_verified']) is bool,'invalid body verification flag')
    _require(record['status'] in {'AVAILABLE','PARTIAL','PENDING'},'unsupported observation status')
    if 'rights_review' in record: _text(record['rights_review'],200)
    if 'missing_reason' in record:
        _require(record['missing_reason'] in {'OFFICIAL_PAGE_HAS_NO_DATA','OFFICIAL_RESULT_NOT_PUBLISHED'}|set(PLACEHOLDER_KINDS),'unsupported missing reason')
    verified=record['body_identity_verified'];data=record.get('data')
    if verified: _require(_time(record.get('closed_at'))==closed,'observation and program cutoff mismatch')
    else:
        _require(record.get('closed_at') is None and record['status']=='PENDING' and (summary or data is None),'unverified body cannot carry facts')
        _require(record.get('missing_reason')=='OFFICIAL_PAGE_HAS_NO_DATA','unverified pending reason missing')
    reason=record.get('missing_reason')
    if reason in PLACEHOLDER_KINDS:
        _require(verified and kind==PLACEHOLDER_KINDS[reason] and record['status']=='PENDING','placeholder body/kind not verified')
        _placeholder_identities(record.get('observed_racers'),identities,kind)
    else: _require('observed_racers' not in record,'unexpected placeholder identity metadata')
    final=kind=='odds3t' and (record['information_phase']=='final_market' if summary else isinstance(data,dict) and data.get('odds_phase')=='final')
    phase='official_result' if kind=='raceresult' else ('final_market' if final else 'pre_race_observation')
    _require(record['information_phase']==phase,'observation information phase conflict')
    eligible=verified and kind!='raceresult' and captured<closed and not final
    _require(type(record['eligible_pre_race']) is bool and record['eligible_pre_race']==eligible,'observation pre-race eligibility conflict')
    _require(type(record['storage_eligible_pre_race']) is bool and record['storage_eligible_pre_race']==(eligible and saved<closed),'observation actual-save eligibility conflict')
    return captured,closed,identities


def _placeholder_identities(racers,identities,kind):
    _require(isinstance(racers,list) and len(racers)==6,'placeholder needs six observed racer identities')
    seen=set()
    for racer in racers:
        _keys(racer,{'lane','racer_registration_id','name'})
        lane=racer['lane'];_integer(lane,1,6);_require(lane not in seen,'duplicate placeholder lane');seen.add(lane)
        _require(_name(racer['name'])==identities[lane]['name'],'placeholder racer name differs from program')
        expected=identities[lane]['racer_registration_id'] if kind=='beforeinfo' else None
        _require(racer['racer_registration_id']==expected,'placeholder registration evidence conflict')


def _identity_rows(rows,identities):
    _require(isinstance(rows,list) and len(rows)==6,'six observed boats required')
    seen=set()
    for row in rows:
        _require(isinstance(row,dict),'invalid observed boat')
        lane=row['lane'];_integer(lane,1,6)
        _require(lane not in seen,'duplicate observed lane');seen.add(lane)
        _require(row['racer_registration_id']==identities[lane]['racer_registration_id'] and _name(row['name'])==identities[lane]['name'],'observed racer differs from program')


def _st(value,status,raw):
    _require(isinstance(raw,str),'invalid raw ST')
    if status=='OK':
        _require(re.fullmatch(r'0?\.[0-9]{2}',raw) is not None,'invalid ST token')
        _number(value,0,.99);_require(value is not None and value==float(raw),'ST numeric/token mismatch')
    elif status in {'F','L'}:
        _require(value is None and re.fullmatch(status+r'(?:0?\.[0-9]{2})?',raw) is not None,'invalid F/L ST')
    else: _require(status=='PENDING' and value is None and raw in MISSING,'invalid missing ST')


def _preview(record,identities):
    data=record['data'];_keys(data,{'boats','weather'});_identity_rows(data['boats'],identities)
    fields={'lane','racer_registration_id','name','display_time','tilt','preview_st','preview_st_status','preview_raw_st','preview_course','actual_course'}
    for boat in data['boats']:
        _keys(boat,fields);_number(boat['display_time'],.01,100);_number(boat['tilt'],-10,10)
        _st(boat['preview_st'],boat['preview_st_status'],boat['preview_raw_st'])
        _require(boat['preview_course'] is None and boat['actual_course'] is None,'unsupported course evidence')
    weather=data['weather']
    fields={'air_temperature_c','water_temperature_c','wind_speed_mps','wave_height_cm','wind_direction_source_code','weather_label','source_reported_local_time'}
    _keys(weather,fields,{'reported_at','freshness_status'})
    for key,low,high in [('air_temperature_c',-40,60),('water_temperature_c',-10,60),('wind_speed_mps',0,100),('wave_height_cm',0,1000)]: _number(weather[key],low,high)
    if weather['wind_direction_source_code'] is not None: _integer(weather['wind_direction_source_code'],0,99)
    if weather['weather_label'] is not None: _text(weather['weather_label'],60)
    clock=weather['source_reported_local_time']
    _require(clock is None or isinstance(clock,str) and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock) is not None,'invalid source weather clock')
    _require(weather.get('reported_at') is None and weather.get('freshness_status','UNKNOWN_SOURCE_TIME_HAS_NO_DATE')=='UNKNOWN_SOURCE_TIME_HAS_NO_DATE','weather source date/freshness not established')
    present=sum(b['display_time'] is not None or b['preview_st'] is not None for b in data['boats'])
    _require(record['status']==('AVAILABLE' if present==6 else 'PARTIAL' if present else 'PENDING'),'preview availability conflict')


def _odds(record,identities):
    data=record['data'];_keys(data,{'odds','racers','odds_phase','source_reported_time_label'})
    racers=data['racers'];_require(isinstance(racers,list) and len(racers)==6,'odds source racers missing')
    seen=set()
    for racer in racers:
        _keys(racer,{'lane','name','racer_registration_id','registration_status'})
        lane=racer['lane'];_integer(lane,1,6);_require(lane not in seen,'duplicate odds source lane');seen.add(lane)
        _require(_name(racer['name'])==identities[lane]['name'],'odds racer name differs from program')
        _require(racer['racer_registration_id'] is None and racer['registration_status']=='NOT_PUBLISHED_IN_ODDS_TABLE','odds registration not published')
    _require(data['odds_phase'] in {'observed','final'},'unsupported odds phase')
    label=_text(data['source_reported_time_label'],100)
    _require(('締切時オッズ' in label)==(data['odds_phase']=='final'),'odds source label/phase conflict')
    rows=data['odds'];_require(isinstance(rows,list) and len(rows)==120,'all120 odds slots required')
    seen=set();present=0
    for row in rows:
        _keys(row,{'combination','odds','availability'});combination=row['combination']
        _require(isinstance(combination,list) and len(combination)==3,'invalid odds combination')
        for lane in combination: _integer(lane,1,6)
        key=tuple(combination);_require(len(set(key))==3 and key not in seen,'duplicate odds combination');seen.add(key)
        price=row['odds']
        if price is not None:
            _require(isinstance(price,str) and re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?',price) is not None,'invalid odds string')
            _require(Decimal(1)<=Decimal(price)<=Decimal(1000000),'odds outside bounds');present+=1
        _require(row['availability']==('PENDING' if price is None else 'AVAILABLE'),'odds availability conflict')
    _require(seen==set(itertools.permutations(range(1,7),3)),'odds identity coverage incomplete')
    _require(record['status']==('AVAILABLE' if present==120 else 'PARTIAL' if present else 'PENDING'),'market availability conflict')


def _types(value):
    _require(isinstance(value,list) and all(isinstance(v,str) and v in ALL_MARKETS for v in value) and len(set(value))==len(value),'invalid market types')
    return set(value)


def _empty_result(record):
    data=record['data'];status=data['status']
    _require(status in {'cancelled','no_contest','postponed'},'unsupported empty result disposition')
    fields={'status','confirmed','settlement_ready','payouts','refunds','refund_boats','special_payouts','results','available_market_types','verified_market_types','refund_policy_status'}
    pending=status=='postponed' and data['confirmed'] is False
    _keys(data,fields if pending else fields|{'finish_confirmed','top3'})
    for key in ('payouts','refund_boats','special_payouts','results'): _require(data[key]==[],'empty result carries unsupported facts')
    if pending:
        _require(record['status']=='PENDING' and data['settlement_ready'] is False and data['refunds'] is None and data['available_market_types']==[] and data['verified_market_types']==[] and data['refund_policy_status']=='REFUND_DISPOSITION_NOT_CONFIRMED','postponement does not prove refund')
    else:
        _require(record['status']=='AVAILABLE' and data['confirmed'] is True and data['settlement_ready'] is True and data['finish_confirmed'] is False and data['top3'] is None and data['refunds']==[] and _types(data['available_market_types'])==ALL_MARKETS and _types(data['verified_market_types'])==ALL_MARKETS and data['refund_policy_status']=='EXPLICIT_FULL_RACE_REFUND','explicit full-refund disposition required')


def _result(record,identities,captured,closed):
    data=record['data'];_require(isinstance(data,dict),'result data required')
    if not data.get('results'):
        _empty_result(record);return
    fields={'status','confirmed','finish_confirmed','results','payouts','top3','available_market_types','verified_market_types','winning_coverage_status','special_payouts','refund_boats','refunds','settlement_ready','refund_policy_status','actual_course_status'}
    _keys(data,fields,{'entry_reconciliation'});_identity_rows(data['results'],identities)
    _require(captured>=closed and record['status']=='AVAILABLE' and data['finish_confirmed'] is True,'normal results cannot precede closing')
    row_fields={'race_id','lane','racer_registration_id','name','finish','finish_status','actual_st','actual_st_status','actual_raw_st','actual_course','verified_official','source_url','captured_at'}
    finishes=[]
    for row in data['results']:
        _keys(row,row_fields)
        _require(row['race_id']==record['race_id'] and row['source_url']==record['source_url'] and _time(row['captured_at'])==captured and row['verified_official'] is True,'nested result provenance conflict')
        if row['finish_status']=='FINISHED': _integer(row['finish'],1,6);finishes.append(row['finish'])
        else: _require(row['finish'] is None and row['finish_status'] in {'欠','転','落','沈','失','妨','不','F','L'},'invalid finish disposition')
        _st(row['actual_st'],row['actual_st_status'],row['actual_raw_st']);_require(row['actual_course'] is None,'actual course unverified')
    payouts=data['payouts'];specials=data['special_payouts']
    _require(isinstance(payouts,list) and len(payouts)<=200 and isinstance(specials,list) and len(specials)<=7,'invalid payout arrays')
    observed={};special_types=set()
    for payout in payouts:
        _keys(payout,{'bet_type','combination','payout_per_100_yen'});kind=payout['bet_type']
        _require(kind in MARKETS,'unsupported payout market');size,unordered=MARKETS[kind];combo=payout['combination']
        _require(isinstance(combo,list) and len(combo)==size,'invalid payout combination')
        for lane in combo: _integer(lane,1,6)
        _require(len(set(combo))==size and (not unordered or sorted(combo)==combo),'payout combination not canonical')
        key=tuple(combo);_require(key not in observed.get(kind,set()),'duplicate payout');observed.setdefault(kind,set()).add(key)
        _integer(payout['payout_per_100_yen'],1,MAX_YEN)
    for payout in specials:
        _keys(payout,{'bet_type','payout_per_100_yen'});kind=payout['bet_type']
        _require(kind in MARKETS and kind not in special_types and kind not in observed,'conflicting special payout')
        _integer(payout['payout_per_100_yen'],1,MAX_YEN);special_types.add(kind)
    _require(bool(payouts or specials),'explicit payouts required')
    available=_types(data['available_market_types']);verified=_types(data['verified_market_types'])
    _require(set(observed)|special_types<=available,'payout market omitted from availability')
    status='special' if specials else 'dead_heat' if len(finishes)!=len(set(finishes)) else 'settled'
    _require(data['status']==status,'result status conflict')
    top3=[next(r['lane'] for r in data['results'] if r['finish']==n) for n in range(1,4)] if status=='settled' and all(finishes.count(n)==1 for n in range(1,4)) else None
    if data['top3'] is not None:
        _require(isinstance(data['top3'],list) and len(data['top3'])==3,'invalid winning triple')
        for lane in data['top3']: _integer(lane,1,6)
    _require(data['top3']==top3,'winning order conflict')
    coverage={kind:'INCOMPLETE' for kind in available};expected_verified=set()
    if status=='dead_heat': coverage={kind:'TIE_COVERAGE_NOT_VERIFIED' for kind in available}
    else:
        for kind in special_types: expected_verified.add(kind);coverage[kind]='VERIFIED_EXPLICIT_SPECIAL_PAYOUT'
        if top3 is not None:
            a,b,c=top3
            wins={'trifecta':{(a,b,c)},'trio':{tuple(sorted((a,b,c)))},'exacta':{(a,b)},'quinella':{tuple(sorted((a,b)))},'win':{(a,)},'place':{(a,),(b,)},'quinella_place':{tuple(sorted(v)) for v in ((a,b),(a,c),(b,c))}}
            for kind in available-special_types:
                if observed.get(kind,set())==wins[kind]: expected_verified.add(kind);coverage[kind]='VERIFIED'
    _require(verified==expected_verified and data['winning_coverage_status']==coverage,'market winning coverage not verified')
    returned=data['refund_boats'];_require(isinstance(returned,list) and len(returned)<=6,'invalid returned boats')
    for lane in returned: _integer(lane,1,6)
    _require(len(set(returned))==len(returned),'duplicate returned boat')
    _require(data['refunds']==(None if returned else []),'unsupported bet-specific refund mapping')
    complete=verified==ALL_MARKETS and not returned
    _require(type(data['confirmed']) is bool and data['confirmed']==complete and type(data['settlement_ready']) is bool and data['settlement_ready']==complete,'financial readiness conflict')
    _require(data['refund_policy_status']==('REQUIRES_BET_SPECIFIC_REFUND_RULES' if returned else 'NO_RETURNED_BOATS') and data['actual_course_status']=='UNKNOWN_REQUIRES_VERIFIED_COURSE_EVIDENCE','unsupported result evidence status')
    if 'entry_reconciliation' in data: _require(data['entry_reconciliation']=='RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED','unsupported entry reconciliation')


def validate_record(record,race,now,*,require_same_day=False):
    """Validate an immutable full stored record and return it without mutation."""
    try:
        captured,closed,identities=_metadata(record,race,now,require_same_day=require_same_day)
        if record['data'] is None:
            _require(record['status']=='PENDING','null body cannot carry available facts')
            if record['body_identity_verified']:
                _require((record['kind']=='raceresult' and record.get('missing_reason')=='OFFICIAL_RESULT_NOT_PUBLISHED') or record.get('missing_reason') in PLACEHOLDER_KINDS,'verified null data lacks pending evidence')
            return record
        _require(record['body_identity_verified'] and 'missing_reason' not in record,'nonverified facts or conflicting missing reason')
        if record['kind']=='beforeinfo': _preview(record,identities)
        elif record['kind']=='odds3t': _odds(record,identities)
        else: _result(record,identities,captured,closed)
        return record
    except (TypeError,KeyError,AttributeError,OverflowError) as exc:
        raise ValueError('invalid observation contract') from exc


def validate_summary(record,race,now,*,require_same_day=False):
    """Validate metadata only; a summary never proves omitted factual payload."""
    try:
        _metadata(record,race,now,summary=True,require_same_day=require_same_day)
        return record
    except (TypeError,KeyError,AttributeError,OverflowError) as exc:
        raise ValueError('invalid observation summary') from exc
