"""Capture review frames from the ordinary visible KDreams race-detail player.

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
from datetime import date, datetime, timezone
import fcntl
from hashlib import file_digest, sha256
from itertools import chain
import json
import math
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from time import sleep
from urllib.parse import urlsplit


HOST = 'keirin.kdreams.jp'
RACE = re.compile(r'([0-9]{8})-([0-9]{2})-(0[1-9]|1[0-2])')
DETAIL = re.compile(r'/[a-z0-9-]+/racedetail/([0-9]{2})([0-9]{8})[0-9]{4}([0-9]{2})/')
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


class PlayerUnavailable(Exception):
    """A specific ordinary source could not be observed."""


class AccessDenied(PlayerUnavailable):
    """Stop this invocation when the source rejects access or rate-limits it."""


def target(row):
    match = RACE.fullmatch(row['race_id'])
    if not match or date.fromisoformat(match[1]).isoformat() != row['race_date']:
        raise ValueError('invalid or mismatched race date')
    url = row['race_detail_url']
    parsed = urlsplit(url)
    page = DETAIL.fullmatch(parsed.path)
    if not (parsed.scheme == 'https' and parsed.netloc == HOST and page
            and not parsed.fragment and parsed.query in ('', 'pageType=showResult')
            and (match[2], match[3]) == (page[1], page[3])):
        raise ValueError('invalid or mismatched KDreams race page')
    result_url = parsed._replace(query='pageType=showResult').geturl()
    return match[1] + match[2] + match[3], result_url


def check_title(key, title):
    day = date.fromisoformat(key[:8])
    pattern = (rf'(?<![0-9]){day.year}年0?{day.month}月0?{day.day}日'
               rf'(?![0-9])')
    race = int(key[-2:])
    if not re.search(pattern, title) or not re.search(rf'(?<![0-9]){race}(?:R|レース)(?![0-9])', title):
        raise PlayerUnavailable('race title did not match the requested date and number')


def timeline(duration, interval):
    if not math.isfinite(duration) or duration <= 1 or not math.isfinite(interval) or interval < 0.1:
        raise ValueError('invalid duration or frame interval')
    end = round(duration - 0.2, 3)
    times = {round(0.2 + i * interval, 3) for i in range(1 + int((end - 0.2) / interval))}
    times.add(end)
    return sorted(times)


def validate_receipt(folder, key, url):
    proof = json.loads((folder / 'overview.json').read_text())
    check_title(key, proof['page_title'])
    if proof['public_result_page'] != url or not proof['frames']:
        raise ValueError('stored capture belongs to another source or has no frames')
    for item in proof['frames']:
        frame = folder / f"t{round(item['video_seconds'] * 100):05d}.png"
        if sha256(frame.read_bytes()).hexdigest() != item['frame_sha256']:
            raise ValueError('stored frame digest does not match')
    return proof


def open_player(page, key, url):
    response = page.goto(url, wait_until='domcontentloaded', timeout=25000)
    if not response:
        raise PlayerUnavailable('no source response')
    if response.status in (401, 403, 429):
        raise AccessDenied(f'source HTTP {response.status}')
    if response.status != 200 or urlsplit(page.url).netloc != HOST:
        raise PlayerUnavailable(f'source status/redirect {response.status}')
    if urlsplit(page.url).path != urlsplit(url).path:
        raise PlayerUnavailable('source redirected to a different race page')
    title = page.title()
    check_title(key, title)
    control = page.locator('[name="digestControl"]').get_by_alt_text('ダイジェスト映像を見る', exact=True)
    if control.count() != 1 or not control.is_visible():
        raise PlayerUnavailable('race digest button unavailable')
    refused_media = []

    def watch_media(result):
        if result.request.resource_type == 'media' and result.status in (401, 403, 429):
            refused_media.append(result.status)

    page.on('response', watch_media)
    control.click(timeout=12000)
    try:
        page.wait_for_function("""() => [...document.querySelectorAll('video')].some(
            v => v.readyState >= 2 && v.videoWidth && Number.isFinite(v.duration))""", timeout=18000)
    finally:
        if refused_media:
            raise AccessDenied(f'source HTTP {refused_media[0]}')
    video = page.locator('video:visible')
    if video.count() != 1:
        raise PlayerUnavailable('visible player is ambiguous')
    if video.evaluate('v => !!v.mediaKeys'):
        raise AccessDenied('protected player')
    return video, title, refused_media


def capture(page, key, url, directory, interval, *, approval=None):
    require_capture_scope(approval, key, url, continuous=False)
    video, title, refused_media = open_player(page, key, url)
    duration = video.evaluate('v => v.duration')
    video.evaluate("""v => {
      v.pause(); v.controls = false;
      Object.assign(v.style,{position:'fixed',left:'0',top:'0',width:'1280px',height:'720px',
                             margin:'0',zIndex:2147483647});
    }""")
    frames = []
    for when in timeline(duration, interval):
        actual = video.evaluate(SEEK, when)
        if refused_media:
            raise AccessDenied(f'source HTTP {refused_media[0]}')
        if actual is None or abs(actual - when) > 0.1:
            raise PlayerUnavailable('decoded player seek unavailable')
        image = video.screenshot(animations='disabled', timeout=9000)
        name = directory / f't{round(actual * 100):05d}.png'
        with name.open('xb') as out:
            out.write(image)
        frames.append({'video_seconds': actual, 'frame_sha256': sha256(image).hexdigest()})
    proof = {'public_result_page': url, 'page_title': title, 'browser_player_seconds': duration,
             'observed_at_utc': datetime.now(timezone.utc).isoformat(),
             'frame_interval_seconds': interval, 'frames': frames}
    (directory / 'overview.json').write_text(json.dumps(proof, ensure_ascii=False) + '\n')


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
    page = context.new_page()
    try:
        video, title, refused_media = open_player(page, key, url)
        duration = video.evaluate('v => v.duration')
        if video.evaluate(SEEK, 0) is None:
            raise PlayerUnavailable('could not seek visible player to start')
        video.evaluate("""v => {
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
            document.body.append(clock);
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
        }""")
        video.evaluate('v => v.play()')
        page.wait_for_function("() => document.querySelector('video').ended",
                               timeout=round((duration + 35) * 1000))
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
               'player_progress': facts,
               'observed_at_utc': datetime.now(timezone.utc).isoformat()}
    (directory / 'clip.json').write_text(json.dumps(receipt, ensure_ascii=False) + '\n')


def check_clip(folder, key, url):
    proof = json.loads((folder / 'clip.json').read_bytes())
    check_title(key, proof['page_title'])
    if (proof['public_result_page'] != url or proof['kind'] != 'clip'
            or proof['path'] != 'digest.mp4'):
        raise ValueError('stored digest is for a different source')
    with (folder / 'digest.mp4').open('rb') as stream:
        if file_digest(stream, 'sha256').hexdigest() != proof['sha256']:
            raise ValueError('stored digest changed')


def failed_attempts(log):
    latest = {}
    if log.exists():
        for line in log.read_text().splitlines():
            entry = json.loads(line)
            latest[(entry['race_id'], entry['source_ref'])] = entry['status']
    return {pair for pair, value in latest.items() if value != 'captured'}


@dataclass(frozen=True)
class SourceApproval:
    rights_sha256: str
    decision_sha256: str
    first: date | None
    last: date | None
    race_ids: frozenset[str] | None
    valid_until: datetime | None
    continuous: bool

    def covers(self, row):
        if self.valid_until and datetime.now(timezone.utc) >= self.valid_until:
            raise ValueError('source approval expired')
        day = date.fromisoformat(row['race_date'])
        if self.first is not None and not self.first <= day <= self.last:
            return False
        return self.race_ids is None or row['race_id'] in self.race_ids


def load_source_approval(path, continuous):
    """Read the operator's scope assessment and verify its referenced permission bytes."""
    if path is None:
        raise ValueError('network capture requires an operator-reviewed source approval')
    path = Path(path)
    raw = path.read_bytes()
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get('source_host') != HOST:
        raise ValueError('source approval does not cover the KDreams replay host')
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
    expiry = doc.get('valid_until')
    if expiry is not None:
        expiry = datetime.fromisoformat(expiry)
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError('source approval expiry is invalid or past')
    return SourceApproval(actual, sha256(raw).hexdigest(), first, last, races, expiry, continuous)


