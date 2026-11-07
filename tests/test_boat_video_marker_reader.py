"""Marker discovery must not silently discard smaller printed marks."""
import importlib.util
import unittest

CV_AVAILABLE = importlib.util.find_spec('cv2') is not None


@unittest.skipUnless(CV_AVAILABLE, 'optional CV dependencies unavailable')
class CompleteMarkerLocalizationTests(unittest.TestCase):
    def test_native_reading_preserves_multichar_and_never_invents_semantic_context(self):
        import hashlib
        from unittest.mock import patch
        import numpy as np
        from race_ai.boat_video_marker_reader import read_marker_candidates
        pixels = np.arange(80*100*3, dtype=np.uint8).reshape(80, 100, 3)
        seen = []
        def infer(crop):
            seen.append(crop.copy())
            return ('12', None) if len(seen) == 1 else ('2', .37)
        boxes = [dict(box=[4, 8, 24, 38], source='mser_dark', score=2., band_origin_y=0),
                 dict(box=[50, 8, 70, 38], source='mser_dark', score=1., band_origin_y=0)]
        with patch('race_ai.boat_video_marker_reader.marker_regions', return_value=boxes):
            result = read_marker_candidates(pixels, infer=infer)
        self.assertEqual([r['text'] for r in result['readings']], ['12', '2'])
        self.assertEqual(result['frame_sha256'], hashlib.sha256(pixels.tobytes()).hexdigest())
        self.assertEqual(result['completed_candidates'], 2)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertFalse(result['identity_validated'])
        self.assertEqual(result['readings'][0]['semantic_parent_evidence'], False)
        self.assertEqual(result['readings'][1]['sequence_likelihood'], .37)
        self.assertFalse(result['calibrated_identification_probability'])
        # The model sees actual source pixels, with no rendering/padding/shear.
        import cv2
        gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
        np.testing.assert_array_equal(seen[0], gray[8:38, 4:24])
        np.testing.assert_array_equal(seen[1], gray[8:38, 50:70])

    def test_inference_failure_preserves_prefix_and_reports_unread_candidates(self):
        from unittest.mock import patch
        import numpy as np
        from race_ai.boat_video_marker_reader import read_marker_candidates
        pixels = np.zeros((80, 100, 3), np.uint8)
        def fail(_):
            raise RuntimeError('private path must not escape')
        boxes = [dict(box=[4, 8, 24, 38], source='mser_dark', score=2., band_origin_y=0)]
        with patch('race_ai.boat_video_marker_reader.marker_regions', return_value=boxes):
            result = read_marker_candidates(pixels, infer=fail)
        self.assertEqual(result['status'], 'INFERENCE_ERROR')
        self.assertEqual(result['completed_candidates'], 0)
        self.assertEqual(result['unread_candidates'], 1)
        self.assertNotIn('private path', str(result))

    def test_mutating_inference_and_invalid_full_vocabulary_scores_fail_closed(self):
        from unittest.mock import patch
        import numpy as np
        from race_ai.boat_video_marker_reader import read_marker_candidates
        pixels = np.zeros((80, 100, 3), np.uint8)
        boxes = [dict(box=[4, 8, 24, 38], source='mser_dark', score=2., band_origin_y=0)]
        def mutate(crop):
            crop[:] = 255
            return '2', .8
        for infer in (mutate, lambda _: ('2', None), lambda _: ('江', .8),
                      lambda _: ('12', .8), lambda _: ('2', float('nan'))):
            with self.subTest(infer=infer), patch(
                    'race_ai.boat_video_marker_reader.marker_regions', return_value=boxes):
                result = read_marker_candidates(pixels, infer=infer)
                self.assertEqual(result['status'], 'INFERENCE_ERROR')
                self.assertEqual(result['readings'], [])
                self.assertEqual(result['unread_candidates'], 1)

    def test_six_distinct_printed_marks_survive_complete_localization(self):
        import numpy as np
        from race_ai import boat_video_crnn
        all_candidate_regions = getattr(boat_video_crnn, 'all_candidate_regions', None)
        self.assertTrue(callable(all_candidate_regions), 'complete marker localization is missing')
        candidate_regions = boat_video_crnn.candidate_regions
        glyph = np.array([[int(c) for c in row] for row in (
            '000000100', '000001100', '000011100', '000110100',
            '001100100', '011000100', '110000100', '111111111',
            '000000100', '000000100', '000000100', '000000100', '000000100',
        )], dtype=np.uint8)
        glyph = np.repeat(np.repeat(glyph, 3, axis=0), 3, axis=1).astype(bool)
        for background, ink in ((30, 235), (235, 30)):
            with self.subTest(background=background):
                pixels = np.full((128, 520, 3), background, np.uint8)
                for x in (20, 100, 180, 260, 340, 420):
                    pixels[20:59, x:x+27][glyph] = ink
                all_regions = all_candidate_regions(pixels)
                boxes = [row['box'] for row in all_regions]
                for expected in ([20, 20, 47, 59], [100, 20, 127, 59],
                                 [180, 20, 207, 59], [260, 20, 287, 59],
                                 [340, 20, 367, 59], [420, 20, 447, 59]):
                    self.assertIn(expected, boxes)
                # The opt-in complete path must not change the ordinary reader.
                self.assertEqual([row['box'] for row in candidate_regions(pixels)],
                                 [[20, 20, 47, 59], [100, 20, 127, 59],
                                  [180, 20, 207, 59], [260, 20, 287, 59]])
