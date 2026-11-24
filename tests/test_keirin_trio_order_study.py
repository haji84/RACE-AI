import unittest

import numpy as np

from scripts import keirin_trio_order_study as study


class TrioOrderTests(unittest.TestCase):
    def test_reordering_can_promote_a_chaser_without_changing_the_three_rider_mass(self):
        orders, groups = study.trio_layout(5)
        baseline = np.arange(1, len(orders) + 1, dtype=float)
        baseline /= baseline.sum()
        adjustment = np.zeros(len(baseline))
        original = np.flatnonzero(np.all(orders == (0, 1, 2), axis=1))[0]
        reverse = np.flatnonzero(np.all(orders == (1, 0, 2), axis=1))[0]
        adjustment[reverse] = 2
        result = study.reorder_trios(baseline, groups, adjustment)
        self.assertGreater(result[reverse], result[original])
        np.testing.assert_allclose(result[groups].sum(axis=-1), baseline[groups].sum(axis=-1))
        np.testing.assert_allclose(study.reorder_trios(baseline, groups, np.zeros(len(baseline))), baseline)

    def test_all_trios_cover_each_legal_permutation_once(self):
        orders, groups = study.trio_layout(9)
        self.assertEqual(orders.shape, (504, 3))
        self.assertEqual(groups.shape, (84, 6))
        np.testing.assert_array_equal(np.sort(groups.ravel()), np.arange(504))
        self.assertTrue(np.all(np.sort(orders[groups], axis=2)==np.sort(orders[groups[:,[0]]],axis=2)))
        self.assertFalse(orders.flags.writeable)


if __name__ == '__main__':
    unittest.main()
