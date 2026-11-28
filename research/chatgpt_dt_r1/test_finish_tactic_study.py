"""Boundary tests for the archived tactic label and coherent winner mixture."""
from math import fsum
import unittest

from research.chatgpt_dt_r1 import finish_tactic_study as study
from research.chatgpt_dt_r1.history_mix_study import exacta_marginal


class FinishTacticTests(unittest.TestCase):
    def test_normalization_preserves_unknown_and_missing_separately(self):
        normalized = [study.tactic_label(label) for label in (' 逃げ ', 'まくり', '差', 'ﾏｰｸ')]
        self.assertEqual(normalized, [(0, 'KNOWN'), (1, 'KNOWN'), (2, 'KNOWN'), (3, 'KNOWN')])
        self.assertEqual(study.tactic_label(None), (None, 'MISSING_MARK'))
        self.assertEqual(study.tactic_label('逃捲'), (None, 'UNKNOWN_MARK'))

    def test_full_mixture_keeps_conditional_placings_and_reconciles_tactic(self):
        base = {(1, 2, 3): .3, (1, 3, 2): .3, (2, 1, 3): .2, (2, 3, 1): .2}
        conditionals = {1: (.7, .1, .1, .1), 2: (.1, .7, .1, .1)}
        field = (.1, .7, .1, .1)
        candidate, tactic, implied = study.tactic_joint(base, conditionals, field, 1.)
        for actual, expected in zip(implied, (.46, .34, .1, .1), strict=True):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(tactic, field)
        self.assertEqual(study.tactic_joint(base, conditionals, field, 0.)[0], base)
        self.assertAlmostEqual(fsum(candidate.values()), 1.)
        self.assertAlmostEqual(candidate[1, 2, 3] / candidate[1, 3, 2], 1.)
        exactas = exacta_marginal(candidate)
        self.assertAlmostEqual(fsum(exactas.values()), 1.)
        self.assertGreater(exactas[2, 1], exactas[1, 2])
        with self.assertRaises(ValueError):
            study.tactic_joint(base, conditionals, field, 1.2)

    def test_unobserved_class_retains_only_prespecified_pseudocount(self):
        cards = [dict(race_id=str(i), riders=[dict(car=car) for car in (1, 2, 3)],
                      top3=[1, 2, 3], result_status='COMPLETE') for i in range(3)]
        marks = {str(i): (i, 'KNOWN') for i in range(3)}
        (plain, fields, riders), receipt = study._fit(cards, marks)
        self.assertEqual(receipt['tactic_class_counts']['マ'], 0)
        self.assertEqual(receipt['classes_without_training_observations'], ['マ'])
        self.assertAlmostEqual(plain[3], 1 / 7)
        self.assertTrue(all(law[3] > 0 for law in [*fields.values(), *riders.values()]))

    def test_line_missing_and_non_applicable_are_distinct(self):
        row = dict(riders=[dict(car=i, style='NIGE') for i in (1, 2, 3)],
                   lines_applicable=True, lines_known=True, line_groups=[[1, 2], [3]])
        context, rider = study.tactic_context(row)
        self.assertEqual(context[0], 'LINE_KNOWN')
        self.assertEqual(rider[1], ('NIGE', 'LEAD'))
        self.assertEqual(rider[2], ('NIGE', 'FOLLOW'))
        self.assertEqual(rider[3], ('NIGE', 'SINGLE'))
        row['lines_known'] = False
        self.assertEqual(study.tactic_context(row)[0][0], 'LINE_UNKNOWN')
        row['lines_applicable'] = False
        self.assertEqual(study.tactic_context(row)[0][0], 'LINE_NOT_APPLICABLE')


if __name__ == '__main__':
    unittest.main()
