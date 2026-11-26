"""Run one private KEIRIN video intake and evaluation cycle under macOS launchd.

Only reviewed input reaches the existing video learner. The cycle can run with
local files alone. Browser recording uses the existing source-approval checks.
Output profiles remain candidates and the report contains only aggregate data.
"""
from argparse import ArgumentParser
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
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
from time import monotonic
from zoneinfo import ZoneInfo

from race_ai.keirin_comparison_snapshot import _read_regular
from race_ai.keirin_note_view import _create, _private_root
from scripts import keirin_market_third_evaluation as market
from scripts import keirin_video_corpus as corpus
from scripts import keirin_video_media as media
from scripts import keirin_video_rider_learning as learning
from scripts import keirin_video_sources as sources

JST = ZoneInfo('Asia/Tokyo')
GIB = 1024**3
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
INPUT_ERRORS = (ImportError, OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError)
REPLAY_RETRY_INTERVAL = timedelta(minutes=30)
REPLAY_MAX_ATTEMPTS = 3


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


def _capture_history(digests):
    if digests.exists() or digests.is_symlink():
        _private_root(digests)
    attempts = digests/'attempts.jsonl'
    if attempts.exists() or attempts.is_symlink():
        _private_file(attempts)
        yield from corpus.input_rows(attempts)


def _capture(db, root, approval, browser, before):
    if approval is None:
        return 'NO_RECORDING_APPROVAL_CONFIGURED', 0
    if shutil.disk_usage(root).free < 50 * GIB:
        return 'HOLD_CAPTURE_STORAGE', 0
    digests = root/'digests'
    if any(_provider_refused(row['status']) for row in _capture_history(digests)):
        return 'HOLD_PROVIDER_REFUSAL', 0
    dates = {row[0] for row in db.execute('SELECT id FROM race WHERE event_status=? AND day<=?',
                                         ('finish_verified', before))}
    dates.discard(sources.KOMATSUSHIMA_REPLAY_RACE)
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


def _register_replay_roster(root, row, race, full_finish):
    ledger = root/'corpus.sqlite'
    _private_file(ledger)
    with closing(sqlite3.connect(ledger, timeout=30)) as db:
        corpus.setup(db)
        with db:
            corpus.load_race(db, dict(race_id=row['race_id'], race_date=row['race_date'],
                roster_complete=True, event_status='finish_verified' if full_finish else 'unknown',
                riders=[dict(car=starter['car'], rider_id=starter['registration_id']) for starter in race['starters']]))


def _replay_media_state(root, folder, key, url, approval, pinned_at, now):
    folder = _private_root(folder)
    if approval.continuous:
        sources.check_clip(folder, key, url)
        receipt_name = 'clip.json'
    else:
        sources.validate_receipt(folder, key, url)
        receipt_name = 'overview.json'
    proof = json.loads(_read_regular(folder/'source-approval.json', 4096))
    expected = dict(race_id=sources.KOMATSUSHIMA_REPLAY_RACE, source_ref=url,
                    decision_sha256=approval.decision_sha256, rights_sha256=approval.rights_sha256,
                    permission_basis=approval.permission_basis)
    if not approval.continuous:
        expected['capture_mode'] = sources.REPLAY_FRAME_MODE
    receipt = json.loads(_read_regular(folder/receipt_name, 16 * 1024))
    observed = datetime.fromisoformat(receipt['observed_at_utc'])
    if (proof != expected or approval.continuous and receipt.get('browser_player_ended') is not True
            or not pinned_at <= observed <= now):
        raise ValueError('recording does not match the settled replay permission')
    ledger = root/'media.sqlite'
    if ledger.is_file():
        _private_file(ledger)
        with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro', uri=True)) as db:
            verified = list(media.verified_rows(db, race_id=sources.KOMATSUSHIMA_REPLAY_RACE))
        if approval.continuous:
            if any(row.get('sha256') == receipt['sha256'] and row['source_ref'] == receipt['source_ref']
                   for row in verified):
                return 'REPLAY_MEDIA_VERIFIED'
        else:
            expected_frames = {(round(item['video_seconds'] * 1000), item['frame_sha256'])
                               for item in receipt['frames']}
            if any(row['kind'] == 'frames' and row['source_ref'] == url and expected_frames == {
                    (item['at_ms'], item['sha256']) for item in row['frames']} for row in verified):
                return 'REPLAY_FRAMES_VERIFIED'
    return ('REPLAY_RECORDED_AWAITING_MEDIA_VERIFICATION' if approval.continuous
            else 'REPLAY_FRAMES_AWAITING_MEDIA_VERIFICATION')


