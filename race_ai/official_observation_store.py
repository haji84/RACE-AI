"""Append-only official observation versions with capture and actual-save gates."""
from datetime import datetime,timezone
import hashlib
import json
import re

from .core import SourceError
from .official_race_updates import KINDS,endpoint


def utc_now(): return datetime.now(timezone.utc)


def stamp(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    if not isinstance(parsed,datetime) or parsed.tzinfo is None: raise SourceError('observation timestamp needs timezone')
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')


def setup_store(db):
    db.executescript('''
CREATE TABLE IF NOT EXISTS official_observations (
 snapshot_id TEXT PRIMARY KEY, race_id TEXT NOT NULL, kind TEXT NOT NULL,
 revision_no INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
 available_at TEXT NOT NULL, captured_at TEXT NOT NULL, saved_at TEXT NOT NULL,
 eligible_pre_race INTEGER NOT NULL CHECK(eligible_pre_race IN (0,1)), payload_json TEXT NOT NULL,
 UNIQUE(race_id,kind,revision_no)
);
CREATE INDEX IF NOT EXISTS official_observation_asof ON official_observations(race_id,kind,captured_at,saved_at);
CREATE TRIGGER IF NOT EXISTS official_observations_no_update BEFORE UPDATE ON official_observations
BEGIN SELECT RAISE(ABORT,'official observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS official_observations_no_delete BEFORE DELETE ON official_observations
BEGIN SELECT RAISE(ABORT,'official observations are append-only'); END;
''')


def save_observation(db,observation):
    try:
        if not isinstance(observation,dict) or 'saved_at' in observation: raise SourceError('caller cannot supply observation save time')
        raw=json.dumps(observation,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
        value=json.loads(raw);race=value.get('race_id');kind=value.get('kind')
        match=re.fullmatch(r'([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',race or '')
        if not match or kind not in KINDS: raise SourceError('invalid observation race identity')
        day=datetime.strptime(match[1],'%Y%m%d').date()
        if value.get('source_url')!=endpoint(day,match[2],int(match[3]),kind) or not re.fullmatch(r'[0-9a-f]{64}',value.get('source_sha256','')):
            raise SourceError('observation source and race identity conflict')
        captured,available,saved=stamp(value['captured_at']),stamp(value['available_at']),stamp(utc_now())
        if not available<=captured<=saved: raise SourceError('observation outside actual save cutoff')
        if value.get('upstream_published_at') is None and available!=captured:
            raise SourceError('unknown upstream publication cannot backdate availability')
        if value.get('upstream_published_at') is not None: raise SourceError('upstream publication evidence not supported by this collector')
        data=value.get('data');verified=value.get('body_identity_verified') is True
        expected=False;closed=None
        if verified:
            closed=stamp(value['closed_at'])
            expected=kind!='raceresult' and captured<closed and not (kind=='odds3t' and isinstance(data,dict) and data.get('odds_phase')=='final')
        elif value.get('status')!='PENDING' or data is not None:
            raise SourceError('unverified body cannot carry race facts')
        if type(value.get('eligible_pre_race')) is not bool or value['eligible_pre_race']!=expected:
            raise SourceError('observation phase eligibility conflicts')
        if kind=='raceresult' and value.get('information_phase')!='official_result': raise SourceError('result cannot masquerade as pre-race data')
        if kind=='beforeinfo' and data is not None:
            if set(data)!={'boats','weather'}: raise SourceError('preview contains unsupported result fields')
            for boat in data['boats']:
                if any(key in boat for key in ('actual_st','finish','payouts','result_course')) or boat.get('actual_course') is not None:
                    raise SourceError('actual outcome cannot enter preview evidence')
        identifier=hashlib.sha256(raw).hexdigest()
        with db:
            if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM official_observations WHERE snapshot_id=?',(identifier,)).fetchone(): return identifier
            revision=db.execute('SELECT COALESCE(MAX(revision_no),0)+1 FROM official_observations WHERE race_id=? AND kind=?',(race,kind)).fetchone()[0]
            # A first save after closing is never pre-race performance evidence,
            # even if an imported capture timestamp purports to be earlier.
            usable=expected and saved<closed
            db.execute('INSERT INTO official_observations VALUES (?,?,?,?,?,?,?,?,?,?)',
                (identifier,race,kind,revision,value['source_sha256'],available,captured,saved,int(usable),raw.decode('utf-8')))
        return identifier
    except (ValueError,TypeError,KeyError,UnicodeError) as exc:
        if isinstance(exc,SourceError): raise
        raise SourceError('invalid official observation') from exc


def latest_observation(db,race_id,kind,*,as_of,pre_race_only=False):
    if kind not in KINDS: raise SourceError('invalid observation kind')
    cutoff=stamp(as_of)
    query='''SELECT payload_json,snapshot_id,saved_at,eligible_pre_race FROM official_observations
 WHERE race_id=? AND kind=? AND available_at<=? AND captured_at<=? AND saved_at<=?'''
    if pre_race_only: query+=' AND eligible_pre_race=1'
    query+=' ORDER BY captured_at DESC,revision_no DESC LIMIT 1'
    row=db.execute(query,(race_id,kind,cutoff,cutoff,cutoff)).fetchone()
    if row is None: return None
    return {**json.loads(row[0]),'snapshot_id':row[1],'saved_at':row[2],'storage_eligible_pre_race':bool(row[3])}
