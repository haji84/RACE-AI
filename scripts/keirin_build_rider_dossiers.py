"""Build private dated basic dossiers with the existing identity/history authority.

The current official registry reconciles identities retrospectively. Neither its
new capture nor archived fetched clocks authenticate historical forecast inputs.
No frozen forecast, inference code, model weight or source database is modified.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from race_ai import keirin_archive_study as archive
from race_ai import keirin_tactical_observations as tactics
from race_ai.keirin_tactical_packets import (TACTICAL_SCHEMA, TACTICAL_SCOPE, TACTICAL_HOSTS,
                                              _tactical_rows, _tactical_receipt)
from race_ai.keirin_note_view import _private_root, _create, canonical
from scripts.keirin_rider_profile_history import HistoryBook, Ride, grade_family, is_registration
from scripts.keirin_rider_profile_identity import IdentityIndex, name_key

SCOPE='RETROSPECTIVE_CURRENT_REGISTRY_IDENTITY_RECONCILIATION'
REGISTRY_SCOPE='NEW_CURRENT_SOURCE_KNOWLEDGE_NOT_BACKDATED_ORIGINAL_INPUT'
JST=ZoneInfo('Asia/Tokyo')
TABLES={
    'races':{'race_date','venue_code','rno','is_girls','fetched_at'},
    'entries':{'race_date','venue_code','rno','kumiban','racer_name','kyu','prefecture','racer_class','fetched_at'},
    'results':{'race_date','venue_code','rno','kumiban','racer_name','rank','is_incident','fetched_at'},
    'line_predictions':{'race_date','venue_code','rno','kumiban','line_no','position_in_line','line_size','role'},
}


def _need(condition,code):
    if not condition:raise ValueError('KEIRIN_DOSSIER_'+code)


def _json(raw):
    _need(type(raw) is bytes and 0<len(raw)<=16*1024*1024,'JSON_BYTES')
    def pairs(values):
        result={}
        for key,value in values:
            _need(key not in result,'JSON_DUPLICATE_KEY');result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:_need(False,'NONFINITE_JSON'))


def _clock(value):
    _need(type(value) is str,'CLOCK_INVALID')
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    _need(parsed.utcoffset() is not None,'CLOCK_INVALID')
    return parsed.astimezone(timezone.utc)


def _day(value):
    _need(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value),'DAY_INVALID')
    return date.fromisoformat(value)



def _registry(registry):
    _need(type(registry) is dict and registry.get('schema')=='KEIRIN_OFFICIAL_CURRENT_REGISTRY_V1' and
          registry.get('scope')==REGISTRY_SCOPE,'REGISTRY_SCHEMA')
    _need(registry.get('complete') is True,'REGISTRY_INCOMPLETE')
    started,completed=map(_clock,(registry['retrieval_started_at'],registry['retrieval_completed_at']))
    _need(started<=completed and type(registry.get('riders')) is list and 0<len(registry['riders'])<=10000,'REGISTRY_ROWS')
    for rider in registry['riders']:
        _need(type(rider) is dict and is_registration(rider.get('registration')) and rider['registration']!='000000' and
              type(rider.get('name')) is str and bool(name_key(rider['name'])) and
              type(rider.get('prefecture_or_country')) is str and bool(name_key(rider['prefecture_or_country'])) and
              (rider.get('cohort') is None or type(rider['cohort']) is int and 1<=rider['cohort']<=999) and
              rider.get('class') in archive.CLASSES,'REGISTRY_RIDER_INVALID')
        url=urlsplit(rider['source_url'])
        _need(url.scheme=='https' and url.hostname in ('keirin.jp','www.keirin.jp') and not url.username and not url.password and
              not url.port and not url.fragment and re.fullmatch('[0-9a-f]{64}',rider['source_sha256']) and
              _clock(rider['captured_at'])<=completed,'REGISTRY_SOURCE_INVALID')
    return IdentityIndex(registry['riders'],[])


def _rows(path,cutoff):
    deadline=time.monotonic()+30
    ticks=0
    def limit():
        nonlocal ticks
        ticks+=1
        return int(ticks>25000 or time.monotonic()>deadline)
    connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True,timeout=3)
    try:
        connection.row_factory=sqlite3.Row
        connection.set_progress_handler(limit,10000)
        connection.execute('PRAGMA trusted_schema=OFF');connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        tables=dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
        for table,required in TABLES.items():
            _need(table in tables and 'virtual table' not in (tables[table] or '').lower(),'DATABASE_SCHEMA')
            _need(required<={row['name'] for row in connection.execute('PRAGMA table_info('+table+')')},'DATABASE_COLUMNS')
            _need(connection.execute('SELECT count(*) FROM '+table).fetchone()[0]<=archive.MAX_ROWS,'DATABASE_ROW_LIMIT')
        _need([tuple(row) for row in connection.execute('PRAGMA quick_check')]==[('ok',)],'DATABASE_INTEGRITY')
        query='''SELECT e.race_date,e.venue_code,e.rno,e.kumiban,e.racer_name,e.kyu,e.prefecture,e.racer_class,
            e.fetched_at AS entry_fetched_at,r.racer_name AS result_name,r.rank,r.is_incident,
            r.fetched_at AS result_fetched_at,l.line_no,l.position_in_line,l.line_size,l.role,
            a.is_girls,a.fetched_at AS race_fetched_at FROM entries e
            LEFT JOIN results r USING(race_date,venue_code,rno,kumiban)
            LEFT JOIN line_predictions l USING(race_date,venue_code,rno,kumiban)
            LEFT JOIN races a USING(race_date,venue_code,rno)
            WHERE e.race_date < ? ORDER BY e.race_date,e.venue_code,e.rno,e.kumiban'''
        yield from connection.execute(query,(cutoff,))
    finally:connection.close()


def _collect(db_paths,registry,cutoff_day,manifest=None,registrations=None):
    cutoff=_day(cutoff_day).strftime('%Y%m%d');index=_registry(registry)
    paths=[Path(path) for path in db_paths]
    _need(0<len(paths)<=archive.MAX_DATABASES and len({p.name for p in paths})==len(paths),'DATABASE_SET')
    expected={}
    if manifest is not None:
        _need(type(manifest) is dict and manifest.get('schema')=='KEIRIN_PUBLIC_GITHUB_DOWNLOAD_V1','MANIFEST_SCHEMA')
        for source in manifest['sources']:
            _need(source['file'] not in expected,'MANIFEST_DUPLICATE');expected[source['file']]=source
    held=Counter();counts=Counter();slots={};conflicts=set();months=set();sources=[];raw_clocks=[]
    source_counts=defaultdict(Counter)
    for path in paths:
        digest,size=archive._fingerprint(path)
        source=expected.get(path.name)
        if manifest is not None:
            _need(source and source.get('sha256')==digest and source.get('bytes')==size,'DATABASE_SHA_MISMATCH')
        local_clocks=[];first=last=None
        try:
            rows=_rows(path,cutoff)
            for _,group in groupby(rows,key=lambda row:(row['race_date'],row['venue_code'],row['rno'])):
                race=[dict(row) for row in group]
                rid=archive._race_id(race[0]);day=rid[:8]
                months.add(day[:6]);first=min(first or day,day);last=max(last or day,day)
                cars={row['kumiban'] for row in race}
                _need(len(cars)==len(race) and all(type(car) is int and 1<=car<=9 for car in cars),'DUPLICATE_OR_INVALID_STARTER')
                line_rows=[row for row in race if row['line_no'] is not None]
                role_map={}
                try:
                    groups,_=archive._lines(line_rows,cars,race[0]['is_girls'])
                    for line in groups:
                        for pos,car in enumerate(line):role_map[car]='SOLO' if len(line)==1 else 'LEAD' if pos==0 else 'SECOND' if pos==1 else 'REAR'
                except ValueError:pass
                for row in race:
                    counts['source_entry_rows']+=1
                    for key in ('entry_fetched_at','result_fetched_at','race_fetched_at'):
                        if type(row[key]) is str and row[key]:local_clocks.append(row[key])
                    cohort=str(row['kyu'] or '').strip()
                    registration=index.bind((name_key(row['racer_name']),int(cohort),row['prefecture'])) if cohort.isascii() and cohort.isdigit() else None
                    if registration is None:held['IDENTITY_UNRESOLVED']+=1;continue
                    if registrations is not None and registration not in registrations:continue
                    source_counts[registration]['source_entry_rows']+=1
                    reason=None
                    if row['rank'] is None and row['result_name'] is None:reason='RESULT_MISSING'
                    elif name_key(row['result_name'])!=name_key(row['racer_name']):reason='RESULT_NAME_MISMATCH'
                    elif type(row['is_incident']) is not int or row['is_incident']!=0 or re.fullmatch('[1-9]',str(row['rank'])) is None:reason='INCIDENT_OR_NONNUMERIC_FINISH'
                    if reason:held[reason]+=1;source_counts[registration][reason]+=1;continue
                    grade=grade_family(row['racer_class']) if row['racer_class'] in archive.CLASSES else None
                    ride=Ride(rid,registration,int(row['rank']),None,role_map.get(row['kumiban']),grade)
                    slot=(rid,row['kumiban']);value=(registration,ride,row['racer_class'])
                    if slot in conflicts:continue
                    if slot in slots:
                        if slots[slot]==value:counts['duplicate_same_count']+=1
                        else:counts['duplicate_conflict_count']+=1;conflicts.add(slot);del slots[slot]
                    else:slots[slot]=value
        except sqlite3.Error:raise ValueError('KEIRIN_DOSSIER_DATABASE_READ_REJECTED') from None
        _need(archive._fingerprint(path)==(digest,size),'DATABASE_CHANGED_DURING_READ')
        raw_clocks.extend(local_clocks)
        sources.append(dict(database_sha256=digest,bytes=size,manifest_verified=manifest is not None,
            source_url=source.get('url') if source else None,
            included_start_day=date.fromisoformat(first).isoformat() if first else None,
            included_end_day=date.fromisoformat(last).isoformat() if last else None,
            fetched_at_min_raw=min(local_clocks) if local_clocks else None,fetched_at_max_raw=max(local_clocks) if local_clocks else None,
            fetched_clock_authentication='UNATTESTED_ARCHIVE_VALUE_NOT_PRE_CUTOFF_EVIDENCE'))
    by_registration=defaultdict(list);classes=defaultdict(dict)
    for registration,ride,klass in slots.values():
        by_registration[registration].append(ride)
        classes[registration].setdefault(ride.race_id[:8],set()).add(klass or 'UNKNOWN')
    rides=[ride for values in by_registration.values() for ride in values]
    days=[ride.race_id[:8] for ride in rides];first=min(days) if days else None;last=max(days) if days else None
    span=(int(max(months)[:4])-int(min(months)[:4]))*12+int(max(months)[4:])-int(min(months)[4:])+1 if months else 0
    summary=dict(schema='KEIRIN_BASIC_RIDER_DOSSIER_SUMMARY_V1',scope=SCOPE,as_of_exclusive=cutoff_day,
        registered_riders=len(registry['riders']),riders_with_numeric_history=len(by_registration),
        numeric_finish_records=len(rides),source_entry_rows=counts['source_entry_rows'],
        held_by_reason=dict(held),duplicate_same_count=counts['duplicate_same_count'],duplicate_conflict_count=counts['duplicate_conflict_count'],
        history_start_day=date.fromisoformat(first).isoformat() if first else None,
        history_end_day=date.fromisoformat(last).isoformat() if last else None,
        calendar_months_observed=len(months),coverage_span_calendar_months=span,archive_sha256s=[source['database_sha256'] for source in sources],
        archive_sources=sources,complete_lifetime_history=False,complete_three_year_history=False,
        omitted_archive_starts_count=None,historical_as_of_authenticated=False,frozen_forecasts_modified=False,model_weights_modified=False)
    return by_registration,index,summary,source_counts,classes


def load_archive_book(db_paths,registry,cutoff_day,*,archive_manifest=None,registrations=None,clock=None):
    """Reuse the same admitted Ride objects in the existing HistoryBook authority."""
    now=(clock or (lambda:datetime.now(timezone.utc)))()
    _need(isinstance(now,datetime) and now.utcoffset() is not None,'BUILD_CLOCK_INVALID')
    _need(_clock(registry['retrieval_completed_at'])<=now,'REGISTRY_CAPTURE_AFTER_BUILD')
    if archive_manifest is not None:
        _need(_clock(archive_manifest['started_at'])<=_clock(archive_manifest['completed_at'])<=now,'SOURCE_CAPTURE_CLOCK')
    rides,index,summary,_,_=_collect(db_paths,registry,cutoff_day,archive_manifest,registrations)
    return HistoryBook(ride for values in rides.values() for ride in values),index,summary


def build_dossiers(db_paths,registry_raw,manifest_raw,*,expected_registry_sha256,as_of_day,clock=None,
                   tactical_raw=None,expected_tactical_sha256=None):
    _need(type(registry_raw) is bytes and sha256(registry_raw).hexdigest()==expected_registry_sha256,'REGISTRY_SHA_MISMATCH')
    registry,manifest=_json(registry_raw),_json(manifest_raw)
    now=(clock or (lambda:datetime.now(timezone.utc)))()
    _need(isinstance(now,datetime) and now.utcoffset() is not None,'BUILD_CLOCK_INVALID')
    _need(_clock(registry['retrieval_completed_at'])<=now and _clock(manifest['started_at'])<=_clock(manifest['completed_at'])<=now,'SOURCE_CAPTURE_CLOCK')
    day=_day(as_of_day)
    tactical_rows,tactical_meta={},None
    if tactical_raw is not None or expected_tactical_sha256 is not None:
        _registry(registry)
        registered={person['registration'] for person in registry['riders']}
        tactical_rows,tactical_meta=_tactical_rows(tactical_raw,expected_tactical_sha256,registered,day,now)
    rides,_,summary,counts,classes=_collect(db_paths,registry,as_of_day,manifest)
    query_id=day.strftime('%Y%m%d')+'0101'
    dossiers=[]
    for person in sorted(registry['riders'],key=lambda row:row['registration']):
        registration=person['registration'];past=rides.get(registration,[])
        latest=max(classes[registration]) if classes[registration] else None
        dossiers.append(dict(registration=registration,name=person['name'],cohort=person['cohort'],
            prefecture_or_country=person['prefecture_or_country'],
            registry_class=dict(value=person['class'],source_label=person.get('class_source_label'),
                captured_at=person['captured_at'],source_url=person['source_url'],source_sha256=person['source_sha256'],
                index_updated_at_jst=person.get('index_updated_at_jst'),scope=REGISTRY_SCOPE),
            archived_classes_on_latest_finish_day=sorted(classes[registration][latest]) if latest else [],
            historical_grade_counts=dict(Counter(ride.grade or 'UNKNOWN' for ride in past)),
            published_line_role_counts=dict(Counter(ride.role or 'UNKNOWN' for ride in past)),
            published_line_roles_are_not_observed_race_positions=True,
            known_source_row_counts=dict(counts[registration]),
            finish_history=HistoryBook(past).finish_history(registration,race_id=query_id)))
        if registration in tactical_rows:
            verified=tactical_rows[registration]
            verified_rows={id(row) for row in verified}
            profile=tactics.profile_episodes(verified,registration=registration,
                as_of=tactical_meta['review_available_before'],target_race_id=query_id,
                verify=lambda row:id(row) in verified_rows)
            del profile['target_race_id']  # This day-level dossier has no target race.
            dossiers[-1]['tactical_observations']=profile
    summary.update(generated_at=now.astimezone(timezone.utc).isoformat(),registry_sha256=expected_registry_sha256,
        registry_capture_completed_at=registry['retrieval_completed_at'],archive_manifest_sha256=sha256(manifest_raw).hexdigest())
    packet=dict(schema='KEIRIN_BASIC_RIDER_DOSSIERS_V1',scope=SCOPE,as_of_exclusive=as_of_day,
        generated_at=summary['generated_at'],identity_knowledge_as_of=registry['retrieval_completed_at'],
        registry_captured_after_history_cutoff=_clock(registry['retrieval_completed_at']).astimezone(JST).date()>=day,
        registry_sha256=expected_registry_sha256,archive_manifest_sha256=summary['archive_manifest_sha256'],
        source_download_started_at=manifest['started_at'],source_download_completed_at=manifest['completed_at'],
        archive_sources=summary['archive_sources'],historical_as_of_authenticated=False,dossiers=dossiers)
    if tactical_meta is not None:
        packet['tactical_observations']=summary['tactical_observations']=tactical_meta
    return packet,summary


def write_private(output_dir,packet,summary):
    root=_private_root(output_dir)
    day=_day(packet['as_of_exclusive']).isoformat()
    paths=dict(dossiers=root/('dossiers-'+day+'.json'),summary=root/('summary-'+day+'.json'))
    _need(all(not path.exists() for path in paths.values()),'EXISTING_SNAPSHOT_PRESERVED')
    _create(paths['dossiers'],canonical(packet)+b'\n');_create(paths['summary'],canonical(summary)+b'\n')
    return {name:str(path) for name,path in paths.items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',action='append',required=True,type=Path)
    for name in ('registry','archive-manifest','output-dir'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--expected-registry-sha256',required=True)
    parser.add_argument('--tactical-observations',type=Path,help='Private independently reviewed observation packet')
    parser.add_argument('--expected-tactical-sha256',help='Independently pinned digest for the tactical packet')
    parser.add_argument('--as-of-day',required=True)
    args=parser.parse_args()
    try:
        packet,summary=build_dossiers(args.database,args.registry.read_bytes(),args.archive_manifest.read_bytes(),
            expected_registry_sha256=args.expected_registry_sha256,as_of_day=args.as_of_day,
            tactical_raw=args.tactical_observations.read_bytes() if args.tactical_observations else None,
            expected_tactical_sha256=args.expected_tactical_sha256)
        write_private(args.output_dir,packet,summary)
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error):
        parser.exit(2,'Dossier build held: source validation or private output failed.\n')
    print(json.dumps(summary,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':main()
