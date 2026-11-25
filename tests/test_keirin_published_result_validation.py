"""Synthetic comparisons exercise the shared result gate without a ranker."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import unittest

from race_ai import keirin_secondary_result_consensus as consensus


class PublishedResultValidationTests(unittest.TestCase):
    def check(self, **changes):
        bound = {'race_id': '209901016201', 'cutoff_at': '2099-01-01T10:00:00+09:00',
                 'starters': [1, 2, 3, 4]}
        comparison = {'race_id': bound['race_id'], 'authority': 'cross_source_reference',
                      'comparison_scope': 'POST_CUTOFF_REFERENCE', 'observed_at': '2099-01-01T01:00:00Z',
                      'winning_3t': [3, 1, 4], 'winning_2t': [3, 1], **changes}
        checked_at = datetime(2099, 1, 1, 1, 30, tzinfo=timezone.utc)
        return consensus.checked_published_result({'comparison': comparison}, bound, checked_at)

    def test_matched_order_and_inclusive_time_boundaries(self):
        for observed in ('2099-01-01T01:00:00Z', '2099-01-01T10:30:00+09:00'):
            with self.subTest(observed=observed):
                self.assertEqual(self.check(observed_at=observed),
                                 ('matched', {'2t': [3, 1], '3t': [3, 1, 4]}))

    def test_outside_time_and_unlisted_winner_remain_separate_states(self):
        for observed in ('2099-01-01T00:59:59.999999Z', '2099-01-01T01:30:00.000001Z'):
            with self.subTest(observed=observed):
                self.assertEqual(self.check(observed_at=observed), ('invalid_timing', None))
        self.assertEqual(self.check(winning_3t=[3, 1, 5]), ('winner_outside_starters', None))

    def test_invalid_provenance_orders_and_clocks_preserve_errors(self):
        for changes, code in [
            ({'authority': 'unconfirmed'}, 'PROSPECTIVE_RESULT_PROVENANCE_MISMATCH'),
            ({'race_id': '209901016202'}, 'PROSPECTIVE_RESULT_PROVENANCE_MISMATCH'),
            ({'comparison_scope': 'PRE_CUTOFF'}, 'PROSPECTIVE_RESULT_PROVENANCE_MISMATCH'),
            ({'winning_3t': [3, 1, 3]}, 'PROSPECTIVE_RESULT_ORDER_INVALID'),
            ({'winning_3t': [3, True, 4]}, 'PROSPECTIVE_RESULT_ORDER_INVALID'),
            ({'winning_2t': [1, 3]}, 'PROSPECTIVE_RESULT_ORDER_INVALID'),
            ({'observed_at': None}, 'SOURCE_TIME_MISSING'),
            ({'observed_at': '2099-01-01T10:00:00'}, 'SOURCE_TIME_MUST_INCLUDE_TIMEZONE'),
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, '^' + code + '$'):
                self.check(**changes)

    def test_forward_scorer_imports_without_site_packages_or_research_studies(self):
        command = """
import sys
from scripts import keirin_forward_score
for name in ('numpy', 'scipy', 'scripts.keirin_line_forward_study',
             'scripts.keirin_rider_context_study', 'scripts.keirin_rider_profile_study'):
    assert name not in sys.modules, name
"""
        result = subprocess.run([sys.executable, '-B', '-S', '-c', command], capture_output=True,
                                text=True, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stderr)
