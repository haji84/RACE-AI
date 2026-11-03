"""Isolate strict source parse failures by race, without repairing source values.

The pinned detail parser is reused unchanged for each original source slice.
A malformed row blocks its entire six-boat race, not all other valid races.
"""
from collections import defaultdict
import hashlib
import re
import unicodedata
from pathlib import Path
import race_ai
reference=str(Path(__file__).resolve().parents[1]/'pr64-reference/race_ai')
if reference not in race_ai.__path__:race_ai.__path__.append(reference)
from .core import SourceError,parse_b,_blocks,_decode
from .official_b_snapshot_adapter import program_details

HEADER=re.compile(r'^\s*(\d{1,2})R\s+.*?H\s*\d{3,4}m[^\r\n]*',re.M|re.I)

def normalize_races(raw,*,day,source_url,observed_at,archive_sha256):
    minimal=parse_b(raw,day.isoformat())
    rosters=defaultdict(dict)
    for row in minimal:
        group=rosters[row['race_id']]
        if row['lane'] in group or row['racer_id'] in group.values():
            raise SourceError('duplicate B participant identity')
        group[row['lane']]=row['racer_id']
    text=unicodedata.normalize('NFKC',_decode(raw))
    venues=[];blocked=[];schedule=[];seen=set()
    for venue,block in _blocks(text,'B'):
        headers=list(HEADER.finditer(block))
        if len(headers)!=12:raise SourceError('incomplete B venue schedule')
        prelude=block[:headers[0].start()];races=[]
        for index,header in enumerate(headers):
            end=headers[index+1].start() if index+1<len(headers) else len(block)
            part=block[header.start():end]
            wrapper=f'STARTB\n{venue:02d}BBGN\n'+prelude
            footer=f'\n{venue:02d}BEND\n'
            rid=f'{day:%Y%m%d}-{venue:02d}-{int(header[1]):02d}'
            if rid in seen or rid not in rosters:raise SourceError('duplicate or foreign B race')
            seen.add(rid)
            # Use the same date and cutoff checks even when an entrant row fails.
            _,closing=program_details((wrapper+header[0]+footer).encode('cp932'),day)
            if set(closing)!={rid}:raise SourceError('B cutoff identity mismatch')
            schedule.append({'race_id':rid,'cutoff_at':closing[rid]})
            try:
                details,cutoffs=program_details((wrapper+part+footer).encode('cp932'),day)
                if set(details)!={(rid,i) for i in range(1,7)}:raise SourceError('B six-boat detail mismatch')
                boats=[]
                for lane in range(1,7):
                    detail=details[(rid,lane)]
                    if detail['racer_registration_id']!=rosters[rid][lane]:raise SourceError('B registration mismatch')
                    boats.append(dict(lane=lane,name=None,average_st=None,display_time=None,preview_course=None,**{k:v for k,v in detail.items() if k!='name'}))
                    boats[-1]['name']=detail['name']
                if any(len({b[field] for b in boats})!=6 for field in ('racer_registration_id','motor_no','boat_no')):
                    raise SourceError('B duplicate allocation')
                races.append({'race_id':rid,'boats':boats,'closed_at':cutoffs[rid],'preview_available':False})
            except SourceError as exc:
                blocked.append({'race_id':rid,'cutoff_at':closing[rid],'reason':str(exc)})
        venues.append({'venue':f'{venue:02d}','races':races})
    if seen!=set(rosters):raise SourceError('B whole-day roster mismatch')
    return dict(date_jst=day.isoformat(),source_url=source_url,source_sha256=archive_sha256,
        extracted_text_sha256=hashlib.sha256(raw).hexdigest(),first_observed_at=observed_at,
        venues=venues,races=sum(len(v['races']) for v in venues),blocked_races=blocked,
        all_schedule=sorted(schedule,key=lambda x:(x['cutoff_at'],x['race_id'])),
        normalization='STRICT_UNCHANGED_PARSER_PER_ORIGINAL_RACE_SLICE_V1')
