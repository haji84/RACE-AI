"""Saved-data acceptance uses the actual Node reader and invented private data."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_boat_prospective_audit as fixtures

DAY, cli = fixtures.DAY, fixtures.cli


class SavedComparisonAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ProspectiveAuditTests.setUpClass.__func__(cls)

    setUp = fixtures.ProspectiveAuditTests.setUp

    def run_comparison(self, *extra, comparison_day=DAY):
        output, errors = io.StringIO(), io.StringIO()
        arguments = ['--output', str(self.output)]
        if comparison_day is not None:
            arguments += ['--saved-comparison-day', comparison_day]
        arguments += list(extra)
        with redirect_stdout(output), redirect_stderr(errors):
            try: code = cli.main(arguments)
            except SystemExit as error: code = error.code
        text = output.getvalue()
        for private in ('SECRET-', self.environment['RACE_AI_STATE_KEY'], self.environment['GH_TOKEN'],
                        'ordered_top8', 'race_id', 'combination'):
            self.assertNotIn(private, text)
        return code, json.loads(text) if text.strip() else {}, errors.getvalue()

    def test_comparison_reads_saved_data_without_runtime_or_prospective_plan(self):
        self.plan.unlink(); before = deepcopy(self.view)
        with patch.object(cli.CLI, 'restore_ready', side_effect=AssertionError('runtime is forbidden')):
            code, result, error = self.run_comparison('--daily-budgets', '10000,5000')
        self.assertEqual(code, 0, error)
        self.assertEqual(result['status'], 'SAVED_COMPARISON_ONLY')
        self.assertEqual(result['feed_generation'], 8)
        self.assertEqual(result['day'], DAY)
        self.assertEqual(result['descriptive']['coverage']['races'], 1)
        self.assertEqual(len(result['descriptive']['groups'][0]['simulations']), 4)
        self.assertFalse(result['accuracy_improvement_proven'])
        self.assertFalse(result['promotion_allowed'])
        self.assertFalse(result['independent_pre_cutoff_receipt_verified'])
        self.assertFalse(result['frozen_plan_evaluated'])
        self.assertEqual(result['source_requests'], 0)
        self.assertEqual(self.view, before)
        self.assertEqual(json.loads(self.output.read_text()), result)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_budget_returns_keep_void_pending_and_actual_purchase_denominator_separate(self):
        source = deepcopy(self.view['records'][0]); rows = []
        for index in range(8):
            row = deepcopy(source); row.update(race_id=f'20300401-01-{index+1:02}', race_no=index+1)
            row['result'] = {'status': 'final', 'winning_combinations': [[6, 5, 4]], 'payout_yen_per_100': 1200}
            if index == 0: row['result']['winning_combinations'] = [[1, 2, 3]]
            if index == 1: row['result'] = {'status': 'void', 'winning_combinations': []}
            if index == 2: row['result'] = None
            rows.append(row)
        self.view['records'] = rows; self.view['event_date_jst'] = DAY
        code, result, error = self.run_comparison('--daily-budgets', '10000,5000')
        self.assertEqual(code, 0, error)
        group = result['descriptive']['groups'][0]
        self.assertEqual(group['observed']['hits'], 1)
        self.assertEqual(group['observed']['misses'], 5)
        self.assertEqual(group['observed']['void'], 1)
        self.assertEqual(group['observed']['pending'], 1)
        scenarios = {s['budgetPerDay']: s for s in group['simulations'] if s['raceBudget'] == 1000}
        large, small = scenarios[10000], scenarios[5000]
        for actual, expected in [(large, (8000, 7000, -3600)), (small, (5000, 4000, -600))]:
            self.assertEqual((actual['spent'], actual['settledStake'], actual['settledNet']), expected)
            self.assertEqual(actual['payout'], 2400)
            self.assertEqual(actual['refund'], 1000)
            self.assertEqual(actual['pendingStake'], 1000)
            self.assertIsNone(actual['net'])
        self.assertEqual((large['bought'], small['bought']), (8, 5))
        self.assertAlmostEqual(small['roi'], 85.0)

    def test_empty_selected_day_cannot_be_reported_as_completed_comparison(self):
        self.view['records'] = [self.view['records'][1]]
        code, result, error = self.run_comparison()
        self.assertEqual(code, 2, error)
        self.assertEqual(result.get('reason'), 'PROSPECTIVE_AUDIT_COMPARISON_DAY_EMPTY')
        self.assertFalse(self.output.exists())

    def test_budget_options_require_comparison_mode_and_valid_distinct_hundred_yen_units(self):
        for budget, day in [('5000', None), ('0', DAY), ('5001', DAY), ('10000,10000', DAY),
                            ('10000,SECRET', DAY), ('10000001', DAY)]:
            with self.subTest(budget=budget, comparison_day=day):
                code, result, _ = self.run_comparison('--daily-budgets', budget, comparison_day=day)
                self.assertEqual(code, 2)
                self.assertEqual(result.get('reason'), 'PROSPECTIVE_AUDIT_COMPARISON_OPTIONS_INVALID')
                self.assertFalse(self.output.exists())
        self.patches[6].assert_not_called()

    def test_comparison_still_requires_owner_context_before_any_saved_view_read(self):
        with patch.dict(os.environ, {k:v for k,v in self.environment.items() if k != 'RACE_AI_STATE_KEY'}, clear=True), \
                patch.object(cli, '_owner_view', side_effect=AssertionError('owner view read without owner key')):
            code, result, _ = self.run_comparison()
        self.assertEqual(code, 2)
        self.assertEqual(result.get('status'), 'PROSPECTIVE_AUDIT_REJECTED')
        self.assertFalse(self.output.exists())

    def test_descriptive_node_never_receives_keys_and_cannot_claim_improvement(self):
        script = self.repo/'scripts/saved_performance_report.cjs'
        text = script.read_text().removeprefix('#!/usr/bin/env node\n')
        script.write_text("if(process.env.RACE_AI_STATE_KEY||process.env.GH_TOKEN)process.exit(9);\n" + text)
        code, result, error = self.run_comparison()
        self.assertEqual(code, 0, error)
        self.output.unlink()
        result['descriptive']['accuracy_improvement_proven'] = True
        script.write_text('process.stdout.write(' + json.dumps(json.dumps(result['descriptive'])) + ');')
        code, result, _ = self.run_comparison()
        self.assertEqual(code, 2)
        self.assertEqual(result.get('reason'), 'PROSPECTIVE_AUDIT_NODE_AGGREGATE_INVALID')
        self.assertFalse(self.output.exists())


if __name__ == '__main__': unittest.main()
