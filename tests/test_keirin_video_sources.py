from hashlib import sha256
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from scripts import keirin_video_sources as source


RACE = {'race_id': '20240504-13-01', 'race_date': '2024-05-04',
        'race_detail_url': 'https://keirin.kdreams.jp/iwakitaira/racedetail/1320240430050001/?pageType=showResult'}
TITLE = 'いわき平競輪 レース詳細 | 日本選手権競輪 1R | 2024年05月04日【楽天Kドリームス】'


class CaptureTests(unittest.TestCase):
    def test_listing_binds_track_and_race_with_cross_month_meeting(self):
        self.assertEqual(source.target(RACE)[0], '202405041301')
        bare = dict(RACE, race_detail_url=RACE['race_detail_url'].split('?')[0])
        self.assertEqual(source.target(bare), source.target(RACE))
        for row in (dict(RACE, race_id='20240504-13-10'),
                    dict(RACE, race_date='2024-04-30'),
                    dict(RACE, race_detail_url=RACE['race_detail_url'].replace('keirin.', 'else.')),
                    dict(RACE, race_detail_url=RACE['race_detail_url'] + '&race=9')):
            with self.assertRaises(ValueError):
                source.target(row)

    def test_title_must_confirm_real_day_and_race_including_old_yenjoy_receipts(self):
        key, _ = source.target(RACE)
        source.check_title(key, TITLE)
        source.check_title(key, '最終日（2024年5月4日） 1レース | 競輪')
        for title in (TITLE.replace(' 1R ', ' 11R '), TITLE.replace('05月04日', '04月30日')):
            with self.assertRaises(source.PlayerUnavailable):
                source.check_title(key, title)

    def test_decoded_images_required_for_resume(self):
        key, url = source.target(RACE)
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            frame = folder / 't00020.png'
            frame.write_bytes(b'reviewed-frame')
            receipt = {'public_result_page': url, 'page_title': TITLE,
                       'frames': [{'video_seconds': .2, 'frame_sha256': sha256(frame.read_bytes()).hexdigest()}]}
            (folder / 'overview.json').write_text(json.dumps(receipt))
            self.assertEqual(source.validate_receipt(folder, key, url), receipt)
            frame.write_bytes(b'another-frame')
            with self.assertRaises(ValueError):
                source.validate_receipt(folder, key, url)

    def test_denial_stops_before_interaction(self):
        key, url = source.target(RACE)
        for code in (401, 403, 429):
            page = Mock()
            page.goto.return_value.status = code
            with self.assertRaises(source.AccessDenied):
                source.capture(page, key, url, None, 3)
            page.locator.assert_not_called()

    def test_sampling_includes_last_and_initial_player_times_once(self):
        self.assertEqual(source.timeline(3.4, 3), [.2, 3.2])
        self.assertEqual(source.timeline(3.8, 3), [.2, 3.2, 3.6])
        with self.assertRaises(ValueError):
            source.timeline(float('nan'), 3)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'video toolchain required')
    def test_screen_clip_clock_excludes_non_playback_frames(self):
        with TemporaryDirectory() as temp:
            video = Path(temp) / 'screen.mkv'
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i',
                            'color=black:s=32x720:r=10:d=1',
                            '-vf', "drawbox=x=0:y=700:w=16:h=16:color=lime:t=fill:enable='between(t,0.2,0.6)'",
                            '-c:v', 'ffv1', str(video)], check=True)
            start, end = source.recording_bounds(video)
            self.assertAlmostEqual(start, .2)
            self.assertGreaterEqual(end, .5)
            self.assertLessEqual(end, .6)

    def test_resumed_movie_must_match_saved_hash_and_ordinary_race(self):
        key, url = source.target(RACE)
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'digest.mp4').write_bytes(b'example recording')
            receipt = {'public_result_page': url, 'page_title': TITLE, 'kind': 'clip',
                       'path': 'digest.mp4', 'sha256': sha256(b'example recording').hexdigest()}
            (folder / 'clip.json').write_text(json.dumps(receipt))
            source.check_clip(folder, key, url)
            (folder / 'digest.mp4').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                source.check_clip(folder, key, url)

    def test_retry_history_does_not_starve_unvisited_rows(self):
        with TemporaryDirectory() as temp:
            log = Path(temp) / 'attempts.jsonl'
            def row(key, status):
                return json.dumps({'race_id': key, 'source_ref': 'public page', 'status': status})
            log.write_text('\n'.join([row('old', 'ordinary player timeout'), row('old', 'captured'),
                                      row('missing', 'digest button unavailable')]))
            self.assertEqual(source.failed_attempts(log), {('missing', 'public page')})


if __name__ == '__main__':
    unittest.main()
