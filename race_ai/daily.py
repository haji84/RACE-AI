"""Daily all-motor research report from permissioned local snapshots.

No online scraping. A daily run without new, valid source snapshots is
reported as incomplete/stale, never as a successful fresh live update.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import connect, save_exhibition, exhibition_asof, SourceError, utc
from .motor import setup_motor, import_motor_observation, import_motor_service, analyze_motor

JST=ZoneInfo("Asia/Tokyo")
KINDS=("inventory","motor_observations","motor_service","exhibition","assignments")
REQUIRED="inventory"


def _read(path: Path, key: str, *, required: bool=False) -> tuple[list|dict|None,str|None]:
    if not path.is_file():
        if required:
            raise SourceError(f'required source missing: {path.name}')
        return None,None
    raw=path.read_bytes()
    if len(raw)>20_000_000:
        raise SourceError(f'{key} source exceeds permitted local input size')
    try:
        obj=json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise SourceError(f'invalid UTF-8 JSON input {key}') from exc
    return obj, hashlib.sha256(raw).hexdigest()


def _time_ok(record:dict, asof:str, key:str) -> None:
    if not isinstance(record,dict):
        raise SourceError(f'{key} must be an object')
    if not record.get('rights_confirmed'):
        raise SourceError(f'{key}: permitted use must be affirmed by operator')
    # No invented publication time. Unpublished/unknown sources are not eligible
    # for an as-of historical prediction, even if retrieved earlier.
    if not record.get('published_at'):
        raise SourceError(f'{key}: published_at is mandatory')
    if not record.get('captured_at'):
        raise SourceError(f'{key}: captured_at is mandatory')
    if utc(record['published_at'])>utc(record['captured_at']):
        raise SourceError(f'{key}: publication follows capture')
    if utc(record['captured_at'])>asof:
        raise SourceError(f'{key}: future captured data unavailable at decision time')


def _inventory(obj:dict, asof:str) -> list[dict]:
    _time_ok(obj,asof,'inventory')
    venues=obj.get('venues')
    if not isinstance(venues,list) or len(venues)==0:
        raise SourceError('inventory: venues list must be nonempty')
    seen=set(); motors=[]
    for entry in venues:
        if not isinstance(entry,dict):
            raise SourceError('inventory venue must be an object')
        venue=entry.get('venue');cycle=entry.get('motor_cycle')
        if not isinstance(venue,str) or not re.fullmatch(r'\d{2}',venue):
            raise SourceError('venue is two digits')
        if not isinstance(cycle,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}',cycle):
            raise SourceError('motor cycle required')
        numbered=entry.get('motors')
        if not isinstance(numbered,list) or not numbered:
            raise SourceError('each venue requires explicit numbered active-motor inventory')
        for number in numbered:
            if type(number) is not int or not 1<=number<=999:
                raise SourceError('invalid motor number in inventory')
            key=(venue,cycle,number)
            if key in seen:
                raise SourceError('duplicate motor number/cycle in inventory')
            seen.add(key)
            motors.append(dict(venue=venue,motor_cycle=cycle,motor_no=number))
    if len(motors)>24*999:
        raise SourceError('unexpected motor inventory size')
    return sorted(motors,key=lambda r:(r['venue'],r['motor_cycle'],r['motor_no']))


def _rows(obj:list|dict|None,key:str,asof:str)->list[dict]:
    if obj is None:
        return []
    if not isinstance(obj,dict):
        raise SourceError(f'{key}: expected envelope object with source timestamps')
    _time_ok(obj,asof,key)
    items=obj.get('rows')
    if not isinstance(items,list):
        raise SourceError(f'{key}: rows list missing')
    for r in items:
        if not isinstance(r,dict):
            raise SourceError(f'{key}: rows must be objects')
        # Caller input may specify an item-level stricter timestamp.
        _time_ok(r,asof,key+'.row')
    return items


def _assignment_rows(items:list[dict], asof:str, day:date)->list[dict]:
    assigned={}; motor_used={}
    for x in items:
        venue=x.get('venue');cycle=x.get('motor_cycle')
        no=x.get('motor_no'); race=x.get('race_id');lane=x.get('lane')
        if (not isinstance(venue,str) or not re.fullmatch(r'\d{2}',venue)
            or not isinstance(cycle,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}',cycle)
            or type(no) is not int or not 1<=no<=999
            or type(lane) is not int or lane not in range(1,7)
            or not isinstance(race,str) or not re.fullmatch(r'\d{8}-\d{2}-\d{2}',race)
            or race[9:11]!=venue):
            raise SourceError('invalid boat-to-motor assignment')
        rd=date.fromisoformat(f'{race[:4]}-{race[4:6]}-{race[6:8]}')
        if rd!=day:
            raise SourceError('assignment race date must match Japan-local report date')
        key=(race,lane)
        mid=(venue,cycle,no)
        if key in assigned or (race,mid) in motor_used:
            raise SourceError('duplicate race/lane or motor allocation in race')
        assigned[key]=x
        motor_used[(race,mid)]=True
    return list(assigned.values())


def _snapshot_asof(db:sqlite3.Connection, race_id:str, lane:int, asof:str)->dict:
    measures=exhibition_asof(db,race_id,asof)
    subset={r['metric']:r for r in measures if r['lane']==lane}
    required=('display','lap','turn','straight','start_exhibition')
    motor_kinds=('display','lap','turn','straight')
    return dict(metrics={
        key:({'value':subset[key]['value'],'captured_at':subset[key]['captured_at'],
              'source_sha256':subset[key]['sha'],'missing_reason':subset[key]['missing_reason']}
             if key in subset else {'value':None,'missing_reason':'not supplied or not published by decision time'})
        for key in required},
        complete=all(key in subset and subset[key]['value'] is not None for key in required),
        original_exhibition_complete=all(key in subset and subset[key]['value'] is not None for key in motor_kinds),
        available_count=sum(key in subset and subset[key]['value'] is not None for key in required))


def build_daily(input_dir:str|Path,asof:str, *, persist_db:str=':memory:')->dict:
    """Build deterministic as-of data report without fetching new data.

    For partial source coverage, returns every *listed* motor with UNKNOWN labels;
    does not claim coverage of all motors nationally.
    """
    cutoff=utc(asof)
    day=datetime.fromisoformat(cutoff).astimezone(JST).date()
    root=Path(input_dir)
    parsed={}; digests={}
    for key in KINDS:
        parsed[key],digests[key]=_read(root/(key+'.json'),key,required=key==REQUIRED)
    listed=_inventory(parsed['inventory'],cutoff)
    known={(x['venue'],x['motor_cycle'],x['motor_no']) for x in listed}
    observations=_rows(parsed['motor_observations'],'motor_observations',cutoff)
    services=_rows(parsed['motor_service'],'motor_service',cutoff)
    exhibitions=_rows(parsed['exhibition'],'exhibition',cutoff)
    assignments=_assignment_rows(_rows(parsed['assignments'],'assignments',cutoff),cutoff,day)
    for kind,items in [('motor_observations',observations),('motor_service',services),('assignments',assignments)]:
        for item in items:
            if (item.get('venue'),item.get('motor_cycle'),item.get('motor_no')) not in known:
                raise SourceError(f'{kind}: motor is not present in current inventory')
    for item in exhibitions:
        if not isinstance(item.get('race_id'),str):
            raise SourceError('exhibition race_id is missing')
        # Race ID is linked by assignment if possible; orphan evidence is not
        # called current motor performance.
    with connect(persist_db) as db:
        setup_motor(db)
        for record in observations:
            import_motor_observation(db,record)
        for record in services:
            import_motor_service(db,record)
        for record in exhibitions:
            save_exhibition(db,record)
        lookup={}
        for x in assignments:
            k=(x['venue'],x['motor_cycle'],x['motor_no'])
            lookup.setdefault(k,[]).append(x)
        reports=[]
        for item in listed:
            k=(item['venue'],item['motor_cycle'],item['motor_no'])
            slots=lookup.get(k,[])
            info=analyze_motor(db,*k,cutoff,
                               target_meeting_id=parsed['inventory'].get('current_meet_id_by_venue',{}).get(k[0]))
            attachments=[]
            for slot in slots:
                z=_snapshot_asof(db,slot['race_id'],slot['lane'],cutoff)
                attachments.append(dict(race_id=slot['race_id'],lane=slot['lane'],**z))
            previous=info['previous_meet']
            reports.append(dict(**item,
                historical_observations=info['finish_sample_n'],
                prior_meet=previous,
                previous_rider_is_rookie=(
                    previous['rookie_starts']>0 if previous is not None else None),
                rider_adjusted_motor_residual=info['adjusted_rider_neutral_residual'],
                rider_adjustment_status=info['confidence'],
                previous_10_motor_races=info['recent_10'],
                service_since=info['motor_since_major_service'],
                current_exhibition=attachments,
                needs=['HISTORICAL_RACE_RESULTS'] if not info['finish_sample_n'] else [],
                provenance='operator-supplied sources; original site not independently verified'))
            if not slots:
                reports[-1]['needs'].append('CURRENT_DAY_MOTOR_ASSIGNMENT')
            elif not any(s['available_count']>0 for s in attachments):
                reports[-1]['needs'].append('CURRENT_DAY_EXHIBITION')
            if previous is None:
                reports[-1]['needs'].append('PREVIOUS_MEET_IDENTITY')
            if info['adjusted_rider_neutral_residual'] is None:
                reports[-1]['needs'].append('MOTOR_BLIND_PRE_RACE_BASELINE')
        n=len(reports)
        n_known=sum(r['historical_observations']>0 for r in reports)
        n_with_exhibition=sum(any(s['available_count']>0 for s in r['current_exhibition']) for r in reports)
        n_with_previous=sum(r['prior_meet'] is not None for r in reports)
        n_full_exhibition=sum(any(s['original_exhibition_complete'] for s in r['current_exhibition']) for r in reports)
        inventory_day=datetime.fromisoformat(utc(parsed['inventory']['captured_at'])).astimezone(JST).date()
        inventory_fresh=inventory_day==day
        status='COVERAGE_INCOMPLETE'
        if len({r['venue'] for r in reports})<24:
            status='PARTIAL_VENUE_SCOPE'
        if n_known==n and n_full_exhibition==n and n_with_previous==n and inventory_fresh and len({r['venue'] for r in reports})==24:
            # Does not mean all venue motor inventories are independently complete.
            status='INPUT_COVERAGE_PRESENT_NOT_INDEPENDENTLY_VERIFIED'
        if not inventory_fresh:
            status='STALE_INVENTORY_SOURCE'
        return dict(report_date_jst=day.isoformat(),decision_at=cutoff,
           generated_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
           status=status,inventory_scope='ONLY MOTORS ENUMERATED IN USER-PROVIDED INVENTORY',
           official_confirmation='UNVERIFIED',
           automatic_web_collection=False,
           number_of_venues=len({r['venue'] for r in reports}),
           inventory_count=n,history_count=n_known,
           current_exhibition_motor_count=n_with_exhibition,
           original_exhibition_complete_motor_count=n_full_exhibition,
           previous_meet_known_count=n_with_previous,
           inventory_fresh_today=inventory_fresh,
           source_sha256={k:v for k,v in digests.items() if v is not None},
           source_snapshot_capture_at=parsed['inventory']['captured_at'],
           motors=reports)


def main()->None:
    p=argparse.ArgumentParser()
    p.add_argument('--input-dir',default='data/live')
    p.add_argument('--asof',help='ISO-8601 time with UTC offset (defaults to execution time)')
    p.add_argument('--output',default='daily-report.json')
    a=p.parse_args()
    cutoff=a.asof or datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        result=build_daily(a.input_dir,cutoff)
    except (SourceError,ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
        result={'status':'SAFE_STOP_MISSING_OR_INVALID_SOURCE','reason':str(exc),
                'asof':cutoff,'motors':[],'auto_web_collection':False}
        Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(result['status']+': '+str(exc),file=sys.stderr)
        raise SystemExit(2)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"{result['status']}: {result['inventory_count']} listed motors, "+
          f"{result['history_count']} with results, "+
          f"{result['current_exhibition_motor_count']} with today's exhibition")
    # Incomplete scope or missing results is useful as a report, but is not a
    # successful update for operators requiring fresh full-venue predictions.
    if result['status']!='INPUT_COVERAGE_PRESENT_NOT_INDEPENDENTLY_VERIFIED':
        raise SystemExit(3)


if __name__=='__main__':
    main()
