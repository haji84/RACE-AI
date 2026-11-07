"""Controlled typed marker observations; no OCR or real-field accuracy claim."""
from copy import deepcopy
import importlib
import importlib.util
import unittest

try:
    marker_module = importlib.import_module('race_ai.boat_video_marker_identity')
except ModuleNotFoundError:
    marker_module = None

NP = importlib.util.find_spec('numpy') is not None


@unittest.skipUnless(NP, 'optional image dependency unavailable')
class MarkerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(marker_module, 'image-only printed-marker tracker is missing')
        import numpy as np
        self.np = np

    def frame(self, index, shape=(100, 600, 3)):
        value = self.np.full(shape, 100, self.np.uint8)
        # Distinct controlled original-frame pixels, not multiple OCR views.
        value[0, 0, 0] = index
        return value

    def marker(self, number='1', x=40, *, y=40, box=None, context='SINGLE_MARK', likelihood=.2):
        return dict(box=box or [x, y, 10, 16], text=number,
                    sequence_likelihood=None if number == '' else likelihood, context_status=context)

    def update(self, tracker, index, markers, *, t=None, scene=0, frame=None):
        return tracker.update(self.frame(index) if frame is None else frame, markers,
                              t=index / 10 if t is None else t, frame_index=index, scene=scene)

    def establish(self, tracker, numbers=('1',), positions=(40,)):
        for index in range(3):
            result = self.update(tracker, index, [self.marker(n, x) for n, x in zip(numbers, positions)])
        return result

    def test_all_six_require_three_distinct_pixel_frames_and_never_emit_world_positions(self):
        tracker = marker_module.MarkerIdentityTracker()
        for index in range(3):
            rows = [self.marker(str(n), 30 + n * 75 + index) for n in range(1, 7)]
            result = self.update(tracker, index, rows)
            if index < 2:
                self.assertEqual(result['tracks'], [])
        self.assertEqual([t['number'] for t in result['tracks']], [1, 2, 3, 4, 5, 6])
        self.assertEqual(len({t['track_id'] for t in result['tracks']}), 6)
        self.assertEqual(result['coordinate_space'], 'IMAGE_PX')
        self.assertEqual(result['schema_version'], 'RACE_AI_BOAT_MARKER_IDENTITY_OBSERVATION_V1')
        for track in result['tracks']:
            evidence = track['number_evidence']
            self.assertEqual(evidence['observations'], 3)
            self.assertEqual(len({f['frame_sha256'] for f in evidence['fresh_frames']}), 3)
            self.assertEqual(track['status'], 'FRESH_NUMBER')
            self.assertIsNone(track['hull_box'])
            self.assertNotIn('world_position', track)
            self.assertNotIn('confidence', evidence)
        self.assertFalse(result['model_eligible'])
        self.assertFalse(result['identity_validated'])

    def test_same_pixel_frame_repeated_at_different_pts_is_not_fresh_evidence(self):
        tracker = marker_module.MarkerIdentityTracker()
        for i in range(5):
            result = self.update(tracker, i, [self.marker()], frame=self.frame(0))
            self.assertEqual(result['tracks'], [])
        self.assertIn('REPEATED_FRAME_PIXELS', result['quality_flags'])

    def test_duplicate_views_of_one_mark_count_once_per_frame(self):
        tracker = marker_module.MarkerIdentityTracker()
        for i in range(3):
            result = self.update(tracker, i, [self.marker(), self.marker(box=[40.2, 40, 10, 16], likelihood=.4)])
            if i < 2:
                self.assertEqual(result['tracks'], [])
        self.assertEqual(len(result['tracks']), 1)
        self.assertEqual(result['tracks'][0]['number_evidence']['observations'], 3)

    def test_visible_empty_ocr_holds_without_new_evidence_and_expires_from_last_number(self):
        tracker = marker_module.MarkerIdentityTracker()
        established = self.establish(tracker)['tracks'][0]
        for i in range(3, 7):
            result = self.update(tracker, i, [self.marker('')])
            held = result['tracks'][0]
            self.assertEqual(held['track_id'], established['track_id'])
            self.assertEqual(held['status'], 'HELD_NUMBER')
            self.assertEqual(held['number_evidence']['observations'], 3)
            self.assertEqual(held['number_evidence']['last_observed_t'], .2)
        self.assertEqual(self.update(tracker, 7, [self.marker('')])['tracks'], [])

    def test_empty_ocr_cannot_create_an_identity_without_numeric_seed(self):
        tracker = marker_module.MarkerIdentityTracker()
        for i in range(8):
            result = self.update(tracker, i, [self.marker('')])
            self.assertEqual(result['tracks'], [])

    def test_missing_marker_emits_no_predicted_position_and_reappearance_reseeds(self):
        tracker = marker_module.MarkerIdentityTracker()
        old = self.establish(tracker)['tracks'][0]['track_id']
        result = self.update(tracker, 3, [])
        self.assertEqual(result['tracks'], [])
        self.assertIn(old, result['lost_track_ids'])
        for i in range(4, 7):
            result = self.update(tracker, i, [self.marker()])
            if i < 6:
                self.assertEqual(result['tracks'], [])
        self.assertNotEqual(result['tracks'][0]['track_id'], old)

    def test_scene_gap_and_shape_reset_old_evidence(self):
        for case in ('scene', 'time', 'shape'):
            with self.subTest(case=case):
                tracker = marker_module.MarkerIdentityTracker()
                old = self.establish(tracker)['tracks'][0]['track_id']
                kwargs = {'scene': 1} if case == 'scene' else ({'t': .8} if case == 'time' else {'frame': self.frame(3, (101, 600, 3))})
                result = self.update(tracker, 3, [self.marker()], **kwargs)
                self.assertEqual(result['tracks'], [])
                self.assertIn(old, result['lost_track_ids'])

    def test_conflicting_number_at_old_location_starts_new_evidence(self):
        tracker = marker_module.MarkerIdentityTracker()
        old = self.establish(tracker)['tracks'][0]['track_id']
        for i in range(3, 6):
            result = self.update(tracker, i, [self.marker('2')])
            if i < 5:
                self.assertEqual(result['tracks'], [])
        self.assertEqual(result['tracks'][0]['number'], 2)
        self.assertNotEqual(result['tracks'][0]['track_id'], old)

    def test_strong_spatially_separate_same_number_is_unknown_on_both(self):
        tracker = marker_module.MarkerIdentityTracker()
        old = self.establish(tracker)['tracks'][0]['track_id']
        result = self.update(tracker, 3, [self.marker(likelihood=.999), self.marker(x=160, likelihood=.9999)])
        self.assertEqual(result['tracks'], [])
        self.assertIn('DUPLICATE_NUMBER', result['quality_flags'])
        self.assertIn(old, result['lost_track_ids'])

    def test_new_fresh_number_cannot_duplicate_a_held_number_elsewhere(self):
        tracker = marker_module.MarkerIdentityTracker()
        old = self.establish(tracker)['tracks'][0]['track_id']
        result = self.update(tracker, 3, [self.marker(''), self.marker('1', 160)])
        self.assertEqual(result['tracks'], [])
        self.assertIn('DUPLICATE_NUMBER', result['quality_flags'])
        self.assertIn(old, result['lost_track_ids'])

    def test_overlapping_conflicting_marks_cannot_establish_either_number(self):
        tracker = marker_module.MarkerIdentityTracker()
        for i in range(4):
            result = self.update(tracker, i, [self.marker('1'), self.marker('2', 42)])
            self.assertEqual(result['tracks'], [])

    def test_equipment_parent_context_blocks_numeric_fragment_and_resets_old_seed(self):
        tracker = marker_module.MarkerIdentityTracker()
        old = self.establish(tracker, ('6',), (40,))['tracks'][0]['track_id']
        fragment = self.marker('6')
        equipment = self.marker('64', box=[35, 35, 32, 25], context='MULTIDIGIT_GROUP', likelihood=None)
        result = self.update(tracker, 3, [fragment, equipment])
        self.assertEqual(result['tracks'], [])
        self.assertIn(old, result['lost_track_ids'])
        self.assertIn('MULTIDIGIT_CONTEXT', result['quality_flags'])

    def test_large_invalid_parent_cannot_redirect_old_number_to_a_separate_unread_mark(self):
        tracker = marker_module.MarkerIdentityTracker()
        old = self.establish(tracker, ('6',), (40,))['tracks'][0]['track_id']
        parent = self.marker('64', box=[38, 35, 15, 30], context='MULTIDIGIT_GROUP', likelihood=None)
        result = self.update(tracker, 3, [self.marker('6'), parent, self.marker('', 60)])
        self.assertEqual(result['tracks'], [])
        self.assertIn(old, result['lost_track_ids'])

    def test_overlay_ambiguous_and_nonempty_nondigit_are_not_empty_ocr_holds(self):
        for row in (self.marker('1', context='NONTARGET'), self.marker('1', context='AMBIGUOUS'),
                    self.marker('64', likelihood=None), self.marker('x')):
            with self.subTest(row=row):
                tracker = marker_module.MarkerIdentityTracker()
                self.establish(tracker)
                self.assertEqual(self.update(tracker, 3, [row])['tracks'], [])

    def test_ambiguous_unread_crossing_does_not_swap_or_coast_identity(self):
        tracker = marker_module.MarkerIdentityTracker()
        established = self.establish(tracker, ('1', '2'), (40, 64))
        old = {r['track_id'] for r in established['tracks']}
        result = self.update(tracker, 3, [self.marker('', 52)])
        self.assertEqual(result['tracks'], [])
        self.assertEqual(set(result['lost_track_ids']), old)
        self.assertIn('AMBIGUOUS_MARKER_ASSOCIATION', result['quality_flags'])

    def test_moving_ambiguous_mark_cannot_transfer_identity_to_an_unread_neighbor(self):
        tracker = marker_module.MarkerIdentityTracker()
        old = self.establish(tracker)['tracks'][0]['track_id']
        result = self.update(tracker, 3, [self.marker('1', 54, context='AMBIGUOUS'), self.marker('', 64)])
        self.assertEqual(result['tracks'], [])
        self.assertIn(old, result['lost_track_ids'])

    def test_fresh_frame_after_visible_hold_adds_one_observation_without_renaming(self):
        tracker = marker_module.MarkerIdentityTracker()
        old = self.establish(tracker)['tracks'][0]['track_id']
        self.update(tracker, 3, [self.marker('')])
        self.update(tracker, 4, [self.marker('')])
        result = self.update(tracker, 5, [self.marker()])['tracks'][0]
        self.assertEqual(result['track_id'], old)
        self.assertEqual(result['number_evidence']['observations'], 4)
        self.assertEqual([f['frame_index'] for f in result['number_evidence']['fresh_frames']], [0, 1, 2, 5])

    def test_fresh_numbers_can_resolve_a_crossing_without_renaming_tracks(self):
        tracker = marker_module.MarkerIdentityTracker()
        rows = self.establish(tracker, ('1', '2'), (40, 60))['tracks']
        ids = {r['number']: r['track_id'] for r in rows}
        result = self.update(tracker, 3, [self.marker('1', 60), self.marker('2', 40)])
        self.assertEqual({r['number']: r['track_id'] for r in result['tracks']}, ids)

    def test_invalid_input_does_not_partially_change_any_tracker_state(self):
        tracker = marker_module.MarkerIdentityTracker()
        self.establish(tracker)
        before = deepcopy(tracker.__dict__)
        invalid = [dict(self.marker(), sequence_likelihood=float('nan')), dict(self.marker(), context_status='OVERLAY'),
                   dict(self.marker(), context_status=[]),
                   dict(self.marker(), box=[599, 0, 10, 4]), {'box': [40, 40, 10, 16]}]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.update(tracker, 3, [self.marker(), row])
            self.assertEqual(tracker.__dict__, before)
        for kwargs in ({'t': .2}, {'t': float('nan')}, {'frame_index': 2}, {'scene': -1}):
            call = dict(t=.3, frame_index=3, scene=0); call.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                tracker.update(self.frame(3), [self.marker()], **call)
            self.assertEqual(tracker.__dict__, before)
        for frame in (self.np.zeros((100, 600), self.np.uint8),
                      self.np.zeros((100, 600, 3), self.np.float32),
                      self.np.zeros((0, 600, 3), self.np.uint8),
                      self.np.zeros((100, 600, 4), self.np.uint8)):
            with self.subTest(shape=frame.shape), self.assertRaises(ValueError):
                self.update(tracker, 3, [self.marker()], frame=frame)
            self.assertEqual(tracker.__dict__, before)

    def test_input_and_output_mutation_cannot_rewrite_internal_evidence(self):
        tracker = marker_module.MarkerIdentityTracker()
        result = self.establish(tracker)
        result['tracks'][0]['number_evidence']['fresh_frames'][0]['marker_box'][0] = 500
        row = self.marker()
        self.update(tracker, 3, [row]); row['box'][0] = 500
        result = self.update(tracker, 4, [self.marker('')])
        self.assertEqual(result['tracks'][0]['marker_box'][0], 40.)
        self.assertEqual(result['tracks'][0]['number_evidence']['fresh_frames'][0]['marker_box'][0], 40.)

    def test_large_global_empty_candidate_list_is_not_truncated_or_sent_to_exponential_assignment(self):
        tracker = marker_module.MarkerIdentityTracker()
        rows = [self.marker('', box=[x * 6, y * 2, 2, 1]) for y in range(50) for x in range(100)]
        result = self.update(tracker, 0, rows)
        self.assertEqual(result['raw_candidate_count'], 5000)
        self.assertEqual(len(result['unknown_markers']), 5000)
        self.assertEqual(result['tracks'], [])

    def classified(self, number='1', x=40, *, model='a' * 64, **kwargs):
        row = self.marker(number, x, likelihood=None, **kwargs)
        return dict(row, label_source='DECLARED_DEVELOPMENT_GLYPH_CLASSIFIER',
                    label_model_sha256=model)

    def test_declared_classifier_labels_need_three_frames_without_fabricated_likelihood(self):
        tracker = marker_module.MarkerIdentityTracker()
        for i in range(3):
            rows = [self.classified(str(n), 30 + n * 75 + i) for n in range(1, 7)]
            result = self.update(tracker, i, rows)
            if i < 2:
                self.assertEqual(result['tracks'], [])
        self.assertEqual([t['number'] for t in result['tracks']], [1, 2, 3, 4, 5, 6])
        for track in result['tracks']:
            evidence = track['number_evidence']
            self.assertEqual(evidence['observations'], 3)
            self.assertIsNone(evidence['sequence_likelihood_scope'])
            self.assertEqual(evidence['classifier_label_scope'],
                             'DISCRETE_DEVELOPMENT_CLASSIFICATION_NOT_PROBABILITY')
            self.assertEqual(evidence['label_model_sha256'], 'a' * 64)
            self.assertEqual([f['label_source'] for f in evidence['fresh_frames']],
                             ['DECLARED_DEVELOPMENT_GLYPH_CLASSIFIER'] * 3)
            self.assertEqual([f['label_model_sha256'] for f in evidence['fresh_frames']], ['a' * 64] * 3)
            self.assertEqual([f['sequence_likelihood'] for f in evidence['fresh_frames']], [None] * 3)
            self.assertEqual([f['frame_index'] for f in evidence['fresh_frames']], [0, 1, 2])
            self.assertEqual([f['t'] for f in evidence['fresh_frames']], [0., .1, .2])
            self.assertEqual(len({f['frame_sha256'] for f in evidence['fresh_frames']}), 3)
        self.assertFalse(result['identity_validated'])
        self.assertFalse(result['model_eligible'])

    def test_invalid_classifier_metadata_rejects_entire_update_atomically(self):
        tracker = marker_module.MarkerIdentityTracker()
        self.establish(tracker)
        before = deepcopy(tracker.__dict__)
        invalid = [dict(self.classified(), sequence_likelihood=v) for v in (1, 0, .4, False)]
        invalid += [dict(self.classified(), label_model_sha256=h) for h in
                    ('A' * 64, 'g' * 64, 'a' * 63, 'a' * 65, None, [])]
        invalid += [dict(self.classified(), label_source=s) for s in ('CTC', '', None, [])]
        invalid += [dict(self.classified(), text=s) for s in ('7', '0', '21', '12', ' 1', '１', None)]
        missing_hash = self.classified(); del missing_hash['label_model_sha256']
        missing_source = self.classified(); del missing_source['label_source']
        invalid += [missing_hash, missing_source, dict(self.classified(), extra=True)]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.update(tracker, 3, [self.marker(), row])
            self.assertEqual(tracker.__dict__, before)
        # A rejected classifier label must not consume the time/frame or a track ID.
        result = self.update(tracker, 3, [self.marker()])
        self.assertEqual(result['tracks'][0]['number_evidence']['observations'], 4)

    def test_classifier_duplicate_views_and_repeated_pixels_never_create_votes(self):
        tracker = marker_module.MarkerIdentityTracker()
        for i in range(4):
            result = self.update(tracker, i, [self.classified(), self.classified()], frame=self.frame(0))
            self.assertEqual(result['tracks'], [])
        self.assertIn('DUPLICATE_VIEWS_COLLAPSED', result['quality_flags'])
        self.assertIn('REPEATED_FRAME_PIXELS', result['quality_flags'])
        self.assertEqual(self.update(tracker, 4, [self.classified(), self.classified()])['tracks'], [])
        result = self.update(tracker, 5, [self.classified(), self.classified()])
        evidence = result['tracks'][0]['number_evidence']
        self.assertEqual(evidence['observations'], 3)
        self.assertEqual([f['frame_index'] for f in evidence['fresh_frames']], [0, 4, 5])

    def test_classifier_visible_blank_holds_but_context_conflict_and_expiry_still_block(self):
        for context in ('SINGLE_MARK', 'MULTIDIGIT_GROUP', 'NONTARGET', 'AMBIGUOUS'):
            with self.subTest(context=context):
                tracker = marker_module.MarkerIdentityTracker()
                for i in range(3):
                    established = self.update(tracker, i, [self.classified()])
                old = established['tracks'][0]['track_id']
                result = self.update(tracker, 3, [self.classified('', context=context)])
                if context != 'SINGLE_MARK':
                    self.assertEqual(result['tracks'], [])
                    self.assertIn(old, result['lost_track_ids'])
                    continue
                held = result['tracks'][0]
                self.assertEqual((held['status'], held['track_id']), ('HELD_NUMBER', old))
                self.assertEqual(held['number_evidence']['observations'], 3)
                self.assertEqual(self.update(tracker, 7, [self.classified('')])['tracks'], [])

    def test_mixed_ctc_classifier_and_model_evidence_keeps_each_origin_and_value(self):
        tracker = marker_module.MarkerIdentityTracker()
        rows = [self.marker(likelihood=.2), self.classified(), self.classified(model='b' * 64)]
        for i, row in enumerate(rows):
            result = self.update(tracker, i, [row])
        evidence = result['tracks'][0]['number_evidence']
        self.assertEqual(evidence['sequence_likelihood_scope'],
                         'UNCALIBRATED_CTC_SEQUENCE_LIKELIHOOD_NOT_ACCURACY')
        self.assertEqual(evidence['classifier_label_scope'],
                         'DISCRETE_DEVELOPMENT_CLASSIFICATION_NOT_PROBABILITY')
        self.assertEqual(evidence['label_model_sha256s'], ['a' * 64, 'b' * 64])
        self.assertEqual([r['sequence_likelihood'] for r in evidence['fresh_frames']], [.2, None, None])
        self.assertNotIn('label_source', evidence['fresh_frames'][0])
        self.assertEqual([r['label_model_sha256'] for r in evidence['fresh_frames'][1:]],
                         ['a' * 64, 'b' * 64])
        evidence['fresh_frames'][1]['label_model_sha256'] = 'c' * 64
        held = self.update(tracker, 3, [self.classified('')])['tracks'][0]['number_evidence']
        self.assertEqual(held['fresh_frames'][1]['label_model_sha256'], 'a' * 64)

    def test_classifier_contradictions_and_spatial_duplicate_numbers_do_not_bypass_rules(self):
        tracker = marker_module.MarkerIdentityTracker()
        for i in range(3):
            first = self.update(tracker, i, [self.classified()])
        old = first['tracks'][0]['track_id']
        for i in range(3, 6):
            result = self.update(tracker, i, [self.classified('2')])
            if i < 5:
                self.assertEqual(result['tracks'], [])
        self.assertEqual(result['tracks'][0]['number'], 2)
        self.assertNotEqual(result['tracks'][0]['track_id'], old)
        result = self.update(tracker, 6, [self.classified('2'), self.classified('2', 160)])
        self.assertEqual(result['tracks'], [])
        self.assertIn('DUPLICATE_NUMBER', result['quality_flags'])
        for i in range(7, 10):
            result = self.update(tracker, i, [self.classified('1'), self.marker('2', 42)])
            self.assertEqual(result['tracks'], [])
            self.assertIn('OVERLAPPING_CONFLICTING_MARKS', result['quality_flags'])

    def test_legacy_four_field_calls_keep_the_exact_legacy_evidence_shape(self):
        evidence = self.establish(marker_module.MarkerIdentityTracker())['tracks'][0]['number_evidence']
        self.assertEqual(set(evidence), {'observations', 'first_frame_index', 'last_frame_index',
                                      'last_observed_t', 'fresh_frames', 'sequence_likelihood_scope'})
        for row in evidence['fresh_frames']:
            self.assertEqual(set(row), {'frame_index', 't', 'frame_sha256', 'marker_box',
                                        'sequence_likelihood'})


if __name__ == '__main__':
    unittest.main()
