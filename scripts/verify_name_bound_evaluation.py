"""Bounded read-only verification of one frozen name-bound forecast and label.

Uses the existing trusted workflow session. No official source acquisition,
POST, new forecast, financial calculation, or adoption decision is performed.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'scripts'))
from publish_day_feed import get_json, validate_target
from publish_race_updates import workflow_session, select_race
from web.name_bound_prediction import validate_name_bound_envelope
from web.name_bound_evaluation import build_name_bound_evaluation
from web.race_contract import canonical, JST, _time as instant, _program

PAYLOADS = {'program.json','forecast.json','result.json','evaluation.json'}
ALLOWED = PAYLOADS | {'manifest.json'}
MAX_BYTES = 256000
MAX_SECONDS = 180
MANIFEST = set('schema_version status failure_reason race_id forecast_request_id commit_sha backups reads_used posts_attempted official_source_requests max_seconds validation_status purchase_decision purchase_recommendations'.split())
REASONS = {'COMPLETED':None, 'STOPPED':'NAME_BOUND_EVALUATION_STOPPED',
    'TIME_LIMIT_REACHED':'NAME_BOUND_EVALUATION_TIME_LIMIT'}
ERRORS = (ValueError, RuntimeError, OSError, KeyError, TypeError, AttributeError, OverflowError, UnicodeError, RecursionError)


class BudgetExhausted(RuntimeError):
    """The single invocation's monotonic budget has been exhausted."""


def utc_now(): return datetime.now(timezone.utc)


def require(value):
    if not value: raise ValueError('NAME_BOUND_EVALUATION_STOPPED')


