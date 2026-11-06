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
OFFICIAL_K_PARSER_REVISION=9


def _complete_document(text):
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    need(lines and lines[0]=='STARTK' and lines[-1] in ('FINALK','ENDK'),'OFFICIAL_K_DOCUMENT_NOT_CLOSED')
    current=None;blocks=0
    for line in lines[1:-1]:
        marker=re.fullmatch(r'([0-9]{1,2})K(BGN|END)',line)
        if marker:
            venue=int(marker[1])
            if marker[2]=='BGN':
                need(current is None,'OFFICIAL_K_NESTED_BLOCK');current=venue;blocks+=1
            else:
                need(current==venue,'OFFICIAL_K_BLOCK_END_MISMATCH');current=None
        else:need(current is not None and line not in ('STARTK','FINALK','ENDK'),'OFFICIAL_K_CONTENT_OUTSIDE_BLOCK')
    need(current is None and blocks>0,'OFFICIAL_K_DOCUMENT_NOT_CLOSED')


def parse_k_rows(raw,day):
    """Retain printed late-start rows outside the legacy timing grammar.

    The legacy parser's missing-row transport supplies its six-lane checks.
    Its temporary ABSENT status is immediately replaced by the original L.
    A printed course is restored; an absent course stays absent. Raw provenance
    and dispositions always come from the original bytes.
    """
    day=date.fromisoformat(day);text=unicodedata.normalize('NFKC',raw.decode('cp932'))
    venue=race=None;late={};adapted=[]
    for line in text.splitlines():
        marker=re.fullmatch(r'\s*([0-9]{1,2})K(BGN|END)\s*',line)
        if marker:
            venue=int(marker[1]) if marker[2]=='BGN' else None;race=None
        header=HEADER.match(line)
        if header:race=int(header[1])
        missing=re.fullmatch(r'\s*([FLS][012]?)\s+([1-6])\s+([0-9]{4})\s+.+?\s+[0-9]+\.[0-9]{2}\s+(?:([0-6])\s+)?([FLS](?:[0-9]+\.[0-9]{2})?)\s+(?:\.\s*){2,3}',line)
        if missing:
            code,lane,reg,course,timing=missing.groups()
            need(code[0]==timing[0],'OFFICIAL_DISPOSITION_ST_CONFLICT')
            need(venue is not None and race is not None,'OFFICIAL_LATE_CONTEXT_MISSING')
            key=(f'{day:%Y%m%d}-{venue:02d}-{race:02d}',int(lane))
            need(key not in late,'OFFICIAL_LATE_DUPLICATE_ROW');late[key]=(reg,int(course) if course and course!='0' else None,timing,code[0])
            line=f' 欠 {lane} {reg}'
        adapted.append(line)
    rows=parse_k('\n'.join(adapted).encode('cp932') if late else raw,day.isoformat())
    for row in rows:
        # The pinned legacy parser uses midnight as a date-sort placeholder.
        # K does not provide the actual race-start timestamp. Never expose that
        # placeholder as an observed time; B's printed cutoff stays separate.
        row['race_at']=None
        key=(row['race_id'],row['lane'])
        if key in late:
            reg,course,timing,status=late[key]
            need(row['racer_id']==reg and row['course'] is None and row['st'] is None
                 and row['finish'] is None and row['st_status']=='ABSENT','OFFICIAL_LATE_BRIDGE_INVALID')
            row.update(course=course,st_status=status,st_raw=timing)
    courses={}
    for row in rows:
        if row['course'] is None:continue
        seen=courses.setdefault(row['race_id'],set())
        need(row['course'] not in seen,'OFFICIAL_DUPLICATE_ACTUAL_COURSE');seen.add(row['course'])
    return rows


