import unittest

import numpy as np

from scripts import keirin_race_risk_study as risk


class KeirinRaceRiskTests(unittest.TestCase):
    def test_manshaken_means_10000_yen_per_100_yen_and_mixed_awards_stay_unknown(self):
        self.assertTrue(risk.payout_risk([10000]))
        self.assertFalse(risk.payout_risk([9990]))
        self.assertTrue(risk.payout_risk([12920, 10000]))
        self.assertIsNone(risk.payout_risk([7000, 13000]))
        self.assertIsNone(risk.payout_risk(None))

    def test_line_risk_requires_competing_lines_and_one_unambiguous_label(self):
        self.assertTrue(risk.line_risk([[1,2],[3,4],[5]], [(1,3,2)]))
        self.assertFalse(risk.line_risk([[1,2],[3,4],[5]], [(1,2,3)]))
        self.assertIsNone(risk.line_risk([[1],[2],[3],[4],[5]], [(1,3,2)]))
        self.assertIsNone(risk.line_risk([[1,2],[3,4],[5]], [(1,3,2),(1,2,3)]))

    def test_risk_fit_discriminates_without_using_outcomes_at_prediction(self):
        values = [[0.], [.1], [.2], [.3], [.7], [.8], [.9], [1.]]
        model = risk.fit_probability(values, [0,0,0,0,1,1,1,1])
        result = risk.predict_probability(model, [[.2],[.8]])
        self.assertLess(result[0], .5)
        self.assertGreater(result[1], .5)

    def test_protected_order_keeps_the_first_four_and_budget(self):
        saved = np.arange(10)
        candidate = np.array([9,1,2,8,5,6,7,4,0,3])
        outcome = risk.guarded_order(saved, candidate, size=8, protect=4)
        np.testing.assert_array_equal(outcome,[0,1,2,3,9,8,5,6])

    def test_line_calibration_moves_mass_only_when_both_groups_are_possible(self):
        initial = np.array([.2, .2, .6])
        legal = np.array([False, True, True])
        np.testing.assert_allclose(risk.line_mass(initial, legal, .4), [.6,.1,.3])
        np.testing.assert_allclose(risk.line_mass(initial, np.ones(3,dtype=bool), .4), initial)


if __name__ == '__main__':
    unittest.main()
