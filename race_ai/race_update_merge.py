"""Pure joins of stored official observations to an approved day program.

Default summaries include only the latest record metadata per kind. Full
immutable per-race history belongs in a separate observation bundle; global
program sources and original boat fields are never rewritten here.
"""
import copy
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import itertools
import json
import re

from .core import SourceError
from .official_observation_store import stamp
from .official_race_updates import KINDS,endpoint
from .venue_detail_join import canonical_name

STORE_FIELDS={'snapshot_id','saved_at','storage_eligible_pre_race'}


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def check_record(record,race,now,*,summary=False):
    if not isinstance(record,dict) or record.get('kind') not in KINDS or record.get('race_id')!=race['race_id']:
        raise SourceError('observation and program race mismatch')
    identifier=record.get('snapshot_id')
    if not isinstance(identifier,str) or not re.fullmatch(r'[0-9a-f]{64}',identifier): raise SourceError('stored snapshot identity missing')
    if not summary and hashlib.sha256(canonical({key:value for key,value in record.items() if key not in STORE_FIELDS})).hexdigest()!=identifier:
        raise SourceError('stored observation content hash conflict')
    hd,venue,number=race['race_id'].split('-');day=datetime.strptime(hd,'%Y%m%d').date();kind=record['kind']
    if record.get('source_url')!=endpoint(day,venue,int(number),kind) or not re.fullmatch(r'[0-9a-f]{64}',record.get('source_sha256','')):
        raise SourceError('observation source and program race mismatch')
    captured,available,saved=(stamp(record[key]) for key in ('captured_at','available_at','saved_at'))
    if not available<=captured<=saved<=stamp(now): raise SourceError('observation time exceeds merge cutoff')
    if record.get('upstream_published_at') is not None: raise SourceError('upstream publication evidence not supported by this collector')
    if captured!=available: raise SourceError('observation availability is backdated')
    cutoff=stamp(race['closed_at'])
    verified=record.get('body_identity_verified') is True
    if verified and stamp(record.get('closed_at'))!=cutoff: raise SourceError('observation and program cutoff mismatch')
    data=record.get('data')
    if not verified and (record.get('status')!='PENDING' or (not summary and data is not None)):
        raise SourceError('unverified observation body cannot carry race facts')
    phase=record.get('information_phase')
    final_market=kind=='odds3t' and (phase=='final_market' if summary else isinstance(data,dict) and data.get('odds_phase')=='final')
    expected_phase='official_result' if kind=='raceresult' else ('final_market' if final_market else 'pre_race_observation')
    if phase!=expected_phase: raise SourceError('observation information phase conflicts')
    expected=verified and kind!='raceresult' and captured<cutoff and not final_market
    if type(record.get('eligible_pre_race')) is not bool or record['eligible_pre_race']!=expected:
        raise SourceError('observation pre-race phase conflicts')
    if type(record.get('storage_eligible_pre_race')) is not bool or record['storage_eligible_pre_race']!=(expected and saved<cutoff):
        raise SourceError('observation actual-save eligibility conflicts')
    if summary:
        if record.get('payload_omitted') is not True or 'data' in record: raise SourceError('invalid observation summary')
        return
    if data is None: return
    program={b['lane']:b for b in race['boats']}
    if set(program)!=set(range(1,7)) or len(program)!=len(race['boats']): raise SourceError('complete program identities required')
    if kind in {'beforeinfo','raceresult'}:
        rows=data.get('boats' if kind=='beforeinfo' else 'results')
        if kind=='raceresult' and data.get('status') in {'cancelled','no_contest','postponed'} and not rows: return
        if not isinstance(rows,list) or len(rows)!=6 or {r.get('lane') for r in rows}!=set(program):
            raise SourceError('observation lane identities incomplete')
        if any(r.get('racer_registration_id')!=program[r['lane']]['racer_registration_id'] for r in rows):
            raise SourceError('observation and program registration mismatch')
        if kind=='beforeinfo' and any(any(key in row for key in ('actual_st','finish','payouts','result_course')) or row.get('actual_course') is not None for row in rows):
            raise SourceError('current outcome cannot enter preview data')
    else:
        racers=data.get('racers')
        if not isinstance(racers,list) or len(racers)!=6 or {r.get('lane') for r in racers}!=set(program):
            raise SourceError('odds table racer identity proof missing')
        for racer in racers:
            expected_racer=program[racer['lane']]
            # The odds table publishes lane/name, not registration. Exact names
            # bind those lanes to the approved program; no new ID is invented.
            if canonical_name(racer.get('name'))!=canonical_name(expected_racer.get('name')):
                raise SourceError('odds and program racer name mismatch')
            if racer.get('racer_registration_id') not in (None,expected_racer['racer_registration_id']):
                raise SourceError('odds and program registration conflict')
        odds=data.get('odds')
        if (not isinstance(odds,list) or len(odds)!=120 or
                {tuple(row.get('combination',[])) for row in odds}!=set(itertools.permutations(range(1,7),3))):
            raise SourceError('all120 verified odds identities required')
        for row in odds:
            price=row.get('odds')
            if price is not None and (not isinstance(price,str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?',price) or not Decimal(1)<=Decimal(price)<=Decimal(1000000)):
                raise SourceError('invalid observation odds')


def bundle_for_race(race,records,*,existing=None,now,summary_only=False):
    values={};history_complete=True
    if existing:
        if existing.get('race_id')!=race['race_id'] or existing.get('schema_version')!=1: raise SourceError('existing update bundle mismatch')
        history_complete=not existing.get('summary_only',False)
        if not history_complete and not summary_only: raise SourceError('full immutable bundle needed to expand a summary')
        for record in existing.get('records',[]):
            check_record(record,race,now,summary=not history_complete)
            identifier=record['snapshot_id'];previous=values.get(identifier)
            if previous is not None and canonical(previous)!=canonical(record):
                raise SourceError('conflicting existing immutable snapshot metadata')
            values[identifier]=copy.deepcopy(record)
    for record in records:
        check_record(record,race,now)
        identifier=record['snapshot_id'];previous=values.get(identifier)
        if previous is not None:
            projected={key:value for key,value in record.items() if key!='data'}
            if previous.get('payload_omitted'):
                projected['payload_omitted']=True
                if canonical(previous)!=canonical(projected): raise SourceError('conflicting immutable summary metadata')
            elif canonical(previous)!=canonical(record): raise SourceError('conflicting immutable snapshot metadata')
        values[identifier]=copy.deepcopy(record)
    ordered=sorted(values.values(),key=lambda r:(stamp(r['captured_at']),stamp(r['saved_at']),r['kind'],r['snapshot_id']))
    latest={};positions={}
    for record in ordered:
        key=(record['kind'],stamp(record['captured_at']),stamp(record['saved_at']))
        if key in positions and positions[key]!=record['snapshot_id']: raise SourceError('ambiguous same-time observation revisions')
        positions[key]=record['snapshot_id'];latest[record['kind']]=record['snapshot_id']
    if summary_only:
        shown=[]
        for record in ordered:
            if record['snapshot_id']==latest[record['kind']]:
                shown.append({**{key:value for key,value in record.items() if key!='data'},'payload_omitted':True})
        return dict(schema_version=1,race_id=race['race_id'],summary_only=True,history_included=False,
                    source_record_count=len(ordered) if history_complete else None,records=shown,latest=latest)
    return dict(schema_version=1,race_id=race['race_id'],records=ordered,latest=latest)


def merge_race_updates(day_feed,observations,*,now=None,summary_only=True):
    """Return a new feed. Original program/approval/source metadata is retained."""
    try:
        now=now or datetime.now(timezone.utc)
        if not isinstance(day_feed,dict) or day_feed.get('redistribution_authorized') is not True or not isinstance(observations,list):
            raise SourceError('approved day feed and stored observations required')
        date=datetime.strptime(day_feed['date_jst'],'%Y-%m-%d').date()
        result=copy.deepcopy(day_feed);races={}
        for venue in result['venues']:
            for race in venue['races']:
                rid=race['race_id']
                if not re.fullmatch(f'{date:%Y%m%d}-{venue["venue"]}-(0[1-9]|1[0-2])',rid) or rid in races:
                    raise SourceError('invalid or duplicate day program race')
                races[rid]=race
        grouped={}
        for record in observations:
            rid=record.get('race_id') if isinstance(record,dict) else None
            if rid not in races: raise SourceError('observation race absent from approved day program')
            grouped.setdefault(rid,[]).append(record)
        # Even an empty update batch must revalidate retained history against
        # the requested cutoff and output mode; untouched races cannot bypass it.
        affected=set(grouped)|{rid for rid,race in races.items() if 'official_updates' in race}
        for rid in sorted(affected):
            records=grouped.get(rid,[])
            race=races[rid]
            race['official_updates']=bundle_for_race(race,records,existing=race.get('official_updates'),now=now,summary_only=summary_only)
        return result
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError) as exc:
        if isinstance(exc,SourceError): raise
        raise SourceError('official update merge contract invalid') from exc