def _capture_settled_replay(root, request, approval_path, settled, video, browser, clock):
    from scripts import keirin_mac_shadow_result as shadow

    receipt_paths = {
        'SHADOW_RESULT_SCORED': 'official-result.json',
        'SHADOW_PUBLIC_PODIUM_SCORED': 'github-public/published-result.json',
        'SHADOW_SECONDARY_PODIUM_SCORED': 'site-two-source/result.json',
    }
    receipt_name = receipt_paths.get(settled['state'])
    if receipt_name is None:
        return 'WAITING_FOR_SHADOW_SETTLEMENT'
    now = clock()
    schedule, race, start, _, _, _, pin, _ = shadow._inputs(request, now)
    key = sources.KOMATSUSHIMA_REPLAY_KEY
    if race['race_id'] != key or race['venue'] != '小松島' or now < start:
        raise ValueError('the settled replay requires the frozen Komatsushima race')
    shadow_state = root/'keirin-mac-shadow-results'/key
    if shadow._read(shadow_state/'request-pins.json', 4096) != pin:
        raise ValueError('settled replay prediction is no longer pinned')
    receipt_path = shadow_state/receipt_name
    shadow._read(receipt_path, shadow.MAX_RECEIPT_BYTES)
    settled_sha = sha256(_read_regular(receipt_path, shadow.MAX_RECEIPT_BYTES)).hexdigest()
    try:
        shadow._read(approval_path, 16 * 1024)
        approval = sources.load_source_approval(approval_path, continuous=True)
        url = approval.settled_replay_url
        sources.require_capture_scope(approval, key, url, continuous=True)
    except INPUT_ERRORS:
        return 'HOLD_REPLAY_PERMISSION_INVALID'

    digests = root/'digests'
    history = list(_capture_history(digests))
    if any(_provider_refused(row['status']) for row in history):
        return 'HOLD_PROVIDER_REFUSAL'
    race_id = sources.KOMATSUSHIMA_REPLAY_RACE
    row = dict(race_id=race_id, race_date=schedule['day_jst'], race_detail_url=url)
    previous = [entry for entry in history if entry.get('race_id') == race_id]
    if any(entry.get('source_ref') != url for entry in previous):
        raise ValueError('the recorded replay source has changed')

    work = _private_root(root/'komatsushima-replay')
    actor = work/'actor-pin.json'
    folder = digests/key
    binding = dict(race_id=race_id, replay_url=url, settlement_sha256=settled_sha,
                   decision_sha256=approval.decision_sha256, **pin)
    if actor.exists() or actor.is_symlink():
        previous_pin = shadow._read(actor, 4096)
        pinned_at = datetime.fromisoformat(previous_pin.pop('admitted_at'))
        if previous_pin != binding or not start <= pinned_at <= now:
            raise ValueError('previous replay authorization does not match')
    else:
        if previous or folder.exists() or folder.is_symlink() or any(work.glob('poll-*.json')):
            raise ValueError('prior replay work requires its original actor pin')
        pinned_at = now
        shadow._preserve(actor, dict(binding, admitted_at=now.isoformat()))

    frame_path = Path(approval_path).with_name('komatsushima-frame-analysis-approval.json')
    frame_pin = work/'frame-actor-pin.json'
    if not (folder/'clip.json').is_file() and (
            frame_path.exists() or frame_path.is_symlink() or frame_pin.exists() or frame_pin.is_symlink()):
        try:
            shadow._read(frame_path, 16 * 1024)
            frame_approval = sources.load_source_approval(frame_path, continuous=False)
            sources.require_capture_scope(frame_approval, key, url, continuous=False)
        except INPUT_ERRORS:
            return 'HOLD_REPLAY_PERMISSION_INVALID'
        frame_binding = dict(binding, decision_sha256=frame_approval.decision_sha256,
                             capture_mode=sources.REPLAY_FRAME_MODE)
        if frame_pin.exists() or frame_pin.is_symlink():
            previous_frame = shadow._read(frame_pin, 4096)
            frame_at = datetime.fromisoformat(previous_frame.pop('admitted_at'))
            if previous_frame != frame_binding or not pinned_at <= frame_at <= now:
                raise ValueError('previous frame inspection approval does not match')
        else:
            if folder.exists() or folder.is_symlink():
                raise ValueError('prior frame inspection requires its original actor pin')
            frame_at = now
            shadow._preserve(frame_pin, dict(frame_binding, admitted_at=frame_at.isoformat()))
        approval, approval_path, pinned_at = frame_approval, frame_path, frame_at

    if folder.exists() or folder.is_symlink():
        return _replay_media_state(root, folder, key, url, approval, pinned_at, now)
    if video.get('capture_state') == 'RECORDED':
        return 'REPLAY_DEFERRED_EXISTING_CAPTURE'
    if shutil.disk_usage(root).free < 50 * GIB:
        return 'HOLD_CAPTURE_STORAGE'
    retryable = {sources.RESULT_PAGE_UNPUBLISHED, sources.DIGEST_BUTTON_UNAVAILABLE}
    # The foreground dialog binding was verified after the original player selection stopped.
    # A new frame approval can use an existing attempt slot after that specific hold.
    if not approval.continuous:
        retryable.add(sources.AMBIGUOUS_PLAYER)
    if previous and previous[-1]['status'] not in retryable:
        return 'HOLD_REPLAY_SOURCE_UNVERIFIED'
    if sum(1 for _ in work.glob('poll-*.json')) != len(previous):
        return 'HOLD_REPLAY_ATTEMPT_UNVERIFIED'
    hold, _ = shadow._claim_poll(work, now, REPLAY_MAX_ATTEMPTS, REPLAY_RETRY_INTERVAL)
    if hold:
        return ('WAITING_FOR_REPLAY_RETRY_INTERVAL' if hold == 'WAITING_FOR_OFFICIAL_POLL_INTERVAL'
                else 'HOLD_REPLAY_ATTEMPT_LIMIT')
    _register_replay_roster(root, row, race, settled['state'] == 'SHADOW_RESULT_SCORED')
    with TemporaryDirectory(dir=root) as folder:
        queue = Path(folder)/'scoped-replay.jsonl'
        media.atomic_jsonl(queue, [row])
        counts = sources.run(queue, digests, interval=3 if approval.continuous else 4, pause=2,
                             limit=1, executable=browser, continuous=approval.continuous,
                             source_approval=approval_path, chromium_sandbox=True,
                             headless=False, stop_after_refusal=True, retry_failed=bool(previous),
                             settled_replay_url=url, settled_replay_decision_sha256=approval.decision_sha256)
    if any(_provider_refused(status) for status in counts):
        return 'HOLD_PROVIDER_REFUSAL'
    if counts['captured'] or counts['reused']:
        return ('REPLAY_RECORDED_AWAITING_MEDIA_VERIFICATION' if approval.continuous
                else 'REPLAY_FRAMES_AWAITING_MEDIA_VERIFICATION')
    if retryable.intersection(counts):
        return 'WAITING_FOR_REPLAY_PUBLICATION'
    return 'HOLD_REPLAY_SOURCE_UNVERIFIED'


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


