import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.keirin_video_review import main


class KeirinVideoReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.race = {'race_id': '20251124-42-04', 'race_date': '2025-11-24'}
        roster = [{'car': 2, 'rider_id': '013456'}, {'car': 1, 'rider_id': '010123'},
                  {'car': 3, 'rider_id': None}]
        self.census = self.root / 'census'
        self.media = self.root / 'verified'
        self.census.write_text(json.dumps(dict(self.race, riders=roster)) + '\n')
        self.frames = []
        for at in [2200, 1000, 1600]:
            file = self.root / f'{at}.png'
            file.write_bytes(f'review image {at}'.encode())
            self.frames.append({'path': str(file), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                                'at_ms': at})
        self.item = dict(self.race, kind='frames', status='verified', frames=self.frames, source_ref='digest-1')
        self.write_media(self.item)
        self.args = ['--census', str(self.census), '--media', str(self.media),
                     '--race-id', self.race['race_id'], '--start-ms', '1000', '--end-ms', '2200']
        self.out = self.root / 'reviews.jsonl'
        self.record = ['record', '--output', str(self.out), '--car', '2', '--task', 'follow',
                       '--value', 'held', '--target-car', '1', '--scope', 'B', '--window-level',
                       'clip', '--reviewer', 'observer', '--note', 'visible in the same lane']

    def write_media(self, *items):
        self.media.write_text(''.join(json.dumps(x) + '\n' for x in items))

    def test_actual_entrypoint_renders_private_sheet_with_ordered_links_and_exact_ms(self):
        output = self.root / 'review.html'
        main([*self.args, 'sheet', '--output', str(output)])
        html = output.read_text()
        self.assertLess(html.index('1000 ms'), html.index('1600 ms'))
        self.assertLess(html.index('1600 ms'), html.index('2200 ms'))
        self.assertIn((self.root / '1000.png').as_uri(), html)
        self.assertIn('013456', html)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_entries_bind_riders_and_bytes_and_retry_does_not_duplicate(self):
        main(self.args + self.record)
        main(self.args + self.record)
        rows = [json.loads(x) for x in self.out.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['rider_id'], rows[0]['target_rider_id']), ('013456', '010123'))
        self.assertEqual([f['at_ms'] for f in rows[0]['evidence_frames']], [1000, 1600, 2200])
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            main(self.args + self.record + ['--value', 'lost'])

    def test_bounded_screenshot_clock_is_for_inspection(self):
        for frame in self.frames:
            frame['window_ms'] = [frame['at_ms'] - 45, frame['at_ms'] + 65]
        self.write_media(self.item)
        output = self.root / 'windows.html'
        main([*self.args, 'sheet', '--output', str(output)])
        self.assertIn('955–1065 ms', output.read_text())
        with self.assertRaisesRegex(ValueError, 'time window'):
            main(self.args + self.record)
        self.assertFalse(self.out.exists())

    def test_unknown_records_reason_but_never_fabricates_a_target(self):
        args = self.record.copy()
        del args[args.index('--target-car'):args.index('--target-car') + 2]
        with self.assertRaisesRegex(ValueError, 'reason'):
            main(self.args + args + ['--value', 'unknown'])
        main(self.args + args + ['--value', 'unknown', '--reason', 'occluded'])
        row = json.loads(self.out.read_text())
        self.assertEqual((row['value'], row['reason']), ('unknown', 'occluded'))
        self.assertNotIn('target_rider_id', row)

    def test_missing_identity_two_clock_sources_mismatch_and_sparse_bounds_fail(self):
        with self.assertRaisesRegex(ValueError, 'rider'):
            main(self.args + self.record + ['--car', '3'])
        with self.assertRaisesRegex(ValueError, 'target'):
            main(self.args + self.record + ['--target-car', '2'])
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            main([*self.args, '--end-ms', '2313', *self.record])
        with self.assertRaisesRegex(ValueError, 'clip'):
            main(self.args + self.record + ['--window-level', 'sector'])
        self.write_media(self.item, dict(self.item, source_ref='other'))
        with self.assertRaisesRegex(ValueError, 'source'):
            main(self.args + self.record)
        self.write_media(dict(self.item, race_date='2025-11-25'))
        with self.assertRaisesRegex(ValueError, 'date'):
            main(self.args + self.record)

    def test_media_rehash_prevents_record_after_private_file_changed(self):
        (self.root / '1600.png').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'hash'):
            main(self.args + self.record)
        self.assertFalse(self.out.exists())

    def test_movie_offset_is_in_replay_clock_and_window_must_be_in_replay(self):
        item = dict(self.race, kind='clip', status='verified', source_ref='owner-2',
                    path=self.frames[0]['path'], sha256=self.frames[0]['sha256'],
                    start_ms=1000, duration_ms=1500)
        self.write_media(item)
        main(self.args + self.record)
        row = json.loads(self.out.read_text())
        self.assertEqual(row['media_sha256'], item['sha256'])
        with self.assertRaisesRegex(ValueError, 'duration'):
            main([*self.args, '--end-ms', '2600', *self.record])

    def test_queue_entrypoint_skips_source_stage_and_renders_whole_time_range(self):
        queue = self.root / 'queue'
        queue.write_text(json.dumps({'stage':'source','race_id':'20251124-42-02'}) + '\n'
                         + json.dumps(dict(self.race, stage='review')) + '\n')
        output = self.root / 'queue.html'
        args = [*self.args[:4], '--queue', str(queue), '--after', '20251124-42-01', 'sheet', '--output', str(output)]
        main(args)
        self.assertIn('2200 ms', output.read_text())
        timed = [*self.args[:4], '--race-id', self.race['race_id'], *self.record]
        with self.assertRaisesRegex(ValueError, 'explicit'):
            main(timed)

    def test_new_early_scope_and_asset_selection_support_dated_digest_bundles(self):
        older = dict(self.race, kind='clip', status='verified', source_ref=self.item['source_ref'],
                     path=self.frames[0]['path'], sha256=self.frames[0]['sha256'], duration_ms=4000, start_ms=0)
        self.write_media(self.item, older)
        args = [*self.args, '--asset', older['sha256'], 'record', '--output', str(self.out),
                '--car', '2', '--task', 'attack', '--value', 'bell', '--scope', 'bell_to_H',
                '--window-level', 'clip', '--reviewer', 'analyst', '--note', 'left at bell']
        main(args)
        self.assertEqual(json.loads(self.out.read_text())['value'], 'bell')
        with self.assertRaisesRegex(ValueError, 'expected one'):
            main([*self.args, 'sheet', '--output', str(self.root/'mixed.html')])

    def test_private_image_sheet_viewable_without_browser_file_access(self):
        from PIL import Image

        for i, f in enumerate(self.frames):
            source = Path(f['path'])
            Image.new('RGB', (80, 60), ('red', 'blue', 'white')[i]).save(source)
            f['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.write_media(self.item)
        sheet = self.root / 'local-view.jpg'
        main([*self.args, 'sheet', '--output', str(sheet)])
        with Image.open(sheet) as result:
            result.load()
            self.assertEqual((result.width, result.format), (1080, 'JPEG'))
        self.assertEqual(sheet.stat().st_mode & 0o777, 0o600)

    def test_passed_target_binds_the_passed_rider(self):
        main(self.args + self.record + ['--value', 'passed_target'])
        row = json.loads(self.out.read_text())
        self.assertEqual((row['value'], row['target_rider_id']), ('passed_target', '010123'))

    def test_independent_crossing_receipt_requires_movie_and_visible_cues(self):
        bounds = ['bounds', '--output', str(self.out), '--scope', 'whole_final_lap', '--car', '2',
                  '--reviewer', 'observer-2', '--start-note', 'black at H', '--end-note', 'black crossed line']
        with self.assertRaisesRegex(ValueError, 'continuous'):
            main(self.args + bounds)
        older = dict(self.race, kind='clip', status='verified', source_ref='movie',
                     path=self.frames[0]['path'], sha256=self.frames[0]['sha256'], duration_ms=4000, start_ms=0)
        self.write_media(older)
        main(self.args + bounds)
        row = json.loads(self.out.read_text())
        self.assertEqual((row['car'], row['media_sha256'], row['scope']), (2, older['sha256'], 'whole_final_lap'))
        self.assertNotIn('value', row)

    def test_indexed_lookup_uses_one_queue_race_from_existing_corpus(self):
        import sqlite3
        from scripts.keirin_video_corpus import setup, load_race, load_media

        db_path = self.root / 'ledger.sqlite'
        with sqlite3.connect(db_path) as db:
            setup(db)
            race = json.loads(self.census.read_text())
            load_race(db, race)
            load_media(db, self.item)
        out = self.root / 'indexed.html'
        main(['--db', str(db_path), '--media', str(self.media), '--next', 'sheet', '--output', str(out)])
        self.assertIn('013456', out.read_text())