def identifiers(race_id, forecast_request_id):
    require(isinstance(race_id,str) and re.fullmatch(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',race_id))
    datetime.strptime(race_id[:8], '%Y%m%d')
    require(isinstance(forecast_request_id,str) and re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',forecast_request_id))


def write_checked(folder, name, value):
    require(name in ALLOWED)
    raw = canonical(value); require(0 < len(raw) <= MAX_BYTES)
    with (folder/name).open('xb') as handle: handle.write(raw)
    require((folder/name).read_bytes() == raw)
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def inventory(folder):
    """Hash actual residual bytes, including truncated failed payload writes."""
    require({p.name for p in folder.iterdir()} <= ALLOWED)
    result = {}
    for name in sorted(ALLOWED):
        path = folder/name
        if path.exists() or path.is_symlink():
            require(path.is_file() and not path.is_symlink())
            if name == 'manifest.json': continue
            raw = path.read_bytes(); require(0 < len(raw) <= MAX_BYTES)
            result[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return result


def verify_response(report, forecast, result, race, forecast_request_id, now):
    """Replay the report's unchanged as_of against all retained full evidence."""
    try:
        require(isinstance(now,datetime) and now.tzinfo is not None and now.utcoffset() is not None)
        clock = instant(now); day, _, _ = _program(race)
        require(clock.astimezone(JST).date() == day)
        identifiers(race['race_id'], forecast_request_id)
        require(forecast['receipt']['request_id'] == forecast_request_id)
        # Bound only the remote report clock; preserve every evidence timestamp
        # and replay at the server's unchanged actual as_of.
        require(isinstance(report,dict) and instant(report['as_of']) <= clock+timedelta(seconds=60))
        rebuilt = build_name_bound_evaluation(forecast, result, race, instant(report['as_of']))
        require(rebuilt['result_proof'] is not None)
        require(canonical(report) == canonical(rebuilt))
        return report
    except ERRORS as exc:
        raise ValueError('NAME_BOUND_EVALUATION_REPLAY_REJECTED') from exc


def verify_backups(folder, manifest):
    """Verify exact inventory, literal manifest types, and completed full replay."""
    try:
        require(isinstance(manifest,dict) and set(manifest) == MANIFEST)
        require(type(manifest['schema_version']) is int and manifest['schema_version'] == 1)
        require(type(manifest['max_seconds']) is int and manifest['max_seconds'] == MAX_SECONDS)
        identifiers(manifest['race_id'], manifest['forecast_request_id'])
        require(isinstance(manifest['commit_sha'],str) and re.fullmatch('[0-9a-f]{40}',manifest['commit_sha']))
        require(manifest['validation_status'] == 'UNVALIDATED' and manifest['purchase_decision'] == 'skip'
            and manifest['purchase_recommendations'] == [])
        for field, limit in [('reads_used',4),('posts_attempted',0),('official_source_requests',0)]:
            require(type(manifest[field]) is int and 0 <= manifest[field] <= limit)
        require(isinstance(manifest['status'],str) and manifest['status'] in REASONS
            and manifest['failure_reason'] == REASONS[manifest['status']])
        backups = manifest['backups']; require(isinstance(backups,dict))
        for name, meta in backups.items():
            require(name in PAYLOADS and isinstance(meta,dict) and set(meta) == {'bytes','sha256'})
            require(type(meta['bytes']) is int and 0 < meta['bytes'] <= MAX_BYTES
                and isinstance(meta['sha256'],str) and re.fullmatch('[0-9a-f]{64}',meta['sha256']))
        require(backups == inventory(folder))
        path = folder/'manifest.json'
        require(path.is_file() and not path.is_symlink())
        raw = path.read_bytes()
        require(0 < len(raw) <= MAX_BYTES and raw == canonical(manifest))
        if manifest['status'] == 'COMPLETED':
            require(set(backups) == PAYLOADS and manifest['reads_used'] == 4)
            values = {}
            for name in sorted(PAYLOADS):
                raw = (folder/name).read_bytes(); value = json.loads(raw)
                require(canonical(value) == raw); values[name] = value
            race = values['program.json']
            require(race['race_id'] == manifest['race_id'])
            verify_response(values['evaluation.json'], values['forecast.json'], values['result.json'],
                race, manifest['forecast_request_id'], utc_now())
        return manifest
    except ERRORS as exc:
        raise ValueError('NAME_BOUND_EVALUATION_BACKUP_REJECTED') from exc


def reopen_owned_manifest(path, identity):
    """Open without truncation, then prove the descriptor is still our file."""
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and (before.st_dev,before.st_ino) == identity)
    descriptor = os.open(path, os.O_RDWR | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_NONBLOCK',0))
    try:
        opened, current = os.fstat(descriptor), path.lstat()
        require(stat.S_ISREG(opened.st_mode) and stat.S_ISREG(current.st_mode)
            and (opened.st_dev,opened.st_ino) == identity == (current.st_dev,current.st_ino))
        return os.fdopen(descriptor,'r+b')
    except BaseException:
        os.close(descriptor)
        raise


def finalize_manifest(folder, manifest, guard):
    """Account for final close; recover only the exclusively created file."""
    path, identity = folder/'manifest.json', None
    def persist(handle):
        raw = canonical(manifest); require(0 < len(raw) <= MAX_BYTES)
        handle.seek(0); handle.truncate(0); handle.write(raw); handle.flush()
        handle.seek(0); require(handle.read() == raw)
    def failure(handle,status):
        manifest.update(status=status, failure_reason=REASONS[status])
        # Truthful state is durable before forensic inventory can itself fail.
        persist(handle)
        manifest['backups'] = inventory(folder)
        persist(handle)
    try:
        with path.open('x+b') as handle:
            owned = os.fstat(handle.fileno())
            require(stat.S_ISREG(owned.st_mode) and owned.st_ino != 0)
            identity = owned.st_dev, owned.st_ino
            try:
                manifest['backups'] = inventory(folder)
                persist(handle)
                guard()
                verify_backups(folder, manifest)
                guard()
            except BudgetExhausted:
                failure(handle,'TIME_LIMIT_REACHED')
            except ERRORS:
                failure(handle,'STOPPED')
        guard()
    except ERRORS as error:
        if identity is None: raise
        status = 'TIME_LIMIT_REACHED' if isinstance(error,BudgetExhausted) else 'STOPPED'
        try: guard()
        except BudgetExhausted: status = 'TIME_LIMIT_REACHED'
        except ERRORS: pass
        # The original handle may already be closed. Check the path before and
        # after opening, and fstat the nontruncating descriptor before any write.
        with reopen_owned_manifest(path,identity) as handle:
            failure(handle,status)
    return manifest


def run(race_id, forecast_request_id, output_dir, *, execute=False):
    if not execute: return None
    started = time.monotonic()
    identifiers(race_id, forecast_request_id)
    url = os.environ.get('RACE_AI_NAME_BOUND_EVALUATION_URL','')
    require(url.endswith('/api/name-bound-evaluation'))
    validate_target(url[:-len('name-bound-evaluation')]+'publish-day')
    commit = os.environ.get('RACE_AI_NAME_BOUND_EVALUATION_COMMIT_SHA','')
    require(re.fullmatch('[0-9a-f]{40}',commit))
    folder = Path(output_dir)
    require(not folder.exists()); folder.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema_version=1, status='STOPPED', failure_reason=REASONS['STOPPED'],
        race_id=race_id, forecast_request_id=forecast_request_id, commit_sha=commit, backups={},
        reads_used=0, posts_attempted=0, official_source_requests=0, max_seconds=MAX_SECONDS,
        validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[])

    def guard(seconds=0):
        if time.monotonic()-started+seconds > MAX_SECONDS:
            raise BudgetExhausted('NAME_BOUND_EVALUATION_TIME_LIMIT')
        now = utc_now()
        require(now.astimezone(JST).strftime('%Y%m%d') == race_id[:8])

    try:
        guard(30)
        opener, headers = workflow_session(commit)
        guard()
        base = url.rsplit('/',1)[0]
        def fetch(path, limit=MAX_BYTES):
            guard(30); require(manifest['reads_used'] < 4)
            manifest['reads_used'] += 1
            value = get_json(opener, urllib.request.Request(base+path,headers=headers), limit=limit)
            guard(); return value
        feed = fetch('/today',6_000_000)
        race, _ = select_race(feed,utc_now(),mode='result',race_id=race_id)
        require(race is not None); _program(race)
        write_checked(folder,'program.json',race); guard()
        forecast = fetch('/name-bound-exhibition?race_id='+race_id+'&request_id='+forecast_request_id)
        require(forecast['receipt']['request_id'] == forecast_request_id)
        validate_name_bound_envelope(forecast,race,now=utc_now()); guard()
        write_checked(folder,'forecast.json',forecast); guard()
        result = fetch('/race?race_id='+race_id)
        # Validate the full projected result before saving; missing labels stop
        # here without a fourth application GET or a completed artifact.
        require(build_name_bound_evaluation(forecast,result,race,utc_now())['result_proof'] is not None)
        guard(); write_checked(folder,'result.json',result); guard()
        report = fetch('/name-bound-evaluation?race_id='+race_id+'&forecast_request_id='+forecast_request_id)
        verify_response(report,forecast,result,race,forecast_request_id,utc_now()); guard()
        write_checked(folder,'evaluation.json',report); guard()
        manifest.update(status='COMPLETED', failure_reason=None)
    except BudgetExhausted:
        manifest.update(status='TIME_LIMIT_REACHED', failure_reason=REASONS['TIME_LIMIT_REACHED'])
    except ERRORS:
        manifest.update(status='STOPPED', failure_reason=REASONS['STOPPED'])
    return finalize_manifest(folder,manifest,guard)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('race-id','forecast-request-id','output-dir'): parser.add_argument('--'+flag,required=True)
    parser.add_argument('--execute',action='store_true'); args = parser.parse_args()
    try:
        result = run(args.race_id,args.forecast_request_id,args.output_dir,execute=args.execute)
    except ERRORS:
        print('NAME_BOUND_EVALUATION_STOPPED'); raise SystemExit(2)
    print(json.dumps(result or {'status':'DRY_RUN','network_requests':0,'official_source_requests':0},sort_keys=True))
    if result and result['status'] != 'COMPLETED': raise SystemExit(2)
