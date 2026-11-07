"""Pure full-vocabulary CTC/preprocessing controls, not real-ONNX accuracy tests."""
from hashlib import sha256
import importlib
import importlib.util
import itertools
from pathlib import Path
import tempfile
import unittest

try:
    ppocr = importlib.import_module('race_ai.boat_video_ppocr')
except ModuleNotFoundError:
    ppocr = None

NP = importlib.util.find_spec('numpy') is not None
CV = NP and importlib.util.find_spec('cv2') is not None


@unittest.skipUnless(NP, 'optional NumPy image dependency unavailable')
class PPOCRCTCTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ppocr, 'pinned optional PP-OCR recognizer is missing')
        import numpy as np
        self.np = np
        self.characters = ['blank'] + [chr(0x5000+i) for i in range(1, 6625)]
        for i in range(1, 7):
            self.characters[i] = str(i)
        self.characters[7:9] = ['A', '中']
        self.characters[-1] = ' '

    def rows(self, path):
        result = self.np.zeros((len(path), 6625), self.np.float32)
        result[self.np.arange(len(path)), path] = 1
        return result

    def test_blank_multidigit_repeated_and_full_vocabulary_decode(self):
        cases = [([0, 0], ''), ([6, 6], '6'), ([6, 0, 6], '66'),
                 ([6, 4], '64'), ([7, 0, 8], 'A中'), ([6624], ' ')]
        for path, text in cases:
            with self.subTest(path=path):
                result = ppocr.decode_softmax(self.rows(path), self.characters)
                self.assertEqual(result['text'], text)
                self.assertEqual(result['sequence_likelihood'], 1. if len(text) == 1 else None)
                self.assertEqual(result['mean_character_score'], 1. if text else 0.)
                self.assertIn('6625', result['score_scope'])
                self.assertIn('NOT_PROBABILITY', result['mean_character_score_scope'])

    def test_single_symbol_ctc_is_sum_of_all_paths_not_mean_character_score(self):
        rows = self.np.zeros((3, 6625), self.np.float64)
        rows[:, [0, 2, 7]] = [[.2, .7, .1], [.55, .4, .05], [.4, .5, .1]]
        expected = 0.
        for path in itertools.product((0, 2, 7), repeat=3):
            collapsed = [v for i, v in enumerate(path) if v != 0 and (i == 0 or v != path[i-1])]
            if collapsed == [2]:
                probability = 1.
                for step, value in enumerate(path):
                    probability *= rows[step, value]
                expected += probability
        self.assertAlmostEqual(ppocr.single_ctc_likelihood(rows, 2), expected, places=14)
        result = ppocr.decode_softmax(rows, self.characters)
        self.assertEqual(result['text'], '22')
        self.assertIsNone(result['sequence_likelihood'])

    def test_other6623_classes_are_not_renormalized_away(self):
        rows = self.np.zeros((1, 6625), self.np.float64)
        rows[0, [0, 6, 7, 6000]] = [.1, .4, .3, .2]
        result = ppocr.decode_softmax(rows, self.characters)
        self.assertEqual(result['text'], '6')
        self.assertEqual(result['sequence_likelihood'], .4)
        self.assertEqual(result['mean_character_score'], .4)
        self.assertNotAlmostEqual(result['sequence_likelihood'], .4 / (.4 + .1))

    def test_mean_score_is_stock_selected_greedy_event_mean(self):
        rows = self.np.zeros((3, 6625), self.np.float32)
        rows[0, [0, 6]] = [.2, .8]
        rows[1, [0, 6]] = [.4, .6]
        rows[2, [0, 6]] = [.7, .3]
        result = ppocr.decode_softmax(rows, self.characters)
        self.assertEqual(result['text'], '6')
        self.assertEqual(result['mean_character_score'], float(rows[0, 6]))
        self.assertNotAlmostEqual(result['mean_character_score'], result['sequence_likelihood'])

    def test_softmax_hash_covers_full_non_greedy_vocabulary(self):
        first = self.np.zeros((1, 6625), self.np.float32)
        first[0, [0, 6, 7]] = [.1, .7, .2]
        second = first.copy()
        second[0, [7, 8]] = [.1, .1]
        a, b = (ppocr.decode_softmax(v, self.characters) for v in (first, second))
        self.assertEqual(a['text'], b['text'])
        self.assertEqual(a['sequence_likelihood'], b['sequence_likelihood'])
        self.assertNotEqual(a['softmax_sha256'], b['softmax_sha256'])
        self.assertEqual(a['softmax_sha256'], sha256(first.tobytes()).hexdigest())

    def test_full_normalized_softmax_is_required_without_second_softmax(self):
        good = self.rows([1])
        bad = [good[:, :37], good.reshape(-1), good.astype(self.np.int64),
               self.np.full((1, 6625), .1), self.np.zeros((0, 6625)),
               self.np.full((1, 6625), float('nan')), self.np.full((1, 6625), float('inf'))]
        negative = good.copy(); negative[0, 0] = -.1; bad.append(negative)
        excessive = good.copy(); excessive[0, 1] = 1.00002; bad.append(excessive)
        for value in bad:
            with self.subTest(shape=value.shape), self.assertRaises(ValueError):
                ppocr.decode_softmax(value, self.characters)
        for symbol in (0, 6625, True, 1.5):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                ppocr.single_ctc_likelihood(good, symbol)

    def test_vocabulary_comes_from6623_metadata_lines_plus_space_and_blank(self):
        lines = self.characters[1:-1]
        result = ppocr.vocabulary_from_metadata('\n'.join(lines))
        self.assertEqual(list(result), self.characters)
        for value in ('', '\n'.join(lines[:-1]), '\n'.join(lines + ['x']),
                      '\n'.join([*lines[:-1], lines[0]]), None):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                ppocr.vocabulary_from_metadata(value)

    def test_model_pin_fails_before_optional_runtime_for_wrong_or_remote_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'not-a-model.onnx'
            file.write_bytes(b'not a valid pinned model')
            for value in (file, 'https://example.invalid/model.onnx', Path(folder) / 'missing'):
                with self.subTest(value=str(value)), self.assertRaises(ValueError):
                    ppocr.PinnedPPOCRRecognizer(model_path=value)


