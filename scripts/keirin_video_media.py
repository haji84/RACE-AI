#!/usr/bin/env python3
"""Verify and inventory local race footage for private research.

Use "inventory" with every capture --root and/or owner --manifest to create,
resume and export one active, combined cohort in a single command.

"frames" imports existing browser screenshot receipts. "verify" accepts JSONL
rows with race_id (YYYYMMDD-VV-RR), race_date, source_ref and kind. A frames
row supplies frames [{at_ms, path, sha256}], with an optional window_ms for a
screen grab whose clock can only be bounded. A clip/full row supplies path,
sha256 and optional start_ms (the time of the first frame on the source
clock). Full coverage and race identity of owner media are supplied by its
provider. Movie verification records size, resolution and black/frozen spans.
One detected span covering at least 90% of playback keeps the movie out of
the review export. The freeze detector starts at two seconds. Only metadata
and paths are written. Paths can be relative to the JSONL. Screenshot
verification uses Pillow or ffmpeg. Local movies use ffmpeg and ffprobe.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import date
from hashlib import file_digest, sha256
import fcntl
from itertools import groupby
import json
from math import ceil, floor
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
from tempfile import NamedTemporaryFile
from time import monotonic
from urllib.parse import urlsplit

if __package__:
    from . import keirin_video_sources as replay
else:
    import keirin_video_sources as replay

RACE = re.compile(r'(\d{8})-(\d{2})-(\d{2})')
SHA = re.compile(r'[0-9a-f]{64}')
FORMATS = 'mov,matroska,webm,avi,mpegts,mpeg,asf,flv,mxf,ogg,h264,hevc'
MOVIE_QUALITY_VERSION = 1
BLACK_SIGNAL = 'lavfi.black'
FREEZE_SIGNAL = 'lavfi.freezedetect.freeze'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def atomic_jsonl(path, rows):
    path = Path(path)
    with NamedTemporaryFile('w', dir=path.parent, encoding='utf8', delete=False) as dest:
        temp = Path(dest.name)
        try:
            for row in rows:
                dest.write(canonical(row) + '\n')
            dest.flush()
            os.fsync(dest.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    temp.replace(path)


def capture_clock(capture, sampling):
    clock = dict(at_ms=round(1000 * capture['video_seconds']))
    if sampling == replay.PASSIVE_REPLAY_SAMPLING:
        clock['window_ms'] = [floor(1000 * capture['presented_at']),
                              ceil(1000 * capture['player_clock_after'])]
    return clock


def frame_window(frame):
    if 'window_ms' not in frame:
        return None
    window = frame['window_ms']
    if (type(window) is not list or len(window) != 2
            or any(type(bound) is not int for bound in window)
            or not 0 <= window[0] <= frame['at_ms'] <= window[1]
            or window[1] - window[0] > ceil(1000 * replay.MAX_REPLAY_STILL_WINDOW) + 2):
        raise ValueError('invalid frame time window')
    return window


def captured_rows(roots):
    """Bind a decoded browser frame to its title, meeting URL, clock and digest."""
    for root in map(Path, roots):
        if not root.is_dir():
            raise ValueError(f'capture root does not exist: {root}')
        for receipt in sorted(root.glob('[0-9]' * 12 + '/*.json')):
            if receipt.name not in ('overview.json', 'detail.json', 'clip.json'):
                continue
            key = receipt.parent.name
            source = json.loads(receipt.read_text(encoding='utf8'))
            url = source['public_result_page']
            page = urlsplit(url)
            base = dict(race_id=f'{key[:8]}-{key[8:10]}-{key[-2:]}',
                        race_date=date.fromisoformat(key[:8]).isoformat())
            if page.netloc == replay.WINTICKET_HOST:
                replay.target(dict(base, race_detail_url=url))
                try:
                    replay.check_title(key, source['page_title'], url=url)
                except replay.PlayerUnavailable as exc:
                    raise ValueError(f'capture race identity mismatch in {receipt}') from exc
                approval = receipt.with_name('source-approval.json')
                proof = json.loads(approval.read_text(encoding='utf8')) if approval.is_file() else {}
                stills = (receipt.name == 'overview.json' and key == replay.KOMATSUSHIMA_REPLAY_KEY
                          and proof.get('capture_mode') == source.get('capture_mode') == replay.REPLAY_FRAME_MODE)
                finished_clip = receipt.name == 'clip.json' and source.get('browser_player_ended') is True
                if (not (stills or finished_clip)
                        or proof.get('race_id') != base['race_id'] or proof.get('source_ref') != url
                        or proof.get('permission_basis') not in replay.WINTICKET_PERMISSION_BASES
                        or not all(isinstance(proof.get(field), str) and SHA.fullmatch(proof[field])
                                   for field in ('decision_sha256', 'rights_sha256'))):
                    raise ValueError(f'capture is missing completed playback or bound source approval in {receipt}')
                if stills:
                    replay.validate_receipt(receipt.parent, key, url)
            else:
                location = re.fullmatch(
                    r'/yenjoy/keirin-kaisai/race-card/result/(\d{10})/(\d{14})/(\d{1,2})/?', page.path)
                direct = re.fullmatch(r'/[a-z0-9-]+/racedetail/(\d{2})\d{12}(\d{2})/?', page.path)
                title_day = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', source['page_title'])
                title_race = re.findall(r'(?<!\d)(\d{1,2})\s*(?:レース|[RＲ])(?![a-zA-Z])',
                                        source['page_title'])
                if location and location[2].startswith(location[1]):
                    venue, number = location[1][:2], int(location[3])
                elif direct:
                    venue, number = direct[1], int(direct[2])
                else:
                    raise ValueError(f'unrecognized capture race URL in {receipt}')
                if (page.scheme != 'https' or page.netloc != replay.HOST
                        or not title_day or venue != key[8:10] or number != int(key[-2:])
                        or number not in [int(n) for n in title_race]):
                    raise ValueError(f'capture race identity mismatch in {receipt}')
                if date(*map(int, title_day.groups())).isoformat() != base['race_date']:
                    raise ValueError(f'capture day mismatch in {receipt}')
            if receipt.name == 'clip.json':
                source_ref = source['public_result_page'] + '#ordinary-screen-digest'
                if (source.get('race_id') != base['race_id'] or source.get('race_date') != base['race_date']
                        or source.get('source_ref') != source_ref or source.get('kind') != 'clip'
                        or source.get('path') != 'digest.mp4' or source.get('start_ms') != 0):
                    raise ValueError(f'clip identity, clock or file mismatch in {receipt}')
                yield dict(base, kind='clip', source_ref=source_ref,
                           path=str(receipt.with_name('digest.mp4').resolve()), start_ms=0,
                           sha256=source['sha256'])
                continue
            frames = []
            for capture in source['frames']:
                seconds = capture['video_seconds']
                if not 0 <= seconds <= source['browser_player_seconds']:
                    raise ValueError(f'capture outside player duration in {receipt}')
                centiseconds = round(100 * seconds)
                frame = receipt.with_name(f't{centiseconds:05d}.png')
                if not frame.exists():
                    # Older captures named the file using the requested time and
                    # recorded the actual player clock. Resolve rounding at 10 ms
                    # boundaries solely when the capture digest matches.
                    for offset in (-1, 1):
                        near = receipt.with_name(f't{centiseconds + offset:05d}.png')
                        if near.is_file():
                            with near.open('rb') as media:
                                if file_digest(media, 'sha256').hexdigest() == capture['frame_sha256']:
                                    frame = near
                                    break
                frames.append(dict(capture_clock(capture, source.get('sampling')), path=str(frame.resolve()),
                                   sha256=capture['frame_sha256']))
            yield dict(base, kind='frames', source_ref=source['public_result_page'], frames=frames)


def assets(row, folder):
    race = RACE.fullmatch(row['race_id'])
    if (not race or race[2] == '00' or not 1 <= int(race[3]) <= 12
            or date.fromisoformat(row['race_date']).strftime('%Y%m%d') != race[1]):
        raise ValueError('invalid manifest race or date')
    ref = row['source_ref']
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError('each recording needs its source reference')
    kind = row['kind']
    if kind == 'frames':
        entries = row['frames']
        if not isinstance(entries, list) or not entries:
            raise ValueError('empty frames row')
    elif kind in ('clip', 'full'):
        entries = [row]
    else:
        raise ValueError('kind must be frames, clip or full')
    for entry in entries:
        at = entry['at_ms'] if kind == 'frames' else entry.get('start_ms', 0)
        if type(at) is not int or at < 0 or not SHA.fullmatch(entry['sha256']):
            raise ValueError('invalid clock or SHA-256')
        if not isinstance(entry['path'], str) or not entry['path'] or '://' in entry['path']:
            raise ValueError('an asset must have a local file path')
        spec = dict(race_id=row['race_id'], race_date=row['race_date'], source_ref=ref,
                    kind=kind, path=str((folder / entry['path']).absolute()), at_ms=at,
                    sha256=entry['sha256'])
        if kind == 'frames' and (window := frame_window(entry)) is not None:
            spec['window_ms'] = window
        yield spec


def connect(db):
    fd = os.open(db, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    conn = sqlite3.connect(db, timeout=30)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY, spec TEXT NOT NULL, fingerprint TEXT,
            status TEXT NOT NULL DEFAULT 'pending', details TEXT);
        CREATE TABLE IF NOT EXISTS active (
            race_id TEXT, source_ref TEXT, kind TEXT, at_ms INTEGER, slot TEXT, id TEXT NOT NULL,
            PRIMARY KEY(race_id, source_ref, kind, at_ms, slot));
    """)
    return conn


