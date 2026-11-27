"""Deterministic offline checks for the KEIRIN racing bib tracker."""
from hashlib import sha256
from pathlib import Path
from shutil import which
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw


def frame(red_x=175, *, duplicate=False):
    image = Image.new('RGB', (640, 360), (120, 119, 110))
    draw = ImageDraw.Draw(image)
    draw.ellipse((red_x-11, 154, red_x+12, 170), fill=(163, 62, 83))
    draw.ellipse((253, 146, 282, 166), fill=(79, 123, 174))
    draw.ellipse((334, 141, 358, 158), fill=(202, 177, 74))
    draw.ellipse((403, 137, 427, 153), fill=(97, 154, 132))
    # Known positions of the Takeo score overlay and event logo.
    draw.rectangle((532, 16, 550, 33), fill=(255, 1, 9))
    draw.rectangle((51, 42, 105, 59), fill=(23, 80, 210))
    if duplicate:
        draw.ellipse((450, 152, 473, 170), fill=(163, 62, 83))
    return np.asarray(image)


class KeirinVideoTrackingTests(unittest.TestCase):
    @unittest.skipUnless(which('ffmpeg') and which('ffprobe'), 'FFmpeg tools are required')
    def test_samples_source_frames_on_the_same_clock_as_the_reviews(self):
        from scripts import keirin_video_tracking as tracking

        with TemporaryDirectory() as folder:
            path = Path(folder)/'clock.mp4'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=1280x720:r=25:d=2',
                            '-vf', "drawbox=w=1280:h=720:c=white:t=fill:enable='not(mod(n,5))'",
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-threads', '1', str(path)],
                           check=True, timeout=20)

            def examine(frames, cars, *, scale):
                selected = list(frames)
                self.assertEqual([at for at, _ in selected], list(range(0, 2000, 200)))
                self.assertTrue(all(frame[100, 100, 0] > 200 for _, frame in selected))
                return []

            with patch.object(tracking, 'track_frames', side_effect=examine):
                tracking._track_clip(path, sha256(path.read_bytes()).hexdigest(), '20261125-84-01', [1])

    def test_track_preserves_car_identity_across_moving_frames_and_ignores_overlays(self):
        from scripts import keirin_video_tracking as tracking

        dataset = [(0, frame()), (200, frame(180)), (400, frame(185))]
        tracks = tracking.track_frames(dataset, (1, 2, 3, 4, 5, 6))
        self.assertEqual(len(tracks), 3)
        self.assertEqual(tracks[0]['riders']['3']['track_id'], tracks[2]['riders']['3']['track_id'])
        self.assertEqual(set(tracks[1]['riders']), {'3', '4', '5', '6'})
        self.assertAlmostEqual(tracks[2]['riders']['3']['x'], 185, delta=3)
        self.assertAlmostEqual(tracks[2]['riders']['4']['y'], 156, delta=3)

    def test_duplicate_colour_away_from_a_confirmed_track_can_abstain(self):
        from scripts import keirin_video_tracking as tracking

        fresh = tracking.track_frames([(0, frame(duplicate=True))], (3, 4, 5, 6))[0]
        self.assertNotIn('3', fresh['riders'])
        linked = tracking.track_frames([(0, frame()), (200, frame(179, duplicate=True))], (3, 4, 5, 6))[1]
        self.assertAlmostEqual(linked['riders']['3']['x'], 179, delta=3)

    def test_phase_observations_require_repeated_broadcast_markers(self):
        from scripts import keirin_video_tracking as tracking

        blank = np.zeros((360,640,3),dtype=np.uint8)
        bell = blank.copy()
        bell[77:108,52:85] = (245,185,10)
        home = blank.copy()
        home[318:330,575:583] = (220,175,70)
        home[318:326,533:545] = (220,175,70)
        home[318:326,550:561] = (220,175,70)
        home[318:326,603:612] = (220,175,70)
        frames = [(0,blank), (200,bell), (400,bell), (600,bell),
                  (800,blank), (2000,home), (2200,home), (2400,home), (2600,home)]
        labels = tracking.phase_observations(frames)
        self.assertEqual(labels['BELL']['observed_from_ms'],200)
        self.assertEqual(labels['HOME']['state'],'BROADCAST_ANCHOR')
        self.assertEqual(labels['BELL']['source'],'bell_icon')
        self.assertEqual(labels['HOME']['source'],'last_lap_graphic')
        self.assertEqual(labels['BACK']['state'],'UNKNOWN')
        self.assertEqual(tracking.phase_observations([(0,bell)])['BELL']['state'],'UNKNOWN')

    def test_independent_scoring_counts_switches_only_for_unambiguous_same_shot_links(self):
        from scripts import keirin_video_tracking as tracking

        reference = {at: {'3': (100, 100), '4': (370, 100)} for at in (0, 200, 400, 600)}
        different_review = {at: {'3': (101, 100), '4': (370, 102)} for at in reference}
        def observation(at, x, *, cut=False):
            return dict(at_ms=at, cut_before=cut, riders={'3': {'x': x, 'y': 100, 'track_id': 9}})
        found = tracking.score_reference([observation(0, 100), observation(200, 370),
            observation(400, 100, cut=True), observation(600, 100)], reference, different_review,
            width=640, cars=(3, 4))
        self.assertEqual(found['identity_links_compared'], 2)
        self.assertEqual(found['identity_switches_observed'], 1)
        self.assertEqual(found['camera_cut_intervals_excluded'], 1)

    def test_independent_scoring_reports_unknowns_and_different_car_assignments(self):
        from scripts import keirin_video_tracking as tracking

        first = {0: {'3': (175, 162), '4': (270, 155), '5': (345, 150)}}
        second = {0: {'3': (173, 160), '4': (270, 154), '5': (430, 182), '6': (413, 146)}}
        measured = [{ 'at_ms': 0, 'riders': {'3': {'x': 170, 'y': 162}, '4': {'x': 100, 'y': 115},
                                           '6': {'x': 415, 'y': 146}}}]
        scores = tracking.score_reference(measured, first, second, width=640, cars=(3, 4, 5, 6))
        self.assertEqual(scores['agreed_points'], 2)
        self.assertEqual(scores['localized_car_correctly'], 1)
        self.assertEqual(scores['localized_car_incorrectly'], 1)
        self.assertEqual(scores['reviewer_disagreements'], 1)
        self.assertEqual(scores['unscored_predictions'], 1)


if __name__ == '__main__':
    unittest.main()
