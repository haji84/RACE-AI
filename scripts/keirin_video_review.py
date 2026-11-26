"""Review registered riders in a verified local replay using its original millisecond clock.

Use the indexed corpus and media databases or their private JSONL exports.
Use the sheet subcommand to inspect originals, then record what is visible over the
selected interval. For large batches use a separate private review JSONL per race.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from contextlib import closing, contextmanager
from datetime import date
from html import escape
from pathlib import Path


from scripts.keirin_video_media import frame_window
from scripts.keirin_video_rider_learning import ATTACK_PHASES, FULL_WINDOWS, LEVELS, TARGETED_FOLLOW, label_values


def race_rows(path, race_id):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if row['race_id'] == race_id:
                    yield row


def read_db(path):
    return closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True))


def lookup_race(args):
    if args.db is None:
        races = list(race_rows(args.census, args.race_id))
        if len(races) != 1:
            raise ValueError('expected one census race')
        return races[0]
    with read_db(args.db) as db:
        row = db.execute('SELECT id,day FROM race WHERE id=?', (args.race_id,)).fetchone()
        if row is None:
            raise ValueError('race missing from corpus')
        starters = db.execute('SELECT car,rider FROM starter WHERE race=? ORDER BY car', (args.race_id,))
        return {'race_id': row[0], 'race_date': row[1],
                'riders': [{'car': car, 'rider_id': rider} for car, rider in starters]}


def local_sources(args):
    if args.media_db is None:
        return list(race_rows(args.media, args.race_id))
    from scripts.keirin_video_media import verified_rows
    with read_db(args.media_db) as db:
        return list(verified_rows(db, race_id=args.race_id))


def checked_file(entry):
    path = Path(entry['path'])
    if not path.is_absolute() or not path.is_file():
        raise ValueError('verified media must reference an existing absolute local file')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
            raise ValueError('media hash differs from verified receipt')
    return path


def review_inputs(args):
    if not re.fullmatch(r'\d{8}-\d{2}-\d{2}', args.race_id):
        raise ValueError('invalid race ID')
    if (args.start_ms is None) != (args.end_ms is None):
        raise ValueError('supply both interval bounds')
    if args.command != 'sheet' and args.start_ms is None:
        raise ValueError('record needs explicit start and end timestamps')
    if args.start_ms is not None and not 0 <= args.start_ms < args.end_ms:
        raise ValueError('invalid interval')
    race = lookup_race(args)
    if date.fromisoformat(race['race_date']).strftime('%Y%m%d') != args.race_id[:8]:
        raise ValueError('race date mismatch')
    riders = {r['car']: r['rider_id'] for r in race['riders']}
    if len(riders) != len(race['riders']):
        raise ValueError('duplicate car in roster')

    matches = [m for m in local_sources(args) if m['status'] == 'verified'
               and (args.source_ref is None or m['source_ref'] == args.source_ref)
               and (args.asset is None or args.asset == m.get('sha256', 'frames'))]
    if len(matches) != 1:
        raise ValueError('expected one verified source; select --source-ref and, for multiple assets, --asset frames or SHA-256')
    source = matches[0]
    if source['race_date'] != race['race_date']:
        raise ValueError('media date differs from census date')
    frames = []
    if args.start_ms is None:
        if source['kind'] == 'frames':
            times = [f['at_ms'] for f in source['frames']]
            args.start_ms, args.end_ms = min(times), max(times)
        else:
            args.start_ms = source['start_ms']
            args.end_ms = args.start_ms + source['duration_ms']
    if source['kind'] == 'frames':
        frames = sorted((f for f in source['frames'] if args.start_ms <= f['at_ms'] <= args.end_ms),
                        key=lambda f: f['at_ms'])
        if not frames:
            raise ValueError('no verified frame in this interval')
        if len({f['at_ms'] for f in frames}) != len(frames):
            raise ValueError('ambiguous frame timestamp in source')
        for frame in frames:
            frame_window(frame)
            checked_file(frame)
    elif source['kind'] in ('clip', 'full'):
        if (args.start_ms < source['start_ms']
                or args.end_ms > source['start_ms'] + source['duration_ms']):
            raise ValueError('interval outside verified media duration')
        checked_file(source)
    else:
        raise ValueError('unsupported verified media kind')
    return race, riders, source, frames


@contextmanager
def atomic_private(path, binary=False):
    with tempfile.NamedTemporaryFile('wb' if binary else 'w', dir=path.parent,
                                     encoding=None if binary else 'utf-8', delete=False) as output:
        temp = Path(output.name)
        try:
            yield output
            output.flush()
            os.fsync(output.fileno())
            output.close()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def frame_label(frame):
    window = frame_window(frame)
    return f'{window[0]}–{window[1]} ms' if window is not None else f"{frame['at_ms']} ms"


def write_contact_sheet(args, race, riders, source, frames):
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageOps

    if frames:
        samples = [(f['at_ms'], Path(f['path'])) for f in frames]
    else:
        # Video thumbnails are explicitly marked as seek targets. The verified continuous
        # asset, not this sampled preview, is the evidence for a whole-race or lap review.
        span = args.end_ms - args.start_ms
        step = args.step_ms or max(1, (span + 14) // 15)
        samples = [(ms, None) for ms in range(args.start_ms, args.end_ms, step)]
    width, height, columns = 360, 205, 3
    sheet = Image.new('RGB', (columns * width, 36 + ((len(samples) + columns - 1) // columns) * (height + 20)),
                      '#202328')
    draw = ImageDraw.Draw(sheet)
    legend = '   '.join(f"{car}={rider or '?'}" for car, rider in sorted(riders.items()))
    draw.text((6, 8), f"{race['race_id']}   {legend}", fill='white')
    for i, (stamp, frame_path) in enumerate(samples):
        x = i % columns * width
        y = 36 + (i // columns) * (height + 20)
        if frame_path is None:
            requested = (stamp - source['start_ms']) / 1000
            proc = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                                   '-threads', '1', '-ss', f'{requested:.3f}',
                                   '-i', source['path'], '-map', '0:v:0', '-frames:v', '1',
                                   '-vf', f'scale={width}:-1', '-threads', '1', '-f', 'image2pipe', '-c:v', 'png', '-'],
                                  check=True, stdout=subprocess.PIPE, timeout=60)
            frame_path = BytesIO(proc.stdout)
        with Image.open(frame_path) as original:
            sheet.paste(ImageOps.contain(original, (width, height)), (x, y + 19))
        label = frame_label(frames[i]) if frames else f'{stamp} ms (seek)'
        draw.text((x + 3, y + 2), label, fill='white')
    with atomic_private(args.output, binary=True) as stream:
        sheet.save(stream, format='PNG' if args.output.suffix.lower() == '.png' else 'JPEG')


def write_sheet(args, race, riders, source, frames):
    title = escape(race['race_id'])
    roster = ' ／ '.join(f'{car}番 {escape(rider or "登録番号未確認")}' for car, rider in sorted(riders.items()))
    if args.output.suffix.lower() in ('.jpg', '.jpeg', '.png'):
        write_contact_sheet(args, race, riders, source, frames)
        return
    with atomic_private(args.output) as f:
        f.write(f'''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src file:; media-src file:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} 競輪映像確認</title><style>
body{{max-width:90rem;margin:auto;padding:1rem;font:1rem system-ui}}
main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,22rem),1fr));gap:1rem}}
figure{{margin:0}} img,video{{display:block;width:100%;height:auto}} figcaption{{padding:.3rem 0}}
</style><h1>{title}</h1><p>{roster}</p>''')
        if frames:
            f.write('<p>フレームを選ぶと原寸で表示します。範囲は撮影時刻の推定区間です。</p><main>')
            for frame in frames:
                link = escape(Path(frame['path']).as_uri(), quote=True)
                label = frame_label(frame)
                f.write(f'<figure><a href="{link}"><img loading="lazy" src="{link}" alt="{label}"></a>'
                        f'<figcaption>{label}</figcaption></figure>')
            f.write('</main>')
        else:
            offset = source['start_ms']
            link = escape(Path(source['path']).as_uri(), quote=True)
            start = (args.start_ms - offset) / 1000
            end = (args.end_ms - offset) / 1000
            f.write(f'<p>元映像の {args.start_ms}〜{args.end_ms} ms。ファイルの開始位置は元映像の {offset} ms。</p>'
                    f'<video src="{link}#t={start:.3f},{end:.3f}" controls preload="metadata"></video>'
                    f'<a href="{link}">元ファイルを開く</a>')
        f.write('</html>\n')


def make_observation(args, race, riders, source, frames):
    if args.value not in (*label_values(args.task, args.scope), 'unknown'):
        raise ValueError('unexpected value for task')
    if not args.reviewer.strip() or not args.note.strip():
        raise ValueError('supply reviewer and direct observation note')
    if not riders.get(args.car):
        raise ValueError('rider must be identified in the census for a trainable observation')
    if args.value == 'unknown' and not (args.reason and args.reason.strip()):
        raise ValueError('unknown needs an explicit reason')
    if args.value != 'unknown' and args.reason:
        raise ValueError('reason is for unknown observations')

    if (args.scope in FULL_WINDOWS or args.window_level in FULL_WINDOWS) and args.scope != args.window_level:
        raise ValueError('whole-race or whole-lap review needs the corresponding scope and level')
    if args.scope == 'whole_race' and source['kind'] != 'full':
        raise ValueError('whole race requires a verified owner-declared full movie')
    if frames:
        if any(frame_window(frame) is not None for frame in frames):
            raise ValueError('a frame time window is for inspection; review records require actual frame timestamps')
        if len(frames) < 2:
            raise ValueError('review needs at least two timestamps')
        if frames[0]['at_ms'] != args.start_ms or frames[-1]['at_ms'] != args.end_ms:
            raise ValueError('record endpoints must be actual frame timestamps')
        if args.window_level != 'clip':
            raise ValueError('discrete images support clip windows only')
        if args.value != 'unknown' and len({f['sha256'] for f in frames}) < 2:
            raise ValueError('movement needs multiple distinct visible frames')
        if args.value in ('no_attack', 'no_target'):
            raise ValueError('discrete images cannot establish absence across an interval')
    if args.value != 'unknown' and args.end_ms <= args.start_ms:
        raise ValueError('movement needs a nonempty interval')

    row = {'race_id': race['race_id'], 'race_date': race['race_date'], 'source_ref': source['source_ref'],
           'start_ms': args.start_ms, 'end_ms': args.end_ms, 'reviewer': args.reviewer.strip(),
           'note': args.note.strip(), 'car': args.car, 'rider_id': riders[args.car], 'task': args.task,
           'value': args.value, 'scope': args.scope, 'window_level': args.window_level}
    if args.task == 'follow' and args.value in TARGETED_FOLLOW:
        if args.target_car == args.car or not riders.get(args.target_car):
            raise ValueError('following needs a different identified target car')
        row.update(target_car=args.target_car, target_rider_id=riders[args.target_car])
    elif args.target_car is not None:
        raise ValueError('target car applies to observed following only')
    if args.value == 'unknown':
        row['reason'] = args.reason.strip()
    if frames:
        row['evidence_frames'] = [{'at_ms': f['at_ms'], 'sha256': f['sha256']} for f in frames]
    else:
        row['media_sha256'] = source['sha256']
    return row


def make_bounds(args, race, riders, source):
    if not riders.get(args.car) or not all(x.strip() for x in (args.reviewer, args.start_note, args.end_note)):
        raise ValueError('observed crossing bounds require a rider and both crossing notes')
    if source['kind'] == 'frames' or (args.scope == 'whole_race' and source['kind'] != 'full'):
        raise ValueError('boundaries require a continuous movie of the requested scope')
    return {'race_id': race['race_id'], 'race_date': race['race_date'], 'car': args.car, 'rider_id': riders[args.car],
            'scope': args.scope, 'source_ref': source['source_ref'], 'media_sha256': source['sha256'],
            'start_ms': args.start_ms, 'end_ms': args.end_ms, 'reviewer': args.reviewer.strip(),
            'note': args.start_note.strip() + ' / ' + args.end_note.strip()}


def store_review(path, row):
    fields = ('race_id', 'source_ref', 'media_sha256', 'car', 'scope', 'reviewer')
    if 'task' in row:
        fields += ('start_ms', 'end_ms', 'task', 'window_level')
    lock = path.with_name(path.name + '.lock')
    with os.fdopen(os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if path.is_symlink():
            raise ValueError('review output must be a regular owner file')
        content = path.read_text(encoding='utf-8') if path.exists() else ''
        for line in content.splitlines():
            prior = json.loads(line)
            if all(prior.get(k) == row.get(k) for k in fields):
                if prior != row:
                    raise ValueError('review conflict; preserve the original and inspect both records')
                return
        with atomic_private(path) as output:
            output.write(content)
            if content and not content.endswith('\n'):
                output.write('\n')
            output.write(json.dumps(row, ensure_ascii=False) + '\n')


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    field = cli.add_mutually_exclusive_group(required=True)
    field.add_argument('--census', type=Path)
    field.add_argument('--db', type=Path, help='Existing corpus ledger for indexed roster and queue lookup')
    footage = cli.add_mutually_exclusive_group(required=True)
    footage.add_argument('--media', type=Path)
    footage.add_argument('--media-db', type=Path, help='Existing verified media inventory, for indexed movie/frame lookup')
    select = cli.add_mutually_exclusive_group(required=True)
    select.add_argument('--race-id')
    select.add_argument('--next', action='store_true', help='Read the next review-stage race from --db')
    select.add_argument('--queue', type=Path, help='Review the next stage=review row from the corpus queue JSONL')
    cli.add_argument('--after', default='', help='Resume queue after this race ID')
    cli.add_argument('--asset', help='Select a movie SHA-256 or frames for a bundled source')
    cli.add_argument('--source-ref')
    cli.add_argument('--start-ms', type=int)
    cli.add_argument('--end-ms', type=int)
    commands = cli.add_subparsers(dest='command', required=True)
    sheet = commands.add_parser('sheet')
    sheet.add_argument('--step-ms', type=int, help='Optional thumbnail spacing for a local movie image sheet')
    sheet.add_argument('--output', type=Path, required=True)
    record = commands.add_parser('record')
    record.add_argument('--output', type=Path, required=True)
    record.add_argument('--car', required=True, type=int)
    record.add_argument('--task', required=True, choices=('attack', 'follow'))
    record.add_argument('--value', required=True)
    record.add_argument('--target-car', type=int)
    record.add_argument('--scope', required=True, choices=tuple(ATTACK_PHASES))
    record.add_argument('--window-level', required=True, choices=LEVELS)
    record.add_argument('--reviewer', required=True)
    record.add_argument('--note', required=True)
    record.add_argument('--reason')
    bounds = commands.add_parser('bounds', help='Independently register both visible crossings of an identified car')
    bounds.add_argument('--output', type=Path, required=True)
    bounds.add_argument('--car', type=int, required=True)
    bounds.add_argument('--scope', choices=FULL_WINDOWS, required=True)
    bounds.add_argument('--reviewer', required=True)
    bounds.add_argument('--start-note', required=True, help='How the rider and start or last home line were identified')
    bounds.add_argument('--end-note', required=True, help='How the same rider crossed the finish')
    args = cli.parse_args(argv)
    if args.queue:
        with args.queue.open(encoding='utf-8') as f:
            pending = (json.loads(line) for line in f if line.strip())
            item = next((r for r in pending if r['stage'] == 'review' and r['race_id'] > args.after), None)
        if item is None:
            raise ValueError('no pending review after cursor')
        args.race_id = item['race_id']
    elif args.next:
        from scripts.keirin_video_corpus import pending
        if args.db is None:
            raise ValueError('--next requires the corpus ledger')
        with read_db(args.db) as db:
            db.row_factory = sqlite3.Row
            row = next(pending(db, stage='review', after=args.after, limit=1), None)
        if row is None:
            raise ValueError('no pending review after cursor')
        args.race_id = row['race_id']
    elif args.after:
        raise ValueError('--after requires a review queue')
    inputs = review_inputs(args)
    _, _, source, frames = inputs
    protected = [args.census or args.db, args.media or args.media_db, *(Path(f['path']) for f in frames)]
    if args.queue:
        protected.append(args.queue)
    if source['kind'] != 'frames':
        protected.append(Path(source['path']))
    if args.output.resolve() in {p.resolve() for p in protected}:
        raise ValueError('output would overwrite a source')
    if args.command == 'sheet':
        if args.step_ms is not None and args.step_ms <= 0:
            raise ValueError('thumbnail spacing must be positive')
        write_sheet(args, *inputs)
    elif args.command == 'bounds':
        store_review(args.output, make_bounds(args, *inputs[:3]))
    else:
        store_review(args.output, make_observation(args, *inputs))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from None
