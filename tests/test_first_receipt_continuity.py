import copy
import unittest
from race_ai import first_receipt_continuity as cycle
from tests.test_frozen_day_cycle import sample, observation
from race_ai.frozen_day_cycle import read_p0

class FirstReceiptContinuityTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(cycle, 'first_receipt_rows'), 'first-receipt merge is missing')
        _, raw, receipt = sample()
        _, self.rows = read_p0(raw, receipt, expected_day='2030-04-01')

    def test_previous_phase_is_retained_and_repeat_is_not_new_forecast(self):
        early = copy.deepcopy(self.rows)
        for row in early: row['stage'] = 'P1'
        later = copy.deepcopy(early)
        for row in later:
            row['server_saved_at'] = '2030-04-01T01:44:00Z'
            row['artifact_id'] = 3
            row['model_sha256'] = 'f' * 64
        untouched = copy.deepcopy(early + later)
        merged, duplicates = cycle.first_receipt_rows(later + early + self.rows)
        self.assertEqual(len(merged), 4)
        self.assertEqual(len(duplicates), 2)
        self.assertEqual({r['artifact_id'] for r in merged if r['stage']=='P1'}, {1})
        self.assertEqual(early + later, untouched)

    def test_same_receipt_cannot_have_two_different_predictions(self):
        changed=copy.deepcopy(self.rows[0]);changed['model_sha256']='e'*64
        with self.assertRaises(ValueError):
            cycle.first_receipt_rows(self.rows+[changed])

    def test_first_forecast_cutoff_and_roster_conflicts_are_not_hidden(self):
        for field,value in [('cutoff_at','2030-04-01T03:00:00+00:00'),('roster',{'1':'9999'})]:
            changed=copy.deepcopy(self.rows[0]);changed[field]=value;changed['artifact_id']=7
            with self.assertRaises(ValueError):
                cycle.first_receipt_rows(self.rows+[changed])

    def test_latest_result_does_not_erase_prior_other_race(self):
        self.assertTrue(hasattr(cycle,'latest_result_observations'))
        old=observation(self.rows[0]);new=copy.deepcopy(old)
        new['captured_at']='2030-04-01T02:20:00Z';new['source_sha256']='c'*64
        other=copy.deepcopy(old);other['race_id']='20300401-02-01'
        output, revisions=cycle.latest_result_observations([old,other,new])
        self.assertEqual(len(output),2);self.assertEqual(len(revisions),3)
        self.assertEqual(next(r for r in output if r['race_id']==old['race_id'])['source_sha256'],'c'*64)

    def test_same_result_capture_with_different_body_is_rejected(self):
        self.assertTrue(hasattr(cycle,'latest_result_observations'))
        a=observation(self.rows[0]);b=copy.deepcopy(a);b['source_sha256']='c'*64
        with self.assertRaises(ValueError): cycle.latest_result_observations([a,b])

if __name__=='__main__':unittest.main()