def _track(db, root, request, clips):
    if request is None:
        return {'state': 'NO_TRACKING_REQUEST'}
    from scripts import keirin_video_tracking as tracking

    if shutil.disk_usage(root).free < 50 * GIB:
        return {'state': 'HOLD_TRACKING_STORAGE'}
    row = json.loads(_read_regular(request, 2048))
    if type(row) is not dict or set(row) != {'race_id', 'media_sha256'}:
        raise ValueError('Tracking requires a race and its reviewed footage SHA.')
    rid, digest = row['race_id'], row['media_sha256']
    if rid == sources.KOMATSUSHIMA_REPLAY_RACE:
        return {'state': 'HOLD_REPLAY_LAYOUT_CALIBRATION'}
    tracking._validate_race(rid)
    if not tracking._hex(digest):
        raise ValueError('Invalid tracking media SHA.')
    media_path = clips.get((rid, digest))
    if media_path is None:
        return {'state': 'WAITING_FOR_VERIFIED_TRACKING_MEDIA'}
    roster = db.execute('SELECT complete_roster, event_status FROM race WHERE id=?', (rid,)).fetchone()
    if roster is None or tuple(roster) != (1, 'finish_verified'):
        return {'state': 'WAITING_FOR_VERIFIED_TRACKING_ROSTER'}
    cars = [car for car, in db.execute(
        'SELECT car FROM starter WHERE race=? ORDER BY car', (rid,))]
    engine = sha256(Path(tracking.__file__).read_bytes()).hexdigest()
    key = sha256(corpus.pack([rid, digest, cars, engine]).encode()).hexdigest()
    target = root/f'tracks-{key}'
    if target.exists() or target.is_symlink():
        _private_root(target)
        track_bytes = _read_regular(target/'tracks.json', 2 * 1024 * 1024)
        receipt = json.loads(_read_regular(target/'receipt.json', 2048))
        if (type(receipt) is not dict or set(receipt) != {
                'tracks_sha256', 'engine_sha256', 'sampled_frames', 'analysis_ms'}
                or receipt['tracks_sha256'] != sha256(track_bytes).hexdigest()
                or receipt['engine_sha256'] != engine
                or type(receipt['sampled_frames']) is not int or not 0 < receipt['sampled_frames'] <= tracking.MAX_SECONDS*tracking.FPS
                or type(receipt['analysis_ms']) is not int or receipt['analysis_ms'] < 0):
            raise ValueError('The stored tracking output changed.')
        return dict(receipt, state='TRACKS_REUSED')
    start = monotonic()
    tracks = tracking._track_clip(media_path, digest, rid, cars)
    track_bytes = tracking._json(tracks)
    receipt = dict(tracks_sha256=sha256(track_bytes).hexdigest(), engine_sha256=engine,
                   sampled_frames=len(tracks['tracks']), analysis_ms=round(1000 * (monotonic()-start)))
    with TemporaryDirectory(dir=root) as temp:
        staging = Path(temp)/'tracks'
        staging.mkdir(mode=0o700)
        _create(staging/'tracks.json', track_bytes)
        _create(staging/'receipt.json', tracking._json(receipt))
        staging.rename(target)
    return dict(receipt, state='TRACKS_GENERATED')