def fingerprint(path):
    try:
        info = Path(path).stat()
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return None
    return canonical((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                      info.st_ctime_ns)) if stat.S_ISREG(info.st_mode) else None


def longest_interval(readings, signal, duration_ms):
    starts = readings.get(f'{signal}_start', [])
    ends = readings.get(f'{signal}_end', [])
    if len(starts) == len(ends) + 1:
        # An interval can continue through the last decoded frame.
        ends = [*ends, duration_ms / 1000]
    spans = (round((float(end) - float(start)) * 1000)
             for start, end in zip(starts, ends, strict=True))
    return max(0, min(duration_ms, max(spans, default=0)))


def movie_facts(path, *, screen_digest=False):
    flags = ['-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMATS]
    probe = subprocess.run(['ffprobe', *flags, '-select_streams', 'v:0', '-show_entries',
                            'stream=width,height', '-of', 'json', path],
                           capture_output=True, check=True, timeout=20)
    streams = json.loads(probe.stdout)['streams']
    if not streams:
        raise ValueError('no_video_stream')
    width, height = (streams[0][field] for field in ('width', 'height'))
    quality = []
    if screen_digest and (width, height) == (1280, 720):
        # The rendered playback receipt uses the bottom 24 pixels for its clock.
        quality.append('crop=iw:ih-24:0:0')
    quality.extend(('blackdetect=d=0:pic_th=0.98:pix_th=0.10', 'freezedetect=n=0.001:d=2'))
    for signal in (BLACK_SIGNAL, FREEZE_SIGNAL):
        for edge in ('start', 'end'):
            quality.append(f"metadata=mode=print:key={signal}_{edge}:file='pipe\\:1':direct=1")
    decode = subprocess.run(['ffmpeg', '-nostdin', '-xerror', *flags, '-err_detect', 'explode',
                             '-threads', '1', '-i', path, '-map', '0:v:0',
                             '-filter_threads', '1', '-vf', ','.join(quality),
                             '-fps_mode', 'passthrough', '-progress', 'pipe:1',
                             '-nostats', '-f', 'null', '-'], capture_output=True, check=True, timeout=120)
    readings = defaultdict(list)
    for line in decode.stdout.decode('ascii').splitlines():
        key, separator, value = line.partition('=')
        if separator:
            readings[key].append(value)
    duration = int(readings.get('out_time_us', ['0'])[-1]) // 1000
    frames = int(readings.get('frame', ['0'])[-1])
    if duration <= 0 or frames <= 0 or readings.get('progress', [None])[-1] != 'end':
        raise ValueError('no_decodable_video')
    return dict(duration_ms=duration, decoded_frames=frames, width=width, height=height,
                longest_black_ms=longest_interval(readings, BLACK_SIGNAL, duration),
                longest_frozen_ms=longest_interval(readings, FREEZE_SIGNAL, duration))


def decode_frame(media):
    try:
        from PIL import Image
    except ModuleNotFoundError:
        # A minimal ffmpeg runner can verify screenshots without Python imaging
        # packages. Whitelist only local still-image demuxers.
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror',
                        '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'png_pipe,jpeg_pipe',
                        '-i', str(media.name), '-map', '0:v:0', '-frames:v', '1', '-f', 'null', '-'],
                       capture_output=True, check=True, timeout=20)
    else:
        media.seek(0)
        with Image.open(media) as frame:
            frame.load()