def official_day(raw, *, day):
    """Extract date-verified official rows/methods and explicitly parsed payout types.

    Payout coverage is explicit; unsupported special payout tables
    remain missing, not invented. Does not authenticate caller-supplied bytes.
    """
    day=date.fromisoformat(day);text=unicodedata.normalize('NFKC',raw.decode('cp932'))
    _complete_document(text)
    methods={};payouts={};dispositions={};cancelled=[];unpublished=[];unreported=[];seen_venues=set()
    for venue,block in _blocks(text,'K'):
        need(venue in range(1,25) and venue not in seen_venues,'OFFICIAL_K_DUPLICATE_OR_INVALID_VENUE');seen_venues.add(venue)
        headers=list(HEADER.finditer(block))
        if not headers and 'データは、この場の全レース終了後に登録されます。' in block:
            lines=[line.strip() for line in block.splitlines() if line.strip()]
            need(len(lines)==2 and lines[0].startswith('ボートレース') and
                 lines[1]=='データは、この場の全レース終了後に登録されます。','OFFICIAL_PUBLICATION_PLACEHOLDER_CHANGED')
            code=f'{venue:02d}';need(code not in unpublished,'OFFICIAL_DUPLICATE_UNPUBLISHED_VENUE');unpublished.append(code)
            continue
        pre=block[:headers[0].start()] if headers else block
        dates=re.findall(r'(20\d\d)\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})',pre)
        need(dates and {(int(y),int(m),int(d)) for y,m,d in dates}=={(day.year,day.month,day.day)},'OFFICIAL_K_DATE_UNVERIFIED')
        if not headers:
            labels=[line for line in block.splitlines() if re.match(r'^\s*[0-9]{1,2}R\b',line)]
            need(labels and not re.search(r'^\s*\S+\s+[1-6]\s+[0-9]{4}\s',block,re.M),'OFFICIAL_K_NO_RACES')
            if '[払戻金]' in block and len(labels)==12 and all(re.fullmatch(r'\s*'+str(n)+r'R\s*',line) for n,line in enumerate(labels,1)):
                unreported.append(f'{venue:02d}');continue
            for line in labels:
                match=re.fullmatch(r'\s*([0-9]{1,2})R\s+中\s*止\s*',line)
                need(match is not None,'OFFICIAL_K_CANCELLATION_UNVERIFIED')
                rid=f'{day:%Y%m%d}-{venue:02d}-{int(match[1]):02d}';race_parts(rid)
                need(rid not in cancelled,'OFFICIAL_K_DUPLICATE_CANCELLATION');cancelled.append(rid)
            continue
        for i,h in enumerate(headers):
            rid=f'{day:%Y%m%d}-{venue:02d}-{int(h[1]):02d}'
            race_parts(rid);need(rid not in methods,'OFFICIAL_K_DUPLICATE_RACE')
            segment=block[h.start():headers[i+1].start() if i+1<len(headers) else len(block)]
            methods[rid]=method_of(segment)
            for line in segment.splitlines():
                t=line.split()
                if (len(t)>=3 and re.fullmatch(r'(?:[0-9]{2}|[FKLS][012]?|欠|欠場|失|転|落|沈|妨|エ|不|不完)',t[0])
                        and re.fullmatch(r'[1-6]',t[1]) and re.fullmatch(r'[0-9]{4}',t[2])):
                    key=(rid,int(t[1]));need(key not in dispositions,'OFFICIAL_DUPLICATE_DISPOSITION')
                    dispositions[key]=(t[0],t[2])
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
    need(methods or cancelled or unpublished or unreported,'OFFICIAL_K_NO_RACES')
    rows=parse_k_rows(raw,day.isoformat()) if methods else []
    for row in rows:
        row['winner_method']=methods[row['race_id']]
        value=dispositions.get((row['race_id'],row['lane']))
        need(value is not None and value[1]==row['racer_id'] and
             (row['finish'] is None or row['finish'] in range(1,7)),'OFFICIAL_DISPOSITION_IDENTITY_OR_FINISH_INVALID')
        row['result_code']=value[0]
    return dict(rows=rows,payouts=payouts,cancelled_races=sorted(cancelled),unpublished_venues=sorted(unpublished),unreported_venues=sorted(unreported),
                parser_revision=OFFICIAL_K_PARSER_REVISION,source_sha256=hashlib.sha256(raw).hexdigest())


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