def _video(root, before, census, manifest, bounds, reviewed, source_approval, track_request, browser):
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
        clips = {}
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
                            if track_request is not None and row['start_ms'] == 0:
                                clips[row['race_id'], row['sha256']] = Path(row['path'])
            for path, loader in ((bounds, corpus.load_bounds), (reviewed, corpus.load_review)):
                if path is not None:
                    for row in corpus.input_rows(path):
                        if _has_verified_media(row, active):
                            loader(db, row)
                        else:
                            held_review_inputs += 1
        try:
            tracking = _track(db, root, track_request, clips)
        except INPUT_ERRORS:
            tracking = {'state': 'HOLD_TRACKING_INPUT_OR_RUNTIME'}
        with db:
            db.execute('BEGIN')
            status = corpus.report(db)
            _, candidates = _fit_rows(db, before, active)
            eligible = sum(row['value'] != 'unknown' for row in candidates)
            result = dict(state='VIDEO_LEDGER_CHECKED', capture_state=capture_state, recorded=recorded,
                          census_races=status['races'], media_races=len(active_races), continuous_media_races=len(continuous),
                          retained_media_races=status['races_with_verified_visual_evidence'], observation_count=eligible,
                          unverified_review_inputs=held_review_inputs,
                          inventory=inventory, tracking=tracking, model_state='WAITING_FOR_REVIEWED_OBSERVATIONS')
            if eligible:
                if shutil.disk_usage(root).free < 50 * GIB:
                    result['model_state'] = 'HOLD_TRAINING_STORAGE'
                else:
                    result['model_state'], result['trial_sha256'] = _fit(db, root, before, active)
        return result


