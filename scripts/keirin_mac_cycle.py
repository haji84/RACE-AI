"""Run one private KEIRIN video intake and evaluation cycle under macOS launchd.

Only reviewed input reaches the existing video learner. The cycle can run with
local files alone. Browser recording uses the existing source-approval checks.
Output profiles remain candidates and the report contains only aggregate data.
"""
from argparse import ArgumentParser
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from race_ai.keirin_note_view import _private_root
from scripts import keirin_market_third_evaluation as market
from scripts import keirin_video_corpus as corpus
from scripts import keirin_video_media as media
from scripts import keirin_video_rider_learning as learning
from scripts import keirin_video_sources as sources

JST = ZoneInfo('Asia/Tokyo')
GIB = 1024**3
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
INPUT_ERRORS = (ImportError, OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError)


@contextmanager
def _lock(path, *, wait=True):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'r+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _provider_refused(status):
    if not isinstance(status, str):
        raise ValueError('Invalid provider status.')
    return sources.source_refused(status)


def _private_file(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('A private regular file is required.')
    finally:
        os.close(fd)


def _capture(db, root, approval, browser, before):
    if approval is None:
        return 'NO_RECORDING_APPROVAL_CONFIGURED', 0
    if shutil.disk_usage(root).free < 50 * GIB:
        return 'HOLD_CAPTURE_STORAGE', 0
    digests = root/'digests'
    if digests.exists() or digests.is_symlink():
        _private_root(digests)
    attempts = digests/'attempts.jsonl'
    if attempts.exists() or attempts.is_symlink():
        _private_file(attempts)
        if any(_provider_refused(row['status']) for row in corpus.input_rows(attempts)):
            return 'HOLD_PROVIDER_REFUSAL', 0
    dates = {row[0] for row in db.execute('SELECT id FROM race WHERE event_status=? AND day<=?',
                                         ('finish_verified', before))}
    rows = sorted((row for row in corpus.pending(db, stage='continuous') if row['race_id'] in dates),
                  key=lambda row: row['race_id'], reverse=True)
    if not rows:
        return 'NO_ELIGIBLE_REPLAY', 0
    with TemporaryDirectory(dir=root) as temp:
        queue = Path(temp)/'queue.jsonl'
        media.atomic_jsonl(queue, rows)
        counts = sources.run(queue, digests, interval=3, pause=2, limit=1, executable=browser,
                             continuous=True, source_approval=approval, chromium_sandbox=True,
                             headless=False, stop_after_refusal=True)
    if any(_provider_refused(status) for status in counts):
        return 'HOLD_PROVIDER_REFUSAL', 0
    return ('RECORDED' if counts['captured'] else 'NO_NEW_RECORDING'), counts['captured']


def _has_verified_media(row, active):
    key = (row['race_id'], row['source_ref'])
    digest = row.get('media_sha256')
    if digest is not None:
        return (*key, digest) in active
    frames = row.get('evidence_frames') or []
    return bool(frames) and all((*key, frame['at_ms'], frame['sha256']) in active for frame in frames)


def _fit_rows(db, before, active):
    census = (row for row in corpus.census_rows(db) if row['race_date'] < before)
    reviewed = (row for row in corpus.training_rows(db) if row['race_date'] < before and _has_verified_media(row, active))
    return census, reviewed


def _fit(db, root, before, active):
    identity = sha256(before.encode())
    identity.update(sha256(Path(__file__).read_bytes()).digest())
    for module in (corpus, learning, media):
        identity.update(sha256(Path(module.__file__).read_bytes()).digest())
    for group in _fit_rows(db, before, active):
        identity.update(b'\n')
        for row in group:
            identity.update((corpus.pack(row)+'\n').encode())
    trial_id = identity.hexdigest()
    target = root/f'trial-{trial_id}'
    profiles_path = target/'profiles.jsonl'
    report_path = target/'scores.json'
    receipt_path = target/'checksums.json'
    if target.exists():
        expected = json.loads(receipt_path.read_bytes())
        for path in (profiles_path, report_path):
            with path.open('rb') as stream:
                if file_digest(stream, 'sha256').hexdigest() != expected[path.name]:
                    raise ValueError('Trial artifact checksum mismatch.')
        return 'TRIAL_PROFILE_REUSED', expected[profiles_path.name]
    census, reviewed = _fit_rows(db, before, active)
    summary, profiles = learning.study(census, reviewed, before=before)
    with TemporaryDirectory(dir=root) as temp:
        staging = Path(temp)/'trial'
        staging.mkdir(mode=0o700)
        learning.write_outputs(summary, profiles, profiles_path=staging/profiles_path.name,
                               report_path=staging/report_path.name)
        expected = {}
        for filename in (profiles_path.name, report_path.name):
            with (staging/filename).open('rb') as stream:
                expected[filename] = file_digest(stream, 'sha256').hexdigest()
        with corpus.output_file(staging/receipt_path.name) as file:
            json.dump(expected, file, sort_keys=True)
        staging.rename(target)
    return 'TRIAL_PROFILE_FITTED', expected[profiles_path.name]


def _video(root, before, census, manifest, bounds, reviewed, source_approval, browser):
    ledger = root/'corpus.sqlite'
    if census is None and not ledger.is_file():
        return {'state': 'WAITING_FOR_CENSUS'}
    if shutil.disk_usage(root).free < 40 * GIB:
        return {'state': 'HOLD_VIDEO_STORAGE'}
    _private_file(ledger)
    with closing(sqlite3.connect(ledger, timeout=30)) as db:
        corpus.setup(db)
        if census is not None:
            with db:
                for row in corpus.input_rows(census):
                    corpus.load_race(db, row)
        try:
            capture_state, recorded = _capture(db, root, source_approval, browser, before)
        except Exception:
            capture_state, recorded = 'HOLD_RECORDING_INPUT_OR_RUNTIME', 0
        manifests = [manifest] if manifest is not None else []
        digests = root/'digests'
        roots = [_private_root(digests)] if digests.exists() or digests.is_symlink() else []
        inventory = {}
        active, active_races, continuous = set(), set(), set()
        held_review_inputs = 0
        with db:
            if manifests or roots:
                media_db = root/'media.sqlite'
                _private_file(media_db)
                with _lock(root/'media.sqlite.lock', wait=False), closing(media.connect(media_db)) as connection:
                    inventory = media.verify_assets(connection, media.input_assets(manifests, roots), limit=24,
                                                    time_budget=120)
                    for row in media.verified_rows(connection):
                        corpus.load_media(db, row)
                        key = (row['race_id'], row['source_ref'])
                        active_races.add(row['race_id'])
                        if row['kind'] == 'frames':
                            active.update((*key, frame['at_ms'], frame['sha256']) for frame in row['frames'])
                        else:
                            active.add((*key, row['sha256']))
                            continuous.add(row['race_id'])
            for path, loader in ((bounds, corpus.load_bounds), (reviewed, corpus.load_review)):
                if path is not None:
                    for row in corpus.input_rows(path):
                        if _has_verified_media(row, active):
                            loader(db, row)
                        else:
                            held_review_inputs += 1
        with db:
            db.execute('BEGIN')
            status = corpus.report(db)
            _, candidates = _fit_rows(db, before, active)
            eligible = sum(row['value'] != 'unknown' for row in candidates)
            result = dict(state='VIDEO_LEDGER_CHECKED', capture_state=capture_state, recorded=recorded,
                          census_races=status['races'], media_races=len(active_races), continuous_media_races=len(continuous),
                          retained_media_races=status['races_with_verified_visual_evidence'], observation_count=eligible,
                          unverified_review_inputs=held_review_inputs,
                          inventory=inventory, model_state='WAITING_FOR_REVIEWED_OBSERVATIONS')
            if eligible:
                if shutil.disk_usage(root).free < 50 * GIB:
                    result['model_state'] = 'HOLD_TRAINING_STORAGE'
                else:
                    result['model_state'], result['trial_sha256'] = _fit(db, root, before, active)
        return result


def run_cycle(root, *, census=None, manifest=None, bounds=None, reviewed=None, source_approval=None,
              browser=CHROME, clock=lambda: datetime.now(timezone.utc)):
    root = _private_root(root)
    with _lock(root/'mac-cycle.lock', wait=False):
        now = clock()
        if now.utcoffset() is None:
            raise ValueError('A timezone-aware cycle clock is required.')
        try:
            market_third = market.evaluate_retained()
        except INPUT_ERRORS:
            market_third = {'candidate_disposition': 'HOLD_RETAINED_EVIDENCE_UNAVAILABLE'}
        try:
            video = _video(root, now.astimezone(JST).date().isoformat(), census, manifest, bounds,
                           reviewed, source_approval, browser)
        except INPUT_ERRORS:
            video = {'state': 'HOLD_VIDEO_INPUT_OR_RUNTIME'}
        result = dict(schema='KEIRIN_MAC_CYCLE_V1', checked_at=now.isoformat(), video=video,
                      market_third=market_third, production_weights_promoted=False)
        with corpus.output_file(root/'cycle-report.json') as report:
            json.dump(result, report, ensure_ascii=False, allow_nan=False, sort_keys=True)
        return result


def main(argv=None):
    parser = ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--input-dir', type=Path, help='Optional private directory with the documented local inputs.')
    for name in ('census', 'manifest', 'bounds', 'reviewed', 'source-approval'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--browser', default=CHROME)
    args = parser.parse_args(argv)
    os.umask(0o077)
    options = vars(args)
    root = options.pop('state_dir')
    try:
        inputs = options.pop('input_dir')
        if inputs is not None:
            inputs = _private_root(inputs)
            for key, name in (('census', 'census.jsonl'), ('manifest', 'owner-films.jsonl'),
                              ('bounds', 'crossings.jsonl'), ('reviewed', 'reviewed.jsonl'),
                              ('source_approval', 'reviewed-source-approval.json')):
                path = inputs/name
                if options[key] is None and path.is_file():
                    options[key] = path
        result = run_cycle(root, **options)
    except BlockingIOError:
        print(json.dumps({'state': 'KEIRIN_MAC_CYCLE_ALREADY_RUNNING'}))
        return 0
    except INPUT_ERRORS:
        print(json.dumps({'state': 'HOLD_KEIRIN_MAC_CYCLE_RUNTIME'}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