def inspect(spec, stamp):
    if stamp is None:
        return 'unavailable', {}
    path = spec['path']
    try:
        with open(path, 'rb') as media:
            if file_digest(media, 'sha256').hexdigest() != spec['sha256']:
                return 'hash_mismatch', {}
            if spec['kind'] == 'frames':
                decode_frame(media)
                details = {}
            else:
                details = movie_facts(path, screen_digest=spec['source_ref'].endswith('#ordinary-screen-digest'))
                details['size_bytes'] = os.fstat(media.fileno()).st_size
    except subprocess.TimeoutExpired:
        return 'decode_timeout', {}
    except subprocess.CalledProcessError:
        return 'decode_failed', {}
    except FileNotFoundError:
        if fingerprint(path) is not None:  # Decoder executable is missing.
            raise
        return 'unavailable', {}
    except (OSError, ValueError, KeyError):
        return 'decode_failed', {}
    if fingerprint(path) != stamp:
        return 'changed_during_read', {}
    for metric, status in (('longest_black_ms', 'black_video'), ('longest_frozen_ms', 'frozen_video')):
        if metric in details and details[metric] * 10 >= details['duration_ms'] * 9:
            return status, details
    return 'verified', details


def input_assets(manifests, roots=()):
    for row in captured_rows(roots):
        yield from assets(row, Path.cwd())
    for manifest in manifests:
        with manifest.open(encoding='utf8') as lines:
            for line in lines:
                if line.strip():
                    yield from assets(json.loads(line), manifest.parent)


