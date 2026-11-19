import unittest
from nationwide_line_gate import classify, audit, validate_snapshot

class GateTests(unittest.TestCase):
    def test_all_same(self):
        self.assertEqual(classify([[1,2,4,6],[3,5,7]],'1-2-4',list(range(1,8))),'SAME_LINE_3')
    def test_two_same(self):
        self.assertEqual(classify([[1,2,4,6],[3,5,7]],'1-2-3',list(range(1,8))),'SAME_LINE_2_PLUS_OTHER')
    def test_all_different(self):
        self.assertEqual(classify([[1,2],[3,5],[4,6],[7]],'1-3-7',list(range(1,8))),'THREE_DIFFERENT_LINES')
    def test_missing_line_rejected(self):
        with self.assertRaises(ValueError): classify([[1,2],[3,4]], '1-2-3',list(range(1,7)))
    def test_unknown_report(self):
        race={'race_key':'20261118_74_03','actual_starters':'1-2-3-4-5-6-7','winning_orders':'1-2-4','gender':'男子'}
        result=audit({'20261118_74_03':race},{})
        self.assertEqual(result['formal_nationwide_verdict'],'HOLD')
        self.assertEqual(result['formal_verified_races'],0)
        self.assertEqual(result['line_applicable_male_races'],1)
    def test_girls_not_line_missing(self):
        race={'race_key':'20261118_74_03','actual_starters':'1-2-3-4-5-6-7','winning_orders':'1-2-4','gender':'ガールズ'}
        result=audit({'20261118_74_03':race},{})
        self.assertEqual(result['not_applicable_girls_races'],1)
        self.assertEqual(result['failure_reasons'],{})
    def test_hash_string_alone_is_not_proof(self):
        race={'race_key':'20261118_74_03','actual_starters':'1-2-3-4-5-6-7','winning_orders':'1-2-4','gender':'男子'}
        s={'race_key':'20261118_74_03','lines':[[1,2,4,6],[3,5,7]],'source_url':'https://example.com/','captured_at':'2026-11-19T20:00:00+09:00','source_sha256':'0'*64,'independent_line_review':'PASS','lineup_status':'PUBLISHED_PREDICTED_LINE','temporal_status':'HISTORICAL_RETROSPECTIVE'}
        status, issue=validate_snapshot(s,race,None)
        self.assertEqual(issue,'SOURCE_BYTES_NOT_AVAILABLE')
    def test_duplicate_starters_rejected(self):
        with self.assertRaises(ValueError): classify([[1,1],[2],[3]],'1-2-3',[1,2,3])

if __name__ == '__main__': unittest.main()