@unittest.skipUnless(CV, 'optional OpenCV image dependencies unavailable')
class PPOCRPreprocessingTests(unittest.TestCase):
    setUp = PPOCRCTCTests.setUp
    def crop(self, height=20, width=10):
        image = self.np.empty((height, width, 3), self.np.uint8)
        image[:] = [0, 64, 255]
        return image

    def test_bgr48_high_aspect_resize_and_normalized_zero_right_padding(self):
        image = self.crop()
        before = image.copy()
        blob = ppocr.prepare_image(image, max_wh_ratio=320/48)
        self.assertEqual(blob.shape, (3, 48, 320))
        self.assertEqual(blob.dtype, self.np.float32)
        self.np.testing.assert_array_equal(blob[:, :, 24:], 0)
        self.np.testing.assert_allclose(blob[:, 0, 0], [-1., (64/255-.5)/.5, 1.], atol=1e-7)
        self.np.testing.assert_array_equal(image, before)

    def test_width_expansion_matches_stock_batch_aspect_rule(self):
        image = self.crop(10, 100)
        blob = ppocr.prepare_image(image, max_wh_ratio=10.)
        self.assertEqual(blob.shape, (3, 48, 480))
        self.assertTrue(self.np.all(blob[0] == -1))

    def test_batch6_global_aspect_sort_is_aligned_and_complete(self):
        crops = [self.crop(10, width) for width in (70, 10, 60, 20, 80, 30, 50, 40)]
        plan = ppocr.plan_batches(crops)
        expected = self.np.argsort(self.np.array([c.shape[1]/c.shape[0] for c in crops])).tolist()
        self.assertEqual([i for batch in plan for i in batch['indices']], expected)
        self.assertEqual([len(batch['indices']) for batch in plan], [6, 2])
        self.assertEqual(plan[0]['max_wh_ratio'], 320/48)
        self.assertEqual(plan[1]['max_wh_ratio'], 8.)
        self.assertEqual(ppocr.plan_batches([]), [])

    def test_invalid_entire_input_rejects_before_any_inference(self):
        # A sentinel verifies orchestration ordering only; it is not ONNX output.
        recognizer = ppocr.PinnedPPOCRRecognizer.__new__(ppocr.PinnedPPOCRRecognizer)
        class NeverSession:
            def run(self, *args):
                raise AssertionError('inference was reached for invalid input')
        recognizer._session = NeverSession()
        bad = self.crop().astype(self.np.float32)
        with self.assertRaises(ValueError):
            recognizer([self.crop() for _ in range(6)] + [bad])
        for value in (self.crop(), (self.crop(),), [self.crop()[:, :, 0]], [self.crop(0, 1)]):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                ppocr.plan_batches(value)

    def fixture_recognizer(self, callback=None):
        """Explicit synthetic inference fixture, never a real-ONNX assertion."""
        recognizer = ppocr.PinnedPPOCRRecognizer.__new__(ppocr.PinnedPPOCRRecognizer)
        recognizer._characters = tuple(self.characters)
        recognizer._vocabulary_sha = '0'*64
        class ControlledFixtureSession:
            def run(session, names, feed):
                blob = feed['x']
                result = self.np.zeros((len(blob), 1, 6625), self.np.float32)
                # The fixture encodes the source B channel, testing only batch
                # alignment. This is not model recognition or accuracy.
                for i, image in enumerate(blob):
                    symbol = round(float((image[0, 0, 0]+1)*.5*255)) % 6 + 1
                    result[i, 0, symbol] = 1.
                if callback:
                    callback()
                return [result]
        recognizer._session = ControlledFixtureSession()
        return recognizer

    def test_controlled_fixture_preserves_original_order_and_pixel_hashes(self):
        crops = [self.crop(10, w) for w in (70, 10, 60, 20, 80, 30, 50, 40)]
        for index, image in enumerate(crops):
            image[:, :, 0] = index
        result = self.fixture_recognizer()(crops)
        self.assertEqual([r['text'] for r in result], [str(i % 6+1) for i in range(8)])
        for image, row in zip(crops, result):
            self.assertEqual(row['input_sha256'], sha256(image.tobytes()).hexdigest())
            self.assertEqual(row['input_sha256_after'], row['input_sha256'])
            self.assertEqual(row['input_shape'], list(image.shape))
            self.assertFalse(row['model_eligible'])

    def test_changed_pixels_or_geometry_reject_whole_call_without_results(self):
        for kind in ('pixels', 'shape'):
            with self.subTest(kind=kind):
                image = self.crop(20, 10)
                def mutate():
                    if kind == 'pixels':
                        image[0, 0, 0] = 99
                    else:
                        image.shape = (10, 20, 3)
                with self.assertRaises(ValueError):
                    self.fixture_recognizer(mutate)([image])

    def test_batch_mutate_then_restore_cannot_hide_changed_inference_pixels(self):
        crops = [self.crop(20, width) for width in range(10, 17)]
        calls = []
        def mutate_between_batches():
            calls.append(1)
            crops[6][:, :, 0] = 10 if len(calls) == 1 else 0
        with self.assertRaises(ValueError):
            self.fixture_recognizer(mutate_between_batches)(crops)
        # The seventh crop differs from its original receipt; reject before a
        # second inference could use it and then restore the source bytes.
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
