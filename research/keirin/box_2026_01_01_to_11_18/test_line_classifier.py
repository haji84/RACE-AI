import unittest
from line_classifier import classify_order, classify_race, InvalidLineup
class LineTests(unittest.TestCase):
    def test_same3(self):
        x=classify_order([[1,4,6],[2,5],[3],[7]],[1,4,6]); self.assertEqual(x['class'],'SAME_LINE_3');self.assertTrue(x['complete_three_rider_line'])
    def test_same3_from_four(self):
        x=classify_order([[1,4,6,8],[2,5],[3],[7,9]],[1,4,8]);self.assertFalse(x['complete_three_rider_line']);self.assertTrue(x['three_from_line_of_4_or_more'])
    def test_pair_plus_single(self):
        x=classify_order([[1,4,6],[2,5],[3],[7]],[4,1,3]);self.assertEqual(x['class'],'SAME_LINE_2_PLUS_OTHER');self.assertEqual(x['singleton_top3_places'],[3]);self.assertEqual(x['same_line_pair_finish_positions'],[1,2])
    def test_all_separate(self):
        x=classify_order([[1,4,6],[2,5],[3],[7]],[2,3,7]);self.assertEqual(x['class'],'THREE_DIFFERENT_LINES');self.assertEqual(x['singleton_top3_places'],[2,3])
    def test_mixed_tie_payout(self):
        x=classify_race([[1,4,6],[2,5],[3],[7]],[{'order':'1-4-6','yen':1000},{'order':'1-3-7','yen':2000}]);self.assertTrue(x['has_multiple_line_classes_due_to_ties'])
    def test_lineup_must_match_starters(self):
        with self.assertRaises(InvalidLineup):classify_order([[1,2],[3],[4]], [1,2,3],starters=[1,2,3])
    def test_duplicate_rider(self):
        with self.assertRaises(InvalidLineup):classify_order([[1,2],[2,3]], [1,2,3])
if __name__=='__main__':unittest.main()
