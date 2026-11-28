"""Boundary checks for archived S/B labels and scenario marginalization."""
import math
import unittest

import numpy as np

from research.chatgpt_dt_r1 import start_back_study as study
from research.chatgpt_dt_r1.features import _bind_feature_input


class StartBackTests(unittest.TestCase):
    def test_pair_requires_unique_explicit_s_and_b_in_matching_roster(self):
        row = dict(riders=[{'car': car} for car in (1, 2, 3)], result_status='COMPLETE',
                   result_rows=[dict(car=1, sb_mark='Ｓ/Ｈ'), dict(car=2, sb_mark='B'),
                                dict(car=3, sb_mark=None)])
        self.assertEqual(study.paired_marks(row), ((1, 2), 'UNIQUE_S_AND_B'))
        self.assertEqual(row['result_rows'][0]['sb_mark'], 'Ｓ/Ｈ')
        row['result_rows'][2]['sb_mark'] = 'S'
        self.assertEqual(study.paired_marks(row), (None, 'AMBIGUOUS_S'))
        row['result_rows'].pop()
        self.assertEqual(study.paired_marks(row), (None, 'RESULT_ROSTER_INCOMPLETE'))

    def test_two_scenarios_both_contribute_to_normalized_b_law(self):
        row = dict(riders=[{'car': car} for car in (1, 2)], lines_known=False)
        relations = study.line_relations(row)
        start = np.array([.25, .75])
        direct = np.array([.5, .5])
        law = study.marginal_back(start, direct, relations, np.array([math.log(2.), 0.]))
        np.testing.assert_allclose(law, [5 / 12, 7 / 12], atol=1e-14)
        np.testing.assert_array_equal(study.marginal_back(start, direct, relations, np.zeros(2)), direct)

    def test_same_line_excludes_self_and_unknown_rosters(self):
        row = dict(riders=[{'car': car} for car in (1, 2, 3)], lines_known=True,
                   lines_applicable=True, line_groups=[[1, 2], [3]])
        actual = study.line_relations(row)
        np.testing.assert_array_equal(actual[:, :, 0], np.eye(3))
        np.testing.assert_array_equal(actual[:, :, 1], [[0, 1, 0], [1, 0, 0], [0, 0, 0]])
        row['lines_known'] = False
        np.testing.assert_array_equal(study.line_relations(row)[:, :, 1], np.zeros((3, 3)))

    def test_changing_the_current_result_labels_changes_no_s_or_b_prediction(self):
        cars = (1, 2, 3)
        row = _bind_feature_input(dict(riders=[dict(car=car) for car in cars], features=np.arange(3.)[:, None],
            feature_names=('fixture',), feature_status='READY', feature_scope='research',
            feature_version='fixture', history_evidence={}, lines_known=True, lines_applicable=True,
            line_groups=[[1, 2], [3]], result_rows=[dict(car=1, sb_mark='S'), dict(car=2, sb_mark='B'),
                                                  dict(car=3, sb_mark=None)], result_status='COMPLETE'))
        model = dict(feature_names=['fixture'], mean=[0.], scale=[1.], weights=[1.])
        swapped = dict(row, result_rows=[dict(car=1, sb_mark='B'), dict(car=2, sb_mark=None),
                                        dict(car=3, sb_mark='S')])
        self.assertNotEqual(study.paired_marks(row), study.paired_marks(swapped))

        def laws(source):
            vector = study._vector(model, source)
            back = study.marginal_back(vector, vector, study.line_relations(source), np.asarray([1., .5]))
            return vector, back

        for first, second in zip(laws(row), laws(swapped), strict=True):
            np.testing.assert_array_equal(first, second)


if __name__ == '__main__':
    unittest.main()
