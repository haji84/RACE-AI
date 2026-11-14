"""Experimental raw CTC contracts, not real-footage performance evidence."""
import importlib
import importlib.util
import itertools
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


CV_AVAILABLE = importlib.util.find_spec('cv2') is not None


class CRNNMathTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('race_ai.boat_video_crnn')
        except ImportError:
            self.fail('the optional actual-pixel CRNN reader is not implemented')

    def logits(self, symbols):
        return [[8. if i == symbol else -8. for i in range(37)] for symbol in symbols]

    def test_full_vocabulary_decoder_preserves_letters_and_separated_repeated_digits(self):
        for symbols, expected in [([2, 2, 0], '1'), ([12, 12, 0], 'b'),
                                  ([2, 0, 2], '11'), ([0, 0, 0], '')]:
            text, likelihood = self.module.decode_ctc_logits(self.logits(symbols))
            self.assertEqual(text, expected)
            self.assertIsNone(likelihood) if len(text) != 1 else self.assertIsInstance(likelihood, float)

    def test_single_symbol_ctc_likelihood_matches_independent_path_enumeration(self):
        rows = []
        for values in ((.2, .5, .3), (.4, .3, .3), (.5, .2, .3)):
            row = [0.] * 37
            for index, p in zip((0, 2, 12), values):
                row[index] = p
            rows.append(row)
        wanted = 0.
        for path in itertools.product((0, 2, 12), repeat=3):
            collapsed = [a for i, a in enumerate(path) if a and (not i or a != path[i-1])]
            if collapsed == [2]:
                wanted += math.prod(rows[i][value] for i, value in enumerate(path))
        self.assertAlmostEqual(self.module.single_ctc_likelihood(rows, 2), wanted, places=14)
        self.assertLess(wanted, 1.)

    def test_full_37_class_softmax_is_not_digit_renormalization(self):
        row = [-20.] * 37
        row[2] = row[12] = 0.
        text, likelihood = self.module.decode_ctc_logits([row])
        self.assertEqual(text, '1')  # deterministic lowest-index argmax tie
        self.assertAlmostEqual(likelihood, .5, places=6)

    def test_logits_reject_nonfinite_wrong_vocabulary_and_already_normalized_outputs(self):
        for value in ([[0.] * 36], [[float('nan')] * 37], [[1/37] * 37],
                      [[math.log(1/37)] * 37], [], [[True] * 37]):
            with self.subTest(value=str(value)[:45]), self.assertRaises(ValueError):
                self.module.decode_ctc_logits(value)

    def test_probabilities_require_normalized_full_rows_and_valid_symbol(self):
        for value, symbol in [([[.2] * 37], 2), ([[1.] + [0.] * 36], 0),
                              ([[1.] + [0.] * 36], 37)]:
            with self.assertRaises(ValueError):
                self.module.single_ctc_likelihood(value, symbol)

    def test_model_integrity_rejects_before_attempting_any_dnn_load(self):
        with tempfile.TemporaryDirectory() as folder:
            wrong = Path(folder)/'wrong.onnx'
            wrong.write_bytes(b'not the pinned model')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                self.module.PinnedCRNNNumberReader(model_path=wrong)