def _now():
    return datetime.now(timezone.utc)


def _save_tick(root, now, report):
    directory = _private_root(root/'ticks')
    body = corpus.pack(report)
    stamp = now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    target = directory/f'{stamp}-{sha256(body.encode()).hexdigest()}.json'
    with corpus.output_file(target) as dest:
        dest.write(body)


def audit_window(root, since, *, clock=_now):
    """Measure completed ticks and gaps in the local worker's observed window."""
    now = clock()
    if since.utcoffset() is None or now.utcoffset() is None or since > now:
        raise ValueError('The audit needs an aware start time in the past.')
    directory = _private_root(_private_root(root)/'ticks')
    start = since.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    ticks, counts = {}, {'new_recordings': 0, 'new_tracks': 0, 'new_candidate_fits': 0}
    stages = {name: {} for name in ('shadow_result', 'shadow_replay', 'shadow_publication')}
    for path in sorted(directory.glob('*.json')):
        if path.name < start:
            continue
        body = _read_regular(path, 1024 * 1024)
        report = json.loads(body)
        at = datetime.fromisoformat(report['checked_at']).astimezone(timezone.utc)
        stamp = at.strftime('%Y%m%dT%H%M%S%f')
        if (path.name != f'{stamp}-{sha256(body).hexdigest()}.json'
                or report['schema'] != 'KEIRIN_MAC_CYCLE_V1' or not since <= at <= now):
            raise ValueError('The cycle audit receipt does not match its recorded timestamp and hash.')
        duration = report['duration_ms']
        if type(duration) is not int or duration < 0:
            raise ValueError('Invalid cycle duration.')
        ticks[at] = max(ticks.get(at, 0), duration/1000)
        video = report['video']
        counts['new_recordings'] += video.get('recorded', 0)
        counts['new_tracks'] += video.get('tracking', {}).get('state') == 'TRACKS_GENERATED'
        counts['new_candidate_fits'] += video.get('model_state') == 'TRIAL_PROFILE_FITTED'
        for name, states in stages.items():
            if name in report:
                state = report[name]['state']
                states[state] = states.get(state, 0) + 1
    ordered = sorted(ticks)
    intervals = [(end-begin).total_seconds() for begin, end in zip(ordered, ordered[1:])]
    idle = [max(0, gap-ticks[begin]) for begin, gap in zip(ordered, intervals)]
    span = (ordered[-1]-ordered[0]).total_seconds() if ordered else 0
    last_age = (now-ordered[-1]).total_seconds() if ordered else None
    since_completion = max(0, last_age-ticks[ordered[-1]]) if ordered else None
    longest_idle = max(idle, default=0)
    return dict(schema='KEIRIN_MAC_CYCLE_TIMING_V1', scope='LOCAL_KEIRIN_RESEARCH',
                since=since.isoformat(), checked_at=now.isoformat(), completed_ticks=len(ordered),
                first_tick=ordered[0].isoformat() if ordered else None,
                last_tick=ordered[-1].isoformat() if ordered else None,
                seconds_observed=span, longest_interval_seconds=max(intervals, default=0),
                intervals_over_16_minutes=sum(gap > 960 for gap in intervals),
                longest_idle_seconds=longest_idle, idle_intervals_over_16_minutes=sum(gap > 960 for gap in idle),
                seconds_since_last_tick=last_age, seconds_since_last_completion=since_completion,
                shadow_states=stages['shadow_result'], shadow_replay_states=stages['shadow_replay'],
                shadow_publication_states=stages['shadow_publication'],
                full_24h_local_cadence=span >= 86400 and longest_idle <= 960 and since_completion <= 960, **counts)


