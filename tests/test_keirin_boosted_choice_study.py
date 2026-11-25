import unittest

import numpy as np

from scripts import keirin_boosted_choice_study as study


class GroupedChoiceTests(unittest.TestCase):
    def test_gradient_normalizes_each_race_independently(self):
        scores = np.array([0., 0., -3., 2., 1.])
        labels = np.array([0., 1., 1., 0., 0.])
        sizes = np.array([2, 3])
        first, hessian = study.group_derivatives(scores, labels, sizes)
        original, _ = study.group_derivatives(scores + np.repeat([100., -20.], sizes), labels, sizes)
        np.testing.assert_allclose(first, original, atol=1e-12)
        np.testing.assert_allclose(np.add.reduceat(first, [0, 2]), [0., 0.], atol=1e-12)
        self.assertTrue((hessian > 0).all())

    def test_missing_mark_projection_preserves_other_evidence(self):
        snapshot = {'race_id': '202604011101', 'riders': [{'car':1, 'mark_rank':1, 'b_count':6}],
                    'line_groups': [[1]]}
        other = study.without_marks(snapshot)
        self.assertIsNone(other['riders'][0]['mark_rank'])
        self.assertEqual(other['riders'][0]['b_count'], 6)
        self.assertEqual(snapshot['riders'][0]['mark_rank'], 1)

    def test_masked_probabilities_preserve_slot_numbers(self):
        rows = np.array([[2., 3., -1.], [4., 1., 9.]])
        candidate = study.masked_probabilities(rows, (np.array([1, 2]),))
        np.testing.assert_allclose(candidate.sum(axis=1), 1.0)
        self.assertEqual(candidate[0, 1], 0.)
        self.assertEqual(candidate[1, 2], 0.)
        self.assertGreater(candidate[1, 0], candidate[1, 1])


if __name__ == '__main__':
    unittest.main()
