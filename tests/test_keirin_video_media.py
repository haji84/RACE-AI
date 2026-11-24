import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
from tempfile import TemporaryDirectory
import unittest
import zlib

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
                         ('clip', receipt['source_ref'], folder))
        path.write_text(json.dumps(dict(receipt, kind='full')))
        with self.assertRaisesRegex(ValueError, 'clip identity'):
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
