import unittest
from itertools import permutations

import numpy as np

from scripts import keirin_rider_variation_study as study


class RiderVariationTests(unittest.TestCase):
    def test_tail_features_distinguish_same_mean_previous_finishes(self):
        early = study.PriorFinishVariation()
        for d, finish in [(1, [1, 3, 2, 4, 5]), (2, [5, 3, 1, 2, 4])]:
            early.start_day(d)
            self.assertEqual(early.features(['X'])[0, 0], (d-1)/(d-1+12))
            early.record(['X', 'Y', 'A', 'B', 'C'], [90.] * 5, finish)
        early.start_day(3)
        a, b = early.features(['X', 'Y'])
        self.assertAlmostEqual(a[1], b[1])
        self.assertGreater(a[2], b[2])
        self.assertGreater(a[3], b[3])
        self.assertGreater(a[4], b[4])

    def test_update_preserves_win_probability_and_each_pairs_conditional_third(self):
        orders = np.array(list(permutations(range(5), 3)))
        ps = np.arange(1, len(orders)+1, dtype=float)
        ps = ps[None, :] / sum(ps)
        pair = study.pair_mass(orders, ps, 5)
        traits = np.arange(5*study.WIDTH,dtype=float).reshape(1,5,-1) / 30.
        groups = np.array([[1, 1, 2, 2, 3]])
        f = study.second_features(traits,groups)
        weights = np.linspace(-.25,.2,f.shape[-1])
        q,new = study.adjust_triples(orders,ps,pair,f,weights)
        a,b=orders[:,:2].T
        self.assertFalse(np.allclose(q,ps))
        np.testing.assert_allclose(new.sum(2), pair.sum(2), atol=1e-12)
        np.testing.assert_allclose(q / new[:,a,b], ps / pair[:,a,b], atol=1e-12)

    def test_same_day_query_reads_only_previous_days_and_old_rows_expire(self):
        history=study.PriorFinishVariation()
        history.start_day(10)
        np.testing.assert_array_equal(history.features(['X']),0.)
        history.record(['X','Y','A','B','C'],[90.,95.,90.,90.,90.],[5,1,2,3,4])
        with self.assertRaisesRegex(ValueError,'day'):
            history.features(['X'])
        history.start_day(11)
        self.assertGreater(history.features(['X'])[0,0],0.)
        history.start_day(500)
        np.testing.assert_array_equal(history.features(['X']),0.)
