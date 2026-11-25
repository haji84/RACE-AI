import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RetainedMarketThirdEvaluationTests(unittest.TestCase):
    def run_evaluation(self, *args):
        return subprocess.run(
            [sys.executable, '-B', '-m', 'scripts.keirin_market_third_evaluation', *args],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_historical_gains_keep_equal_budgets_and_the_nested_window(self):
        result = self.run_evaluation()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        historical = report['historical_market_replay']
        self.assertEqual(historical['races'], 61)
        self.assertEqual(historical['complete_windows_pooled']['4'], {
            'races': 61, 'tickets_per_arm': 244, 'baseline_hits': 19, 'candidate_hits': 18,
            'gained': 1, 'lost': 2,
        })
        strict = historical['windows']['2026-11-25_strict_T15_T10']
        self.assertEqual(strict['subset_of'], '2026-11-25_complete')
        self.assertEqual(strict['scores']['8'], {
            'races': 9, 'tickets_per_arm': 72, 'baseline_hits': 2, 'candidate_hits': 6,
            'gained': 4, 'lost': 0,
        })
        self.assertEqual(historical['exacta_top2']['scored'], 0)

    def test_registered_baseline_races_cannot_count_as_market_forward_evaluation(self):
        result = self.run_evaluation()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        prospective = report['retained_prospective_commitment']
        self.assertEqual(prospective['races'], 84)
        self.assertEqual(prospective['earliest_cutoff'], '2026-11-26T08:45:00+09:00')
        self.assertEqual(prospective['market_candidates_registered_in_receipts'], 0)
        self.assertEqual(prospective['races_scored_at_receipt'], 0)
        self.assertEqual(report['candidate_disposition'], 'HOLD_INDEPENDENT_MARKET_EVALUATION')
        self.assertIn('COMPLETE_HISTORICAL_TOP4_DECREASED', report['candidate_disposition_reasons'])
        self.assertFalse(report['production_weights_promoted'])

    def test_missing_git_evidence_fails_without_an_assessment(self):
        with tempfile.TemporaryDirectory() as missing:
            result = self.run_evaluation('--repo', missing)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('CalledProcessError', result.stderr)


if __name__ == '__main__':
    unittest.main()