@unittest.skipUnless(CV_AVAILABLE, 'optional video dependencies are unavailable')
class CRNNPixelAndProviderTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('race_ai.boat_video_crnn')
        except ImportError:
            self.fail('the optional actual-pixel CRNN reader is not implemented')
        import cv2
        import numpy as np
        self.cv2, self.np = cv2, np
        self.frame = np.full((140, 320, 3), 100, np.uint8)

    def reading(self, proposals=(), **options):
        return dict(schema_version=self.module.READING_SCHEMA, proposals=list(proposals),
                    status=options.get('status', 'COMPLETE'), attempts=[],
                    soft_budget_seconds=3., soft_budget_exceeded=False, skipped_views=0,
                    score_scope=self.module.SCORE_SCOPE, accepted_identity=False,
                    hard_deadline_guaranteed=False)

    def proposal(self, number='1', likelihood=.4, box=(8, 6, 10, 12)):
        return dict(text=number, sequence_likelihood=likelihood, box=list(box))

    def detection(self, x=30):
        return {'box': [x, 50, 35, 30], 'score': .95}

    def observe(self, provider, i, detections=None, scene=0):
        return provider.identify(self.frame, [self.detection()] if detections is None else detections,
                                 t=i/10, frame_index=i, scene=scene)

    def provider(self, values, **options):
        queue = iter(values)
        return self.module.ExperimentalCRNNIdentityProvider(
            detector=lambda frame: [], number_reader=lambda crop: next(queue), **options)

    def test_actual_gray_views_preserve_grayscale_instead_of_ocring_an_isolated_mask(self):
        mask = self.np.zeros((20, 12), self.np.uint8)
        mask[3:17, 4:8] = 255
        gray = self.np.tile(self.np.arange(12, dtype=self.np.uint8)*12+100, (20, 1))
        view, info = self.module.normalize_region(mask, False, gray)
        self.assertIs(info['actual_grayscale_pixels_preserved'], True)
        self.assertIs(info['segmentation_isolated_mask'], False)
        self.assertGreater(len(self.np.unique(view)), 4)

    def test_stock_crnn_blob_uses_bgr_grayscale_and_bounded_minus_one_to_one_values(self):
        crop = self.np.full((32, 100, 3), [0, 0, 255], self.np.uint8)
        blob = self.module.prepare_crnn_blob(crop)
        self.assertEqual(blob.shape, (1, 1, 32, 100))
        # OpenCV BGR red has grayscale76, not blue's29.
        self.assertAlmostEqual(float(blob[0, 0, 10, 10]), (76-127.5)/127.5, places=6)

    def test_three_distinct_frames_admit_only_an_explicit_uncalibrated_candidate(self):
        provider = self.provider([self.reading([self.proposal()])]*3)
        for i in range(3):
            output = self.observe(provider, i)
            if i < 2:
                self.assertEqual(output['regions'], [])
        self.assertEqual(len(output['regions']), 1)
        evidence = output['regions'][0]['number_evidence']
        self.assertNotIn('minimum_confidence', evidence)
        self.assertNotIn('confidence', str(evidence))
        self.assertEqual(evidence['minimum_sequence_likelihood'], .4)
        self.assertEqual(evidence['score_scope'], self.module.SCORE_SCOPE)
        self.assertEqual(evidence['admission_policy'], self.module.ADMISSION_POLICY)
        self.assertFalse(output['identity_validated'])
        self.assertFalse(output['model_eligible'])
        self.assertEqual(provider.metadata()['number_reader']['engine'], 'INJECTED_RAW_CTC_READER')

    def test_legacy_tesseract_gate_and_outputs_are_unchanged(self):
        from race_ai.boat_video_identity import BoatIdentityProvider, MIN_NUMBER_CONFIDENCE
        self.assertEqual(MIN_NUMBER_CONFIDENCE, .9)
        old = BoatIdentityProvider(detector=lambda frame: [],
            number_reader=lambda crop: [{'text': '1', 'score': .4, 'box': [8, 6, 10, 12]}])
        for i in range(3):
            self.assertEqual(self.observe(old, i)['regions'], [])

    def test_duplicate_normalizations_are_one_geometry_not_two_observations(self):
        proposal = self.proposal()
        provider = self.provider([self.reading([proposal, dict(proposal, sequence_likelihood=.6)])]*3)
        for i in range(3):
            output = self.observe(provider, i)
        evidence = output['regions'][0]['number_evidence']
        self.assertEqual(evidence['observations'], 3)
        self.assertEqual(evidence['minimum_sequence_likelihood'], .6)

    def test_conflicting_digits_or_two_distinct_regions_are_ambiguous(self):
        cases = ([self.proposal(), self.proposal('2')],
                 [self.proposal(), self.proposal(box=(22, 6, 10, 12))])
        for proposals in cases:
            with self.subTest(proposals=proposals):
                provider = self.provider([self.reading(proposals)]*3)
                for i in range(3):
                    output = self.observe(provider, i)
                self.assertEqual(output['regions'], [])
                self.assertIn('AMBIGUOUS_NUMBER_MARKS', output['quality_flags'])

    def test_letters_multidigit_and_nonlocalized_or_foreign_legacy_rows_never_anchor(self):
        for row in [self.proposal('b'), self.proposal('11'),
                    dict(self.proposal(), localized=False),
                    {'text':'1','score':.99,'box':[8,6,10,12]}]:
            with self.subTest(row=row):
                provider = self.provider([self.reading([row])]*3)
                for i in range(3):
                    output = self.observe(provider, i)
                self.assertEqual(output['regions'], [])

    def test_incomplete_or_failed_reader_invalidates_prior_identity_and_requires_fresh_three(self):
        for status, code in [('INCOMPLETE_BUDGET', 'LOCAL_OCR_TIMEOUT'),
                             ('INFERENCE_ERROR', 'LOCAL_OCR_PROCESS_FAILED')]:
            good = self.reading([self.proposal()])
            provider = self.provider([good]*3 + [self.reading(status=status)] + [good]*3)
            for i in range(3):
                self.observe(provider, i)
            output = self.observe(provider, 3)
            self.assertEqual(output['regions'], [])
            self.assertIn(code, output['quality_flags'])
            self.assertEqual(self.observe(provider, 4)['regions'], [])
            self.assertEqual(self.observe(provider, 5)['regions'], [])
            self.assertEqual(self.observe(provider, 6)['regions'][0]['number_evidence']['observations'], 3)

    def test_moving_ambiguous_hull_cannot_transfer_established_identity_to_unread_neighbor(self):
        from race_ai.boat_video_identity import BoatIdentityProvider
        for mode in ('raw_ctc', 'legacy_ocr'):
            with self.subTest(mode=mode):
                if mode == 'raw_ctc':
                    good = self.reading([self.proposal()])
                    ambiguous = self.reading([self.proposal(), self.proposal('2')])
                    unread = self.reading()
                    provider = self.provider([good]*3 + [ambiguous, unread] + [good]*3)
                else:
                    good = [{'text':'1','score':.98,'box':[8,6,10,12]}]
                    ambiguous = good + [{'text':'2','score':.98,'box':[8,6,10,12]}]
                    values = iter([good]*3 + [ambiguous, []] + [good]*3)
                    provider = BoatIdentityProvider(detector=lambda frame: [],
                        number_reader=lambda crop: next(values))
                for i in range(3):
                    output = self.observe(provider, i, detections=[self.detection(100)])
                old_track_id = output['regions'][0]['track_id']
                interrupted = self.observe(provider, 3,
                    detections=[self.detection(135), self.detection(100)])
                self.assertIn('AMBIGUOUS_NUMBER_MARKS', interrupted['quality_flags'])
                self.assertEqual(interrupted['regions'], [])
                # The interrupted hull moved without overlapping its old box,
                # but remains inside the unchanged association geometry gate.
                self.assertEqual(self.observe(provider, 4, detections=[self.detection(135)])['regions'], [])
                self.assertEqual(self.observe(provider, 5, detections=[self.detection(135)])['regions'], [])
                recovered = self.observe(provider, 6, detections=[self.detection(135)])['regions'][0]
                self.assertNotEqual(recovered['track_id'], old_track_id)
                self.assertEqual(recovered['number_evidence']['observations'], 3)
                self.assertEqual(recovered['number_evidence']['first_frame_index'], 4)

    def test_other_blocked_moving_hulls_cannot_transfer_identity_to_unread_neighbor(self):
        for reason in ('low_score', 'overlay', 'overlapping_hulls'):
            with self.subTest(reason=reason):
                good = self.reading([self.proposal()])
                options = {'exclusions': [[135, 50, 35, 30]]} if reason == 'overlay' else {}
                provider = self.provider([good]*3 + [self.reading()], **options)
                for i in range(3):
                    output = self.observe(provider, i, detections=[self.detection(100)])
                self.assertEqual(len(output['regions']), 1)
                moved = self.detection(135)
                if reason == 'low_score':
                    moved['score'] = .4
                detections = [moved]
                if reason == 'overlapping_hulls':
                    detections.append(self.detection(140))
                detections.append(self.detection(100))
                output = self.observe(provider, 3, detections=detections)
                self.assertEqual(output['regions'], [])

    def test_fresh_matching_number_preserves_healthy_track_near_moving_ambiguous_hull(self):
        good = self.reading([self.proposal('2')])
        ambiguous = self.reading([self.proposal(), self.proposal('3')])
        provider = self.provider([good]*3 + [ambiguous, good])
        for i in range(3):
            output = self.observe(provider, i, detections=[self.detection(100)])
        old_track_id = output['regions'][0]['track_id']
        output = self.observe(provider, 3, detections=[self.detection(135), self.detection(100)])
        self.assertIn('AMBIGUOUS_NUMBER_MARKS', output['quality_flags'])
        self.assertEqual(len(output['regions']), 1)
        healthy = output['regions'][0]
        self.assertEqual(healthy['lane'], 2)
        self.assertEqual(healthy['track_id'], old_track_id)
        self.assertEqual(healthy['number_evidence']['observations'], 4)
        self.assertTrue(healthy['number_evidence']['current_observation'])

    def test_scene_gap_and_missing_hulls_do_not_inherit_raw_identity(self):
        good = self.reading([self.proposal()])
        for case in ('scene', 'gap', 'missing'):
            provider = self.provider([good]*4)
            for i in range(3):
                self.observe(provider, i)
            if case == 'missing':
                self.observe(provider, 3, detections=[])
            output = self.observe(provider, 9 if case=='gap' else 4, scene=1 if case=='scene' else 0)
            self.assertEqual(output['regions'], [])

    def test_richer_evidence_is_accepted_by_actual_tracking_consumer_without_fake_confidence(self):
        from race_ai.boat_video_tracking import _provider_candidates
        good = self.reading([self.proposal()])
        provider = self.provider([good]*3)
        for i in range(3):
            output = self.observe(provider, i)
        roi = self.np.full(self.frame.shape[:2], 255, self.np.uint8)
        candidates, ambiguous = _provider_candidates(output, roi, roi, self.cv2, self.np)
        self.assertFalse(ambiguous)
        self.assertEqual(len(candidates[1]), 1)
        self.assertNotIn('minimum_confidence', candidates[1][0]['number_evidence'])

    def test_soft_budget_records_overrun_and_skips_later_views_without_claiming_hard_limit(self):
        crop = self.np.full((60, 90, 3), 180, self.np.uint8)
        region = {'box':[10,25,22,45], 'mask':self.np.full((20,12),255,self.np.uint8)}
        tick = [0.]
        def infer(view):
            tick[0] += 3.5
            return '1', .4
        with patch.object(self.module, 'candidate_regions', return_value=[region]):
            output = self.module.read_number_regions(crop, infer=infer, monotonic=lambda:tick[0])
        self.assertEqual(output['status'], 'INCOMPLETE_BUDGET')
        self.assertTrue(output['soft_budget_exceeded'])
        self.assertFalse(output['hard_deadline_guaranteed'])
        self.assertEqual(output['attempts'][0]['seconds'], 3.5)
        self.assertEqual(output['proposals'], [])  # whole-hull diagnostic cannot anchor an ID
        self.assertEqual(output['skipped_views'], 2)

    def test_explicit_factory_paths_are_loaded_only_when_each_media_is_extracted(self):
        from unittest.mock import Mock
        self.assertTrue(hasattr(self.module, 'create_crnn_identity_provider'))
        create = Mock(side_effect=[object(), object()])
        with patch.object(self.module, 'create_crnn_identity_provider', create), \
             patch('race_ai.boat_video_tracking.extract_tracks', return_value={'tracks': []}) as extract:
            run = self.module.make_crnn_identity_extractor(model_path='/local/hull.onnx',
                crnn_model_path='/local/crnn.onnx', tiled_hulls=True, exclusions=[[1, 2, 3, 4]])
            self.assertEqual(create.call_count, 0)
            run('media-a.mp4', options={'sampling_fps': 4})
            run('media-b.mp4', options={'sampling_fps': 4})
            self.assertEqual(create.call_count, 2)
            providers = [call.kwargs['identity_provider'] for call in extract.call_args_list]
            self.assertIsNot(providers[0], providers[1])
            self.assertEqual(extract.call_args_list[0].kwargs['options'], {'sampling_fps': 4})
            self.assertTrue(create.call_args_list[0].kwargs['tiled_hulls'])

    def test_explicit_factory_preserves_pinned_reader_and_tiled_detector_metadata(self):
        # Constructors are the only native-asset boundary; temporal adapter is real.
        self.assertTrue(hasattr(self.module, 'PinnedBoatDetector'))
        from race_ai.boat_video_identity import PinnedBoatDetector, TiledBoatDetector
        detector = object.__new__(PinnedBoatDetector)
        detector.kind, detector.cv_version = 'yolox', 'test-version'
        reader = object.__new__(self.module.PinnedCRNNNumberReader)
        reader.cv_version, reader.soft_budget_seconds = 'test-version', 3.
        with patch.object(self.module, 'PinnedBoatDetector', return_value=detector), \
             patch.object(self.module, 'PinnedCRNNNumberReader', return_value=reader):
            provider = self.module.create_crnn_identity_provider(model_path='/explicit/hull',
                crnn_model_path='/explicit/crnn', tiled_hulls=True)
        self.assertIs(type(provider.detector), TiledBoatDetector)
        # Patch is over before calling metadata: exact type recognition remains real.
        metadata = provider.metadata()
        self.assertEqual(metadata['number_reader']['model_sha256'], self.module.MODEL_SHA256)
        self.assertEqual(metadata['number_reader']['score_scope'], self.module.SCORE_SCOPE)
        self.assertFalse(metadata['calibrated_identification_probability'])
        self.assertEqual(metadata['detector']['model_sha256'],
            'c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063')

    def test_optional_diagnostic_observer_gets_a_copy_without_changing_reader_output(self):
        records = []
        reader = object.__new__(self.module.PinnedCRNNNumberReader)
        reader.soft_budget_seconds = 3.
        reader._infer = lambda view: ('b', .3)
        def observer(reading):
            records.append(reading)
            reading['status'] = 'FORGED_BY_OBSERVER'
            reading['attempts'].clear()
        reader.diagnostic_callback = observer
        with patch.object(self.module, 'candidate_regions', return_value=[]):
            output = reader(self.frame)
        self.assertEqual(len(records), 1)
        self.assertEqual(output['status'], 'COMPLETE')
        self.assertEqual(len(output['attempts']), 1)
        self.assertEqual(output['attempts'][0]['text'], 'b')

    def test_diagnostic_observer_invalidity_or_failure_is_explicit_and_sanitized(self):
        with self.assertRaisesRegex(ValueError, 'diagnostic observer'):
            self.module.PinnedCRNNNumberReader(model_path='/not-read', diagnostic_callback=42)
        reader = object.__new__(self.module.PinnedCRNNNumberReader)
        reader.soft_budget_seconds = 3.
        reader._infer = lambda view: ('1', .3)
        def bad_observer(reading):
            raise RuntimeError('/private/callback/path')
        reader.diagnostic_callback = bad_observer
        with patch.object(self.module, 'candidate_regions', return_value=[]), \
             self.assertRaisesRegex(ValueError, '^local CRNN diagnostic observer failed$'):
            reader(self.frame)

    def test_reader_failure_is_explicit_and_does_not_leak_private_error_text(self):
        crop = self.np.full((60, 90, 3), 180, self.np.uint8)
        def infer(view):
            raise RuntimeError('/private/model/path')
        with patch.object(self.module, 'candidate_regions', return_value=[]):
            output = self.module.read_number_regions(crop, infer=infer)
        self.assertEqual(output['status'], 'INFERENCE_ERROR')
        self.assertNotIn('/private', str(output))


if __name__ == '__main__':
    unittest.main()
