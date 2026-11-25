import unittest
import numpy as np

from scripts import keirin_joint_pair_study as study


class OrderedPairChoiceTests(unittest.TestCase):
    def test_joint_reference_retains_both_orders_and_excludes_self_pairs(self):
        head = np.array([[1., 0., -1.]])
        second = np.array([[5., 0., -1.], [1., 5., 0.], [2., 1., 5.]])
        first, next_rider, score = study.reference_pairs(head, second)
        self.assertEqual(list(zip(first, next_rider)), [(0,1),(0,2),(1,0),(1,2),(2,0),(2,1)])
        self.assertTrue(np.isclose(score.sum(), 1.))
        self.assertNotEqual(score[0], score[2])


if __name__ == '__main__':
    unittest.main()