def verify(conn, manifest, limit=None):
    return verify_assets(conn, input_assets([manifest]), limit)


def verify_assets(conn, specs, limit=None, *, time_budget=None):
    """Activate the complete cohort atomically without discarding earlier receipts."""
    if limit is not None and limit < 1:
        raise ValueError('limit must be positive')
    deadline = monotonic() + time_budget if time_budget is not None else None
    with conn:
        conn.execute('DELETE FROM active')
        for spec in specs:
            if spec['kind'] != 'frames':
                spec = dict(spec, movie_quality_version=MOVIE_QUALITY_VERSION)
            serialized = canonical(spec)
            identity = sha256(serialized.encode()).hexdigest()
            slot = '' if spec['kind'] == 'frames' else spec['path']
            key = (spec['race_id'], spec['source_ref'], spec['kind'], spec['at_ms'], slot)
            conn.execute('INSERT OR IGNORE INTO assets(id,spec) VALUES(?,?)',
                         (identity, serialized))
            existing = conn.execute(
                'SELECT id FROM active WHERE (race_id,source_ref,kind,at_ms,slot)=(?,?,?,?,?)',
                key).fetchone()
            if existing is None:
                conn.execute('INSERT INTO active VALUES(?,?,?,?,?,?)', (*key, identity))
            elif existing[0] != identity:
                raise ValueError('conflicting input for one capture timestamp or movie path')
    # Invalidate all modified files before bounded work, including ones past the limit.
    with conn:
        for identity, raw, old, status in conn.execute(
                'SELECT id,spec,fingerprint,status FROM active JOIN assets USING(id)'):
            stamp = fingerprint(json.loads(raw)['path'])
            if old != stamp or status == 'changed_during_read':
                conn.execute("UPDATE assets SET status='pending',details=NULL,fingerprint=? WHERE id=?",
                             (stamp, identity))
    query = ("SELECT id,spec FROM active JOIN assets USING(id) WHERE status='pending' "
             "ORDER BY race_id,source_ref,kind,at_ms,slot LIMIT ?")
    processed = 0
    for identity, raw in conn.execute(query, (-1 if limit is None else limit,)):
        if deadline is not None and monotonic() >= deadline:
            break
        spec = json.loads(raw)
        stamp = fingerprint(spec['path'])
        status, details = inspect(spec, stamp)
        with conn:
            conn.execute('UPDATE assets SET status=?,details=?,fingerprint=? WHERE id=?',
                         (status, canonical(details), stamp, identity))
        processed += 1
    counts = dict(conn.execute('SELECT status,COUNT(*) FROM active JOIN assets USING(id) GROUP BY status'))
    return dict(processed=processed, **counts)


