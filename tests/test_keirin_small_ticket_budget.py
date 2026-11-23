import unittest

from race_ai import keirin_small_ticket_budget as budget


class SmallTicketBudgetTests(unittest.TestCase):
    def test_one_four_eight_follow_the_frozen_thresholds(self):
        policy = {'one_min': 0.32, 'four_max_for_eight': 0.58, 'extra_gain_min': 0.15}
        self.assertEqual(budget.pick_budget((0.34, 0.62, 0.77), policy), 1)
        self.assertEqual(budget.pick_budget((0.19, 0.57, 0.75), policy), 8)
        self.assertEqual(budget.pick_budget((0.18, 0.61, 0.82), policy), 4)
        self.assertEqual(budget.pick_budget((0.13, 0.36, 0.45), policy), 4)

    def test_confidence_thresholds_cannot_create_a_result_from_too_few_races(self):
        self.assertLess(budget.wilson_lower(9, 9), 0.9)
        self.assertGreater(budget.wilson_lower(100, 100), 0.9)
        self.assertEqual(budget.wilson_lower(0, 0), 0)

    def test_no_candidate_expansion_and_no_duplicates_when_spreading_heads(self):
        ordered = [(1, 2, 3), (1, 3, 2), (1, 2, 4), (1, 4, 2),
                   (2, 3, 1), (2, 1, 3), (3, 1, 2)]
        result = budget.spread_heads(ordered, 4, 2)
        self.assertEqual(result, [ordered[i] for i in (0, 1, 4, 5)])
        self.assertEqual(budget.spread_heads(ordered[:4], 4, 2), ordered[:4])


if __name__ == '__main__':
    unittest.main()
