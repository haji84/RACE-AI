"""Save a bounded current-day research cohort without replacing older forecasts.

One next eligible race per active venue. No official source requests or user
purchases. Existing scoped Preview OIDC and server-side generation only.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_research_prediction import verify_receipt, instant, JST
from publish_day_feed import get_json, validate_target, canonical_sha
from publish_race_updates import workflow_session
from web.evaluation_contract import _checked_prediction

REVIEW = 'user-confirmation-2026-10-15-official-facts'
MARGIN = timedelta(seconds=120)


def choose_cohort(feed, now, max_races=24):
    if type(max_races) is not int or not 1 <= max_races <= 24:
        raise ValueError('COHORT_LIMIT_INVALID')
    if not isinstance(feed, dict):
        raise ValueError('CURRENT_APPROVED_PROGRAM_REQUIRED')
    day = now.astimezone(JST).date().isoformat()
    venues = feed.get('venues', [])
    if (feed.get('date_jst') != day or feed.get('schedule_verified') is not True
            or feed.get('redistribution_authorized') is not True or not isinstance(venues, list)
            or len(venues) != 24 or not all(isinstance(v, dict) for v in venues)
            or {v.get('venue') for v in venues} != {f'{i:02}' for i in range(1, 25)}):
        raise ValueError('CURRENT_APPROVED_PROGRAM_REQUIRED')
    selected, seen = [], set()
    for venue in venues:
        candidates = []
        for race in venue.get('races', []):
            identifier = race.get('race_id')
            if (not isinstance(identifier, str)
                    or not re.fullmatch(day.replace('-', '')+'-'+venue['venue']+r'-(0[1-9]|1[0-2])', identifier)
                    or identifier in seen):
                raise ValueError('COHORT_PROGRAM_IDENTITY_INVALID')
            seen.add(identifier)
            closed = instant(race['closed_at'])
            if closed.astimezone(JST).date().isoformat() != day:
                raise ValueError('COHORT_PROGRAM_IDENTITY_INVALID')
            if venue.get('status') == 'READY' and len(race.get('boats', [])) == 6 and closed > now + MARGIN:
                candidates.append(race)
        if candidates:
            selected.append(min(candidates, key=lambda r: (instant(r['closed_at']), r['race_id'])))
    return sorted(selected, key=lambda r: (instant(r['closed_at']), r['race_id']))[:max_races]


def _write(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if not 0 < len(raw) <= 256000:
        raise ValueError('COHORT_BACKUP_SIZE_INVALID')
    with path.open('xb') as handle:
        handle.write(raw)
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def _safe_failure(error):
    code = str(error)
    if re.fullmatch(r'DAY_PUBLISH_HTTP_[0-9]{3}', code):
        return code
    return type(error).__name__


def run(output_dir, *, execute=False, max_races=24):
    if type(max_races) is not int or not 1 <= max_races <= 24:
        raise ValueError('COHORT_LIMIT_INVALID')
    if not execute:
        print(json.dumps(dict(result='DRY_RUN', network_requests=0, official_source_requests=0, max_races=max_races)))
        return
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError('COHORT_OUTPUT_ALREADY_EXISTS')
    url = os.environ.get('RACE_AI_RESEARCH_PUBLISH_URL', '')
    if not url.endswith('/api/publish-prediction'):
        raise ValueError('RESEARCH_TARGET_INVALID')
    validate_target(url[:-len('publish-prediction')]+'publish-day')
    commit = os.environ.get('RACE_AI_RESEARCH_COMMIT_SHA', '')
    request_id = os.environ.get('GITHUB_RUN_ID', '')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT', '')
    if not re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}', request_id):
        raise ValueError('RESEARCH_REQUEST_ID_INVALID')
    opener, headers = workflow_session(commit)
    base = url.rsplit('/', 1)[0]
    feed = get_json(opener, urllib.request.Request(base+'/today', headers=headers), limit=6_000_000)
    start = datetime.now(timezone.utc)
    races = choose_cohort(feed, start, max_races)
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema_version=1, date_jst=feed['date_jst'], request_id=request_id, commit_sha=commit,
        started_at=start.isoformat(), finished_at=None, status='COMPLETED',
        selected_race_ids=[r['race_id'] for r in races], saved=[], preserved=[], skipped=[], failure=None,
        validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[], official_source_requests=0)
    try:
        for race in races:
            identifier = race['race_id']
            clock = datetime.now(timezone.utc)
            if clock.astimezone(JST).date().isoformat() != feed['date_jst'] or instant(race['closed_at']) <= clock + MARGIN:
                manifest['skipped'].append(dict(race_id=identifier, reason='JST_DAY_OR_CUTOFF_MARGIN_CHANGED'))
                continue
            try:
                existing = get_json(opener, urllib.request.Request(base+'/prediction?race_id='+identifier, headers=headers), limit=256000)
            except RuntimeError as error:
                if str(error) != 'DAY_PUBLISH_HTTP_404':
                    raise
                existing = None
            if existing is not None:
                checked = _checked_prediction(existing, race, datetime.now(timezone.utc), clock.astimezone(JST).date(), instant(race['closed_at']))
                manifest['preserved'].append(dict(race_id=identifier, snapshot_id=checked['snapshot']['snapshot_id'],
                    cloud_saved_at=existing['cloud_saved_at'], receipt_sha256=canonical_sha(existing)))
                continue
            # Network delay may consume the remaining margin: recheck immediately
            # before backing up and sending a new publication request.
            clock = datetime.now(timezone.utc)
            if clock.astimezone(JST).date().isoformat() != feed['date_jst'] or instant(race['closed_at']) <= clock + MARGIN:
                manifest['skipped'].append(dict(race_id=identifier, reason='JST_DAY_OR_CUTOFF_MARGIN_CHANGED'))
                continue
            request = dict(publication_review=REVIEW, race_id=identifier, request_id=request_id)
            request_path = output_dir/(identifier+'.request.json')
            request_backup = _write(request_path, request)
            publication = urllib.request.Request(url, data=request_path.read_bytes(), method='POST', headers=headers)
            clock = datetime.now(timezone.utc)
            if clock.astimezone(JST).date().isoformat() != feed['date_jst'] or instant(race['closed_at']) <= clock + MARGIN:
                manifest['skipped'].append(dict(race_id=identifier, reason='JST_DAY_OR_CUTOFF_MARGIN_CHANGED'))
                continue
            response = get_json(opener, publication, limit=16384)
            receipt = get_json(opener, urllib.request.Request(base+'/prediction?race_id='+identifier+'&request_id='+request_id, headers=headers), limit=256000)
            verify_receipt(receipt, race, response, commit, request_id, datetime.now(timezone.utc))
            receipt_backup = _write(output_dir/(identifier+'.receipt.json'), receipt)
            snapshot = receipt['snapshot']
            manifest['saved'].append(dict(race_id=identifier, snapshot_id=snapshot['snapshot_id'], as_of=snapshot['as_of'],
                cloud_saved_at=receipt['cloud_saved_at'], closed_at=race['closed_at'],
                request_backup=request_backup, receipt_backup=receipt_backup))
    except (ValueError, RuntimeError, OSError) as error:
        manifest['status'] = 'STOPPED'
        manifest['failure'] = _safe_failure(error)
        raise
    finally:
        manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
        _write(output_dir/'manifest.json', manifest)
        print(json.dumps(dict(result='RESEARCH_COHORT_'+manifest['status'], date_jst=manifest['date_jst'],
            selected=len(races), saved=len(manifest['saved']), preserved=len(manifest['preserved']), skipped=len(manifest['skipped']),
            manifest_sha256=canonical_sha(manifest), official_source_requests=0, validation_status='UNVALIDATED', purchase_decision='skip'), sort_keys=True))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--max-races', type=int, default=24)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        run(args.output_dir, execute=args.execute, max_races=args.max_races)
    except (ValueError, RuntimeError, OSError) as error:
        print('SAFE_STOP: bounded national research cohort '+_safe_failure(error), flush=True)
        raise SystemExit(2)
