"""Boundary tests for frozen-rank ordering motif discovery."""
from itertools import permutations
from math import fsum, log
import unittest

from research.chatgpt_dt_r1 import line_order_discovery_study as study
from research.chatgpt_dt_r1.history_mix_study import exacta_marginal


class LineOrderDiscoveryTests(unittest.TestCase):
    def test_motifs_distinguish_direction_without_inventing_unknown_lines(self):
        law = {triple: 1 / 6 for triple in permutations((1, 2, 3))}
        row = dict(riders=[dict(car=i) for i in (1, 2, 3)], lines_known=True,
                   lines_applicable=True, line_groups=[[1, 2], [3]])
        actual = study.order_motifs(row, law)
        self.assertEqual(actual[(1, 2, 3)][0][1], 'SAME_FORWARD_ADJACENT')
        self.assertEqual(actual[(2, 1, 3)][0][1], 'SAME_REVERSE_ADJACENT')
        self.assertEqual(actual[(1, 3, 2)][0][1], 'DIFFERENT_LINES')
        row['lines_known'] = False
        self.assertEqual(study.order_motifs(row, law)[(1, 2, 3)][0][1], 'LINE_UNKNOWN')
        row['lines_applicable'] = False
        self.assertEqual(study.order_motifs(row, law)[(1, 2, 3)][0][1], 'LINE_NOT_APPLICABLE')

    def test_joint_reweight_is_normalized_and_exacta_is_its_marginal(self):
        baseline = {triple: 1 / 24 for triple in permutations((1, 2, 3, 4), 3)}
        selected = (1, 2, 3)
        codes = {key: ('raised',) if key == selected else ('other',) for key in baseline}
        probabilities = study.adjusted_law(baseline, codes, {'raised': log(2)}, 1.)
        self.assertAlmostEqual(fsum(probabilities.values()), 1.)
        self.assertAlmostEqual(probabilities[selected], 2 / 25)
        self.assertAlmostEqual(exacta_marginal(probabilities)[selected[:2]], 3 / 25)
        self.assertEqual(study.adjusted_law(baseline, codes, {'raised': log(2)}, 0.), baseline)

    def test_log_loss_guard_and_one_point_lexicographic_order(self):
        def score(tri1, ex1, triline, exline):
            return dict(hits=dict(tri1=tri1, ex1=ex1),
                        proper=dict(tri_log_loss=triline, ex_log_loss=exline))
        baseline = study.BASELINE
        report = {baseline: score(10, 20, 4., 2.),
                  (10, .5): score(11, 30, 4., 2.),
                  (10, 1.): score(12, 25, 4., 2.1),
                  (40, .5): score(11, 31, 4., 1.9)}
        self.assertEqual(study.choose_candidate(report), (40, .5))


if __name__ == '__main__':
    unittest.main()
