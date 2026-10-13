import unittest
from race_ai.core import SourceError
from race_ai.motor_spotcheck import spotcheck


class MotorSpotcheckTest(unittest.TestCase):
    def fixture(self):
        boats=[dict(lane=i,motor_no=i+11,motor_top2_rate=30.1,boat_no=i+20) for i in range(1,7)]
        return dict(sample_race_id='20261013-19-09',sample_source_boats=boats),dict(race_id='20261013-19-09',boats=boats,source='https://www.boatrace.jp/')

    def test_all_six_motor_rate_boat_matches(self):
        got,ref=self.fixture()
        x=spotcheck(got,ref)
        self.assertEqual(x['motor_number_matches'],6)

    def test_wrong_motor_fails_closed(self):
        got,ref=self.fixture()
        ref['boats']=[dict(b) for b in ref['boats']]
        ref['boats'][2]['motor_no']=99
        with self.assertRaises(SourceError):
            spotcheck(got,ref)

    def test_wrong_rate_fails_closed(self):
        got,ref=self.fixture()
        ref['boats']=[dict(b) for b in ref['boats']]
        ref['boats'][5]['motor_top2_rate']=90.3
        with self.assertRaises(SourceError):
            spotcheck(got,ref)

    def test_wrong_race_fails_closed(self):
        got,ref=self.fixture()
        ref['race_id']='20261014-19-09'
        with self.assertRaises(SourceError):
            spotcheck(got,ref)

if __name__=='__main__':
    unittest.main()
