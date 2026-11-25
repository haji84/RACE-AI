import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
from tempfile import TemporaryDirectory
import unittest
import zlib

from scripts import keirin_video_corpus as corpus
from scripts import keirin_video_media as media


def png(red):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack(
            '>I', zlib.crc32(kind + payload))
    header = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(bytes([0, red, 60, 30]))) + chunk(b'IEND', b''))


class TestLocalMedia(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.manifest = self.root / 'assets.jsonl'
        self.db = media.connect(self.root / 'ledger.db')
        self.addCleanup(self.db.close)
        self.base = dict(race_id='20261123-26-02', race_date='2026-11-23',
                         source_ref='owner-export:race-26-02')
        self.frame = self.root / '1.png'
        self.frame.write_bytes(png(20))
        self.digest = hashlib.sha256(png(20)).hexdigest()

    def entry(self, clock, filename=None, digest=None):
        return dict(at_ms=clock, path=filename or self.frame.name, sha256=digest or self.digest)

    def write_frames(self, *frames):
        media.atomic_jsonl(self.manifest, [dict(self.base, kind='frames', frames=list(frames))])

    def test_incremental_and_changed_file_after_export(self):
        self.write_frames(self.entry(0), self.entry(12, 'later.png'))
        self.assertEqual(media.verify(self.db, self.manifest, 1),
                         dict(processed=1, pending=1, verified=1))
        self.assertEqual(media.verify(self.db, self.manifest),
                         dict(processed=1, unavailable=1, verified=1))
        self.assertEqual(media.verify(self.db, self.manifest)['processed'], 0)
        (self.root / 'later.png').write_bytes(self.frame.read_bytes())
        self.assertEqual(media.verify(self.db, self.manifest), dict(processed=1, verified=2))
        self.assertEqual(list(media.verified_rows(self.db, '20261123-26-03')), [])
        row, = media.verified_rows(self.db, self.base['race_id'])
        self.assertEqual([f['at_ms'] for f in row['frames']], [0, 12])
        self.assertEqual(row['coverage'], 'discrete_frames')
        self.frame.write_bytes(png(100))
        with self.assertRaisesRegex(ValueError, 'changed since verification'):
            list(media.verified_rows(self.db))
        self.assertEqual(media.verify(self.db, self.manifest), dict(processed=1, hash_mismatch=1, verified=1))
        self.assertEqual(len(next(media.verified_rows(self.db))['frames']), 1)

    def test_bad_bytes_decoding_and_invalid_manifest_rollback(self):
        self.frame.write_bytes(b'bad image')
        self.write_frames(self.entry(0, digest=hashlib.sha256(b'bad image').hexdigest()))
        self.assertEqual(media.verify(self.db, self.manifest), dict(processed=1, decode_failed=1))
        self.write_frames(self.entry(0), self.entry(0, digest='f' * 64))
        with self.assertRaisesRegex(ValueError, 'conflicting input'):
            media.verify(self.db, self.manifest)
        self.assertEqual(self.db.execute('SELECT status FROM active JOIN assets USING(id)').fetchall(),
                         [('decode_failed',)])

    def test_capture_binding_and_filename_rounding(self):
        folder = self.root / '202611232602'
        folder.mkdir()
        path = folder / 'overview.json'
        item = dict(public_result_page='https://keirin.kdreams.jp/seibuen/racedetail/2620261123010002/',
                    page_title='競輪 2R | 2026年11月23日', browser_player_seconds=11.0,
                    frames=[dict(video_seconds=2.214, frame_sha256=self.digest)])
        (folder / 't00222.png').write_bytes(self.frame.read_bytes())
        path.write_text(json.dumps(item))
        row, = media.captured_rows([self.root])
        self.assertEqual(row['frames'][0]['at_ms'], 2214)
        self.assertEqual(Path(row['frames'][0]['path']).name, 't00222.png')
        path.write_text(json.dumps(dict(item, page_title='競輪 2R | 2026年11月22日')))
        with self.assertRaisesRegex(ValueError, 'day mismatch'):
            list(media.captured_rows([self.root]))

    def test_combined_manifests_and_resume_without_old_active_rows(self):
        self.write_frames(self.entry(11))
        other = self.root / 'second.jsonl'
        media.atomic_jsonl(other, [dict(self.base, kind='frames', frames=[self.entry(22)])])
        def collect(paths):
            return media.verify_assets(self.db, media.input_assets(paths))
        self.assertEqual(collect([self.manifest, other]), dict(processed=2, verified=2))
        self.assertEqual(collect([other]), dict(processed=0, verified=1))
        row, = media.verified_rows(self.db)
        self.assertEqual([f['at_ms'] for f in row['frames']], [22])
        self.assertEqual(collect([self.manifest, other]), dict(processed=0, verified=2))

    def test_digest_capture_identity_cannot_be_upgraded_to_full(self):
        folder = self.root / '202611232602'
        folder.mkdir()
        url = 'https://keirin.kdreams.jp/seibuen/racedetail/2620261123010002/'
        receipt = dict(self.base, kind='clip', public_result_page=url,
                       source_ref=url + '#ordinary-screen-digest', path='digest.mp4',
                       start_ms=0, sha256=self.digest, page_title='2R | 2026年11月23日')
        path = folder / 'clip.json'
        path.write_text(json.dumps(receipt))
        row, = media.captured_rows([self.root])
        self.assertEqual((row['kind'], row['source_ref'], Path(row['path']).parent),
                         ('clip', receipt['source_ref'], folder.resolve()))
        path.write_text(json.dumps(dict(receipt, kind='full')))
        with self.assertRaisesRegex(ValueError, 'clip identity'):
            list(media.captured_rows([self.root]))

    def test_winticket_capture_root_requires_bound_identity_approval_and_player_end(self):
        folder = self.root / '202405038401'
        folder.mkdir()
        url = 'https://www.winticket.jp/keirin/takeo/raceresult/2024050184/3/1'
        race = '20240503-84-01'
        receipt = dict(race_id=race, race_date='2024-05-03', kind='clip',
                       public_result_page=url, source_ref=url + '#ordinary-screen-digest',
                       path='digest.mp4', start_ms=0, sha256=self.digest, browser_player_ended=True,
                       page_title='武雄競輪 開催名（2024年5月3日)1レース 結果')
        proof = dict(race_id=race, source_ref=url, permission_basis='owner_attestation',
                     decision_sha256='a' * 64, rights_sha256='b' * 64)
        path = folder / 'clip.json'
        approval = folder / 'source-approval.json'
        path.write_text(json.dumps(receipt))
        approval.write_text(json.dumps(proof))
        row, = media.captured_rows([self.root])
        self.assertEqual((row['race_id'], row['kind'], row['source_ref']),
                         (race, 'clip', receipt['source_ref']))
        for changed in ({'browser_player_ended': False}, {'page_title': '小倉競輪 2024年5月3日 1レース'},
                        {'public_result_page': url.replace('/3/1', '/2/1')}):
            path.write_text(json.dumps({**receipt, **changed}))
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                list(media.captured_rows([self.root]))
        path.write_text(json.dumps(receipt))
        approval.write_text(json.dumps(dict(proof, source_ref=url.replace('/3/1', '/3/2'))))
        with self.assertRaises(ValueError):
            list(media.captured_rows([self.root]))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local movie decoder unavailable')
    def test_decode_complete_local_movie_and_clip_clock(self):
        path = self.root / 'small.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=32x32:r=4:d=1',
                        '-c:v', 'mpeg4', str(path)], check=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        media.atomic_jsonl(self.manifest, [dict(self.base, kind='clip', start_ms=12500,
                                               path=path.name, sha256=digest)])
        self.assertEqual(media.verify(self.db, self.manifest), dict(processed=1, verified=1))
        row, = media.verified_rows(self.db)
        self.assertEqual((row['coverage'], row['start_ms'], row['duration_ms'], row['decoded_frames']),
                         ('owner_declared_clip', 12500, 1000, 4))
        self.assertNotIn('frames', row)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local movie decoder unavailable')
    def test_quality_rejects_black_and_frozen_movies_before_corpus_ingest(self):
        capture = self.root / 'capture' / '202611232602'
        capture.mkdir(parents=True)
        blank = capture / 'digest.mp4'
        # A clock changing in the footer can mask a black race image.
        make_movie(blank, 'color=black:s=1280x720:r=8:d=4',
                   "drawbox=x=0:y=696:w=iw:h=24:color=white:t=fill:enable='lt(mod(t,1),0.5)'")
        url = 'https://keirin.kdreams.jp/seibuen/racedetail/2620261123010002/'
        (capture / 'clip.json').write_text(json.dumps(dict(
            self.base, kind='clip', source_ref=url + '#ordinary-screen-digest',
            public_result_page=url, page_title='2R | 2026年11月23日', start_ms=0,
            path=blank.name, sha256=hashlib.sha256(blank.read_bytes()).hexdigest())))

        frozen = self.root / 'frozen.mp4'
        make_movie(frozen, 'color=red:s=160x96:r=8:d=4')
        usable = self.root / 'moving.mp4'
        make_movie(usable, 'testsrc2=s=160x96:r=8:d=4',
                   "drawbox=color=black:t=fill:enable='lt(t,0.5)'")
        media.atomic_jsonl(self.manifest, [dict(
            self.base, race_id=f'20261123-26-{number:02}', kind='full', path=movie.name,
            sha256=hashlib.sha256(movie.read_bytes()).hexdigest())
            for number, movie in ((3, frozen), (4, usable))])

        results = media.verify_assets(self.db, media.input_assets([self.manifest], [capture.parent]))
        self.assertEqual(results, dict(processed=3, black_video=1, frozen_video=1, verified=1))
        row, = media.verified_rows(self.db)
        self.assertEqual(row['race_id'], '20261123-26-04')
        self.assertEqual((row['width'], row['height'], row['size_bytes']),
                         (160, 96, usable.stat().st_size))
        self.assertEqual((row['longest_black_ms'], row['longest_frozen_ms']), (500, 0))
        with sqlite3.connect(':memory:') as review:
            corpus.setup(review)
            for number in (2, 3, 4):
                corpus.load_race(review, dict(race_id=f'20261123-26-{number:02}',
                                               race_date='2026-11-23', riders=[]))
            corpus.load_media(review, row)
            self.assertEqual([race['race_id'] for race in corpus.pending(review, stage='continuous')],
                             ['20261123-26-02', '20261123-26-03'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local movie decoder unavailable')
    def test_prior_decode_only_movie_receipt_is_preserved_but_needs_quality_check(self):
        path = self.root / 'black.mp4'
        make_movie(path, 'color=black:s=64x36:r=4:d=1')
        row = dict(self.base, kind='clip', path=path.name,
                   sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        media.atomic_jsonl(self.manifest, [row])
        spec = dict(self.base, kind='clip', path=str(path), at_ms=0, sha256=row['sha256'])
        old_id = hashlib.sha256(media.canonical(spec).encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT INTO assets VALUES(?,?,?,?,?)', (
                old_id, media.canonical(spec), media.fingerprint(path), 'verified',
                '{"decoded_frames":4,"duration_ms":1000}'))
            self.db.execute('INSERT INTO active VALUES(?,?,?,?,?,?)', (
                row['race_id'], row['source_ref'], 'clip', 0, str(path), old_id))

        with self.assertRaisesRegex(ValueError, 'quality check'):
            list(media.verified_rows(self.db))
        self.assertEqual(media.verify(self.db, self.manifest), dict(processed=1, black_video=1))
        self.assertEqual(list(media.verified_rows(self.db)), [])
        self.assertEqual(self.db.execute('SELECT status FROM assets WHERE id=?', (old_id,)).fetchone(),
                         ('verified',))


def make_movie(path, source, video_filter=None):
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', source]
    if video_filter:
        args.extend(('-vf', video_filter))
    subprocess.run([*args, '-c:v', 'mpeg4', '-threads', '1', str(path)], check=True)