def verified_rows(conn, race_id=None):
    query = ("SELECT race_id,source_ref,kind,spec,details,fingerprint FROM active JOIN assets USING(id) "
             "WHERE status='verified'")
    args = ()
    if race_id is not None:
        query += ' AND race_id=?'
        args = (race_id,)
    query += ' ORDER BY race_id,source_ref,kind,at_ms,slot'
    for (race_id, ref, kind), group in groupby(conn.execute(query, args), key=lambda row: row[:3]):
        frames = []
        for _, _, _, raw, details, stamp in group:
            item = json.loads(raw)
            if fingerprint(item['path']) != stamp:
                raise ValueError('media changed since verification; verify again before export')
            header = dict(race_id=race_id, race_date=item['race_date'], source_ref=ref,
                          kind=kind, status='verified')
            if kind == 'frames':
                frames.append({key: item[key] for key in ('at_ms', 'path', 'sha256', 'window_ms')
                               if key in item})
            else:
                if item.get('movie_quality_version') != MOVIE_QUALITY_VERSION:
                    raise ValueError('movie quality check required; verify the original manifest or capture root again')
                yield dict(header, coverage=f'owner_declared_{kind}', path=item['path'],
                           sha256=item['sha256'], start_ms=item['at_ms'], **json.loads(details))
        if frames:
            yield dict(header, coverage='discrete_frames', frames=frames)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest='action', required=True)
    frames = sub.add_parser('frames')
    frames.add_argument('--root', type=Path, action='append', required=True)
    frames.add_argument('--out', type=Path, required=True)
    check = sub.add_parser('verify')
    check.add_argument('--manifest', type=Path, required=True)
    check.add_argument('--db', type=Path, required=True)
    check.add_argument('--limit', type=int)
    export = sub.add_parser('export')
    export.add_argument('--db', type=Path, required=True)
    export.add_argument('--out', type=Path, required=True)
    inventory = sub.add_parser('inventory', help='verify and export a combined active set of local assets')
    inventory.add_argument('--root', type=Path, action='append', default=[])
    inventory.add_argument('--manifest', type=Path, action='append', default=[])
    inventory.add_argument('--db', type=Path, required=True)
    inventory.add_argument('--out', type=Path, required=True)
    inventory.add_argument('--limit', type=int)
    args = cli.parse_args()
    if args.action == 'inventory' and not (args.root or args.manifest):
        cli.error('inventory requires a capture root or a manifest')
    if args.action == 'frames':
        atomic_jsonl(args.out, captured_rows(args.root))
    else:
        # One consumer per private ledger. Concurrent manifest swaps must never
        # mix one caller's cohort with another caller's verification/export.
        fd = os.open(str(args.db) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.action == 'export' and not args.db.is_file():
                cli.error('verification ledger does not exist')
            with closing(connect(args.db)) as conn:
                if args.action == 'verify':
                    print(json.dumps(verify(conn, args.manifest, args.limit), sort_keys=True))
                if args.action == 'inventory':
                    specs = input_assets(args.manifest, args.root)
                    print(json.dumps(verify_assets(conn, specs, args.limit), sort_keys=True))
                if args.action in ('inventory', 'export'):
                    atomic_jsonl(args.out, verified_rows(conn))


if __name__ == '__main__':
    main()