def require_capture_scope(approval, key, url, *, continuous):
    if not isinstance(approval, SourceApproval) or continuous != approval.continuous:
        raise ValueError('source approval for this capture mode is required')
    row = {'race_id': f'{key[:8]}-{key[8:10]}-{key[10:]}', 'race_date': date.fromisoformat(key[:8]).isoformat(),
           'race_detail_url': url}
    if target(row)[0] != key or not approval.covers(row):
        raise ValueError('race outside approved capture scope')


def run(queue, output, *, interval, pause, limit, executable, retry_failed=False, continuous=False,
        source_approval=None):
    approval = load_source_approval(source_approval, continuous)
    tally = Counter()
    attempted = 0

    def permitted_rows(source):
        for line in source:
            row = json.loads(line)
            if not row.get('race_detail_url'):
                tally['no_listed_url'] += 1
                continue
            key, url = target(row)
            if approval.covers(row):
                yield row, key, url
            else:
                tally['outside_approved_scope'] += 1

    with ExitStack() as stack:
        rows = permitted_rows(stack.enter_context(queue.open()))
        first = next(rows, None)
        if first is None:
            return tally
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(output, 0o700)
        lock = stack.enter_context((output / '.capture.lock').open('a'))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attempt_log = output / 'attempts.jsonl'
        failed = failed_attempts(attempt_log)
        browser = None
        try:
            with attempt_log.open('a') as attempts:
                for row, key, url in chain((first,), rows):
                    folder = output / key
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
                        browser = engine.chromium.launch(executable_path=executable)
                    attempted += 1
                    status = 'captured'
                    try:
                        with TemporaryDirectory(prefix='.capture-', dir=output) as stage:
                            tmp = Path(stage) / key
                            tmp.mkdir()
                            if continuous:
                                record_digest(browser, key, url, tmp, approval=approval)
                                check_clip(tmp, key, url)
                            else:
                                page = browser.new_page(locale='ja-JP', timezone_id='Asia/Tokyo',
                                                        viewport={'width': 1360, 'height': 860})
                                try:
                                    capture(page, key, url, tmp, interval, approval=approval)
                                    validate_receipt(tmp, key, url)
                                finally:
                                    page.close()
                            with (tmp / 'source-approval.json').open('x') as receipt:
                                json.dump({'decision_sha256': approval.decision_sha256,
                                           'rights_sha256': approval.rights_sha256,
                                           'race_id': row['race_id'], 'source_ref': url}, receipt)
                            tmp.rename(folder)
                    except AccessDenied as exc:
                        status = str(exc)
                    except PlayerUnavailable as exc:
                        status = str(exc)
                    except PlaywrightTimeout:
                        status = 'ordinary player timeout'
                    except Error:
                        status = 'ordinary browser error'
                    tally[status] += 1
                    if status != 'captured':
                        failed.add(pair)
                    attempts.write(json.dumps({'race_id': row['race_id'], 'source_ref': url,
                                               'status': status,
                                               'at_utc': datetime.now(timezone.utc).isoformat()}) + '\n')
                    attempts.flush()
                    if status.startswith('source HTTP ') or status == 'protected player':
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
                     help='private operator-reviewed KDreams capture and research permission record')
    cli.add_argument('--queue', type=Path, required=True)
    cli.add_argument('--out', type=Path, required=True)
    cli.add_argument('--interval', type=float, default=3, help='seconds between visible digest frames')
    cli.add_argument('--pause', type=float, default=2, help='pause between race pages')
    cli.add_argument('--limit', type=int, help='new race attempts this invocation')
    cli.add_argument('--retry-failed', action='store_true', help='retry previously unavailable pages')
    cli.add_argument('--chromium', default='/usr/bin/chromium')
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
