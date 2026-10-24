"""Digits in actual pictures are observations, never inferred boat identities."""
import unittest

from race_ai.core import SourceError


def row(text='3', score=.99, x=100, y=100):
    return {'text': text, 'score': score,
            'box': [[x, y], [x+12, y], [x+12, y+20], [x, y+20]]}


class NumberMarkTests(unittest.TestCase):
    def module(self):
        try:
            import race_ai.video_number_marks as module
        except ModuleNotFoundError:
            self.fail('number-mark observation contract is missing')
        return module

    def test_exact_single_digit_outside_overlay_is_only_candidate(self):
        result = self.module().assess_marks([row()], width=854, height=480,
                                           exclusions=[[0, 0, 854, 60]])
        self.assertEqual(result['candidates'][0]['candidate_number'], 3)
        self.assertEqual(result['candidates'][0]['box'], [100., 100., 12., 20.])
        self.assertEqual(result['boat_identity'], 'UNVERIFIED')
        self.assertFalse(result['prediction_eligible'])
        self.assertEqual(result['boat_features'], [])

    def test_scoreboard_digit_is_excluded_even_with_perfect_confidence(self):
        result = self.module().assess_marks([row(score=1, x=720, y=20)], width=854,
                                           height=480, exclusions=[[600, 0, 254, 180]])
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['excluded_overlay_marks'], 1)

    def test_exact_digit_rule_and_low_score_do_not_correct_ocr(self):
        values = [row(text=s, x=20+i*25) for i,s in enumerate(['３', '3 ', '13', 'O', '7', '3R'])]
        values.append(row(score=.89))
        result = self.module().assess_marks(values, width=854, height=480, exclusions=[])
        self.assertEqual(result['candidates'], [])

    def test_duplicate_number_is_ambiguous_not_arbitrarily_selected(self):
        result = self.module().assess_marks([row(x=100), row(x=300)], width=854,
                                           height=480, exclusions=[])
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['ambiguous_numbers'], [3])

    def test_invalid_geometry_and_nonfinite_values_are_rejected(self):
        for change in ({'score': float('nan')}, {'score': True}, {'score': 10**1000}, {'box': [[-1,0]]*4},
                       {'box': [[10,10]]*4}, {'box': [[0,0],[20,20],[0,20],[20,0]]},
                       {'box': [[0,0],[900,0],[900,20],[0,20]]}):
            with self.subTest(change=change), self.assertRaises(SourceError):
                self.module().assess_marks([dict(row(), **change)], width=854,
                                           height=480, exclusions=[])

    def test_missing_exclusion_contract_or_excess_rows_fails(self):
        for exclusions in (None, [[0,0,0,10]], [[-1,0,20,10]]):
            with self.subTest(exclusions=exclusions), self.assertRaises(SourceError):
                self.module().assess_marks([row()], width=854, height=480, exclusions=exclusions)
        with self.assertRaises(SourceError):
            self.module().assess_marks([row()]*129, width=854, height=480, exclusions=[])

    def test_track_cut_gap_and_ambiguous_frame_reset_association(self):
        module = self.module()
        tracker = module.NumberMarkTracker(width=854, height=480, exclusions=[])
        tracker.observe([row(x=100)], second=0, segment=0)
        tracker.observe([row(x=110)], second=1, segment=0)
        tracker.observe([row(x=120)], second=2, segment=0, scene_cut=True)
        tracker.observe([row(x=130)], second=3, segment=1)
        tracker.observe([row(x=140)], second=10, segment=1)
        tracker.observe([row(x=150),row(x=300)], second=11, segment=1)
        tracker.observe([row(x=160)], second=12, segment=1)
        result = tracker.finish()
        self.assertEqual(len(result['tracks']), 1)
        self.assertEqual(result['tracks'][0]['samples'], 2)
        self.assertEqual(result['tracks'][0]['dx_pixels'], 10.)
        self.assertFalse(result['prediction_eligible'])
        self.assertEqual(result['boat_features'], [])
        self.assertNotIn('kmh', str(result).lower())

    def test_clock_reversal_and_bad_segment_stop(self):
        tracker = self.module().NumberMarkTracker(width=854, height=480, exclusions=[])
        tracker.observe([row()], second=2, segment=0)
        for args in ({'second':1,'segment':0}, {'second':3,'segment':-1}):
            with self.subTest(args=args), self.assertRaises(SourceError):
                tracker.observe([row()], **args)

    def test_each_dimension_must_be_positive_and_bounded(self):
        for width,height in ((-854,-480),(921600,1),(1,921600),(0,480)):
            with self.subTest(width=width,height=height),self.assertRaises(SourceError):
                self.module().assess_marks([],width=width,height=height,exclusions=[])

    def test_returned_observations_cannot_modify_tracker_history(self):
        tracker=self.module().NumberMarkTracker(width=854,height=480,exclusions=[])
        assessment=tracker.observe([row()],second=0,segment=0)
        assessment['candidates'][0]['candidate_number']=1
        result=tracker.finish()
        self.assertEqual(result['observations'][0]['candidates'][0]['candidate_number'],3)
        result['observations'][0]['candidates'][0]['candidate_number']=2
        self.assertEqual(tracker.finish()['observations'][0]['candidates'][0]['candidate_number'],3)


if __name__ == '__main__':
    unittest.main()
