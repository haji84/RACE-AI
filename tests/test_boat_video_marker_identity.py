"""Controlled typed marker observations; no OCR or real-field accuracy claim."""
from copy import deepcopy
from hashlib import sha256
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

    def context_hint(self, frame, index, box, *, key='S1', status='TRACKED', previous=None,
                     move=(0., 0.), scene=0, points=40, fb=0., dispersion=0., area=1.):
        return dict(scope='CONTEXT_IMAGE_TRACK', key=key, status=status,
            frame_sha256=sha256(frame.tobytes()).hexdigest(), frame_index=index, scene=scene,
            previous_frame_sha256=sha256(previous.tobytes()).hexdigest() if previous is not None else None,
            box=list(box), point_count=points,
            median_displacement_px=list(move) if status == 'TRACKED' else None,
            median_forward_backward_error_px=fb if status == 'TRACKED' else None,
            displacement_dispersion_px=dispersion if status == 'TRACKED' else None,
            affine_area_ratio=area if status == 'TRACKED' else None)

    def lineage_established(self, *, number='1', x=40):
        tracker = marker_module.MarkerIdentityTracker()
        previous = None
        for index in range(3):
            image = self.frame(index)
            row = self.marker(number, x)
            row['context_image_track'] = self.context_hint(image, index, [0, 20, 150, 65],
                previous=previous, status='SEEDED' if previous is None else 'TRACKED')
            tracker.update(image, [row], t=index/10, frame_index=index, scene=0)
            previous = image
        return tracker, previous

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

    def test_recorded_five_same_context_gate_failures_keep_fresh_evidence_without_lowering_minimum(self):
        # Numeric geometry/state from frozen development diagnostics; all
        # pixels below are synthetic controls, not private frames or real OCR.
        cases = [
            (2, 207, 5, 6.874, 6.907, [1424,1003,38,49], [1387,1007,39,45],
             [-2632.3529411764853,2500.000000000014], [1375,978,136,98],
             [1338.6607666015625,980.75146484375,136,98], [-36.3392333984375,2.75146484375],31,.028115948662161827,1.2475323677062988,.92876852517001),
            (2, 211, 1, 7.007, 7.04, [1242,996,38,38], [1202,938,65,46],
             [0,0], [1204,977,114,76], [1191.508544921875,920.8983154296875,114,76],
             [-12.49151611328125,-56.101654052734375],29,.04061058536171913,.5463746786117554,1.0769190588223816),
            (2, 215, 4, 7.14, 7.174, [1119,848,67,46], [1166,857,38,35],
             [-1151.51515151517,-772.727272727285], [1108.8592529296875,832.0599365234375,114,76],
             [1128.5517578125,838.2786254882812,114,76], [19.69244384765625,6.21868896484375],12,.017399363219738007,.5628819465637207,.9919221027619091),
            (1, 241, 1, 8.008, 8.041, [1323,692,31,43], [1354.5604248046875,767.8436889648438,31,43],
             [0,0], [1280,670,117,86], [1311.5604248046875,745.8436889648438,117,86],
             [31.5604248046875,75.84368896484375],23,.037672340869903564,.6987093091011047,1.017260139056516),
            (3, 316, 4, 10.511, 10.544, [875,777,37,37], [888.3541870117188,856.0651245117188,37,37],
             [-29.411764705883286,-205.882352941183], [837.9570922851562,759.2068481445312,112,76],
             [851.311279296875,838.27197265625,112,76], [13.35418701171875,79.06512451171875],35,.06662176549434662,.4955279231071472,1.0210451395325537),
        ]
        def pixels(index):
            image = self.np.full((1080,1920,3),100,self.np.uint8)
            image[0,0,0] = index % 256
            return image
        for number, index, count, before_t, t, old_box, box, velocity, old_context, context, move, points, fb, dispersion, area in cases:
            with self.subTest(recorded_frame=index):
                for typed in (False, True):
                    tracker = marker_module.MarkerIdentityTracker(); previous = None
                    for step in range(count):
                        frame_index = index-count+step; image = pixels(frame_index)
                        row = self.marker(str(number), box=old_box)
                        if typed:
                            row['context_image_track'] = self.context_hint(image,frame_index,old_context,
                                status='SEEDED' if previous is None else 'TRACKED',previous=previous)
                        tracker.update(image,[row],t=before_t-.033*(count-1-step),frame_index=frame_index,scene=0)
                        previous = image
                    old_id = tracker._tracks[0]['track_id']
                    # Reconstruct the recorded independent M velocity, not a
                    # detector/GroundTruth ROI or an automatic-inference claim.
                    tracker._tracks[0]['velocity'] = tuple(velocity)
                    image = pixels(index); row = self.marker(str(number),box=box)
                    if typed:
                        row['context_image_track'] = self.context_hint(image,index,context,previous=previous,
                            move=move,points=points,fb=fb,dispersion=dispersion,area=area)
                    result = tracker.update(image,[row],t=t,frame_index=index,scene=0)
                    if not typed:
                        self.assertNotEqual(tracker._tracks[0]['track_id'],old_id)
                        self.assertEqual(result['tracks'],[])
                        continue
                    self.assertEqual(tracker._tracks[0]['track_id'],old_id)
                    self.assertEqual(len(tracker._tracks[0]['evidence']),count+1)
                    self.assertIn('CONTEXT_IMAGE_TRACK_ASSOCIATION',result['quality_flags'])
                    if count == 1:
                        self.assertEqual(result['tracks'],[])  # Still requires THREE fresh frames.
                        next_image=pixels(index+1); row=self.marker(str(number),box=box)
                        row['context_image_track']=self.context_hint(next_image,index+1,context,previous=image)
                        result=tracker.update(next_image,[row],t=t+.033,frame_index=index+1,scene=0)
                    self.assertEqual(result['tracks'][0]['track_id'],old_id)
                    self.assertEqual(result['tracks'][0]['number_evidence']['context_image_track_scope'],'CONTEXT_IMAGE_TRACK')
                    self.assertFalse(result['identity_validated'])
                    self.assertIsNone(result['tracks'][0]['hull_box'])

    def test_new_key_seed_or_inconsistent_context_motion_cannot_override_geometry(self):
        for kind in ('key','seed','motion'):
            with self.subTest(kind=kind):
                tracker,previous=self.lineage_established(); old_id=tracker._tracks[0]['track_id']
                image=self.frame(3);row=self.marker(box=[100,40,10,16])
                hint=self.context_hint(image,3,[0,20,150,65],previous=previous)
                if kind=='key':hint['key']='M000001'  # Not a selector for an M ID.
                elif kind=='seed':hint=self.context_hint(image,3,[0,20,150,65],status='SEEDED')
                else:hint['median_displacement_px']=[10.,0.]
                row['context_image_track']=hint
                result=self.update(tracker,3,[row],frame=image)
                self.assertEqual(result['tracks'],[])
                self.assertNotEqual(tracker._tracks[0]['track_id'],old_id)

    def test_bad_context_hints_reject_atomically_and_allow_same_frame_retry(self):
        invalid = [dict(scope='WORLD_IDENTITY'),dict(key=True),dict(status='PREDICTED'),
                   dict(frame_sha256='0'*64),dict(previous_frame_sha256='0'*64),dict(frame_index=99),
                   dict(scene=1),dict(point_count=3),dict(point_count=True),
                   dict(median_forward_backward_error_px=1.1),dict(displacement_dispersion_px=2.1),
                   dict(affine_area_ratio=1.4),dict(box=[0,0,2,2]),dict(track_id='M000001')]
        for change in invalid:
            with self.subTest(change=change):
                tracker,previous=self.lineage_established(); before=deepcopy(tracker.__dict__)
                image=self.frame(3);row=self.marker(box=[100,40,10,16])
                good=self.context_hint(image,3,[0,20,150,65],previous=previous)
                row['context_image_track']=dict(good,**change)
                with self.assertRaises(ValueError):self.update(tracker,3,[row],frame=image)
                self.assertEqual(tracker.__dict__,before)
                row['context_image_track']=good
                result=self.update(tracker,3,[row],frame=image)
                self.assertEqual(result['tracks'][0]['track_id'],'M000001')

    def test_duplicate_context_key_is_not_an_arbitrary_correspondence_selector(self):
        tracker,previous=self.lineage_established();before=deepcopy(tracker.__dict__);image=self.frame(3)
        a,b=self.marker(box=[100,40,10,16]),self.marker('2',box=[120,40,10,16])
        a['context_image_track']=self.context_hint(image,3,[0,20,150,65],previous=previous)
        b['context_image_track']=deepcopy(a['context_image_track'])
        with self.assertRaises(ValueError):self.update(tracker,3,[a,b],frame=image)
        self.assertEqual(tracker.__dict__,before)

    def test_context_hint_never_bypasses_blank_duplicate_or_conflicting_numbers(self):
        for kind in ('blank','duplicate','conflict','parent','ambiguous','changed_number','replay','scene','gap','size'):
            with self.subTest(kind=kind):
                tracker,previous=self.lineage_established();image=self.frame(3)
                if kind=='size':image=self.frame(3,shape=(100,601,3))
                if kind=='replay':image=previous.copy()
                scene=1 if kind=='scene' else 0
                row=self.marker('' if kind=='blank' else '2' if kind=='changed_number' else '1',box=[100,40,10,16])
                row['context_image_track']=self.context_hint(image,3,[0,20,150,65],previous=previous,scene=scene)
                if kind=='ambiguous':row['context_status']='AMBIGUOUS'
                rows=[row]
                if kind=='duplicate':rows.append(self.marker('1',box=[300,40,10,16]))
                if kind=='conflict':rows.append(self.marker('2',box=[101,40,10,16]))
                if kind=='parent':rows.append(self.marker('64',box=[100,40,10,16],context='MULTIDIGIT_GROUP'))
                result=self.update(tracker,3,rows,frame=image,scene=scene,t=.7 if kind=='gap' else .3)
                self.assertEqual(result['tracks'],[])

    def test_different_view_hints_disable_recovery_after_dedup(self):
        tracker,previous=self.lineage_established();image=self.frame(3)
        rows=[self.marker(box=[100,40,10,16]),self.marker(box=[100,40,10,16])]
        for row,key in zip(rows,('S1','S2')):
            row['context_image_track']=self.context_hint(image,3,[0,20,150,65],previous=previous,key=key)
        result=self.update(tracker,3,rows,frame=image)
        self.assertEqual(result['tracks'],[])
        self.assertIn('DUPLICATE_VIEWS_COLLAPSED',result['quality_flags'])

    def test_context_binding_survives_input_sorting_without_index_aliases(self):
        tracker=marker_module.MarkerIdentityTracker();previous=None
        for index in range(4):
            image=self.frame(index);rows=[]
            for number,x,context,key in [('1',40,[0,20,150,65],'left'),('2',240,[200,20,150,65],'right')]:
                row=self.marker(number,box=[x+(60 if index==3 else 0),40,10,16])
                row['context_image_track']=self.context_hint(image,index,context,key=key,previous=previous,
                    status='SEEDED' if previous is None else 'TRACKED')
                rows.append(row)
            result=self.update(tracker,index,list(reversed(rows)),frame=image)
            previous=image
        self.assertEqual([r['track_id'] for r in result['tracks']],['M000001','M000002'])
        self.assertEqual([r['number_evidence']['fresh_frames'][-1]['context_image_track']['key']
                          for r in result['tracks']],['left','right'])

    def test_context_input_and_evidence_output_cannot_rewrite_stored_lineage(self):
        tracker=marker_module.MarkerIdentityTracker();previous=None
        for index in range(3):
            image=self.frame(index);row=self.marker()
            row['context_image_track']=self.context_hint(image,index,[0,20,150,65],previous=previous,
                status='SEEDED' if previous is None else 'TRACKED')
            result=self.update(tracker,index,[row],frame=image);previous=image
        row['context_image_track']['key']='tampered'
        row['context_image_track']['box'][0]=300
        result['tracks'][0]['number_evidence']['fresh_frames'][-1]['context_image_track']['key']='tampered'
        image=self.frame(3);row=self.marker(box=[100,40,10,16])
        row['context_image_track']=self.context_hint(image,3,[0,20,150,65],previous=previous)
        self.assertEqual(self.update(tracker,3,[row],frame=image)['tracks'][0]['track_id'],'M000001')


if __name__ == '__main__':
    unittest.main()
