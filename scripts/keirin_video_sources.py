"""Capture review media from approved ordinary, visible KEIRIN replay players.

The JSONL queue uses race_id (YYYYMMDD-VV-RR), race_date (ISO) and
race_detail_url from the dated calendar. Network capture requires a private
operator-reviewed source approval covering the race and the requested uses.
--continuous records the normal rendered digest with a visible player clock
using the browser recorder from the existing GitHub-only video workflow.
keirin_video_media verifies the resulting private images and clips.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import fcntl
from hashlib import file_digest, sha256
from itertools import chain
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import sleep
from urllib.parse import urlsplit


HOST = 'keirin.kdreams.jp'
WINTICKET_HOST = 'www.winticket.jp'
WINTICKET_VENUES = {'84': ('takeo', '武雄')}
WINTICKET_PERMISSION_BASES = ('owner_attestation', 'provider_document')
KOMATSUSHIMA_REPLAY_RACE = '20261126-73-01'
KOMATSUSHIMA_REPLAY_KEY = KOMATSUSHIMA_REPLAY_RACE.replace('-', '')
KOMATSUSHIMA_DIALOG = '[role="dialog"][aria-modal="true"]'
REPLAY_FRAME_MODE = 'settled_replay_frames'
FORWARD_REPLAY_SAMPLING = 'ordinary_playback'
PASSIVE_REPLAY_SAMPLING = 'passive_playback'
MAX_REPLAY_FRAME_SAMPLES = 24
MAX_REPLAY_STILL_WINDOW = 0.8
RESULT_PAGE_UNPUBLISHED = 'replay result page not yet published'
DIGEST_BUTTON_UNAVAILABLE = 'race digest button unavailable'
AMBIGUOUS_PLAYER = 'visible player is ambiguous'
PLAYER_SEEK_UNAVAILABLE = 'decoded player seek unavailable'
REPLAY_FRAME_UNOBSERVED = 'ordinary replay frame not observed'
RACE = re.compile(r'([0-9]{8})-([0-9]{2})-(0[1-9]|1[0-2])')
DETAIL = re.compile(r'/[a-z0-9-]+/racedetail/([0-9]{2})([0-9]{8})[0-9]{4}([0-9]{2})/')
WINTICKET_DETAIL = re.compile(r'/keirin/([a-z0-9-]+)/raceresult/([0-9]{8})([0-9]{2})/([1-7])/(1[0-2]|[1-9])')
BROWSER_REFUSAL = re.compile(r'\bERR_(?:BLOCKED_BY_(?:ADMINISTRATOR|CLIENT|RESPONSE)|(?:NETWORK_)?ACCESS_DENIED)\b')
MASK_SOURCE = """(() => {
    if (window !== top) return;
    document.addEventListener('encrypted', () => { window.__raceEncrypted = true; }, true);
    const mask = document.createElement('div');
    Object.assign(mask.style, {position:'fixed',inset:0,margin:0,background:'black',
                              zIndex:2147483647,pointerEvents:'none'});
    function mount() {
        if (!document.documentElement) return false;
        document.documentElement.append(mask);
        window.__raceMask = mask;
        return true;
    }
    if (!mount()) {
        const observer = new MutationObserver(() => { if (mount()) observer.disconnect(); });
        observer.observe(document, {childList:true});
    }
})()"""
SEEK = """async (video, target) => {
    video.pause();
    if (Math.abs(video.currentTime-target) > 0.001) {
        const ready = new Promise(resolve => {
            const finish = () => { clearTimeout(timer); resolve(true); };
            const timer = setTimeout(() => {
                video.removeEventListener('seeked', finish);
                resolve(false);
            }, 7000);
            video.addEventListener('seeked', finish, {once:true});
        });
        video.currentTime = target;
        if (!await ready) return null;
    }
    if (video.readyState < 2 || video.videoWidth <= 0) return null;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return video.currentTime;
}"""
OBSERVE_RENDERED_REPLAY = """async (video, target) => {
    if (!video.isConnected || video.mediaKeys || window.__raceEncrypted) return null;
    const actual = await new Promise(resolve => {
        let frame;
        let finished = false;
        const stop = seconds => {
            if (finished) return;
            finished = true;
            clearTimeout(timer);
            video.cancelVideoFrameCallback(frame);
            resolve(seconds);
        };
        const secondsUntilTarget = Math.max(0, target - video.currentTime);
        const timer = setTimeout(() => stop(null), (secondsUntilTarget + 12) * 1000);
        const check = (_, sample) => {
            if (video.mediaKeys || window.__raceEncrypted || video.error || !video.isConnected) {
                stop(null);
            } else if (sample.mediaTime >= target - .04) {
                stop(sample.mediaTime);
            } else {
                frame = video.requestVideoFrameCallback(check);
            }
        };
        frame = video.requestVideoFrameCallback(check);
    });
    if (actual === null || video.readyState < 2 || !video.videoWidth) return null;
    await new Promise(resolve => requestAnimationFrame(resolve));
    return actual;
}"""


class PlayerUnavailable(Exception):
    """A specific ordinary source could not be observed."""


class AccessDenied(PlayerUnavailable):
    """Stop this invocation when the source rejects access or rate-limits it."""


def _winticket_venue(key):
    if key == KOMATSUSHIMA_REPLAY_KEY:
        return 'komatsushima', '小松島'
    return WINTICKET_VENUES.get(key[8:10])


def target(row):
    match = RACE.fullmatch(row['race_id'])
    if not match or date.fromisoformat(match[1]).isoformat() != row['race_date']:
        raise ValueError('invalid or mismatched race date')
    url = row['race_detail_url']
    parsed = urlsplit(url)
    key = match[1] + match[2] + match[3]
    if parsed.netloc == WINTICKET_HOST:
        page = WINTICKET_DETAIL.fullmatch(parsed.path)
        venue = _winticket_venue(key)
        if not (parsed.scheme == 'https' and page and venue and not parsed.query and not parsed.fragment
                and (page[1], page[3], int(page[5])) == (venue[0], match[2], int(match[3]))
                and date.fromisoformat(page[2]) + timedelta(days=int(page[4]) - 1) == date.fromisoformat(match[1])):
            raise ValueError('invalid or mismatched WINTICKET race page')
        return key, url
    page = DETAIL.fullmatch(parsed.path)
    if not (parsed.scheme == 'https' and parsed.netloc == HOST and page
            and not parsed.fragment and parsed.query in ('', 'pageType=showResult')
            and (match[2], match[3]) == (page[1], page[3])):
        raise ValueError('invalid or mismatched KDreams race page')
    result_url = parsed._replace(query='pageType=showResult').geturl()
    return key, result_url


def check_title(key, title, *, url=''):
    day = date.fromisoformat(key[:8])
    pattern = (rf'(?<![0-9]){day.year}年0?{day.month}月0?{day.day}日'
               rf'(?![0-9])')
    race = int(key[-2:])
    if not re.search(pattern, title) or not re.search(rf'(?<![0-9]){race}(?:R|レース)(?![0-9])', title):
        raise PlayerUnavailable('race title did not match the requested date and number')
    if urlsplit(url).netloc == WINTICKET_HOST:
        venue = _winticket_venue(key)
        if not venue or not title.startswith(venue[1] + '競輪 '):
            raise PlayerUnavailable('race title did not match the requested venue')


def timeline(duration, interval):
    if not math.isfinite(duration) or duration <= 1 or not math.isfinite(interval) or interval < 0.1:
        raise ValueError('invalid duration or frame interval')
    end = round(duration - 0.2, 3)
    times = {round(0.2 + i * interval, 3) for i in range(1 + int((end - 0.2) / interval))}
    times.add(end)
    return sorted(times)


def validate_receipt(folder, key, url):
    proof = json.loads((folder / 'overview.json').read_text())
    check_title(key, proof['page_title'], url=url)
    if proof['public_result_page'] != url or not proof['frames']:
        raise ValueError('stored capture belongs to another source or has no frames')
    if urlsplit(url).netloc == WINTICKET_HOST:
        clocks = [frame['video_seconds'] for frame in proof['frames']]
        duration = proof['browser_player_seconds']
        interval = proof['frame_interval_seconds']
        if (key != KOMATSUSHIMA_REPLAY_KEY or proof.get('capture_mode') != REPLAY_FRAME_MODE
                or not 2 <= len(clocks) <= MAX_REPLAY_FRAME_SAMPLES
                or not 1 < duration <= 360
                or not math.isfinite(interval) or interval < duration / (MAX_REPLAY_FRAME_SAMPLES - 1)):
            raise ValueError('stored stills exceed the approved replay bounds')
        targets = timeline(duration, interval)
        sampling = proof.get('sampling')
        passive = sampling == PASSIVE_REPLAY_SAMPLING
        forward = sampling in {FORWARD_REPLAY_SAMPLING, PASSIVE_REPLAY_SAMPLING}
        starts = [frame['presented_at'] for frame in proof['frames']] if passive else clocks
        if passive and any(
                not 0 <= item['presented_at'] <= item['video_seconds'] <= item['player_clock_after'] <= duration
                or item['player_clock_after'] - item['presented_at'] > MAX_REPLAY_STILL_WINDOW
                for item in proof['frames']):
            raise ValueError('stored stills have an invalid displayed time window')
        if (len(clocks) != len(targets) or not 0 <= starts[0] <= (.6 if forward else .35)
                or forward and proof.get('browser_player_ended') is not True
                or not duration - .4 <= clocks[-1] <= duration
                or any(first >= second for first, second in zip(clocks, clocks[1:]))
                or any(abs(observed - target) > (.4 if forward and i == 0 else .1)
                       for i, (observed, target) in enumerate(zip(starts, targets, strict=True)))
                or len({frame['frame_sha256'] for frame in proof['frames']}) < 2):
            raise ValueError('stored stills did not cover the approved replay clock')
    for item in proof['frames']:
        frame = folder / f"t{round(item['video_seconds'] * 100):05d}.png"
        if sha256(frame.read_bytes()).hexdigest() != item['frame_sha256']:
            raise ValueError('stored frame digest does not match')
    return proof


def open_player(page, key, url):
    expected = urlsplit(url)
    if expected.scheme != 'https' or expected.netloc not in (HOST, WINTICKET_HOST):
        raise ValueError('unsupported replay source')
    response = page.goto(url, wait_until='domcontentloaded', timeout=25000)
    if not response:
        raise PlayerUnavailable('no source response')
    winticket = expected.netloc == WINTICKET_HOST
    exact = winticket and key == KOMATSUSHIMA_REPLAY_KEY
    denials = (401, 403, 407, 429) if exact else (401, 403, 429)
    if response.status in denials:
        raise AccessDenied(f'source HTTP {response.status}')
    actual = urlsplit(page.url)
    if exact and response.status == 404 and actual == expected:
        raise PlayerUnavailable(RESULT_PAGE_UNPUBLISHED)
    if response.status != 200 or actual.scheme != 'https' or actual.netloc != expected.netloc:
        raise PlayerUnavailable(f'source status/redirect {response.status}')
    if actual.path != expected.path or (winticket and actual != expected):
        raise PlayerUnavailable('source redirected to a different race page')
    title = page.title()
    check_title(key, title, url=url)
    if winticket:
        control = page.get_by_role('button', name='映像を観る', exact=True)
    else:
        control = page.locator('[name="digestControl"]').get_by_alt_text('ダイジェスト映像を見る', exact=True)
    if control.count() != 1 or not control.is_visible():
        raise PlayerUnavailable(DIGEST_BUTTON_UNAVAILABLE)
    dialog = page.locator(KOMATSUSHIMA_DIALOG + ':visible') if exact else None
    if dialog is not None and dialog.count():
        raise PlayerUnavailable(AMBIGUOUS_PLAYER)
    refused_media = []

    def watch_media(result):
        resource = result.request.resource_type
        if (resource == 'media' or exact and resource in ('fetch', 'xhr')) and result.status in denials:
            refused_media.append(result.status)

    if not winticket or exact:
        page.on('response', watch_media)
    try:
        control.click(timeout=12000)
        selector = KOMATSUSHIMA_DIALOG + ' video' if exact else 'video'
        page.wait_for_function("""selector => [...document.querySelectorAll(selector)].some(
            v => v.getClientRects().length && v.readyState >= 2 && v.videoWidth
                && Number.isFinite(v.duration))""", arg=selector, timeout=18000)
        if dialog is not None and dialog.count() != 1:
            raise PlayerUnavailable(AMBIGUOUS_PLAYER)
        video = dialog.locator('video:visible') if dialog is not None else page.locator('video:visible')
        if video.count() != 1:
            raise PlayerUnavailable(AMBIGUOUS_PLAYER)
        if video.evaluate('v => !!(v.mediaKeys || window.__raceEncrypted)'):
            raise AccessDenied('protected player')
        return video, title, refused_media
    finally:
        if refused_media:
            raise AccessDenied(f'source HTTP {refused_media[0]}')


def capture(page, key, url, directory, interval, *, approval=None):
    require_capture_scope(approval, key, url, continuous=False)
    video, title, refused_media = open_player(page, key, url)
    exact_winticket = urlsplit(url).netloc == WINTICKET_HOST
    try:
        if exact_winticket:
            video = video.element_handle()
        duration = video.evaluate('v => v.duration')
        if exact_winticket:
            if not 1 < duration <= 360:
                raise PlayerUnavailable('visible replay exceeds the supported inspection duration')
            interval = max(interval, duration / (MAX_REPLAY_FRAME_SAMPLES - 1))
        else:
            video.evaluate("""v => {
                v.pause(); v.controls = false;
                Object.assign(v.style,{position:'fixed',left:'0',top:'0',width:'1280px',height:'720px',
                                       margin:'0',zIndex:2147483647});
            }""")
        frames = []
        for index, when in enumerate(timeline(duration, interval)):
            actual = video.evaluate(OBSERVE_RENDERED_REPLAY if exact_winticket else SEEK, when)
            if refused_media:
                raise AccessDenied(f'source HTTP {refused_media[0]}')
            if exact_winticket and video.evaluate('v => !!(v.mediaKeys || window.__raceEncrypted)'):
                raise AccessDenied('protected player')
            tolerance = .4 if exact_winticket and index == 0 else .1
            if actual is None or abs(actual - when) > tolerance:
                raise PlayerUnavailable(REPLAY_FRAME_UNOBSERVED if exact_winticket
                                        else PLAYER_SEEK_UNAVAILABLE)
            image = video.screenshot(animations='allow' if exact_winticket else 'disabled', timeout=9000)
            if exact_winticket and video.evaluate('v => !!(v.mediaKeys || window.__raceEncrypted)'):
                raise AccessDenied('protected player')
            if exact_winticket and (page.url != url or not video.evaluate(
                    '(v, selector) => v.isConnected && !!v.closest(selector)', KOMATSUSHIMA_DIALOG)):
                raise PlayerUnavailable('the foreground replay changed during inspection')
            frame = dict(video_seconds=actual, frame_sha256=sha256(image).hexdigest())
            if exact_winticket:
                after = video.evaluate('v => v.currentTime')
                if not actual <= after <= duration or after - actual > MAX_REPLAY_STILL_WINDOW:
                    raise PlayerUnavailable('ordinary replay still time window unverified')
                frame.update(video_seconds=(actual + after) / 2, presented_at=actual,
                             player_clock_after=after)
            name = directory / f"t{round(frame['video_seconds'] * 100):05d}.png"
            with name.open('xb') as out:
                out.write(image)
            frames.append(frame)
        if exact_winticket:
            page.wait_for_function('v => v.ended || v.error || v.mediaKeys || window.__raceEncrypted',
                                   arg=video, timeout=10000)
            if video.evaluate('v => !!(v.mediaKeys || window.__raceEncrypted)'):
                raise AccessDenied('protected player')
            if not video.evaluate('v => v.ended && !v.error') or page.url != url:
                raise PlayerUnavailable('ordinary replay did not finish')
    finally:
        if refused_media:
            raise AccessDenied(f'source HTTP {refused_media[0]}')
    proof = {'public_result_page': url, 'page_title': title, 'browser_player_seconds': duration,
             'observed_at_utc': datetime.now(timezone.utc).isoformat(),
             'frame_interval_seconds': interval, 'frames': frames}
    if exact_winticket:
        proof['capture_mode'] = REPLAY_FRAME_MODE
        proof['sampling'] = PASSIVE_REPLAY_SAMPLING
        proof['browser_player_ended'] = True
    (directory / 'overview.json').write_text(json.dumps(proof, ensure_ascii=False) + '\n')
    return refused_media


def recording_bounds(path):
    """Find the green timing marker in the rendered screen recording."""
    times_run = subprocess.run(
        ['ffprobe', '-v', 'error', '-threads', '1', '-select_streams', 'v:0', '-show_entries',
         'frame=best_effort_timestamp_time', '-of', 'json', str(path)],
        check=True, capture_output=True)
    times = [float(f['best_effort_timestamp_time']) for f in json.loads(times_run.stdout)['frames']]
    marks = subprocess.run(
        ['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(path), '-vf', 'crop=4:4:4:704,scale=1:1',
         '-pix_fmt', 'rgb24', '-threads', '1', '-fps_mode', 'passthrough',
         '-f', 'rawvideo', '-'], check=True, capture_output=True).stdout
    if len(marks) != 3 * len(times):
        raise PlayerUnavailable('screen clock count mismatch')
    selected = [i for i in range(len(times)) if marks[3*i] < 65
                and marks[3*i+1] > 195 and marks[3*i+2] < 65]
    if not selected or selected != list(range(selected[0], selected[-1]+1)):
        raise PlayerUnavailable('screen clock marker missing or discontinuous')
    return times[selected[0]], times[selected[-1]]


def record_digest(browser, key, url, directory, *, approval=None):
    """Record the rendered viewport and retain only normal, uninterrupted playback."""
    require_capture_scope(approval, key, url, continuous=True)
    context = browser.new_context(locale='ja-JP', timezone_id='Asia/Tokyo',
                                  viewport={'width': 1280, 'height': 720},
                                  record_video_dir=str(directory),
                                  record_video_size={'width': 1280, 'height': 720})
    isolate = urlsplit(url).netloc == WINTICKET_HOST
    try:
        if isolate:
            context.add_init_script(MASK_SOURCE)
        page = context.new_page()
        video, title, refused_media = open_player(page, key, url)
        video = video.element_handle()
        if isolate and not page.evaluate('() => !!window.__raceMask?.isConnected'):
            raise PlayerUnavailable('player viewport mask unavailable')
        duration, width, height = video.evaluate('v => [v.duration, v.videoWidth, v.videoHeight]')
        if isolate and key == KOMATSUSHIMA_REPLAY_KEY and not 1 < duration <= 360:
            raise PlayerUnavailable('visible replay exceeds the supported recording duration')
        if video.evaluate(SEEK, 0) is None:
            raise PlayerUnavailable('could not seek visible player to start')
        video.evaluate("""(v, isolate) => {
            v.pause(); v.controls = false; v.muted = true;
            Object.assign(v.style,{position:'fixed',left:0,top:0,width:'1280px',height:'696px',
                margin:0,background:'black',objectFit:'contain',zIndex:2147483646});
            const clock = document.createElement('div');
            Object.assign(clock.style,{position:'fixed',bottom:0,left:0,right:0,height:'24px',
                background:'black',color:'white',textAlign:'right',font:'16px monospace',
                zIndex:2147483647,pointerEvents:'none'});
            const mark = document.createElement('i');
            Object.assign(mark.style,{position:'absolute',left:0,top:0,width:'16px',height:'20px'});
            const label = document.createElement('span');
            clock.append(mark,label);
            if (isolate) {
                window.__raceMask.append(v, clock);
            } else {
                document.body.append(clock);
            }
            window.__raceReadback = {error:null, first:null, last:null, count:0, maxGap:0};
            const state = window.__raceReadback;
            function sample(now, frame) {
                const t = frame.mediaTime;
                if (state.last !== null) {
                    if (t < state.last) state.error = 'backward source clock';
                    state.maxGap = Math.max(state.maxGap, t - state.last);
                } else { state.first = t; }
                state.count++; state.last = t;
                mark.style.background = '#00ff00';
                label.textContent = 'Player ' + t.toFixed(3) + ' s';
                if (!v.ended) v.requestVideoFrameCallback(sample);
            }
            v.requestVideoFrameCallback(sample);
            v.addEventListener('ended', () => { mark.style.background = 'black'; });
        }""", isolate)
        video.evaluate('v => v.play()')
        try:
            page.wait_for_function("v => v.ended || v.error || v.mediaKeys || window.__raceEncrypted",
                                   arg=video, timeout=round((duration + 35) * 1000))
        finally:
            if isolate and key == KOMATSUSHIMA_REPLAY_KEY and refused_media:
                raise AccessDenied(f'source HTTP {refused_media[0]}')
        finished, failed, protected = video.evaluate(
            'v => [v.ended, !!v.error, !!(v.mediaKeys || window.__raceEncrypted)]')
        if protected:
            raise AccessDenied('protected player')
        if failed or not finished:
            raise PlayerUnavailable('ordinary player did not finish')
        facts = page.evaluate('window.__raceReadback')
        if refused_media:
            raise AccessDenied(f'source HTTP {refused_media[0]}')
        if (facts['error'] or facts['count'] < 2 or facts['first'] is None or facts['first'] > .6
                or duration - facts['last'] > .6 or facts['maxGap'] > .75):
            raise PlayerUnavailable('incomplete or interrupted visible replay')
        page.wait_for_timeout(150)
        recording = page.video
    finally:
        context.close()
    raw = Path(recording.path())
    start, end = recording_bounds(raw)
    if abs((end - start) - duration) > 1.25:
        raise PlayerUnavailable(f'screen clock and player duration disagree: screen={end - start:.3f}, '
                                f'player={duration:.3f}, observed={facts["last"] - facts["first"]:.3f}')
    movie = directory / 'digest.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-i', str(raw),
                    '-ss', str(start), '-t', str(end - start + .04), '-c:v', 'libx264',
                    '-threads', '2', '-preset', 'veryfast', '-crf', '18', '-an',
                    '-movflags', '+faststart', str(movie)], check=True)
    raw.unlink()
    with movie.open('rb') as stream:
        digest = file_digest(stream, 'sha256').hexdigest()
    day = date.fromisoformat(key[:8]).isoformat()
    receipt = {'race_id': f'{key[:8]}-{key[8:10]}-{key[10:]}', 'race_date': day,
               'source_ref': url + '#ordinary-screen-digest', 'public_result_page': url,
               'kind': 'clip', 'start_ms': 0, 'path': movie.name, 'sha256': digest,
               'clock_basis': 'local_clip_zero_player_time_visible_in_footer',
               'page_title': title, 'browser_player_seconds': duration, 'screen_duration_seconds': end-start,
               'browser_player_ended': finished, 'browser_player_resolution': [width, height],
               'player_progress': facts,
               'observed_at_utc': datetime.now(timezone.utc).isoformat()}
    (directory / 'clip.json').write_text(json.dumps(receipt, ensure_ascii=False) + '\n')


def check_clip(folder, key, url):
    proof = json.loads((folder / 'clip.json').read_bytes())
    check_title(key, proof['page_title'], url=url)
    if (proof['public_result_page'] != url or proof['kind'] != 'clip'
            or proof['path'] != 'digest.mp4'):
        raise ValueError('stored digest is for a different source')
    with (folder / 'digest.mp4').open('rb') as stream:
        if file_digest(stream, 'sha256').hexdigest() != proof['sha256']:
            raise ValueError('stored digest changed')


def private_log_fd(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('capture lock or log is not a regular file')
    except BaseException:
        os.close(fd)
        raise
    return fd


def source_refused(status):
    return status.startswith('source HTTP ') or status in ('protected player', 'browser access refused')


def read_attempt_history(lines):
    latest = {}
    refusal = None
    for line in lines:
        entry = json.loads(line)
        status = entry['status']
        latest[(entry['race_id'], entry['source_ref'])] = status
        if refusal is None and source_refused(status):
            refusal = status
    return {pair for pair, value in latest.items() if value != 'captured'}, refusal


def failed_attempts(log):
    try:
        with open(log, encoding='utf8', opener=private_log_fd) as history:
            failed, _ = read_attempt_history(history)
            return failed
    except FileNotFoundError:
        return set()


@dataclass(frozen=True)
class SourceApproval:
    rights_sha256: str
    decision_sha256: str
    first: date | None
    last: date | None
    race_ids: frozenset[str] | None
    valid_until: datetime | None
    continuous: bool
    source_host: str = HOST
    permission_basis: str | None = None
    settled_replay_url: str | None = None

    def covers(self, row):
        if self.valid_until and datetime.now(timezone.utc) >= self.valid_until:
            raise ValueError('source approval expired')
        day = date.fromisoformat(row['race_date'])
        if self.first is not None and not self.first <= day <= self.last:
            return False
        return (urlsplit(row['race_detail_url']).netloc == self.source_host
                and (self.race_ids is None or row['race_id'] in self.race_ids))


def load_source_approval(path, continuous):
    """Read the operator's scope assessment and verify its referenced permission bytes."""
    if path is None:
        raise ValueError('network capture requires an operator-reviewed source approval')
    path = Path(path)
    raw = path.read_bytes()
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get('source_host') not in (HOST, WINTICKET_HOST):
        raise ValueError('source approval does not cover a supported replay host')
    host = doc['source_host']
    basis = doc.get('permission_basis')
    if host == WINTICKET_HOST and basis not in WINTICKET_PERMISSION_BASES:
        raise ValueError('WINTICKET requires permission provenance for the requested capture mode')
    for field in ('reviewer', 'rights_ref', 'rights_sha256'):
        if not isinstance(doc.get(field), str) or not doc[field].strip():
            raise ValueError('source approval missing reviewer or permission evidence')
    uses = doc.get('allowed_uses')
    mode = 'video_recording' if continuous else 'frame_capture'
    if (not isinstance(uses, list) or not all(isinstance(use, str) for use in uses)
            or not {'automated_fetch', 'private_retention', 'history_analysis', mode}.issubset(uses)):
        raise ValueError('source approval does not cover the requested uses')
    evidence = path.parent / doc['rights_ref']
    if not evidence.is_file() or evidence.samefile(path) or evidence.stat().st_size == 0:
        raise ValueError('underlying source permission evidence is missing or self-referential')
    with evidence.open('rb') as stream:
        actual = file_digest(stream, 'sha256').hexdigest()
    if actual != doc['rights_sha256']:
        raise ValueError('source permission evidence digest mismatch')
    first = last = None
    if 'first_race_date' in doc or 'last_race_date' in doc:
        first = date.fromisoformat(doc['first_race_date'])
        last = date.fromisoformat(doc['last_race_date'])
        if first > last:
            raise ValueError('invalid permitted race date range')
    races = doc.get('race_ids')
    if races is not None:
        if (not isinstance(races, list) or not races or
                not all(isinstance(race, str) and RACE.fullmatch(race) for race in races)):
            raise ValueError('invalid permitted race IDs')
        races = frozenset(races)
    if first is None and races is None:
        raise ValueError('source approval must identify permitted race dates or race IDs')
    if host == WINTICKET_HOST and not continuous and races != {KOMATSUSHIMA_REPLAY_RACE}:
        raise ValueError('WINTICKET stills require a separate approval for the exact settled replay')
    expiry = doc.get('valid_until')
    if expiry is not None:
        expiry = datetime.fromisoformat(expiry)
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError('source approval expiry is invalid or past')
    return SourceApproval(actual, sha256(raw).hexdigest(), first, last, races, expiry, continuous,
                          host, basis, doc.get('race_detail_url'))


