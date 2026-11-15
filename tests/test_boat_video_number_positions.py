"""Printed hull marks must not depend on a detector crop's vertical origin."""
import importlib.util
import unittest


CV_AVAILABLE = importlib.util.find_spec('cv2') is not None


@unittest.skipUnless(CV_AVAILABLE, 'optional video dependencies are unavailable')
class PrintedNumberPositionTests(unittest.TestCase):
    def test_same_four_remains_localized_above_and_below_the_hull_crop_center(self):
        # A lower-only position prior would discard the upper copy of this
        # identical physical mark even though its shape/contrast is unchanged.
        import numpy as np
        from race_ai.boat_video_crnn import candidate_regions

        # Hand-defined connected printed4: no OCR/model output supplies the
        # expected bounds. Each cell is three native pixels wide and high.
        glyph = np.array([[int(pixel) for pixel in row] for row in (
            '000000100',
            '000001100',
            '000011100',
            '000110100',
            '001100100',
            '011000100',
            '110000100',
            '111111111',
            '000000100',
            '000000100',
            '000000100',
            '000000100',
            '000000100',
        )], dtype=np.uint8)
        glyph = np.repeat(np.repeat(glyph, 3, axis=0), 3, axis=1).astype(bool)

        for background, ink in ((30, 235), (235, 30)):
            with self.subTest(background=background):
                for y, expected in ((100, [80, 100, 107, 139]),
                                    (20, [80, 20, 107, 59])):
                    crop = np.full((160, 240, 3), background, np.uint8)
                    patch = crop[y:y+39, 80:107]
                    patch[glyph] = ink
                    regions = candidate_regions(crop)
                    self.assertIn(expected, [region['box'] for region in regions],
                                  'translating a readable mark upward must not erase its region')


if __name__ == '__main__':
    unittest.main()
