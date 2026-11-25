import unittest

import numpy as np

from scripts import keirin_ordered_ticket_study as study


class OrderedTicketStudyTests(unittest.TestCase):
    def test_third_depends_on_both_candidates_and_position_in_their_lines(self):
        group = np.array([0, 0, 0, 1, 1, 2])
        positions = np.array([0, 1, 2, 0, 1, 0])
        sizes = np.array([3, 3, 3, 2, 2, 1])
        features = study.line_context(group, positions, sizes,
                                      (np.array([0, 0]), np.array([1, 3])))
        self.assertGreater(np.count_nonzero(features[0, 2] != features[1, 2]), 0)
        self.assertGreater(np.count_nonzero(features[1, 2] != features[1, 4]), 0)
        self.assertTrue(np.isfinite(features).all())

    def test_variable_points_spend_same_budget_as_four_each(self):
        masses = [[.14, .18, .20]] * 4 + [[.05, .15, .39]] * 3
        chosen = study.allocate_points(masses)
        self.assertEqual(chosen, [1, 1, 1, 1, 8, 8, 8])
        self.assertEqual(sum(chosen), 4 * len(masses))
        self.assertEqual(study.allocate_points([[.10, .30, .35]] * 3), [4, 4, 4])


if __name__ == '__main__':
    unittest.main()
