"""Independent AES/Git tests using fictional pre-cutoff races only."""
import unittest
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
        self.assertEqual(report['source_provider_requests'],0)
        self.assertGreaterEqual(report['archived_days'],1)
        self.assertGreaterEqual(report['independent_day_readbacks'],1)

    def test_one_real_day_proves_one_day_even_if_another_remains_hold(self):
        state,bridge,now=self.setUpFixture()
        state.control['model_pdca_recent_audit']['days'].append(dict(
            day='2017-01-01',status='HOLD_MODEL_PDCA_INPUT',total_forecasts=None,total_scored=None))
        report=verify_snapshot(state,bridge,now=now)
        self.assertEqual(report['held_days'],1)
        self.assertGreater(report['formally_scored_forecasts'],0)
        self.assertFalse(report['all_history_completion_proven'])

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
