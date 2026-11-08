"""Independent AES/Git tests using fictional pre-cutoff races only."""
import unittest
import os,json,io
from unittest.mock import patch
from contextlib import redirect_stdout
from datetime import timedelta
from race_ai.racer_intraday import IntradayState
from race_ai.racer_result_bridge import SavedResultBridge
from scripts.verify_all_history_pdca_readback import verify_snapshot
from tests.test_racer_result_bridge import BridgeTests,saved_view
from tests.test_racer_daily import NOW
from tests.test_retained_model_pdca_audit import HistoricalModelPdcaAudit

class IndependentReadbackTests(unittest.TestCase):
    def setUpFixture(self):
        fixture=BridgeTests('test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        v=HistoricalModelPdcaAudit().capture(saved_view(('2026-11-04','2026-11-07','2026-11-08')))
        fixture.seed(v)
        state=IntradayState();now=NOW+timedelta(days=1)
        bridge=SavedResultBridge(fixture.repo,now=now,transport=fixture.git,bootstrap=fixture.boot)
        bridge.prepare(state)
        return state,bridge,now

    def test_actual_aes_fictional_historical_snapshot_recomputes(self):
        state,bridge,now=self.setUpFixture()
        report=verify_snapshot(state,bridge,now=now)
        self.assertEqual(report['status'],'AES_AUTHENTICATED_HISTORICAL_PDCA_READBACK_VERIFIED')
        self.assertGreaterEqual(report['historical_days_with_formal_scores'],1)
        self.assertFalse(report['all_history_completion_proven'])
        self.assertEqual(report['full_period_saved_days'],len(bridge.available_days))
        self.assertEqual(report['full_period_missing_pdca_days'],0)
        self.assertEqual(report['full_period_orphan_pdca_days'],0)
        self.assertTrue(report['full_period_readback_coverage_proven'])
        self.assertEqual(report['source_provider_requests'],0)
        self.assertGreaterEqual(report['archived_days'],1)
        self.assertGreaterEqual(report['independent_day_readbacks'],1)
        self.assertTrue(report['pdca_day_counts'])
        self.assertIsInstance(report['pdca_focus_groups'],list)
        self.assertEqual(report['pdca_payout_threshold_yen_per_100'],10000)
        for group in report['pdca_focus_groups']:
            self.assertEqual(sum(group['first_candidate_rank_by_top8_order'].values()),group['eligible'])
            self.assertEqual(sum(group['actual_winning_combo_rank_in_top8'].values()),group['eligible'])
            self.assertEqual(group['high_payout_official_cases'],group['high_payout_captured']+group['high_payout_missed'])

    def test_one_real_day_proves_one_day_even_if_another_remains_hold(self):
        state,bridge,now=self.setUpFixture()
        state.control['model_pdca_recent_audit']['days'].append(dict(
            day='2017-01-01',status='HOLD_MODEL_PDCA_INPUT',total_forecasts=None,total_scored=None))
        report=verify_snapshot(state,bridge,now=now)
        self.assertEqual(report['held_days'],1)
        self.assertGreater(report['formally_scored_forecasts'],0)
        self.assertFalse(report['all_history_completion_proven'])

    def test_full_period_gap_does_not_disappear_from_authenticated_readback(self):
        state,bridge,now=self.setUpFixture()
        bridge.available_days=list(bridge.available_days)+['2017-01-01']
        report=verify_snapshot(state,bridge,now=now)
        self.assertEqual(report['full_period_missing_pdca_days'],1)
        self.assertFalse(report['full_period_readback_coverage_proven'])
        self.assertFalse(report['all_history_completion_proven'])
        self.assertEqual(report['source_provider_requests'],0)

    def test_reject_modified_model_return_amount(self):
        state,bridge,now=self.setUpFixture()
        state.control['model_pdca_recent_audit']['days'][0]['summary']['model_groups'][0]['net_yen']+=1
        with self.assertRaisesRegex(ValueError,'ALL_HISTORY_PDCA_MODEL_PDCA_SNAPSHOT_MISMATCH'):
            verify_snapshot(state,bridge,now=now)

    def test_reject_absent_aes_snapshot_and_due_ledger(self):
        state,bridge,now=self.setUpFixture()
        state.control.pop('model_pdca_recent_audit')
        with self.assertRaisesRegex(ValueError,'ALL_HISTORY_PDCA_SNAPSHOT_ABSENT'):
            verify_snapshot(state,bridge,now=now)
        state,bridge,now=self.setUpFixture()
        state.control.pop('result_due_ledger')
        with self.assertRaisesRegex(ValueError,'ALL_HISTORY_PDCA_PERSISTENT_DUE_LEDGER_MISSING'):
            verify_snapshot(state,bridge,now=now)

    def test_zero_historical_real_score_is_hold_not_success(self):
        state,bridge,now=self.setUpFixture()
        state.control['model_pdca_recent_audit']['days'][0]['summary']['total_scored']=0
        with self.assertRaisesRegex(ValueError,'ALL_HISTORY_PDCA_MODEL_PDCA_SNAPSHOT_MISMATCH'):
            verify_snapshot(state,bridge,now=now)


class ActualReadbackAuthenticationGuardTests(unittest.TestCase):
    def test_main_applies_owner_stage_header_isolation_before_any_git_read(self):
        from scripts.verify_all_history_pdca_readback import main
        output=io.StringIO()
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'haji84/RACE-AI',
                                     'RACE_AI_STATE_KEY':'test-only-nonproduction'},clear=True):
            with patch('scripts.racer_intraday_refresh._stage_git_header_scope',
                       side_effect=ValueError('MODEL_PDCA_CHECKOUT_HEADER_CONFLICT')) as guard:
                with redirect_stdout(output):
                    self.assertEqual(main([]),2)
        guard.assert_called_once_with()
        report=json.loads(output.getvalue())
        self.assertEqual(report['status'],'HOLD')
        self.assertEqual(report['source_provider_requests'],0)
        self.assertNotIn('test-only-nonproduction',output.getvalue())
        self.assertIn('code_trace',report)
