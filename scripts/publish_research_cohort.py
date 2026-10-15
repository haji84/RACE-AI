"""Save a bounded current-day research cohort without replacing older forecasts.

Defaults to one next eligible race per active venue; all-upcoming scans at most
288 races. Each batch creates at most 24 new request/receipt pairs, independently
of preserved receipt reads. No official source requests or user purchases.
Existing scoped Preview OIDC and server-side generation only.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from time import monotonic
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_research_prediction import verify_receipt, instant, JST
from publish_day_feed import get_json, validate_target, canonical_sha
from publish_race_updates import workflow_session
from web.evaluation_contract import _checked_prediction

REVIEW = 'user-confirmation-2026-10-15-official-facts'
MARGIN = timedelta(seconds=120)
MAX_CANDIDATES = 24 * 12
MAX_READS = 1 + MAX_CANDIDATES + 24  # today, existing receipts, new pinned receipts
HTTP_SECONDS = 30


class _BudgetStop(Exception):
    """An ordinary bounded batch stop; never hide an invalid receipt as a stop."""


def _selection_options(max_races, selection):
    if type(max_races) is not int or not 1 <= max_races <= 24:
        raise ValueError('COHORT_LIMIT_INVALID')
    if selection not in ('next-per-venue', 'all-upcoming'):
        raise ValueError('COHORT_SELECTION_INVALID')


def choose_cohort(feed, now, max_races=24, *, selection='next-per-venue'):
    _selection_options(max_races, selection)
    if not isinstance(feed, dict):
        raise ValueError('CURRENT_APPROVED_PROGRAM_REQUIRED')
    day = now.astimezone(JST).date().isoformat()
    venues = feed.get('venues', [])
    if (feed.get('date_jst') != day or feed.get('schedule_verified') is not True
            or feed.get('redistribution_authorized') is not True or not isinstance(venues, list)
            or len(venues) != 24 or not all(isinstance(v, dict) for v in venues)
            or not all(isinstance(v.get('venue'), str) for v in venues)
            or {v.get('venue') for v in venues} != {f'{i:02}' for i in range(1, 25)}):
        raise ValueError('CURRENT_APPROVED_PROGRAM_REQUIRED')
    selected, seen = [], set()
    for venue in venues:
        candidates = []
        program = venue.get('races', [])
        if not isinstance(program, list) or len(program) > 12:
            raise ValueError('COHORT_PROGRAM_IDENTITY_INVALID')
        for race in program:
            if not isinstance(race, dict):
                raise ValueError('COHORT_PROGRAM_IDENTITY_INVALID')
            identifier = race.get('race_id')
            if (not isinstance(identifier, str)
                    or not re.fullmatch(day.replace('-', '')+'-'+venue['venue']+r'-(0[1-9]|1[0-2])', identifier)
                    or identifier in seen):
                raise ValueError('COHORT_PROGRAM_IDENTITY_INVALID')
            seen.add(identifier)
            try:
                closed = instant(race['closed_at'])
            except (KeyError, TypeError, ValueError):
                raise ValueError('COHORT_PROGRAM_IDENTITY_INVALID') from None
            if closed.astimezone(JST).date().isoformat() != day:
                raise ValueError('COHORT_PROGRAM_IDENTITY_INVALID')
            boats = race.get('boats', [])
            if not isinstance(boats, list):
                raise ValueError('COHORT_PROGRAM_IDENTITY_INVALID')
            if venue.get('status') == 'READY' and len(boats) == 6 and closed > now + MARGIN:
                candidates.append(race)
        if candidates:
            if selection == 'all-upcoming':
                selected.extend(candidates)
            else:
                selected.append(min(candidates, key=lambda r: (instant(r['closed_at']), r['race_id'])))
    ordered = sorted(selected, key=lambda r: (instant(r['closed_at']), r['race_id']))
    return ordered if selection == 'all-upcoming' else ordered[:max_races]


def _canonical(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if not 0 < len(raw) <= 256000:
        raise ValueError('COHORT_BACKUP_SIZE_INVALID')
    return raw


def _read_backup(path, value):
    with path.open('rb') as handle:
        raw = handle.read(256001)
    if raw != _canonical(value):
        raise ValueError('COHORT_BACKUP_READBACK_MISMATCH')
    return raw


def _write(path, value):
    raw = _canonical(value)
    with path.open('xb') as handle:
        handle.write(raw)
    _read_backup(path, value)
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def _safe_failure(error):
    code = str(error)
    if re.fullmatch(r'DAY_PUBLISH_HTTP_[0-9]{3}', code):
        return code
    return type(error).__name__


def run(output_dir, *, execute=False, max_races=24, selection='next-per-venue', max_seconds=240, max_reads=None):
    """Save a sequential batch, preserving checked existing receipts without POST.

    max_races caps request backup slots, including requests abandoned after I/O.
    This conservatively bounds POSTs and keeps at most 49 files. Reads count feed,
    existing lookup (including 404), and pinned receipt readback, excluding OIDC.
    not_attempted identifies candidates whose processing never started; pending
    also includes an interrupted candidate without a verified or cutoff outcome.
    """
    _selection_options(max_races, selection)
    if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 240:
        raise ValueError('COHORT_TIME_LIMIT_INVALID')
    if max_reads is None:
        max_reads = MAX_READS if selection == 'all-upcoming' else 1 + max_races * 2
    if type(max_reads) is not int or not 1 <= max_reads <= MAX_READS:
        raise ValueError('COHORT_READ_LIMIT_INVALID')
    if not execute:
        print(json.dumps(dict(result='DRY_RUN', network_requests=0, official_source_requests=0,
            max_races=max_races, selection=selection, max_seconds=max_seconds, max_reads=max_reads)))
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
    base = url.rsplit('/', 1)[0]
    began = monotonic()
    start = datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema_version=2, date_jst=None, request_id=request_id, commit_sha=commit,
        started_at=start.isoformat(), finished_at=None, status='COMPLETED',
        selection=selection, max_races=max_races, max_seconds=max_seconds, max_reads=max_reads,
        reads_used=0, write_slots_used=0, posts_attempted=0, elapsed_seconds=0,
        selected_race_ids=[], attempted_race_ids=[], not_attempted_race_ids=[], pending_race_ids=[],
        saved=[], preserved=[], skipped=[], request_backups=[], failure=None, failure_race_id=None,
        validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[], official_source_requests=0)
    races, identifier = [], None

    def check_time(reserve=0):
        elapsed = monotonic() - began
        if elapsed >= max_seconds or elapsed + reserve > max_seconds:
            raise _BudgetStop('TIME_LIMIT_REACHED')

    def check_reads():
        if manifest['reads_used'] >= max_reads:
            raise _BudgetStop('READ_LIMIT_REACHED')

    def read(request, *, limit):
        check_time(HTTP_SECONDS)
        check_reads()
        manifest['reads_used'] += 1
        return get_json(opener, request, limit=limit)

    try:
        check_time(HTTP_SECONDS)
        opener, headers = workflow_session(commit)
        feed = read(urllib.request.Request(base+'/today', headers=headers), limit=6_000_000)
        races = choose_cohort(feed, start, max_races, selection=selection)
        manifest['date_jst'] = feed['date_jst']
        manifest['selected_race_ids'] = [r['race_id'] for r in races]
        check_time()
        for race in races:
            identifier = None
            check_time(HTTP_SECONDS)
            if manifest['write_slots_used'] >= max_races:
                raise _BudgetStop('BATCH_LIMIT_REACHED')
            check_reads()
            identifier = race['race_id']
            manifest['attempted_race_ids'].append(identifier)
            clock = datetime.now(timezone.utc)
            if clock.astimezone(JST).date().isoformat() != feed['date_jst'] or instant(race['closed_at']) <= clock + MARGIN:
                manifest['skipped'].append(dict(race_id=identifier, reason='JST_DAY_OR_CUTOFF_MARGIN_CHANGED'))
                continue
            try:
                existing = read(urllib.request.Request(base+'/prediction?race_id='+identifier, headers=headers), limit=256000)
                missing = False
            except RuntimeError as error:
                if str(error) != 'DAY_PUBLISH_HTTP_404':
                    raise
                missing = True
            if not missing:
                if existing is None:
                    raise ValueError('COHORT_EXISTING_RECEIPT_INVALID')
                checked = _checked_prediction(existing, race, datetime.now(timezone.utc), clock.astimezone(JST).date(), instant(race['closed_at']))
                manifest['preserved'].append(dict(race_id=identifier, snapshot_id=checked['snapshot']['snapshot_id'],
                    request_id=existing['request_id'], as_of=checked['snapshot']['as_of'],
                    generated_at=checked['snapshot']['generated_at'], cloud_saved_at=existing['cloud_saved_at'],
                    closed_at=race['closed_at'], receipt_sha256=canonical_sha(existing)))
                check_time()
                continue
            # Network delay may consume the remaining margin: recheck immediately
            # before backing up and sending a new publication request. Reserve a
            # pinned read and both HTTP timeouts before starting a new write.
            check_reads()
            check_time(2 * HTTP_SECONDS)
            clock = datetime.now(timezone.utc)
            if clock.astimezone(JST).date().isoformat() != feed['date_jst'] or instant(race['closed_at']) <= clock + MARGIN:
                manifest['skipped'].append(dict(race_id=identifier, reason='JST_DAY_OR_CUTOFF_MARGIN_CHANGED'))
                continue
            request = dict(publication_review=REVIEW, race_id=identifier, request_id=request_id)
            request_path = output_dir/(identifier+'.request.json')
            manifest['write_slots_used'] += 1
            request_backup = _write(request_path, request)
            manifest['request_backups'].append(dict(race_id=identifier, request_backup=request_backup))
            publication = urllib.request.Request(url, data=_read_backup(request_path, request), method='POST', headers=headers)
            check_time(2 * HTTP_SECONDS)
            clock = datetime.now(timezone.utc)
            if clock.astimezone(JST).date().isoformat() != feed['date_jst'] or instant(race['closed_at']) <= clock + MARGIN:
                manifest['skipped'].append(dict(race_id=identifier, reason='JST_DAY_OR_CUTOFF_MARGIN_CHANGED'))
                continue
            manifest['posts_attempted'] += 1
            response = get_json(opener, publication, limit=16384)
            if not isinstance(response, dict):
                raise ValueError('COHORT_PUBLICATION_RESULT_INVALID')
            receipt = read(urllib.request.Request(base+'/prediction?race_id='+identifier+'&request_id='+request_id, headers=headers), limit=256000)
            verify_receipt(receipt, race, response, commit, request_id, datetime.now(timezone.utc))
            receipt_backup = _write(output_dir/(identifier+'.receipt.json'), receipt)
            snapshot = receipt['snapshot']
            manifest['saved'].append(dict(race_id=identifier, snapshot_id=snapshot['snapshot_id'], as_of=snapshot['as_of'],
                generated_at=snapshot['generated_at'], cloud_saved_at=receipt['cloud_saved_at'], closed_at=race['closed_at'],
                request_backup=request_backup, receipt_backup=receipt_backup))
            check_time()
        check_time()
    except _BudgetStop as error:
        manifest['status'] = str(error)
    except (ValueError, RuntimeError, OSError) as error:
        manifest['status'] = 'STOPPED'
        manifest['failure'] = _safe_failure(error)
        manifest['failure_race_id'] = identifier
        raise
    finally:
        manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
        manifest['elapsed_seconds'] = round(monotonic() - began, 6)
        attempted = set(manifest['attempted_race_ids'])
        finished = {r['race_id'] for kind in ('saved', 'preserved', 'skipped') for r in manifest[kind]}
        manifest['not_attempted_race_ids'] = [r['race_id'] for r in races if r['race_id'] not in attempted]
        manifest['pending_race_ids'] = [r['race_id'] for r in races if r['race_id'] not in finished]
        _write(output_dir/'manifest.json', manifest)
        print(json.dumps(dict(result='RESEARCH_COHORT_'+manifest['status'], date_jst=manifest['date_jst'],
            selected=len(races), saved=len(manifest['saved']), preserved=len(manifest['preserved']), skipped=len(manifest['skipped']),
            attempted=len(attempted), not_attempted=len(manifest['not_attempted_race_ids']), pending=len(manifest['pending_race_ids']),
            selection=selection, reads_used=manifest['reads_used'], write_slots_used=manifest['write_slots_used'],
            posts_attempted=manifest['posts_attempted'], elapsed_seconds=manifest['elapsed_seconds'],
            manifest_sha256=canonical_sha(manifest), official_source_requests=0, validation_status='UNVALIDATED', purchase_decision='skip'), sort_keys=True))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--max-races', type=int, default=24)
    parser.add_argument('--selection', choices=('next-per-venue', 'all-upcoming'), default='next-per-venue')
    parser.add_argument('--max-seconds', type=float, default=240)
    parser.add_argument('--max-reads', type=int)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        run(args.output_dir, execute=args.execute, max_races=args.max_races, selection=args.selection,
            max_seconds=args.max_seconds, max_reads=args.max_reads)
    except (ValueError, RuntimeError, OSError) as error:
        print('SAFE_STOP: bounded national research cohort '+_safe_failure(error), flush=True)
        raise SystemExit(2)
