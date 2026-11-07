"""Controlled callbacks/pixels only, never real OCR or six-boat field evidence."""
from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
import unittest
from unittest.mock import patch

try:
    module = importlib.import_module('race_ai.boat_video_marker_pipeline')
except ModuleNotFoundError:
    module = None

CV = importlib.util.find_spec('cv2') is not None and importlib.util.find_spec('numpy') is not None


@unittest.skipUnless(CV, 'optional image dependencies unavailable')
class MarkerPipelineTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'optional marker pipeline is missing')
        import cv2
        import numpy as np
        from race_ai.boat_video_ppocr import SCORE_SCOPE
        from race_ai.boat_video_marker_verifier import GLYPH_MODEL_SHA256
        self.cv, self.np, self.scope = cv2, np, SCORE_SCOPE
        self.glyph_sha = GLYPH_MODEL_SHA256
        self.cv.setNumThreads(1)
        self.base = np.zeros((160, 720, 3), np.uint8)
        self.numbers = range(1, 7)
        for number in self.numbers:
            x = 30+(number-1)*110
            texture = np.random.default_rng(123+number).integers(32, 224, (40, 52, 3), dtype=np.uint8)
            self.base[50:90, x-20:x+32] = texture
            self.base[60:80, x:x+12] = number*25
        self.mode = 'numeric'
        self.discover_calls, self.recognizer_calls, self.verifier_calls = [], [], []
        self.fail_stage = None
        owner = self
        class FixtureVerifier:
            def metadata(self):
                return dict(glyph_model_sha256=owner.glyph_sha, development_opt_in=True,
                            training_scope='DEVELOPMENT_TRAIN_OVERLAP', model_eligible=False)
            def __call__(self, frame, boxes):
                owner.verifier_calls.append(deepcopy(boxes))
                if owner.fail_stage == 'verifier_count':
                    return []
                result = []
                for x, y, right, bottom in boxes:
                    value = round(int(frame[(y+bottom)//2, (x+right)//2, 0])/25)
                    result.append(dict(context_class=0 if owner.mode == 'reject' or
                                       owner.mode == 'partial_reject' and value > 2 else 1,
                                       glyph_class=value if 1 <= value <= 6 else 0))
                if owner.fail_stage == 'verifier_mutation':
                    frame[0, 0, 0] ^= 255
                return result
        self.verifier = FixtureVerifier()

    def image(self, index):
        result = self.cv.warpAffine(self.base, self.np.float32([[1, 0, index], [0, 1, 0]]), (720, 160))
        result[0, 0, 0] = index
        return result

    def discover(self, frame):
        index = int(frame[0, 0, 0])
        self.discover_calls.append(index)
        if self.fail_stage == 'bad_box':
            return [dict(box=[-1, 0, 10, 20])]
        return [dict(box=[30+(n-1)*110+index, 60, 42+(n-1)*110+index, 80], source='CONTROLLED_FIXTURE')
                for n in self.numbers]

    def recognize(self, crops):
        self.recognizer_calls.append(len(crops))
        result = []
        for crop in crops:
            number = round(int(crop[crop.shape[0]//2, crop.shape[1]//2, 0])/25)
            text = str(number) if 1 <= number <= 6 else 'x'
            if self.mode == 'blank': text = ''
            elif self.mode == 'multi': text = '64'
            elif self.mode == 'contradict': text = '2' if text != '2' else '6'
            elif self.mode == 'wrong_ctc': text = '7' if number == 1 else '21' if number == 2 else text
            digest = sha256(crop.tobytes()).hexdigest()
            result.append(dict(text=text, sequence_likelihood=.2 if len(text) == 1 else None,
                full_vocabulary_size=6625, score_scope=self.scope,
                input_sha256=digest, input_sha256_after=digest, input_shape=list(crop.shape),
                softmax_sha256='a'*64, softmax_shape=[1, 6625], model_eligible=False))
        if self.fail_stage == 'recognizer_count': return result[:-1]
        if self.fail_stage == 'recognizer_mutation' and crops: crops[0][:] = 0
        return result

    def pipeline(self, **kwargs):
        return module.MarkerIdentityPipeline(self.recognize, self.verifier, discover=self.discover, **kwargs)

    def call(self, pipeline, index, *, t=None, scene=0, frame=None):
        return pipeline.update(self.image(index) if frame is None else frame,
                               t=index/10 if t is None else t, frame_index=index, scene=scene)

    def test_six_controlled_numbers_require_three_fresh_original_frames(self):
        pipeline = self.pipeline()
        for index in range(3):
            result = self.call(pipeline, index)
            self.assertFalse(result['model_eligible'])
            self.assertEqual(result['coordinate_space'], 'IMAGE_PX')
            self.assertEqual(result['callback_provenance'], 'EXPLICIT_CALLBACKS_NOT_AUTHENTICATED')
            self.assertEqual(len(result['local_attempts']), 6)
            if index < 2:
                self.assertEqual(result['identity']['tracks'], [])
        self.assertEqual([r['number'] for r in result['identity']['tracks']], list(range(1, 7)))
        self.assertEqual([r['number_evidence']['observations'] for r in result['identity']['tracks']], [3]*6)
        self.assertEqual(self.discover_calls, [0])

    def test_refresh_reconciles_same_physical_marks_without_duplicate_flow_keys(self):
        pipeline = self.pipeline()
        for index in range(9):
            result = self.call(pipeline, index, t=index/30)
        self.assertEqual(self.discover_calls, [0, 8])
        self.assertEqual(len(result['flow']['tracked']), 6)
        self.assertEqual(result['global_scan']['suppressed_reseed_count'], 6)
        self.assertEqual([r['number'] for r in result['identity']['tracks']], list(range(1, 7)))

    def test_ambiguous_refresh_retires_old_mark_instead_of_picking_best_score(self):
        self.numbers = (1,)
        def discover(frame):
            rows = self.discover(frame)
            if int(frame[0, 0, 0]) >= 2:
                other = deepcopy(rows[0]); other['box'][0] += 1; other['box'][2] += 1
                rows.append(other)
            return rows
        original = self.verifier.__class__.__call__
        class ContradictoryVerifier:
            metadata = self.verifier.metadata
            def __call__(wrapper, frame, boxes):
                result = original(self.verifier, frame, boxes)
                if len(boxes) == 2: result[1]['glyph_class'] = 2
                return result
        pipeline = module.MarkerIdentityPipeline(self.recognize, ContradictoryVerifier(), discover=discover,
                   refresh_frames=2, label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')
        self.call(pipeline, 0); self.call(pipeline, 1)
        result = self.call(pipeline, 2)
        self.assertEqual(result['local_attempts'], [])
        self.assertEqual(result['identity']['tracks'], [])
        self.assertEqual(len(result['global_scan']['retired_refresh_keys']), 1)
        self.assertEqual(result['global_scan']['ambiguous_candidates'], [0, 1])

    def test_blank_hold_requires_verified_same_visible_key_and_expires(self):
        pipeline = self.pipeline()
        for index in range(3): result = self.call(pipeline, index)
        ids = [r['track_id'] for r in result['identity']['tracks']]
        self.mode = 'blank'
        held = self.call(pipeline, 3)
        self.assertEqual([r['status'] for r in held['identity']['tracks']], ['HELD_NUMBER']*6)
        self.assertEqual([r['track_id'] for r in held['identity']['tracks']], ids)
        self.assertEqual([r['number_evidence']['observations'] for r in held['identity']['tracks']], [3]*6)
        self.assertEqual(self.call(pipeline, 7)['identity']['tracks'], [])

    def test_multidigit_conflicting_and_rejected_nonempty_reads_never_become_blank_hold(self):
        for mode in ('multi', 'contradict', 'reject'):
            with self.subTest(mode=mode):
                self.mode = 'numeric'
                pipeline = self.pipeline()
                for index in range(3): self.call(pipeline, index)
                self.mode = mode
                result = self.call(pipeline, 3)
                self.assertEqual(result['identity']['tracks'], [])
                self.assertTrue(all(a['admission'] == 'UNKNOWN' for a in result['local_attempts']))

    def test_missing_pixels_emits_no_invisible_marker_positions(self):
        pipeline = self.pipeline()
        for index in range(3): self.call(pipeline, index)
        result = self.call(pipeline, 3, frame=self.np.zeros_like(self.base))
        self.assertEqual(result['identity']['tracks'], [])
        self.assertEqual(result['local_attempts'], [])
        self.assertEqual(len(result['flow']['lost_keys']), 6)

    def test_scene_time_gap_and_size_change_force_immediate_scan_and_reset(self):
        for kind in ('scene', 'gap', 'size'):
            with self.subTest(kind=kind):
                self.discover_calls.clear()
                pipeline = self.pipeline()
                self.call(pipeline, 0)
                image = self.image(1)
                if kind == 'size': image = image[:150]
                result = self.call(pipeline, 1, frame=image, scene=int(kind == 'scene'),
                                   t=.5 if kind == 'gap' else .1)
                self.assertTrue(result['global_scan']['performed'])
                self.assertEqual(len(self.discover_calls), 2)
                self.assertEqual(result['identity']['tracks'], [])

    def test_all_callbacks_must_be_aligned_and_mutation_fails_without_clock_advance(self):
        for failure in ('recognizer_count', 'verifier_count', 'recognizer_mutation', 'verifier_mutation'):
            with self.subTest(failure=failure):
                pipeline = self.pipeline()
                self.call(pipeline, 0)
                self.fail_stage = failure
                with self.assertRaises(ValueError): self.call(pipeline, 1)
                self.fail_stage = None
                self.call(pipeline, 1)
                result = self.call(pipeline, 2)
                self.assertEqual(len(result['identity']['tracks']), 6)

    def test_original_mutation_after_callbacks_does_not_poison_staged_seen_frames(self):
        pipeline = self.pipeline()
        self.call(pipeline, 0); self.call(pipeline, 1)
        original = self.image(2)
        good = original.copy()
        saved = pipeline.recognizer
        def mutate(crops):
            result = saved(crops)
            original[0, 0, 0] ^= 255
            return result
        pipeline.recognizer = mutate
        with self.assertRaises(ValueError): self.call(pipeline, 2, frame=original)
        original[:] = good
        pipeline.recognizer = saved
        result = self.call(pipeline, 2, frame=original)
        self.assertEqual(len(result['identity']['tracks']), 6)

    def test_invalid_clock_frame_and_discovered_coordinates_precede_inference(self):
        pipeline = self.pipeline()
        for arguments in (dict(t=float('nan'), frame_index=0, scene=0),
                          dict(t=0, frame_index=True, scene=0), dict(t=0, frame_index=0, scene=-1)):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                pipeline.update(self.image(0), **arguments)
        self.assertEqual(self.discover_calls, [])
        self.assertEqual(self.recognizer_calls, [])
        self.fail_stage = 'bad_box'
        with self.assertRaises(ValueError): self.call(pipeline, 0)
        self.assertEqual(self.recognizer_calls, [])
        self.assertEqual(self.verifier_calls, [])

    def test_development_classifier_mode_admits_classes_not_ctc_substrings(self):
        self.mode = 'wrong_ctc'
        pipeline = self.pipeline(label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')
        for index in range(3): result = self.call(pipeline, index)
        self.assertEqual([r['number'] for r in result['identity']['tracks']], list(range(1, 7)))
        wrong = result['local_attempts'][:2]
        self.assertEqual([r['recognition']['text'] for r in wrong], ['7', '21'])
        self.assertTrue(all(r['pp_classifier_disagreement'] for r in wrong))
        self.assertTrue(all(r['number_evidence']['fresh_frames'][0]['label_source'] == 'DECLARED_DEVELOPMENT_GLYPH_CLASSIFIER'
                            for r in result['identity']['tracks']))

    def test_development_classifier_reject_has_no_blank_hold_or_probability(self):
        pipeline = self.pipeline(label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')
        for index in range(3): result = self.call(pipeline, index)
        for row in result['identity']['tracks']:
            self.assertTrue(all(r['sequence_likelihood'] is None for r in row['number_evidence']['fresh_frames']))
        self.mode = 'reject'
        self.assertEqual(self.call(pipeline, 3)['identity']['tracks'], [])

    def test_classifier_opt_in_and_pinned_metadata_are_required(self):
        original = self.verifier.metadata
        for key, value in (('development_opt_in', False), ('glyph_model_sha256', '0'*64)):
            self.verifier.metadata = lambda key=key, value=value: dict(original(), **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.pipeline(label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')
        self.verifier.metadata = original
        with self.assertRaises(ValueError): self.pipeline(label_policy='NOT_A_POLICY')
        with self.assertRaises(ValueError): self.pipeline(refresh_frames=0)

    def test_classifier_rejects_are_processed_without_hidden_ctc_attempts(self):
        self.mode = 'partial_reject'
        result = self.call(self.pipeline(label_policy='DEVELOPMENT_GLYPH_CLASSIFIER'), 0)
        self.assertEqual(self.recognizer_calls, [2, 2])
        self.assertEqual(len(result['global_scan']['attempts']), 6)
        self.assertEqual(result['global_scan']['ctc_requested_images'], 2)
        for attempt in result['global_scan']['attempts'][2:]:
            self.assertEqual(attempt['recognition']['status'], 'CLASSIFIER_REJECTED_NO_CTC_ATTEMPT')
            self.assertIsNone(attempt['recognition']['text'])

    def test_same_class_nested_views_collapse_to_larger_geometry_once(self):
        self.numbers = (1,)
        def nested(frame):
            large = self.discover(frame)[0]
            x, y, r, b = large['box']
            return [dict(box=[x+3, y+4, r-2, b-4]), large]
        pipeline = module.MarkerIdentityPipeline(self.recognize, self.verifier, discover=nested,
                                                 label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')
        for index in range(3): result = self.call(pipeline, index)
        self.assertEqual(len(result['flow']['tracked']), 1)
        self.assertEqual(len(result['identity']['tracks']), 1)
        self.assertEqual(result['identity']['tracks'][0]['number_evidence']['observations'], 3)
        self.assertEqual(len(result['global_scan']['attempts']), 0)  # no refresh on frame2
        first = self.call(self.pipeline(), 0)  # independent default path is unchanged
        self.assertEqual(len(first['global_scan']['attempts']), 1)

    def test_nested_inner_only_refresh_reuses_outer_live_mark(self):
        self.numbers = (1,)
        def shrinking(frame):
            rows = self.discover(frame)
            if int(frame[0, 0, 0]) >= 2:
                x, y, r, b = rows[0]['box']; rows[0]['box'] = [x+3, y+4, r-2, b-4]
            return rows
        pipeline = module.MarkerIdentityPipeline(self.recognize, self.verifier, discover=shrinking,
                   label_policy='DEVELOPMENT_GLYPH_CLASSIFIER', refresh_frames=2)
        for index in range(3): result = self.call(pipeline, index)
        self.assertEqual(result['global_scan']['suppressed_reseed_count'], 1)
        self.assertEqual(len(result['flow']['tracked']), 1)
        # A much smaller corrected geometry can conservatively restart M's
        # three-observation association; it must not create duplicate flow.
        self.assertEqual(result['global_scan']['attempts'][0]['action'], 'CORRECTED_LIVE_MARKER')

    def test_distinct_same_class_far_apart_still_is_duplicate_unknown(self):
        self.numbers = (1, 2)
        self.base[60:80, 140:152] = 25
        pipeline = self.pipeline(label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')
        for index in range(3): result = self.call(pipeline, index)
        self.assertEqual(result['identity']['tracks'], [])
        self.assertIn('DUPLICATE_NUMBER', result['identity']['quality_flags'])

    def test_callback_exception_can_retry_same_original_frame(self):
        pipeline = self.pipeline()
        self.call(pipeline, 0)
        original = pipeline.recognizer
        def fail(_):
            raise RuntimeError('CONTROLLED_CALLBACK_FAILURE')
        pipeline.recognizer = fail
        with self.assertRaises(RuntimeError): self.call(pipeline, 1)
        pipeline.recognizer = original
        self.call(pipeline, 1)
        self.assertEqual(len(self.call(pipeline, 2)['identity']['tracks']), 6)

    def test_replayed_pixels_never_establish_three_fresh_number_observations(self):
        pipeline = self.pipeline()
        image = self.image(0)
        for index in range(4):
            result = self.call(pipeline, index, frame=image)
            self.assertEqual(result['identity']['tracks'], [])
        self.assertIn('REPEATED_FRAME_PIXELS', result['identity']['quality_flags'])

    def test_output_changes_do_not_rewrite_future_internal_tracking(self):
        pipeline = self.pipeline()
        result = self.call(pipeline, 0)
        result['flow']['tracked'][0]['box'][0] = 700
        result['local_attempts'][0]['recognition']['text'] = '64'
        result['marker_observations'][0]['box'][0] = 700
        self.call(pipeline, 1)
        result = self.call(pipeline, 2)
        self.assertEqual(len(result['identity']['tracks']), 6)

    def test_unique_refresh_corrects_printed_roi_before_current_local_inference(self):
        self.numbers = (1,)
        def shifted(frame):
            rows = self.discover(frame)
            if int(frame[0, 0, 0]) >= 2:
                rows[0]['box'][0] += 2; rows[0]['box'][2] += 2
            return rows
        pipeline = module.MarkerIdentityPipeline(self.recognize, self.verifier, discover=shifted, refresh_frames=2)
        first = self.call(pipeline, 0)
        key = first['flow']['tracked'][0]['key']
        self.call(pipeline, 1)
        result = self.call(pipeline, 2)
        self.assertEqual(result['local_attempts'][0]['box_xyxy'], [34, 60, 46, 80])
        self.assertEqual(result['flow']['tracked'][0]['key'], key)
        self.assertEqual(result['flow']['tracked'][0]['status'], 'TRACKED')
        attempt = result['global_scan']['attempts'][0]
        self.assertEqual(attempt['action'], 'CORRECTED_LIVE_MARKER')
        self.assertEqual(attempt['corrected_marker_box'], [34, 60, 12, 20])
        self.assertAlmostEqual(attempt['previous_marker_box'][0], 32, delta=.25)
        self.assertEqual(result['identity']['tracks'][0]['number_evidence']['observations'], 3)

    def test_refresh_roi_outside_live_context_explicitly_retires_and_reseeds(self):
        self.numbers = (1,)
        def expanded(frame):
            rows = self.discover(frame)
            if int(frame[0, 0, 0]) >= 2:
                rows[0]['box'][0] -= 22; rows[0]['box'][2] += 22
            return rows
        pipeline = module.MarkerIdentityPipeline(self.recognize, self.verifier, discover=expanded,
                   refresh_frames=2, label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')
        key = self.call(pipeline, 0)['flow']['tracked'][0]['key']
        self.call(pipeline, 1)
        result = self.call(pipeline, 2)
        self.assertNotEqual(result['flow']['tracked'][0]['key'], key)
        self.assertEqual(result['flow']['tracked'][0]['status'], 'SEEDED')
        self.assertIn(key, result['global_scan']['retired_refresh_keys'])
        self.assertEqual(result['global_scan']['attempts'][0]['action'], 'RESEEDED_OUTSIDE_LIVE_CONTEXT')

    def audit_blank_pipeline(self, blank_x, rejected_text='64'):
        """Typed-stage audit fixture; this does not claim measured LK or OCR."""
        pipeline = self.pipeline()
        for index in range(3):
            pipeline._tracker.update(self.image(index), [
                dict(box=[40, 40, 12, 20], text='1', sequence_likelihood=.2, context_status='SINGLE_MARK'),
                dict(box=[80, 40, 12, 20], text='2', sequence_likelihood=.2, context_status='SINGLE_MARK')],
                t=index/10, frame_index=index, scene=0)
        class ControlledFlow:
            def update(flow, frame, seeds, *, t, frame_index, scene):
                return dict(tracked=[dict(key='key1', box=[54, 40, 12, 20], status='TRACKED'),
                                     dict(key='key2', box=[blank_x, 40, 12, 20], status='TRACKED')],
                            lost_keys=[], fixture_scope='CONTROLLED_TYPED_STAGE_NOT_REAL_FLOW')
        def recognize(crops):
            result = []
            for crop, text in zip(crops, (rejected_text, '')):
                digest = sha256(crop.tobytes()).hexdigest()
                result.append(dict(text=text, sequence_likelihood=.2 if len(text) == 1 else None,
                    full_vocabulary_size=6625, score_scope=self.scope, input_sha256=digest,
                    input_sha256_after=digest, input_shape=list(crop.shape), softmax_sha256='a'*64))
            return result
        pipeline._flow = ControlledFlow()
        pipeline._offsets = {'key1': (0, 0, 12, 20), 'key2': (0, 0, 12, 20)}
        pipeline._verified = {'key1': 1, 'key2': 2}
        pipeline._time, pipeline._index, pipeline._scene, pipeline._shape = .2, 2, 0, (720, 160)
        pipeline._last_scan = 0
        pipeline.recognizer = recognize
        pipeline.verifier = lambda frame, boxes: [dict(context_class=1, glyph_class=1),
                                                  dict(context_class=1, glyph_class=2)]
        return pipeline

    def test_blank_expected2_at_rejected_old1_position_never_holds_number1(self):
        for rejected_text in ('64', '2'):
            with self.subTest(rejected_text=rejected_text):
                result = self.call(self.audit_blank_pipeline(40, rejected_text), 3)
                self.assertEqual(result['identity']['tracks'], [])
                held = result['local_attempts'][1]
                self.assertEqual(held['admission'], 'HOLD_EXPECTATION_MISMATCH')
                self.assertEqual(held['blank_hold_evidence']['expected_number'], 2)
                self.assertEqual([r['number'] for r in held['blank_hold_evidence']['compatible_previous_tracks']], [1])

    def test_blank_requires_unique_expected_track_without_compatible_other_number(self):
        result = self.call(self.audit_blank_pipeline(60), 3)
        self.assertEqual(result['identity']['tracks'], [])
        held = result['local_attempts'][1]
        self.assertEqual(held['admission'], 'HOLD_EXPECTATION_MISMATCH')
        self.assertEqual(sorted(r['number'] for r in held['blank_hold_evidence']['compatible_previous_tracks']), [1, 2])

    def test_unambiguous_blank_at_expected_old2_still_holds_only2(self):
        result = self.call(self.audit_blank_pipeline(80), 3)
        self.assertEqual([r['number'] for r in result['identity']['tracks']], [2])
        held = result['local_attempts'][1]
        self.assertEqual(held['admission'], 'VISIBLE_BLANK_HOLD')
        self.assertEqual(held['blank_hold_evidence']['expected_number'], 2)

    def test_mutual_center_partial_views_are_one_observation_not_duplicate_number(self):
        self.numbers = (1,)
        def partial(frame):
            full = self.discover(frame)[0]
            x, y, right, bottom = full['box']
            return [full, dict(box=[x-1, y+7, right-3, bottom+2])]
        pipeline = module.MarkerIdentityPipeline(self.recognize, self.verifier, discover=partial,
                   label_policy='DEVELOPMENT_GLYPH_CLASSIFIER')
        for index in range(3): result = self.call(pipeline, index)
        self.assertEqual(len(result['flow']['tracked']), 1)
        self.assertEqual([r['number'] for r in result['identity']['tracks']], [1])
        self.assertEqual(result['identity']['tracks'][0]['number_evidence']['observations'], 3)

    def test_mutual_centers_keep_half_open_boundary_and_contradictory_labels_safe(self):
        _collapse_views = module._collapse_views
        full, partial = [203, 816, 35, 46], [201, 833, 29, 35]
        self.assertEqual(_collapse_views([full, partial], [4, 4]), ({1: 0}, set()))
        self.assertEqual(_collapse_views([full, partial], [4, 5]), ({}, {0, 1}))
        self.assertEqual(_collapse_views([full, [300, 816, 35, 46]], [4, 4]), ({}, set()))
        self.assertEqual(_collapse_views([[0, 0, 10, 10], [5, 0, 10, 10]], [4, 4]), ({}, set()))

    def assert_bridge_remains_duplicate_unknown(self, boxes, expected_collapsed):
        collapsed, ambiguous = module._collapse_views(boxes, [4, 4, 4])
        self.assertEqual(ambiguous, set())
        remaining = [box for i, box in enumerate(boxes) if i not in collapsed]
        tracker = module.MarkerIdentityTracker()
        for index in range(3):
            result = tracker.update(self.image(index), [dict(box=list(box), text='4',
                sequence_likelihood=.2, context_status='SINGLE_MARK') for box in remaining],
                t=index/10, frame_index=index, scene=0)
        self.assertEqual(result['tracks'], [])
        self.assertIn('DUPLICATE_NUMBER', result['quality_flags'])
        self.assertEqual(len(remaining), 2)
        self.assertEqual(collapsed, expected_collapsed)

    def test_same_class_pairwise_chain_cannot_merge_distinct_endpoints(self):
        self.assert_bridge_remains_duplicate_unknown(
            [[40, 40, 10, 20], [44, 40, 10, 20], [48, 40, 10, 20]], {1: 0})

    def test_larger_middle_view_cannot_bridge_nonmatching_endpoints(self):
        self.assert_bridge_remains_duplicate_unknown(
            [[40, 40, 10, 20], [43.5, 39.5, 11, 21], [48, 40, 10, 20]], {0: 1})

    def test_pairwise_matching_contained_views_still_collapse_once(self):
        boxes = [[40, 40, 20, 30], [43, 42, 15, 25], [46, 44, 8, 18]]
        self.assertEqual(module._collapse_views(boxes, [4, 4, 4]), ({1: 0, 2: 0}, set()))

    def test_conflicting_label_abstention_still_propagates_to_same_view_aliases(self):
        boxes = [[40, 40, 10, 20], [44, 40, 10, 20], [48, 40, 10, 20]]
        self.assertEqual(module._collapse_views(boxes, [4, 4, 5]), ({}, {0, 1, 2}))


    def test_separate_complete_groups_cannot_be_recombined_by_m_view_dedupe(self):
        boxes = [[40, 40, 10, 20], [44, 40, 11, 20], [45, 40, 10, 20]]
        collapsed, ambiguous = module._collapse_views(boxes, [4, 4, 4])
        remaining = [box for i, box in enumerate(boxes) if i not in collapsed and i not in ambiguous]
        tracker = module.MarkerIdentityTracker()
        for index in range(3):
            result = tracker.update(self.image(index), [dict(box=box, text='4',
                sequence_likelihood=.2, context_status='SINGLE_MARK') for box in remaining],
                t=index/10, frame_index=index, scene=0)
        self.assertEqual(result['tracks'], [])
        self.assertEqual(collapsed, {})
        self.assertEqual(ambiguous, {0, 1, 2})

    def test_reordering_bridge_views_never_creates_single_registered_number(self):
        import itertools
        boxes = [[40, 40, 10, 20], [44, 40, 11, 20], [45, 40, 10, 20]]
        for permutation in itertools.permutations(boxes):
            with self.subTest(permutation=permutation):
                collapsed, ambiguous = module._collapse_views(list(permutation), [4, 4, 4])
                remaining = [box for i, box in enumerate(permutation) if i not in collapsed and i not in ambiguous]
                tracker = module.MarkerIdentityTracker()
                for index in range(3):
                    result = tracker.update(self.image(index), [dict(box=box, text='4',
                        sequence_likelihood=.2, context_status='SINGLE_MARK') for box in remaining],
                        t=index/10, frame_index=index, scene=0)
                self.assertEqual(result['tracks'], [])

    def test_same_actual_context_key_preserves_fresh_number_through_partial_roi_scale_change(self):
        self.numbers=(1,)
        def partial(frame):
            rows=self.discover(frame)
            if int(frame[0,0,0])>=3:
                x,y,right,bottom=rows[0]['box'];rows[0]['box']=[x+3,y+6,right-3,bottom-6]
            return rows
        pipeline=module.MarkerIdentityPipeline(self.recognize,self.verifier,discover=partial,
                   label_policy='DEVELOPMENT_GLYPH_CLASSIFIER',refresh_frames=1)
        for index in range(3):result=self.call(pipeline,index)
        old_id=result['identity']['tracks'][0]['track_id'];key=result['flow']['tracked'][0]['key']
        result=self.call(pipeline,3)
        self.assertEqual(result['flow']['tracked'][0]['status'],'TRACKED')
        self.assertEqual(result['flow']['tracked'][0]['key'],key)
        self.assertEqual(result['identity']['tracks'][0]['track_id'],old_id)
        self.assertEqual(result['identity']['tracks'][0]['number_evidence']['observations'],4)
        hint=result['marker_observations'][0]['context_image_track']
        self.assertEqual(hint['scope'],'CONTEXT_IMAGE_TRACK')
        self.assertEqual(hint['key'],key)
        self.assertEqual(hint['frame_sha256'],result['frame_sha256'])
        self.assertFalse(result['identity_validated'])

    def post_refit_flow(self, *, rotate=False):
        """Real producer math with controlled corners/LK arrays, not real LK."""
        from race_ai.boat_video_marker_flow import MarkerPixelFollower
        np=self.np
        phase=.3 if rotate else 0.
        inner_phase=np.pi/4 if rotate else 0.
        outer=[[50+25*np.cos(phase+2*np.pi*i/5),50+25*np.sin(phase+2*np.pi*i/5)] for i in range(5)]
        inner=[[50+15*np.cos(inner_phase+2*np.pi*i/4),50+15*np.sin(inner_phase+2*np.pi*i/4)] for i in range(4)]
        excluded=[[50+35*np.cos(2*np.pi*i/3),50+35*np.sin(2*np.pi*i/3)] for i in range(3)]
        origin=np.array(outer+inner+excluded,np.float32)
        destination=origin.copy();destination[:9]+=(origin[:9]-50)*.1
        if rotate:destination[:,0]+=106.04
        status=np.ones((12,1),np.uint8);errors=np.zeros((12,1),np.float32)
        first=np.zeros((200,300,3),np.uint8);second=first.copy();second[0,0,0]=1
        flow=MarkerPixelFollower()
        with patch.object(self.cv,'goodFeaturesToTrack',return_value=origin.reshape(-1,1,2)):
            seed=flow.update(first,[dict(key='S1',box=[0,0,100,100])],t=0.,frame_index=0,scene=0)
        with patch.object(self.cv,'calcOpticalFlowPyrLK',side_effect=[
                (destination.reshape(-1,1,2),status,errors),(origin.reshape(-1,1,2),status,errors)]):
            tracked=flow.update(second,[],t=.033,frame_index=1,scene=0)
        return first,second,seed,tracked

    def test_optional_context_hint_omits_existing_valid_post_refit_quality_instead_of_aborting(self):
        for rotate in (False,True):
            with self.subTest(post_refit_norm_case=rotate):
                first,second,seed,flowed=self.post_refit_flow(rotate=rotate)
                tracker=module.MarkerIdentityTracker()
                seeded=module._context_image_track(seed,seed['tracked'][0],
                    frame_sha=sha256(first.tobytes()).hexdigest(),frame_index=0,scene=0)
                tracker.update(first,[dict(box=[40,40,10,16],text='1',sequence_likelihood=.2,
                    context_status='SINGLE_MARK',context_image_track=seeded)],t=0.,frame_index=0,scene=0)
                row=flowed['tracked'][0]
                self.assertEqual(row['status'],'TRACKED');self.assertEqual(row['point_count'],9)
                self.assertGreater(row['displacement_dispersion_px'],2.)
                gate=max(8.,.75*self.np.hypot(row['box'][2],row['box'][3]))
                if rotate:self.assertGreater(self.np.linalg.norm(row['median_displacement_px']),gate)
                diagnostic={}
                hint=module._context_image_track(flowed,row,frame_sha=sha256(second.tobytes()).hexdigest(),
                    frame_index=1,scene=0,diagnostic=diagnostic)
                self.assertIsNone(hint)
                self.assertEqual(diagnostic['status'],'OMITTED')
                self.assertEqual(diagnostic['fallback'],'GEOMETRY_ONLY')
                self.assertIn('POST_REFIT_DISPERSION_EXCEEDS_HINT_BOUND',diagnostic['reasons'])
                if rotate:self.assertIn('POST_REFIT_DISPLACEMENT_EXCEEDS_HINT_BOUND',diagnostic['reasons'])
                x,y,w,h=row['box'];marker=dict(box=[x+40,y+40,10,16],text='1',sequence_likelihood=.2,context_status='SINGLE_MARK')
                # The direct M API remains strict for an explicitly bad hint.
                bad={k:deepcopy(row[k]) for k in ('key','status','previous_frame_sha256','box','point_count',
                    'median_displacement_px','median_forward_backward_error_px','displacement_dispersion_px','affine_area_ratio')}
                bad.update(scope='CONTEXT_IMAGE_TRACK',frame_sha256=sha256(second.tobytes()).hexdigest(),frame_index=1,scene=0)
                with self.assertRaises(ValueError):
                    tracker.update(second,[dict(marker,context_image_track=bad)],t=.033,frame_index=1,scene=0)
                self.assertEqual(tracker._frame_index,0)
                result=tracker.update(second,[marker],t=.033,frame_index=1,scene=0)
                self.assertEqual(result['tracks'],[])
                self.assertEqual(tracker._tracks[0]['evidence'][-1]['frame_index'],1)

    def test_context_hint_quality_boundaries_omit_only_finite_ineligible_packets(self):
        _,second,_,flowed=self.post_refit_flow();row=deepcopy(flowed['tracked'][0])
        row['displacement_dispersion_px']=2.
        args=dict(frame_sha=sha256(second.tobytes()).hexdigest(),frame_index=1,scene=0)
        self.assertIsNotNone(module._context_image_track(flowed,row,**args))
        for field,value,reason in [
                ('displacement_dispersion_px',2.000001,'POST_REFIT_DISPERSION_EXCEEDS_HINT_BOUND'),
                ('median_displacement_px',[.75*self.np.hypot(100.,100.)+1e-5,0.],'POST_REFIT_DISPLACEMENT_EXCEEDS_HINT_BOUND')]:
            with self.subTest(field=field):
                current=deepcopy(row);current[field]=value;diagnostic={}
                self.assertIsNone(module._context_image_track(flowed,current,diagnostic=diagnostic,**args))
                self.assertIn(reason,diagnostic['reasons'])
        for change in (dict(displacement_dispersion_px=float('nan')),dict(displacement_dispersion_px=None),
                       dict(median_displacement_px=[float('inf'),0.]),dict(point_count='9'),dict(status='PREDICTED')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                module._context_image_track(flowed,dict(row,**change),**args)

    def test_finite_ineligible_flow_keeps_pipeline_geometry_and_records_omission(self):
        from race_ai.boat_video_marker_flow import MarkerPixelFollower
        self.numbers=(1,);pipeline=self.pipeline();original=MarkerPixelFollower.update
        def report_post_refit(flow,*args,**kwargs):
            result=original(flow,*args,**kwargs)
            for row in result['tracked']:
                if row['status']=='TRACKED':row['displacement_dispersion_px']=2.5
            return result
        # Controlled producer metadata; the actual accepted post-refit case is
        # exercised separately above with the real affine/inlier computation.
        with patch.object(MarkerPixelFollower,'update',report_post_refit):
            for index in range(3):result=self.call(pipeline,index)
        self.assertEqual(len(result['identity']['tracks']),1)
        self.assertEqual(result['identity']['tracks'][0]['number_evidence']['observations'],3)
        self.assertNotIn('context_image_track',result['marker_observations'][0])
        diagnostic=result['local_attempts'][0]['context_image_track_diagnostic']
        self.assertEqual(diagnostic['status'],'OMITTED')
        self.assertEqual(diagnostic['fallback'],'GEOMETRY_ONLY')

    def test_nonfinite_flow_metadata_still_rejects_atomically_before_hint_fallback(self):
        from race_ai.boat_video_marker_flow import MarkerPixelFollower
        self.numbers=(1,);pipeline=self.pipeline();self.call(pipeline,0)
        original=MarkerPixelFollower.update
        def nonfinite(flow,*args,**kwargs):
            result=original(flow,*args,**kwargs)
            result['tracked'][0]['displacement_dispersion_px']=float('nan')
            return result
        with patch.object(MarkerPixelFollower,'update',nonfinite),self.assertRaises(ValueError):
            self.call(pipeline,1)
        self.assertEqual(pipeline._index,0)
        self.call(pipeline,1)
        self.assertEqual(len(self.call(pipeline,2)['identity']['tracks']),1)



if __name__ == '__main__':
    unittest.main()