def require_capture_scope(approval, key, url, *, continuous):
    if not isinstance(approval, SourceApproval) or continuous != approval.continuous:
        raise ValueError('source approval for this capture mode is required')
    row = {'race_id': f'{key[:8]}-{key[8:10]}-{key[10:]}', 'race_date': date.fromisoformat(key[:8]).isoformat(),
           'race_detail_url': url}
    if key == KOMATSUSHIMA_REPLAY_KEY and not (
            approval.source_host == WINTICKET_HOST and approval.race_ids == {KOMATSUSHIMA_REPLAY_RACE}
            and approval.settled_replay_url == url):
        raise ValueError('separate permission for the exact WINTICKET replay is required')
    if approval.source_host == WINTICKET_HOST and not continuous and key != KOMATSUSHIMA_REPLAY_KEY:
        raise ValueError('WINTICKET stills require a settled replay scope')
    if target(row)[0] != key or not approval.covers(row):
        raise ValueError('race outside approved capture scope')


def run(queue, output, *, interval, pause, limit, executable, retry_failed=False, continuous=False,
        source_approval=None, chromium_sandbox=None, headless=None, stop_after_refusal=False,
        settled_replay_url=None, settled_replay_decision_sha256=None):
    approval = load_source_approval(source_approval, continuous)
    if settled_replay_url is not None and not (limit == 1 and stop_after_refusal):
        raise ValueError('settled replay requires a bounded single attempt and refusal stop')
    if settled_replay_url is not None and settled_replay_decision_sha256 != approval.decision_sha256:
        raise ValueError('settled replay permission has changed since admission')
    if headless is None:
        headless = approval.source_host != WINTICKET_HOST
    chromium_sandbox = sys.platform == 'darwin' or chromium_sandbox is True
    tally = Counter()
    attempted = 0

    def permitted_rows(source):
        for line in source:
            row = json.loads(line)
            if not row.get('race_detail_url'):
                tally['no_listed_url'] += 1
                continue
            key, url = target(row)
            if key == KOMATSUSHIMA_REPLAY_KEY or settled_replay_url is not None:
                if key != KOMATSUSHIMA_REPLAY_KEY or settled_replay_url != url:
                    tally['outside_settled_replay_scope'] += 1
                    continue
                require_capture_scope(approval, key, url, continuous=continuous)
            if approval.covers(row):
                yield row, key, url
            else:
                tally['outside_approved_scope'] += 1

    with ExitStack() as stack:
        rows = permitted_rows(stack.enter_context(queue.open()))
        first = next(rows, None)
        if first is None:
            return tally
        if output.is_symlink():
            raise ValueError('capture output is a symbolic link')
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(output, 0o700)
        lock = stack.enter_context(open(output / '.capture.lock', 'a', encoding='utf8', opener=private_log_fd))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attempt_log = output / 'attempts.jsonl'
        browser = None
        try:
            with open(attempt_log, 'a+', encoding='utf8', opener=private_log_fd) as attempts:
                attempts.seek(0)
                failed, refusal = read_attempt_history(attempts)
                if stop_after_refusal and refusal is not None:
                    tally[refusal] += 1
                    return tally
                for row, key, url in chain((first,), rows):
                    folder = output / key
                    if folder.is_symlink():
                        raise ValueError('race capture folder is a symbolic link')
                    if folder.exists():
                        (check_clip if continuous else validate_receipt)(folder, key, url)
                        tally['reused'] += 1
                        continue
                    pair = (row['race_id'], url)
                    if pair in failed and not retry_failed:
                        tally['previously_unavailable'] += 1
                        continue
                    if limit is not None and attempted >= limit:
                        break
                    if browser is None:
                        from playwright.sync_api import Error, TimeoutError as PlaywrightTimeout, sync_playwright

                        engine = stack.enter_context(sync_playwright())
                        browser = engine.chromium.launch(executable_path=executable, headless=headless,
                                                         chromium_sandbox=chromium_sandbox)
                    attempted += 1
                    status = 'captured'
                    try:
                        with TemporaryDirectory(prefix='.capture-', dir=output) as stage:
                            tmp = Path(stage) / key
                            tmp.mkdir(mode=0o700)
                            if continuous:
                                record_digest(browser, key, url, tmp, approval=approval)
                                check_clip(tmp, key, url)
                            else:
                                page = browser.new_page(locale='ja-JP', timezone_id='Asia/Tokyo',
                                                        viewport={'width': 1360, 'height': 860})
                                refused = None
                                try:
                                    if approval.source_host == WINTICKET_HOST:
                                        page.add_init_script(
                                            "document.addEventListener('encrypted', "
                                            "() => { window.__raceEncrypted = true; }, true);")
                                    refused = capture(page, key, url, tmp, interval, approval=approval)
                                    validate_receipt(tmp, key, url)
                                finally:
                                    page.close()
                                    if refused:
                                        raise AccessDenied(f'source HTTP {refused[0]}')
                            proof = {'decision_sha256': approval.decision_sha256,
                                     'rights_sha256': approval.rights_sha256,
                                     'race_id': row['race_id'], 'source_ref': url}
                            if approval.permission_basis:
                                proof['permission_basis'] = approval.permission_basis
                            if row.get('result_commit'):
                                proof['result_discovery'] = dict(commit=row['result_commit'],
                                    observed_at=row['result_observed_at'], scope='two_source_confirmed_end')
                            if approval.source_host == WINTICKET_HOST and not continuous:
                                proof['capture_mode'] = REPLAY_FRAME_MODE
                            with (tmp / 'source-approval.json').open('x') as receipt:
                                json.dump(proof, receipt)
                            tmp.rename(folder)
                    except AccessDenied as exc:
                        status = str(exc)
                    except PlayerUnavailable as exc:
                        status = str(exc)
                    except PlaywrightTimeout:
                        status = 'ordinary player timeout'
                    except Error as exc:
                        status = ('browser access refused' if BROWSER_REFUSAL.search(str(exc))
                                  else 'ordinary browser error')
                    tally[status] += 1
                    if status != 'captured':
                        failed.add(pair)
                    attempt = dict(race_id=row['race_id'], source_ref=url, status=status,
                                   at_utc=datetime.now(timezone.utc).isoformat())
                    if approval.source_host == WINTICKET_HOST and not continuous:
                        attempt['capture_mode'] = REPLAY_FRAME_MODE
                        attempt['sampling'] = PASSIVE_REPLAY_SAMPLING
                    attempts.write(json.dumps(attempt) + '\n')
                    attempts.flush()
                    if source_refused(status):
                        break
                    sleep(pause)
        finally:
            if browser is not None:
                browser.close()
    return tally


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--continuous', action='store_true',
                     help='save rendered digest movies, using a separate output directory')
    cli.add_argument('--source-approval', type=Path, required=True,
                     help='private operator-reviewed capture and research permission record')
    cli.add_argument('--queue', type=Path, required=True)
    cli.add_argument('--out', type=Path, required=True)
    cli.add_argument('--interval', type=float, default=3, help='seconds between visible digest frames')
    cli.add_argument('--pause', type=float, default=2, help='pause between race pages')
    cli.add_argument('--limit', type=int, help='new race attempts this invocation')
    cli.add_argument('--retry-failed', action='store_true', help='retry previously unavailable pages')
    cli.add_argument('--chromium', default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                     if sys.platform == 'darwin' else '/usr/bin/chromium')
    args = cli.parse_args()
    if (not math.isfinite(args.pause) or args.pause < 0 or not math.isfinite(args.interval)
            or args.interval < 0.1 or (args.limit is not None and args.limit < 1)):
        cli.error('invalid interval, pause or limit')
    os.umask(0o077)
    try:
        tally = run(args.queue, args.out, interval=args.interval, pause=args.pause,
                    limit=args.limit, executable=args.chromium, retry_failed=args.retry_failed,
                    continuous=args.continuous, source_approval=args.source_approval)
    except (KeyError, ValueError, TypeError, OSError) as exc:
        cli.exit(1, f'capture stopped: {exc}\n')
    print(json.dumps(tally, sort_keys=True))
    if any(status not in ('reused', 'captured', 'no_listed_url') for status in tally):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