def run_cycle(root, *, census=None, manifest=None, bounds=None, reviewed=None, source_approval=None,
              track_request=None, shadow_request=None,
              browser=CHROME, clock=_now):
    root = _private_root(root)
    with _lock(root/'mac-cycle.lock', wait=False):
        now = clock()
        if now.utcoffset() is None:
            raise ValueError('A timezone-aware cycle clock is required.')
        start = monotonic()
        try:
            market_third = market.evaluate_retained()
        except INPUT_ERRORS:
            market_third = {'candidate_disposition': 'HOLD_RETAINED_EVIDENCE_UNAVAILABLE'}
        try:
            video = _video(root, now.astimezone(JST).date().isoformat(), census, manifest, bounds,
                           reviewed, source_approval, track_request, browser)
        except INPUT_ERRORS:
            video = {'state': 'HOLD_VIDEO_INPUT_OR_RUNTIME'}
        result = dict(schema='KEIRIN_MAC_CYCLE_V1', checked_at=now.isoformat(), video=video,
                      market_third=market_third, production_weights_promoted=False)
        if shadow_request is not None:
            try:
                from scripts import keirin_mac_shadow_result
                result['shadow_result'] = keirin_mac_shadow_result.run(root, shadow_request, clock=clock)
            except INPUT_ERRORS:
                result['shadow_result'] = {'state': 'HOLD_SHADOW_RESULT_INPUT_OR_RUNTIME'}
            replay_approval = Path(shadow_request).with_name('komatsushima-replay-approval.json')
            if replay_approval.exists() or replay_approval.is_symlink():
                try:
                    replay_state = _capture_settled_replay(root, shadow_request, replay_approval,
                        result['shadow_result'], video, browser, clock)
                except INPUT_ERRORS + (sources.PlayerUnavailable,):
                    replay_state = 'HOLD_REPLAY_EVIDENCE_OR_RUNTIME'
                result['shadow_replay'] = dict(state=replay_state,
                    tracking_state='HOLD_REPLAY_LAYOUT_CALIBRATION')
            from scripts import keirin_mac_shadow_publication
            result['shadow_publication'] = keirin_mac_shadow_publication.run(root, shadow_request, clock=clock)
        result['duration_ms'] = round(1000*(monotonic()-start))
        _save_tick(root, now, result)
        with corpus.output_file(root/'cycle-report.json') as report:
            json.dump(result, report, ensure_ascii=False, allow_nan=False, sort_keys=True)
        return result


def main(argv=None):
    parser = ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--input-dir', type=Path, help='Optional private directory with the documented local inputs.')
    for name in ('census', 'manifest', 'bounds', 'reviewed', 'source-approval', 'track-request', 'shadow-request'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--audit-since', type=datetime.fromisoformat, help='Read completed cycles from this timestamp.')
    parser.add_argument('--browser', default=CHROME)
    args = parser.parse_args(argv)
    os.umask(0o077)
    options = vars(args)
    root = options.pop('state_dir')
    try:
        since = options.pop('audit_since')
        inputs = options.pop('input_dir')
        if inputs is not None:
            inputs = _private_root(inputs)
            for key, name in (('census', 'census.jsonl'), ('manifest', 'owner-films.jsonl'),
                              ('bounds', 'crossings.jsonl'), ('reviewed', 'reviewed.jsonl'),
                              ('source_approval', 'reviewed-source-approval.json'),
                              ('track_request', 'track-clip.json'), ('shadow_request', 'shadow-result.json')):
                path = inputs/name
                if options[key] is None and path.is_file():
                    options[key] = path
        result = audit_window(root, since) if since is not None else run_cycle(root, **options)
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
