"""Official K archives: duplicate member names require typed-fact consensus.

Never select a duplicate by name (lhafile returns only the last). Each bounded
member is revalidated with the existing single-file extractor, without disk
extraction. The complete original archive remains the provenance object.
"""
from datetime import date
import hashlib
import io

from .official_lzh_extract import extract_daily_lzh,MAX_UNCOMPRESSED
from .teiai_official_reconciliation import official_day
from .teiai_history import need


def parse_archive(raw,*,day):
    import lhafile
    d=date.fromisoformat(day);name=f'K{d:%y%m%d}.TXT'
    need(type(raw) is bytes and 25<=len(raw)<=16000000,'OFFICIAL_ARCHIVE_SIZE_INVALID')
    try:entries=lhafile.Lhafile(io.BytesIO(raw)).infolist()
    except Exception as exc:raise ValueError('OFFICIAL_ARCHIVE_HEADER_INVALID') from exc
    need(1<=len(entries)<=4,'OFFICIAL_ARCHIVE_MEMBER_LIMIT')
    total=0;previous=0;documents=[];hashes=[]
    for e in entries:
        need(e.filename.upper()==name and not any(x in e.filename for x in ('/','\\','..'))
             and not getattr(e,'directory',None),'OFFICIAL_ARCHIVE_MEMBER_NAME_INVALID')
        start=e.header_offset;body=e.file_offset;end=body+e.compress_size
        need(type(start) is int and previous==start and start<body<end<=len(raw), 'OFFICIAL_ARCHIVE_MEMBER_BOUNDS_INVALID')
        total+=e.file_size;need(0<e.file_size and total<=MAX_UNCOMPRESSED,'OFFICIAL_ARCHIVE_OUTPUT_LIMIT')
        text=extract_daily_lzh(raw[start:end]+b'\0',name)
        documents.append(official_day(text,day=day));hashes.append(hashlib.sha256(text).hexdigest());previous=end
    need(raw[previous:] in (b'',b'\0'),'OFFICIAL_ARCHIVE_TRAILING_BYTES')
    first=documents[0]
    for other in documents[1:]:
        need(all(first[k]==other[k] for k in ('rows','cancelled_races','unpublished_venues','unreported_venues')),
             'OFFICIAL_ARCHIVE_MEMBER_RESULT_CONFLICT')
        need(set(first['payouts'])==set(other['payouts']),'OFFICIAL_ARCHIVE_MEMBER_RACE_CONFLICT')
    conflicts=[];payouts={}
    for rid,values in first['payouts'].items():
        if all(sorted(x['payouts'][rid],key=lambda p:(p['bet_type'],p['combo']))==
               sorted(values,key=lambda p:(p['bet_type'],p['combo'])) for x in documents[1:]):payouts[rid]=values
        else:conflicts.append(rid);payouts[rid]=[]
    return dict(first,payouts=payouts,archive_sha256=hashlib.sha256(raw).hexdigest(),
                archive_member_sha256=hashes,payout_conflict_races=sorted(conflicts),
                member_consensus_fields=['rows','cancelled_races','unpublished_venues','unreported_venues','undisputed_payouts'])
