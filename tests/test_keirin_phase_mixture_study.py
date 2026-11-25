import unittest

import numpy as np

from scripts import keirin_phase_mixture_study as study


class ConditionalPhaseTests(unittest.TestCase):
    def test_h_back_transfer_is_marginalized_over_all_possible_home_leaders(self):
        logits = np.log([.40, .30, .20, .10])
        groups = np.array([0, 0, 1, 2])
        transition = np.array([1.2, .4, -.2, .1])
        homes = np.array([.30, .10, .55, .05])
        conditional = study.back_given_home(logits, groups, transition)
        np.testing.assert_allclose(np.sum(conditional, axis=1), 1)
        self.assertGreater(conditional[2, 2], conditional[0, 2])
        expected = sum(homes[index] * conditional[index] for index in range(4))
        np.testing.assert_allclose(study.marginal_back(homes, conditional), expected)

    def test_null_transfer_preserves_original_back_probabilities(self):
        logits = np.log([.40, .30, .20, .10])
        conditional = study.back_given_home(logits, np.array([0, 0, 1, 2]), np.zeros(4))
        result = study.marginal_back(np.array([0, 1, 0, 0]), conditional)
        np.testing.assert_allclose(result, np.exp(logits))

    def test_finish_choices_keep_car_identity_distinct_from_its_line(self):
        groups = np.array([0, 0, 1, 2])
        layout = np.array([0, 1, 0, 3])
        context = study.finish_design(groups, layout, np.array([0, 2]), ())
        self.assertEqual(context.shape[:3], (2, 1, 4))
        np.testing.assert_array_equal(context[0, 0, :, 0], [1, 0, 0, 0])
        np.testing.assert_array_equal(context[0, 0, :, 1], [1, 1, 0, 0])
        np.testing.assert_array_equal(context[1, 0, :, 0], [0, 0, 1, 0])


if __name__ == '__main__':
    unittest.main()
