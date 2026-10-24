"""Pure joins of stored official observations to an approved day program.

Default summaries include only the latest record metadata per kind. Full
immutable per-race history belongs in a separate observation bundle; global
program sources and original boat fields are never rewritten here.
"""
import copy
from datetime import datetime,timezone
import re

from web.race_contract import canonical,stamp,validate_record,validate_summary
from .core import SourceError


def check_record(record,race,now,*,summary=False):
    """Keep the offline SourceError API around the standalone web contract."""
    try:
        (validate_summary if summary else validate_record)(record,race,now)
    except ValueError as exc:
        raise SourceError(str(exc)) from exc


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
