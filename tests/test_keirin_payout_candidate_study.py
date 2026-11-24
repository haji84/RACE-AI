import unittest

import numpy as np

from scripts import keirin_payout_candidate_study as study
from scripts.keirin_trio_order_study import trio_layout


class PayoutCandidateTests(unittest.TestCase):
    def test_large_payout_order_uses_joint_probability_rather_than_payout_risk_alone(self):
        p = np.array([.21, .12, .01, .66])
        large = np.array([.2, .8, .97, .01])
        np.testing.assert_array_equal(study.high_payout_order(p,large),[1,0,2,3])

    def test_layout_features_can_differ_between_hypothetical_tickets_in_one_race(self):
        snapshot = {'line_groups':[[1,2],[3,4],[5]],
                    'riders':[{'car':i,'competition_points':90+i} for i in range(1,6)]}
        tickets,_=trio_layout(5)
        probability=np.arange(1,len(tickets)+1,dtype=float)
        probability/=probability.sum()
        data=study.candidate_vectors(snapshot,[1,2,3,4,5],tickets,probability)
        self.assertEqual(len(data),len(tickets))
        self.assertTrue(np.all(np.isfinite(data)))
        self.assertFalse(np.allclose(data[0],data[-1]))

    def test_candidate_inputs_reject_post_race_data(self):
        with self.assertRaisesRegex(ValueError,'forecast fields'):
            study.candidate_vectors({'payouts':{}},[],None,None)


if __name__ == '__main__':
    unittest.main()
