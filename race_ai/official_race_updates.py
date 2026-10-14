"""Offline official preview/market/result observations, with distinct phases.

Source publication time is unknown. Availability begins at actual capture;
historical HTML fetched after the race cannot become pre-race evidence.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from html import escape
import itertools
import re
from urllib.parse import urlsplit, parse_qs, urljoin

from .core import SourceError
from .official_racelist_adapter import Tree, Node, one, identity, HOST, JST, MAX_BYTES
from .venue_detail_join import canonical_name
from .venue_result_reconciliation import reconcile_results
from .venue_result_bridge import parse_and_reconcile

KINDS={'beforeinfo','odds3t','raceresult'}
MISSING={'','-','--','―','—','発売なし','欠場'}
BET_TYPES={'3連単':('trifecta',3,False),'3連複':('trio',3,True),'2連単':('exacta',2,False),
           '2連複':('quinella',2,True),'拡連複':('quinella_place',2,True),'単勝':('win',1,False),'複勝':('place',1,False)}


class PendingData:
    def __init__(self,reason,racers): self.reason=reason;self.racers=racers


def endpoint(day,venue,race_no,kind):
    from .official_racelist_adapter import endpoint as race_endpoint
    if kind not in KINDS: raise SourceError('unsupported official update kind')
    return race_endpoint(day,venue,race_no).replace('/racelist?','/'+kind+'?')


def cells(row):
    return [n for n in row.children if isinstance(n,Node) and n.tag in {'td','th'}]


def number(text,*,maximum=100,minimum=0):
    text=text.strip()
    if text in MISSING: return None
    if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',text): raise SourceError('invalid official numeric field')
    value=float(text)
    if not minimum<=value<=maximum: raise SourceError('official numeric field outside bounds')
    return value


def st_value(text):
    token=text.split()[0] if text.split() else ''
    if token in MISSING: return None,'PENDING',token
    if re.fullmatch(r'0?\.[0-9]{2}',token): return float(token),'OK',token
    if re.fullmatch(r'[FL](?:0?\.[0-9]{2})?',token): return None,token[0],token
    raise SourceError('invalid official ST')


def table_with(frame,*labels):
    matches=[]
    for table in frame.find('table'):
        head=next(table.find('thead'),None)
        if head is not None and all(label in head.text() for label in labels): matches.append(table)
    return one(matches,'/'.join(labels)+' table')


def context(raw,kind,day,venue,race_no,source_url,captured_at):
    expected=(f'{day:%Y%m%d}',venue,race_no)
    if identity(source_url,path='/owpc/pc/race/'+kind)!=expected: raise SourceError('update URL race identity mismatch')
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BYTES: raise SourceError('update body outside bounds')
    captured=datetime.fromisoformat(captured_at.replace('Z','+00:00'))
    if captured.tzinfo is None: raise SourceError('update capture timezone absent')
    tree=Tree();tree.feed(raw.decode('utf-8'))
    base=dict(schema_version=1,race_id=f'{day:%Y%m%d}-{venue}-{race_no:02d}',kind=kind,
        source_url=source_url,source_sha256=hashlib.sha256(raw).hexdigest(),captured_at=captured.isoformat(),
        available_at=captured.isoformat(),upstream_published_at=None,eligible_pre_race=False,
        information_phase='official_result' if kind=='raceresult' else 'pre_race_observation')
    if 'データがありません。' in tree.root.text() and not list(tree.root.find('table')):
        return None,{**base,'status':'PENDING','body_identity_verified':False,'data':None,
                     'missing_reason':'OFFICIAL_PAGE_HAS_NO_DATA'}
    if tree.invalid or any(n.tag in {'table','thead','tbody','tr','td','th'} for n in tree.stack): raise SourceError('malformed update table')
    frame=one(tree.root.find(css='contentsFrame1_inner'),'race update frame')
    schedule=one((t for t in frame.find('table') if '締切予定時刻' in t.text()),'dated race schedule')
    headers=list(one(schedule.find('thead'),'race schedule header').find('th'))[1:]
    selected=[]
    if len(headers)!=12: raise SourceError('incomplete update schedule')
    for n,cell in enumerate(headers,1):
        link=one(cell.find('a'),'schedule race link')
        if identity(link.attrs.get('href',''),path='/owpc/pc/race/'+kind)!=(expected[0],venue,n) or link.text().strip()!=f'{n}R':
            raise SourceError('update body day or venue mismatch')
        if not cell.has('is-thColor2') and not cell.has('is-thColor3'): selected.append(n)
    if selected!=[race_no]: raise SourceError('update selected race mismatch')
    times=list(one(schedule.find('tbody'),'closing schedule').find('td'))
    if len(times)!=13 or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',times[race_no].text().strip()):
        raise SourceError('update closing time invalid')
    closed=f'{day.isoformat()}T{times[race_no].text().strip()}:00+09:00'
    return frame,{**base,'body_identity_verified':True,'closed_at':closed,
                  'eligible_pre_race':kind!='raceresult' and captured<datetime.fromisoformat(closed)}


def start_rows(frame,label,*,allow_empty=False):
    table=table_with(frame,label)
    rows=list(one(table.find('tbody'),'start rows').find('tr'))
    if (allow_empty and len(rows)==6 and all(cells(row) and not row.text().strip() and not list(row.find('img'))
            and not list(row.find(css='table1_boatImage1Number')) and not list(row.find(css='table1_boatImage1Time')) for row in rows)):
        return None
    result={}
    for row in rows:
        image=one((n for n in row.find('img') if re.fullmatch(r'/static_extra/pc/images/img_boat2_[1-6]\.png',n.attrs.get('src',''))),'start boat identity')
        lane=int(image.attrs['src'][-5])
        displayed=one(row.find(css='table1_boatImage1Number'),'start number').text().strip()
        if not re.fullmatch(r'[1-6]',displayed) or lane in result: raise SourceError('duplicate or invalid start boat')
        raw=one(row.find(css='table1_boatImage1Time'),'start time').text().strip()
        value,status,token=st_value(raw)
        # DOM display order is retained as evidence, never relabelled actual course.
        result[lane]=dict(st=value,st_status=status,raw_st=token,source_position_number=int(displayed))
    if set(result)!=set(range(1,7)): raise SourceError('start evidence incomplete')
    return result


def preview_data(frame):
    table=table_with(frame,'ボートレーサー','展示','チルト')
    starts=start_rows(frame,'スタート展示',allow_empty=True)
    boats=[]
    for body in table.find('tbody'):
        row=next(body.find('tr'),None);values=cells(row) if row else []
        if len(values)<6: raise SourceError('preview entry incomplete')
        lane=values[0].text().strip()
        if not re.fullmatch(r'[1-6]',lane) or not values[0].has('is-boatColor'+lane): raise SourceError('preview lane mismatch')
        profile=one(values[2].find('a'),'preview racer profile')
        u=urlsplit(urljoin('https://'+HOST,profile.attrs.get('href','')));q=parse_qs(u.query)
        if (u.scheme!='https' or u.netloc!=HOST or u.path!='/owpc/pc/data/racersearch/profile'
                or set(q)!={'toban'} or len(q['toban'])!=1 or not re.fullmatch(r'[0-9]{4}',q['toban'][0])):
            raise SourceError('preview registration unverified')
        lane=int(lane);st=starts[lane] if starts is not None else dict(st=None,st_status='PENDING',raw_st='')
        boats.append(dict(lane=lane,racer_registration_id=q['toban'][0],name=profile.text().strip(),
            display_time=number(values[4].text(),minimum=0.01),tilt=number(values[5].text(),minimum=-10,maximum=10),
            preview_st=st['st'],preview_st_status=st['st_status'],preview_raw_st=st['raw_st'],
            preview_course=None,actual_course=None))
    if len(boats)!=6 or len({b['lane'] for b in boats})!=6 or len({b['racer_registration_id'] for b in boats})!=6: raise SourceError('preview identities incomplete or duplicate')
    if starts is None:
        if any(b['display_time'] is not None or b['tilt'] is not None for b in boats): raise SourceError('empty exhibition grid conflicts with published preview metrics')
        return PendingData('OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID',
            [{key:b[key] for key in ('lane','racer_registration_id','name')} for b in sorted(boats,key=lambda b:b['lane'])])
    weather=dict(air_temperature_c=None,water_temperature_c=None,wind_speed_mps=None,wave_height_cm=None,
                 wind_direction_source_code=None,weather_label=None,source_reported_local_time=None,
                 reported_at=None,freshness_status='UNKNOWN_SOURCE_TIME_HAS_NO_DATE')
    blocks=list(frame.find(css='weather1'))
    if len(blocks)>1: raise SourceError('ambiguous weather')
    if blocks:
        block=blocks[0];title=next(block.find(css='weather1_title'),None)
        match=re.search(r'([0-2][0-9]:[0-5][0-9])現在',title.text() if title else '')
        weather['source_reported_local_time']=match.group(1) if match else None
        fields={'気温':('air_temperature_c','°C',-40,60),'水温':('water_temperature_c','°C',-10,60),
                '風速':('wind_speed_mps','m',0,100),'波高':('wave_height_cm','cm',0,1000)}
        for unit in block.find(css='weather1_bodyUnit'):
            name=next(unit.find(css='weather1_bodyUnitLabelTitle'),None)
            value=next(unit.find(css='weather1_bodyUnitLabelData'),None)
            label=name.text().strip() if name else ''
            if label in fields and value:
                key,suffix,low,high=fields[label];raw=value.text().strip()
                weather[key]=number(raw[:-len(suffix)] if raw.endswith(suffix) else raw,minimum=low,maximum=high)
            if unit.has('is-weather'): weather['weather_label']=label or None
            if unit.has('is-windDirection'):
                classes=' '.join(n.attrs.get('class','') for n in unit.find())
                code=re.search(r'\bis-wind([0-9]{1,2})\b',classes)
                weather['wind_direction_source_code']=int(code.group(1)) if code else None
    return dict(boats=sorted(boats,key=lambda b:b['lane']),weather=weather)


def expanded_rows(table,width):
    carry={};output=[]
    for body in table.find('tbody'):
        for row in body.find('tr'):
            current={col:item[0] for col,item in carry.items()}
            following={col:(node,left-1) for col,(node,left) in carry.items() if left>1}
            col=0
            for cell in cells(row):
                while col in current: col+=1
                span=int(cell.attrs.get('colspan','1'));rows=int(cell.attrs.get('rowspan','1'))
                if not 1<=span<=width or not 1<=rows<=20: raise SourceError('invalid source table span')
                for offset in range(span):
                    if col+offset in current or col+offset>=width: raise SourceError('source table overlap')
                    current[col+offset]=cell
                    if rows>1: following[col+offset]=(cell,rows-1)
                col+=span
            if set(current)!=set(range(width)): raise SourceError('source table grid incomplete')
            output.append([current[n] for n in range(width)]);carry=following
        if carry: raise SourceError('source table rowspan exceeds body')
    return output


def odds_data(frame):
    table=one((t for t in frame.find('table') if list(t.find(css='oddsPoint'))),'trifecta odds table')
    head=list(one(table.find('thead'),'odds racers').find('th'))
    if len(head)!=12: raise SourceError('odds racer columns incomplete')
    for lane in range(1,7):
        if head[2*(lane-1)].text().strip()!=str(lane) or not head[2*(lane-1)].has('is-boatColor'+str(lane)) or not head[2*lane-1].text().strip():
            raise SourceError('odds racer header identity mismatch')
    rows=expanded_rows(table,18)
    if len(rows)!=20: raise SourceError('all120 trifecta slots required')
    odds={};zero_slots=0;ordinary_missing=0
    for row in rows:
        for first in range(1,7):
            second,third,value=row[(first-1)*3:first*3]
            a,b=second.text().strip(),third.text().strip()
            if not re.fullmatch(r'[1-6]',a) or not re.fullmatch(r'[1-6]',b) or len({first,int(a),int(b)})!=3 or not value.has('oddsPoint'):
                raise SourceError('invalid odds combination identity')
            key=(first,int(a),int(b));text=value.text().strip()
            if key in odds: raise SourceError('duplicate odds combination')
            if text=='0.0': price=None;zero_slots+=1
            elif text in MISSING: price=None;ordinary_missing+=1
            else:
                if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?',text) or not Decimal(1)<=Decimal(text)<=Decimal(1000000): raise SourceError('invalid official odds')
                price=format(Decimal(text),'f')
            odds[key]=dict(combination=list(key),odds=price,availability='PENDING' if price is None else 'AVAILABLE')
            if text=='0.0': odds[key]['missing_reason']='SOURCE_ZERO_PLACEHOLDER'
    if set(odds)!=set(itertools.permutations(range(1,7),3)): raise SourceError('odds coverage incomplete')
    legacy_labels=list(frame.find(css='tab4_time'))
    if zero_slots and legacy_labels: raise SourceError('unsupported zero odds under normal or final label')
    if not legacy_labels:
        update=one((p for p in frame.find('p') if 'オッズ更新時間' in p.text()),'odds placeholder update clock')
        if not re.fullmatch(r'\s*オッズ更新時間\s+(?:[01]?[0-9]|2[0-3]):[0-5][0-9]\s*',update.text()): raise SourceError('odds placeholder clock invalid')
        if ordinary_missing: raise SourceError('unsupported missing slot in current odds profile')
        label=update.text().strip()
    else:
        label=one(legacy_labels,'odds observation label').text().strip()
    if zero_slots==120:
        return PendingData('OFFICIAL_ODDS_ALL_ZERO_PLACEHOLDER',
            [dict(lane=n,name=head[2*n-1].text().strip(),racer_registration_id=None) for n in range(1,7)])
    racers=[dict(lane=n,name=head[2*n-1].text().strip(),racer_registration_id=None,
                 registration_status='NOT_PUBLISHED_IN_ODDS_TABLE') for n in range(1,7)]
    return dict(odds=[odds[key] for key in sorted(odds)],racers=racers,odds_phase='final' if '締切時オッズ' in label else 'observed',
                source_reported_time_label=label)


def result_data(frame,base):
    table=table_with(frame,'着','枠','ボートレーサー','レースタイム')
    starts=start_rows(frame,'スタート情報');results=[]
    for row in (row for body in table.find('tbody') for row in body.find('tr')):
        values=cells(row)
        if len(values)!=4: raise SourceError('finish row incomplete')
        finish,lane=values[0].text().strip(),values[1].text().strip()
        racer=re.fullmatch(r'\s*([0-9]{4})(?!\d)\s*(.+?)\s*',values[2].text())
        if not re.fullmatch(r'[1-6]',lane) or not values[1].has('is-boatColor'+lane) or not racer: raise SourceError('finish identity unverified')
        if finish not in {'1','2','3','4','5','6','欠','転','落','沈','失','妨','不','F','L'}: raise SourceError('unsupported finish disposition')
        lane=int(lane);st=starts[lane]
        results.append(dict(race_id=base['race_id'],lane=lane,racer_registration_id=racer.group(1),name=racer.group(2).strip(),
            finish=int(finish) if finish.isdecimal() else None,finish_status='FINISHED' if finish.isdecimal() else finish,
            actual_st=st['st'],actual_st_status=st['st_status'],actual_raw_st=st['raw_st'],actual_course=None,
            verified_official=True,source_url=base['source_url'],captured_at=base['captured_at']))
    if len(results)!=6 or len({r['lane'] for r in results})!=6 or len({r['racer_registration_id'] for r in results})!=6: raise SourceError('six unique results required')
    payouts=[];specials=[];seen=set();available_markets=set()
    payout_table=table_with(frame,'勝式','組番','払戻金')
    for row in expanded_rows(payout_table,4):
        label,combination,amount,_=(cell.text().strip() for cell in row)
        if label not in BET_TYPES: raise SourceError('unsupported official payout type')
        available_markets.add(BET_TYPES[label][0])
        if not combination and not amount: continue
        kind,size,unordered=BET_TYPES[label]
        text=re.sub(r'[¥￥,円\s]','',amount)
        if not re.fullmatch(r'[0-9]+',text) or not 1<=int(text)<=9007199254740991: raise SourceError('explicit official payout required')
        if '特払い' in combination:
            specials.append(dict(bet_type=kind,payout_per_100_yen=int(text)));continue
        values=[int(v) for v in re.findall(r'[1-6]',combination)]
        if len(values)!=size or len(set(values))!=size or re.sub(r'[1-6\s=\-]','',combination): raise SourceError('invalid official payout combination')
        if unordered: values.sort()
        key=(kind,tuple(values))
        if key in seen: raise SourceError('duplicate official payout')
        seen.add(key);payouts.append(dict(bet_type=kind,combination=values,payout_per_100_yen=int(text)))
    if not payouts and not specials: raise SourceError('final result lacks explicit payouts')
    returns=table_with(frame,'返還');refunded=[]
    for n in returns.find(css='numberSet1_number'):
        text=n.text().strip()
        if not re.fullmatch(r'[1-6]',text) or int(text) in refunded: raise SourceError('invalid returned boat evidence')
        refunded.append(int(text))
    statuses=[r['finish'] for r in results if r['finish'] is not None]
    status='special' if specials else ('dead_heat' if len(statuses)!=len(set(statuses)) else 'settled')
    top3=[next(r['lane'] for r in results if r['finish']==n) for n in range(1,4)] if status=='settled' and all(statuses.count(n)==1 for n in range(1,4)) else None
    verified_markets=set()
    coverage={kind:'INCOMPLETE' for kind in available_markets}
    special_types=[p['bet_type'] for p in specials]
    if len(special_types)!=len(set(special_types)) or any(p['bet_type'] in special_types for p in payouts):
        raise SourceError('conflicting or duplicate special payout')
    if status=='dead_heat':
        coverage={kind:'TIE_COVERAGE_NOT_VERIFIED' for kind in available_markets}
    else:
        for kind in special_types:
            verified_markets.add(kind);coverage[kind]='VERIFIED_EXPLICIT_SPECIAL_PAYOUT'
        if top3 is not None:
            a,b,c=top3
            expected={'trifecta':{(a,b,c)},'trio':{tuple(sorted((a,b,c)))},'exacta':{(a,b)},
                'quinella':{tuple(sorted((a,b)))},'win':{(a,)},'place':{(a,),(b,)},
                'quinella_place':{tuple(sorted(pair)) for pair in ((a,b),(a,c),(b,c))}}
            for kind in available_markets-set(special_types):
                observed={tuple(p['combination']) for p in payouts if p['bet_type']==kind}
                if observed==expected[kind]: verified_markets.add(kind);coverage[kind]='VERIFIED'
    all_markets={definition[0] for definition in BET_TYPES.values()}
    complete=verified_markets==all_markets and not refunded
    return dict(status=status,confirmed=complete,finish_confirmed=True,results=sorted(results,key=lambda r:r['lane']),payouts=payouts,
        top3=top3,
        available_market_types=sorted(available_markets),verified_market_types=sorted(verified_markets),
        winning_coverage_status=coverage,
        special_payouts=specials,refund_boats=sorted(refunded),refunds=None if refunded else [],
        settlement_ready=complete,refund_policy_status='REQUIRES_BET_SPECIFIC_REFUND_RULES' if refunded else 'NO_RETURNED_BOATS',
        actual_course_status='UNKNOWN_REQUIRES_VERIFIED_COURSE_EVIDENCE')


def parse_update(raw,*,kind,day,venue,race_no,source_url,captured_at,entries=None):
    if kind not in KINDS: raise SourceError('unsupported update kind')
    try:
        frame,base=context(raw,kind,day,venue,race_no,source_url,captured_at)
        if frame is None: return base
        if kind=='beforeinfo':
            data=preview_data(frame)
            if isinstance(data,PendingData):
                return pending_record(base,data,entries)
            present=sum(b['display_time'] is not None or b['preview_st'] is not None for b in data['boats'])
            status='AVAILABLE' if present==6 else ('PARTIAL' if present else 'PENDING')
        elif kind=='odds3t':
            data=odds_data(frame)
            if isinstance(data,PendingData):
                return pending_record(base,data,entries)
            check_observed_program(data['racers'],entries)
            present=sum(row['odds'] is not None for row in data['odds'])
            status='AVAILABLE' if present==120 else ('PARTIAL' if present else 'PENDING')
            if data['odds_phase']=='final': base.update(eligible_pre_race=False,information_phase='final_market')
        else:
            messages=list(frame.find(css='heading1_mainLabel'))
            text=' '.join(message.text().strip() for message in messages)
            cancellation=next((status for marker,status in (('レース中止','cancelled'),('不成立','no_contest'),('レース延期','postponed')) if marker in text),None)
            if cancellation=='postponed' and '全額返還' not in text:
                return {**base,'status':'PENDING','data':dict(status='postponed',confirmed=False,
                    settlement_ready=False,payouts=[],refunds=None,refund_boats=[],special_payouts=[],results=[],
                    available_market_types=[],verified_market_types=[],refund_policy_status='REFUND_DISPOSITION_NOT_CONFIRMED')}
            if cancellation:
                return {**base,'status':'AVAILABLE','data':dict(status=cancellation,confirmed=True,
                    results=[],payouts=[],refunds=[],refund_boats=[],special_payouts=[],settlement_ready=True,
                    available_market_types=sorted(definition[0] for definition in BET_TYPES.values()),
                    verified_market_types=sorted(definition[0] for definition in BET_TYPES.values()),finish_confirmed=False,
                    refund_policy_status='EXPLICIT_FULL_RACE_REFUND',top3=None)}
            if any(marker in frame.text() for marker in ('結果はまだありません。','レース結果はありません。','データがありません。')):
                return {**base,'status':'PENDING','data':None,'missing_reason':'OFFICIAL_RESULT_NOT_PUBLISHED'}
            data=result_data(frame,base);status='AVAILABLE'
            if datetime.fromisoformat(base['captured_at'])<datetime.fromisoformat(base['closed_at']): raise SourceError('normal results observed before scheduled closing')
            if entries is not None:
                # Reuse the existing venue bridge's verified column contract
                # where it applies. The canonical table is only an in-memory
                # projection of already identified source cells, not a source
                # original or newly attributed upstream document.
                legacy_statuses={'FINISHED','欠','転','落','沈','失','妨','不'}
                if venue=='18' and all(r['finish_status'] in legacy_statuses for r in data['results']):
                    canonical='<table>'+''.join('<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in
                        (r['finish'] if r['finish'] is not None else r['finish_status'],r['lane'],r['racer_registration_id'],r['name'],r['actual_raw_st'] or '--'))+'</tr>' for r in data['results'])+'</table>'
                    joined=parse_and_reconcile(canonical,source_url=source_url,day=day,race_no=race_no,
                        column_map={'finish':0,'lane':1,'registration':2,'name':3,'st':4},table_index=0,
                        entries=entries,captured_at=captured_at,independently_verified=True)
                else:
                    joined=reconcile_results(entries,data['results'],day=day,venue=venue)
                data['entry_reconciliation']=joined['status']
        if entries is not None and kind=='beforeinfo':
            known={r['lane']:r['racer_registration_id'] for r in entries}
            if known!={b['lane']:b['racer_registration_id'] for b in data['boats']}: raise SourceError('preview and program racer identities conflict')
        return {**base,'status':status,'data':data}
    except (ValueError,UnicodeError,TypeError,AttributeError,KeyError,InvalidOperation) as exc:
        if isinstance(exc,SourceError): raise
        raise SourceError('official race update malformed') from exc


def pending_record(base,data,entries):
    check_observed_program(data.racers,entries)
    return {**base,'status':'PENDING','data':None,'missing_reason':data.reason,'observed_racers':data.racers}


def check_observed_program(racers,entries):
    if entries is not None:
        known={r['lane']:r for r in entries}
        if len(entries)!=6 or set(known)!=set(range(1,7)): raise SourceError('pending observation program identities incomplete')
        for racer in racers:
            program=known[racer['lane']]
            if racer['racer_registration_id'] is not None and racer['racer_registration_id']!=program['racer_registration_id']:
                raise SourceError('pending observation and program registration conflict')
            if 'name' not in program or canonical_name(racer['name'])!=canonical_name(program['name']):
                raise SourceError('pending observation and program name conflict')


def settlement_for_market(observation,bet_type):
    """Export only a positively verified market; absent markets never lose."""
    data=observation.get('data') if isinstance(observation,dict) else None
    if (not isinstance(observation,dict) or observation.get('kind')!='raceresult' or not isinstance(data,dict)
            or bet_type not in data.get('verified_market_types',[]) or data.get('refund_boats')
            or data.get('refunds') is None):
        raise SourceError('requested result market is not settlement-ready')
    specials=[p for p in data.get('special_payouts',[]) if p['bet_type']==bet_type]
    status='settled' if data['status']=='special' and not specials else data['status']
    return dict(race_id=observation['race_id'],status=status,confirmed=True,verified_market_types=[bet_type],
        payouts=[p for p in data['payouts'] if p['bet_type']==bet_type],refunds=data['refunds'],
        special_payouts=specials)
