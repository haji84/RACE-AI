"""Strict official SP trifecta observations, without network or forecast writes."""
from datetime import datetime
import html,itertools,json,re,unicodedata
from .racer_intraday_source import parse_result
from .racer_daily import need,sha,wire

def settlement_digest(observation):
    return sha(wire({k:observation.get(k) for k in ('race_id','closed_at','status','body_identity_verified','data')}).encode())

def parse_settlement(raw,receipt,*,now):
    parsed=parse_result(raw,receipt,now=now)
    deadline=next(v['cutoff_at'] for v in parsed['deadlines'] if v['race_id']==parsed['race_id'])
    out=dict(race_id=parsed['race_id'],closed_at=deadline,captured_at=receipt['captured_at'],
        source_url=receipt['source_url'],source_sha256=receipt['source_sha256'],body_identity_verified=True,
        status='PENDING',data=None,schedule_binding='SP_EXPLICIT_RACE_HEADER')
    if parsed['status']=='PENDING':return out
    doc=json.loads(raw)['maindata'];prices=doc.get('infolist3t');returned=doc.get('returnlist')
    need(type(prices) is list and type(returned) is list,'RESULT_SP_SETTLEMENT_FIELDS_REQUIRED')
    refunds=[]
    for token in returned:
        need(type(token) is str and re.fullmatch('[1-6]',token) and int(token) not in refunds,'RESULT_REFUND_INVALID');refunds.append(int(token))
    if parsed['status']=='CANCELLED':
        need(not prices and not refunds,'RESULT_CANCELLATION_CONFLICT')
        return dict(out,status='AVAILABLE',data=dict(status='cancelled',confirmed=True,finish_confirmed=False,results=[],payouts=[],refund_boats=[],refunds=[],top3=None,confirmed_scope='TRIFECTA_ONLY'))
    need(all((r['finish'] is None or r['st_status'] not in ('F','L','ABSENT')) and
             (r['st_status'] not in ('F','L') or r['result_code']==r['st_status']) and
             (r['result_code'] not in ('F','L') or r['st_status']==r['result_code'])
             for r in parsed['rows']),'RESULT_START_FINISH_CONFLICT')
    records=[dict(race_id=r['race_id'],lane=r['lane'],racer_registration_id=r['racer_id'],name=r['name'],finish=r['finish'],
        finish_status='FINISHED' if r['finish'] is not None else r['result_code'],verified_official=True) for r in parsed['rows']]
    need(all(r['lane'] in refunds for r in records if r['finish_status'] in ('F','L','欠')),'RESULT_REFUND_DISPOSITION_MISSING')
    if not prices:return out
    if len(prices)==1 and type(prices[0]) is dict and unicodedata.normalize('NFKC',html.unescape(str(prices[0].get('winno','')))).strip()=='不成立':
        amount=unicodedata.normalize('NFKC',html.unescape(str(prices[0].get('dividend',''))))
        amount=re.sub(r'[¥￥円,\s]','',amount)
        # With at most two non-refunded boats, every possible trifecta is returned.
        need(amount=='100' and len(refunds)>=4,'RESULT_TRIFECTA_VOID_PROOF_REQUIRED')
        need(all(r['finish'] is None and r['finish_status'] in ('F','L','欠') for r in records if r['lane'] in refunds),
             'RESULT_START_FINISH_CONFLICT')
        return dict(out,status='AVAILABLE',data=dict(status='no_contest',confirmed=True,finish_confirmed=True,
            confirmed_scope='TRIFECTA_ONLY',results=records,payouts=[],refund_boats=sorted(refunds),refunds=[],top3=None))
    payouts=[]
    for item in prices:
        need(type(item) is dict,'RESULT_PAYOUT_INVALID')
        combo=unicodedata.normalize('NFKC',html.unescape(str(item.get('winno','')))).strip()
        need(re.fullmatch('[1-6]-[1-6]-[1-6]',combo),'RESULT_WINNER_INVALID');numbers=list(map(int,combo.split('-')))
        need(len(set(numbers))==3,'RESULT_WINNER_INVALID')
        amount=unicodedata.normalize('NFKC',html.unescape(str(item.get('dividend',''))));money=re.sub(r'[¥￥円,\s]','',amount)
        need(re.fullmatch('[0-9]+',money) and 1<=int(money)<=9007199254740991,'RESULT_PAYOUT_INVALID')
        payouts.append(dict(bet_type='trifecta',combination=numbers,payout_per_100_yen=int(money)))
    finishes={r['lane']:r['finish'] for r in records};expected=set()
    for t in itertools.permutations(finishes,3):
        places=[finishes[n] for n in t]
        if all(type(p) is int for p in places) and places==sorted(places) and places[0]==1 and places[-1]<=3 and all(n in t for n,p in finishes.items() if p is not None and p<places[-1]):expected.add(t)
    winners={tuple(p['combination']) for p in payouts}
    need(winners and len(winners)==len(payouts) and winners==expected,'RESULT_WINNER_MISMATCH')
    need(not any(set(t).intersection(refunds) for t in winners),'RESULT_WINNER_REFUND_CONFLICT')
    numeric=[p for p in finishes.values() if p is not None]
    return dict(out,status='AVAILABLE',data=dict(status='settled',confirmed=True,finish_confirmed=True,confirmed_scope='TRIFECTA_ONLY',
        results=records,payouts=payouts,top3=payouts[0]['combination'],dead_heat=len(numeric)!=len(set(numeric)),refund_boats=sorted(refunds),refunds=None if refunds else []))
