"""Real decoding with controlled detector/OCR observations; never field proof."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

AVAILABLE = importlib.util.find_spec('cv2') is not None and shutil.which('ffmpeg') and shutil.which('ffprobe')


class ControlledHullIdentity:
    """Known synthetic boxes isolate extractor integration from detector quality."""
    def __init__(self, *, stationary=False, missing=None, switch_track_at=None):
        self.stationary, self.missing, self.calls = stationary, missing, 0
        self.switch_track_at = switch_track_at
        self.frame_hashes = {}

    def detect(self, frame):
        i = self.calls
        self.calls += 1
        self.frame_hashes[i] = hashlib.sha256(frame.tobytes()).hexdigest()
        return [{'box': [38 + 60 * n + (0 if self.stationary else 3 * i) - i, 105, 15, 11],
                 'score': .99} for n in range(6)]

    def identify(self, frame, detections, *, t, frame_index, scene, previous_to_current=None):
        if frame_index < 2:
            return {'regions': [], 'exclusion_boxes': [d['box'] for d in detections]}
        return {'regions': [{'lane': n + 1, 'box': d['box'], 'track_id': 'T%06d' % (n + 1 +
                (10 if self.switch_track_at is not None and frame_index >= self.switch_track_at else 0)),
                'identity_status': 'NUMBER_TEMPORAL_CANDIDATE',
                'number_evidence': {'frames': [frame_index - 2, frame_index - 1, frame_index],
                                    'digit': str(n + 1)}} for n, d in enumerate(detections)
                if not (self.missing == n + 1 and 12 <= frame_index <= 15)],
                'exclusion_boxes': [d['box'] for d in detections]}

    def metadata(self):
        return {'schema_version': 'SYNTHETIC_IDENTITY_PROVIDER_V1',
                'identity_status': 'NUMBER_TEMPORAL_CANDIDATE', 'model_eligible': False,
                'validation_status': 'UNVALIDATED'}


@unittest.skipUnless(AVAILABLE, 'optional CV and FFmpeg required')
class IdentityTrackingIntegrationTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.cv2, self.np = cv2, np
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def video(self, *, stationary=False):
        cv2, np = self.cv2, self.np
        bg = cv2.cvtColor(cv2.GaussianBlur(np.random.default_rng(108).integers(
            45, 165, (240, 640), dtype=np.uint8), (3, 3), 0), cv2.COLOR_GRAY2BGR)
        path = self.root / 'SYNTHETIC-six-achromatic-hulls.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (480, 240))
        self.assertTrue(writer.isOpened())
        for i in range(32):
            frame = bg[:, i:i + 480].copy()
            for n, value in enumerate((245, 5, 210, 190, 20, 225)):
                x = 38 + 60 * n + (0 if stationary else 3 * i) - i
                cv2.rectangle(frame, (x, 105), (x + 14, 115), (value,) * 3, -1)
            writer.write(frame)
        writer.release()
        return path

    def extract(self, path, provider):
        from race_ai.boat_video_tracking import extract_tracks
        try:
            return extract_tracks(path, identity_provider=provider)
        except TypeError as exc:
            if 'identity_provider' in str(exc):
                self.fail('extractor has no optional all-six identity provider')
            raise

    def test_all_six_achromatic_hulls_are_candidates_not_verified_identities(self):
        provider = ControlledHullIdentity()
        out = self.extract(self.video(), provider)
        self.assertFalse(out['model_eligible'])
        self.assertEqual(out['validation_status'], 'UNVALIDATED')
        for track in out['tracks']:
            self.assertEqual(track['identity_status'], 'NUMBER_TEMPORAL_CANDIDATE')
            valid = [s for s in track['samples'] if s['valid']]
            self.assertGreaterEqual(len(valid), 20, track['lane'])
            for sample in valid:
                expected = 45 + 60 * (track['lane'] - 1) + 3 * sample['frame_index']
                self.assertAlmostEqual(sample['x'], expected, delta=1.5)
                self.assertIn('identity_evidence', sample)
                self.assertEqual(sample['frame_sha256'], provider.frame_hashes[sample['frame_index']])
        self.assertIn('identity_provider', out['quality'])
        self.assertNotIn('ACHROMATIC_LANES_UNRESOLVED', out['quality']['flags'])

    def test_camera_only_movement_does_not_become_six_measured_boats(self):
        out = self.extract(self.video(stationary=True), ControlledHullIdentity(stationary=True))
        self.assertTrue(all(not s['valid'] for t in out['tracks'] for s in t['samples']))

    def test_actual_identity_provider_integrates_with_decoder_for_all_six(self):
        from race_ai.boat_video_identity import BoatIdentityProvider
        boxes = ControlledHullIdentity()
        values = (245, 5, 210, 190, 20, 225)
        def numbered_crop(crop):
            # Explicit synthetic fixture reader; actual association is not mocked.
            mean = float(crop[2:-2, 2:-2].mean())
            number = min(range(6), key=lambda n: abs(values[n]-mean)) + 1
            return [{'text': str(number), 'score': .99, 'box': [3, 2, 4, 6]}]
        provider = BoatIdentityProvider(detector=boxes.detect, number_reader=numbered_crop)
        result = self.extract(self.video(), provider)
        for track in result['tracks']:
            valid = [s for s in track['samples'] if s['valid']]
            self.assertGreaterEqual(len(valid), 20, track['lane'])
            self.assertTrue(all(isinstance(s['identity_track_id'], str) for s in valid))
            self.assertTrue(all(s['identity_evidence']['number'] == track['lane'] for s in valid))

    def test_small_valid_detector_boxes_are_excluded_but_not_measured(self):
        from race_ai.boat_video_identity import BoatIdentityProvider, decode_yolox_regions
        from race_ai.boat_video_tracking import _provider_detections, _provider_candidates
        import math
        frame = self.np.zeros((640, 640, 3), dtype=self.np.uint8)
        prediction = self.np.zeros((1, 8400, 85), dtype=self.np.float32)
        prediction[0, 0, :4] = [10, 10, math.log(.25), math.log(.25)]
        prediction[0, 0, 4] = prediction[0, 0, 13] = 1
        boxes = decode_yolox_regions(prediction, width=640, height=640)
        self.assertTrue(boxes)
        self.assertLess(boxes[0]['box'][2], 3)
        provider = BoatIdentityProvider(detector=lambda _: boxes, number_reader=lambda _: [])
        roi = self.np.full(frame.shape[:2], 255, dtype=self.np.uint8)
        raw, exclusion = _provider_detections(provider, frame, roi, self.np)
        self.assertGreater(int((exclusion > 0).sum()), 0)
        self.assertEqual(len(raw), 1)
        observation = {'regions': [{'lane': 1, 'track_id': 'T000001', 'box': raw[0]['box'],
            'identity_status': 'NUMBER_TEMPORAL_CANDIDATE', 'number_evidence': {'number': 1}}]}
        candidates, _ = _provider_candidates(observation, roi, None, self.cv2, self.np)
        self.assertEqual(candidates[1], [])

    def test_visible_hull_without_number_continuity_remains_missing(self):
        out = self.extract(self.video(), ControlledHullIdentity(missing=1))
        lane = out['tracks'][0]
        self.assertTrue(all(not s['valid'] for s in lane['samples'] if 12 <= s['frame_index'] <= 15))
        before = [s for s in lane['samples'] if s['valid'] and s['frame_index'] < 12][-1]
        after = [s for s in lane['samples'] if s['valid'] and s['frame_index'] > 15][0]
        self.assertNotEqual(before['scene'], after['scene'])

    def test_new_anonymous_track_cannot_continue_the_old_identity_segment(self):
        out = self.extract(self.video(), ControlledHullIdentity(switch_track_at=18))
        for lane in out['tracks']:
            crossing = next(s for s in lane['samples'] if s['frame_index'] == 18)
            self.assertFalse(crossing['valid'])
            self.assertEqual(crossing['reason'], 'IDENTITY_TRACK_DISCONTINUITY')
            before = [s for s in lane['samples'] if s['valid'] and s['frame_index'] < 18][-1]
            after = [s for s in lane['samples'] if s['valid'] and s['frame_index'] > 18][0]
            self.assertNotEqual(before['scene'], after['scene'])

    def test_explicit_none_provider_preserves_default_behavior(self):
        from race_ai.boat_video_tracking import extract_tracks
        path = self.video()
        old = extract_tracks(path)
        self.assertEqual(self.extract(path, None), old)

    def test_temporal_number_status_reaches_measurement_without_promotion(self):
        from race_ai.boat_video_measurements import measure_tracks
        tracks = [{'lane': 1, 'identity_status': 'NUMBER_TEMPORAL_CANDIDATE', 'samples': [
            {'t': i / 10, 'x': float(4 * i), 'y': 0., 'valid': True,
             'frame_index': i, 'scene': 0} for i in range(6)]}]
        result = measure_tracks(tracks, coordinate_space='REFERENCE_IMAGE_PX')
        self.assertEqual(result['lanes'][0]['identity_status'], 'NUMBER_TEMPORAL_CANDIDATE')
        self.assertEqual(result['lanes'][0]['phases']['straight']['status'], 'MEASURED')
        self.assertFalse(result['identity_validated'])
