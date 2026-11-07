"""Controlled identity continuity never certifies camera motion or real footage."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

CV_AVAILABLE = importlib.util.find_spec('cv2') is not None


@unittest.skipUnless(CV_AVAILABLE, 'optional CV dependencies unavailable')
class CameraIdentityTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from race_ai import boat_video_crnn, boat_video_identity
        self.np, self.crnn, self.identity = np, boat_video_crnn, boat_video_identity
        self.frame = np.full((140, 320, 3), 100, np.uint8)

    def reading(self, number='5', *, ambiguous=False):
        proposals = [] if number is None else [dict(text=number, sequence_likelihood=.4, box=[8, 6, 10, 12])]
        if ambiguous:
            proposals.append(dict(text='2', sequence_likelihood=.3, box=[8, 6, 10, 12]))
        return dict(schema_version=self.crnn.READING_SCHEMA, score_scope=self.crnn.SCORE_SCOPE,
            proposals=proposals, status='COMPLETE', accepted_identity=False,
            soft_budget_exceeded=False, skipped_views=0, attempts=[])

    def provider(self, readings):
        values = iter(readings)
        return self.crnn.ExperimentalCRNNIdentityProvider(detector=lambda frame:[self.box()],
            number_reader=lambda crop:next(values))

    def box(self, x=100):
        return dict(box=[x, 50, 35, 30], score=.95)

    def observe(self, provider, i, *, scene=None, status='INSUFFICIENT_BACKGROUND',
                detections=None, t=None, frame=None, homography=None):
        self.assertTrue(callable(getattr(provider, 'identify_with_camera_status', None)),
                        'explicit camera-evidence identity integration is missing')
        return provider.identify_with_camera_status(self.frame if frame is None else frame,
            [self.box()] if detections is None else detections, t=i/10 if t is None else t,
            frame_index=i, scene=i if scene is None else scene, camera_status=status,
            previous_to_current=homography)

    def establish(self, provider):
        out = self.observe(provider, 0, status='REFERENCE_INITIALIZATION')
        self.assertEqual(out['regions'], [])
        out = self.observe(provider, 1)
        self.assertEqual(out['regions'], [])
        return self.observe(provider, 2, status='CAMERA_FIT_REJECTED')

    def test_three_fresh_numeric_observations_survive_only_soft_metric_camera_resets(self):
        provider = self.provider([self.reading()]*3)
        out = self.establish(provider)
        self.assertEqual([row['lane'] for row in out['regions']], [5])
        self.assertEqual(out['scene'], 2)
        self.assertEqual(out['identity_continuity_scene'], 0)
        self.assertTrue(out['identity_camera_evidence']['fresh_identity_required'])
        self.assertFalse(out['identity_camera_evidence']['metric_positions_inferred'])
        self.assertFalse(out['model_eligible'])
        self.assertFalse(out['identity_validated'])
        self.assertEqual(out['regions'][0]['number_evidence']['observations'], 3)
        self.assertNotIn('minimum_confidence', out['regions'][0]['number_evidence'])

    def test_unread_soft_frame_interrupts_then_requires_three_fresh_observations(self):
        provider = self.provider([self.reading()]*3 + [self.reading(None)] + [self.reading()]*3)
        old = self.establish(provider)['regions'][0]['track_id']
        self.assertEqual(self.observe(provider, 3)['regions'], [])
        self.assertEqual(self.observe(provider, 4)['regions'], [])
        self.assertEqual(self.observe(provider, 5)['regions'], [])
        recovered = self.observe(provider, 6)['regions'][0]
        self.assertNotEqual(recovered['track_id'], old)
        self.assertEqual(recovered['number_evidence']['first_frame_index'], 4)
        self.assertEqual(recovered['number_evidence']['observations'], 3)

    def test_ambiguous_moved_hull_and_unread_neighbor_cannot_steal_identity_during_camera_gap(self):
        provider = self.provider([self.reading()]*3 +
            [self.reading(ambiguous=True), self.reading(None)] + [self.reading()]*3)
        old = self.establish(provider)['regions'][0]['track_id']
        out = self.observe(provider, 3, detections=[self.box(135), self.box(100)])
        self.assertIn('AMBIGUOUS_NUMBER_MARKS', out['quality_flags'])
        self.assertEqual(out['regions'], [])
        self.assertEqual(self.observe(provider, 4, detections=[self.box(135)])['regions'], [])
        self.assertEqual(self.observe(provider, 5, detections=[self.box(135)])['regions'], [])
        self.assertNotEqual(self.observe(provider, 6, detections=[self.box(135)])['regions'][0]['track_id'], old)

    def test_hard_camera_statuses_reset_identity_and_require_new_three(self):
        for status in ('SCENE_CHANGE_OR_BACKGROUND_MISMATCH', 'DISPLAY_PTS_GAP', 'REFERENCE_INITIALIZATION'):
            with self.subTest(status=status):
                provider = self.provider([self.reading()]*6)
                old = self.establish(provider)['regions'][0]['track_id']
                out = self.observe(provider, 3, status=status)
                self.assertEqual(out['regions'], [])
                self.assertEqual(out['identity_continuity_scene'], 1)
                self.assertEqual(self.observe(provider, 4)['regions'], [])
                recovered = self.observe(provider, 5)['regions'][0]
                self.assertNotEqual(recovered['track_id'], old)
                self.assertEqual(recovered['number_evidence']['observations'], 3)

    def test_time_shape_and_unexplained_metric_scene_jump_reset_even_with_soft_status(self):
        for reason in ('time', 'shape', 'scene_jump'):
            with self.subTest(reason=reason):
                provider = self.provider([self.reading()]*4)
                self.establish(provider)
                options = {'t': 1.} if reason == 'time' else (
                    {'frame':self.np.full((150, 320, 3),100,self.np.uint8)} if reason=='shape' else {'scene':9})
                out = self.observe(provider, 3, **options)
                self.assertEqual(out['regions'], [])
                self.assertEqual(out['identity_continuity_scene'], 1)

    def test_accepted_transform_preserves_identity_only_with_consistent_actual_metric_scene(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                provider = self.provider([self.reading()]*4)
                old = self.establish(provider)['regions'][0]['track_id']
                out = self.observe(provider, 3, scene=3 if changed else 2,
                    status='ACCEPTED', homography=self.np.eye(3))
                self.assertEqual(out['scene'], 3 if changed else 2)
                if changed:
                    self.assertEqual(out['regions'], [])
                    self.assertEqual(out['identity_continuity_scene'], 1)
                else:
                    self.assertEqual(out['regions'][0]['track_id'], old)
                    self.assertFalse(out['identity_camera_evidence']['fresh_identity_required'])

    def test_invalid_camera_contracts_do_not_commit_helper_or_tracker_state(self):
        provider = self.provider([self.reading()]*3)
        self.establish(provider)
        before = deepcopy(provider.__dict__)
        for options in ({'status':'ACCEPTED'}, {'status':'UNKNOWN_STATUS'},
                        {'scene':1}, {'homography':self.np.eye(3)}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.observe(provider, 3, **options)
            self.assertEqual(provider._time, before['_time'])
            self.assertEqual(provider._scene, before['_scene'])
            self.assertEqual(provider._camera_identity_state, before['_camera_identity_state'])

    def test_reader_failure_does_not_commit_camera_helper_state(self):
        readings = iter([self.reading(), ValueError('controlled invalid reader contract')])
        def read(crop):
            value = next(readings)
            if isinstance(value, Exception):
                raise value
            return value
        provider = self.crnn.ExperimentalCRNNIdentityProvider(detector=lambda frame:[], number_reader=read)
        self.observe(provider, 0, status='REFERENCE_INITIALIZATION')
        state = deepcopy(provider._camera_identity_state)
        with self.assertRaises(ValueError):
            self.observe(provider, 1)
        self.assertEqual(provider._camera_identity_state, state)
        self.assertEqual(provider._time, 0.)

    def test_default_legacy_identify_outputs_remain_byte_compatible(self):
        from race_ai.boat_video_identity import BoatIdentityProvider
        def make():
            return BoatIdentityProvider(detector=lambda frame:[], number_reader=lambda crop:[
                dict(text='5',score=.98,box=[8,6,10,12])])
        default, explicit = make(), make()
        self.assertFalse(hasattr(default, 'identify_with_camera_status'))
        for i in range(4):
            kwargs = dict(t=i/10, frame_index=i, scene=i)
            left = default.identify(self.frame,[self.box()],**kwargs)
            right = explicit.identify(self.frame,[self.box()],require_current_number=False,**kwargs)
            self.assertEqual(json.dumps(left,sort_keys=True),json.dumps(right,sort_keys=True))
            self.assertEqual(left['regions'], [])
            self.assertNotIn('identity_continuity_scene', left)

    def test_explicit_fresh_identity_base_flag_drops_an_unread_observation(self):
        from race_ai.boat_video_identity import BoatIdentityProvider
        values = iter([[dict(text='5',score=.98,box=[8,6,10,12])]]*3+[[]])
        provider = BoatIdentityProvider(detector=lambda frame:[],number_reader=lambda crop:next(values))
        for i in range(3):
            out = provider.identify(self.frame,[self.box()],t=i/10,frame_index=i,scene=0)
        self.assertEqual(len(out['regions']),1)
        out = provider.identify(self.frame,[self.box()],t=.3,frame_index=3,scene=0,
                                require_current_number=True)
        self.assertEqual(out['regions'],[])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'real local decoder required')
    def test_actual_decoder_keeps_metric_positions_missing_despite_fresh_identity_continuity(self):
        import cv2
        from race_ai.boat_video_tracking import extract_tracks
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'controlled-no-camera-background.avi'
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'),10,(320,140))
            self.assertTrue(writer.isOpened())
            for _ in range(8):
                writer.write(self.frame)
            writer.release()
            provider = self.provider([self.reading()]*8)
            result = extract_tracks(path, identity_provider=provider)
            observations = result['quality']['identity_observations']
            self.assertEqual(len(observations),8)
            self.assertEqual([row['scene'] for row in observations],list(range(8)))
            self.assertEqual({row['identity_continuity_scene'] for row in observations},{0})
            self.assertEqual([row['lane'] for row in observations[-1]['regions']],[5])
            self.assertTrue(all(not row['valid'] and row['x'] is None and row['y'] is None
                                for track in result['tracks'] for row in track['samples']))
            self.assertEqual(sum(result['quality']['valid_sample_counts'].values()),0)
            self.assertFalse(result['model_eligible'])


if __name__=='__main__':
    unittest.main()
