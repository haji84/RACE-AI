import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'NumPy is required for research scoring.')
class KeirinLineHistoryResearchTests(unittest.TestCase):
    def setUp(self):
        from scripts import keirin_line_history_study
        self.research = keirin_line_history_study
        self.card = {
            'race_id': '202611012201', 'line_groups': [[1, 3, 4], [2, 5]],
            'riders': [
                {'car': car, 'competition_points': 105-car,
                 'registration': f'{10001+car:06d}', 'class': 'S2',
                 'history': {'b': {'n': 6, 'yes': 3}}}
                for car in range(1, 6)
            ],
        }

    def test_unbound_identity_and_sparse_records_have_no_phase_support(self):
        self.card['riders'][0]['registration'] = 'not-a-registration'
        self.card['riders'][1]['history']['b'] = {'n': 2, 'yes': 1}
        columns = self.research.frame(self.card)[2]
        self.assertEqual(list(columns['previous_b_support'][:3]), [0.0, 0.0, 0.5])

    def test_pair_terms_use_the_ordered_positions_and_leave_third_unchanged(self):
        import numpy as np

        info = self.research.frame(self.card)
        prefix = (np.array([0]),)
        values = self.research.design(info, 'published_line', prefix)
        names = self.research.names_for('published_line', 1)
        self.assertEqual(list(values[0,:,names.index('next_in_order')]), [0, 0, 1, 0, 0])
        pair = (np.array([0]), np.array([2]))
        self.assertTrue(np.array_equal(
            self.research.design(info, 'line_with_history', pair),
            self.research.design(info, 'entry_only', pair)))

    def test_fitting_refuses_an_order_that_places_the_same_rider_twice(self):
        with self.assertRaisesRegex(ValueError, 'Fitting result orders'):
            self.research.fit([{'input': self.card,
                                'outcomes': {'2t': [[1, 2]], '3t': [[1, 2, 2]]}}])
