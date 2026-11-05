"""Offline official K cross-check. Missing/mismatched rows stay quarantined.

Reuses PR64 K row parser and existing kimarite parser. Raw result bytes and
revisions belong in private storage, never in public evidence reports.
"""
from copy import deepcopy
from datetime import date
import hashlib
from pathlib import Path
import re
import unicodedata
import race_ai

from .teiai_history import need, race_parts
from .boat_k_day_methods import HEADER, method_of

_REFERENCE=str(Path(__file__).resolve().parents[1]/'pr64-reference'/'race_ai')
if _REFERENCE not in race_ai.__path__:race_ai.__path__.append(_REFERENCE)
from .core import _blocks, parse_k

FIELDS=('race_id','racer_id','lane','course','st','st_status','finish','result_code','winner_method')


def official_day(raw, *, day):
    """Extract date-verified official rows/methods and explicitly parsed payout types.

    Payout coverage is explicit; unsupported special payout tables
    remain missing, not invented. Does not authenticate caller-supplied bytes.
    """
    day=date.fromisoformat(day);text=unicodedata.normalize('NFKC',raw.decode('cp932'))
    methods={};payouts={};dispositions={}
    for venue,block in _blocks(text,'K'):
        headers=list(HEADER.finditer(block));need(headers,'OFFICIAL_K_NO_RACES')
        pre=block[:headers[0].start()]
        dates=re.findall(r'(20\d\d)\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})',pre)
        need(dates and {(int(y),int(m),int(d)) for y,m,d in dates}=={(day.year,day.month,day.day)},'OFFICIAL_K_DATE_UNVERIFIED')
        for i,h in enumerate(headers):
            rid=f'{day:%Y%m%d}-{venue:02d}-{int(h[1]):02d}'
            race_parts(rid);need(rid not in methods,'OFFICIAL_K_DUPLICATE_RACE')
            segment=block[h.start():headers[i+1].start() if i+1<len(headers) else len(block)]
            methods[rid]=method_of(segment)
            for line in segment.splitlines():
                t=line.split()
                if len(t)>=3 and re.fullmatch(r'[1-6]',t[1]) and re.fullmatch(r'[0-9]{4}',t[2]):
                    dispositions[(rid,int(t[1]))]=t[0]
            found=[]
            labels={'単勝':('win',1),'複勝':('place',1),'3連単':('trifecta',3),
                    '3連複':('trio',3),'2連単':('exacta',2),'2連複':('quinella',2),'拡連複':('wide',2)}
            active=None
            for line in segment.splitlines():
                tokens=line.split()
                if not tokens:active=None;continue
                if tokens[0] in labels:
                    active=labels[tokens.pop(0)]
                elif active is None or active[0]!='wide':
                    active=None;continue
                kind,n=active
                if kind in ('win','place'):
                    if len(tokens)%2 or not all(t.isdecimal() for t in tokens):continue
                    pairs=list(zip(tokens[::2],tokens[1::2]))
                else:
                    if len(tokens)!=4 or tokens[2]!='人気' or not tokens[3].isdecimal():continue
                    pairs=[(tokens[0],tokens[1])]
                for combo,amount in pairs:
                    if re.fullmatch(r'[1-6](?:-[1-6]){'+str(n-1)+r'}',combo) and amount.isdecimal():
                        found.append(dict(bet_type=kind,combo=combo,amount=int(amount)))
            payouts[rid]=found
    rows=parse_k(raw,day.isoformat())
    for row in rows:
        row['winner_method']=methods[row['race_id']]
        row['result_code']=dispositions.get((row['race_id'],row['lane']))
    return dict(rows=rows,payouts=payouts,source_sha256=hashlib.sha256(raw).hexdigest())


def reconcile_rows(provider, official):
    """Row rate denominator is the provider rows; missing is NOT a match.

    Method comparison is only possible where provider supplies winner method.
    Identity includes lane; registration changes therefore mismatch, never join
    to a convenient different frame. Accepted rows carry matched field names.
    """
    index={}
    for r in official:
        key=(r['race_id'],r['lane']);need(key not in index,'OFFICIAL_DUPLICATE_ROW');index[key]=r
    ties=set()
    for data in (provider,official):
        finishes={}
        for row in data:
            if row.get('finish') is not None:
                key=(row['race_id'],row['finish']);finishes[key]=finishes.get(key,0)+1
        ties|={rid for (rid,_),count in finishes.items() if count>1}
    accepted=[];quarantine=[];seen=set();missing_rows=mismatched_rows=matched_rows=compared=missing_fields=checks=abnormal=0
    for row in provider:
        key=(row['race_id'],row['lane']);need(key not in seen,'PROVIDER_DUPLICATE_ROW');seen.add(key)
        o=index.get(key);mismatch=[];missing=[];matched=[]
        fields=FIELDS if row.get('finish')==1 or row.get('winner_method') is not None else FIELDS[:-1]
        for field in fields:
            a=row.get(field);b=o.get(field) if o else None
            code=row.get('result_code')
            expected_null=(code is not None and code not in ('','00') and o is not None and code==o.get('result_code')
                           and ((field=='finish' and not code.isdecimal())
                                or (field=='st' and row.get('st_status') in ('F','L','ABSENT'))
                                or (field=='course' and code in ('K0','K1'))))
            if a is None and b is None and expected_null:
                checks+=1;matched.append(field)
            elif a is None or b is None:missing.append(field)
            else:
                checks+=1
                same=abs(a-b)<1e-9 if field=='st' else a==b
                (matched if same else mismatch).append(field)
        compared+=bool(o);missing_fields+=len(missing)
        abnormal+=row.get('finish') is None
        missing_rows+=bool(missing);mismatched_rows+=bool(mismatch)
        if mismatch or missing:
            quarantine.append(dict(race_id=row['race_id'],lane=row['lane'],mismatched_fields=mismatch,missing_fields=missing))
        else:
            matched_rows+=1;accepted.append(dict(deepcopy(row),special_result=row['race_id'] in ties))
    n=len(provider)
    return dict(provider_rows=n,compared_rows=compared,matched_rows=matched_rows,
                mismatched_rows=mismatched_rows,mismatch_rate=mismatched_rows/compared if compared else None,
                missing_rows=missing_rows,missing_rate=missing_rows/n if n else None,
                missing_fields=missing_fields,field_checks=checks,abnormal_rows=abnormal,
                duplicate_rows=0,special_result_rows=sum(r['race_id'] in ties for r in provider),accepted=accepted,quarantine=quarantine)


def reconcile_payouts(provider, official):
    """Check every requested (bet type, combination), including missing coverage."""
    index={(p['bet_type'],p['combo']):p['amount'] for p in official}
    need(len(index)==len(official),'OFFICIAL_DUPLICATE_PAYOUT')
    seen=set();matched=missing=mismatched=0
    for p in provider:
        key=(p['bet_type'],p['combo']);need(key not in seen,'PROVIDER_DUPLICATE_PAYOUT');seen.add(key)
        if key not in index:missing+=1
        elif p['amount']!=index[key]:mismatched+=1
        else:matched+=1
    return dict(requested=len(provider),matched=matched,missing=missing,mismatched=mismatched)
