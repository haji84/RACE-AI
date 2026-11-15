"""No network, synthetic in-memory Git fixture with real AES round-trip."""
import copy
import unittest
from datetime import timedelta
from race_ai import model_pdca_history as H, retained_model_pdca_audit as P, saved_view_feed as F
from race_ai.racer_intraday import IntradayState
from race_ai.racer_result_bridge import SavedResultBridge
from tests.test_racer_result_bridge import BridgeTests,saved_view
from tests.test_retained_model_pdca_audit import HistoricalModelPdcaAudit
from tests.test_racer_daily import NOW

class PersistentHistoryTests(unittest.TestCase):
    def test_all_days_remain_scored_and_double_run_does_not_double_count(self):
        control={}
        for day in ('2017-01-01','2026-11-07','2026-11-08'):
            v=saved_view((day,))
            s=P.score_view(v,authenticated=True)
            self.assertTrue(H.record(control,day=day,view=v,summary=s)['changed'])
            self.assertFalse(H.record(control,day=day,view=v,summary=s)['changed'])
        stats=H.latest(control)
        self.assertEqual((stats['days'],stats['revisions'],stats['unscored']),(3,3,3))
        self.assertEqual((stats['model_groups'][0]['forecasts'],stats['model_groups'][0]['pending']),(3,3))
        self.assertFalse(stats['full_history_coverage_verified'])

    def test_official_result_revision_is_append_only_and_counts_latest_once(self):
        control={};v=saved_view()
        day='2026-11-07';summary=P.score_view(v,authenticated=True)
        H.record(control,day=day,view=v,summary=summary)
        a=HistoricalModelPdcaAudit()
        settled=a.capture(v);score=P.score_view(settled,authenticated=True)
        self.assertTrue(H.record(control,day=day,view=settled,summary=score)['changed'])
        self.assertFalse(H.record(control,day=day,view=settled,summary=score)['changed'])
        historic=H._unwrap(control)['days'][day]
        self.assertEqual(len(historic),2)
        self.assertEqual(historic[0]['summary']['total_scored'],0)
        self.assertEqual(historic[-1]['summary']['total_scored'],1)
        stats=H.latest(control)
        self.assertEqual((stats['days'],stats['revisions'],stats['unscored']),(1,2,0))
        self.assertEqual((stats['model_groups'][0]['hits'],stats['model_groups'][0]['net_yen']),(1,450))
        self.assertEqual(H.verify_day(control,day=day,view=settled,summary=score)['status'],'VERIFIED')
        with self.assertRaisesRegex(ValueError,'MODEL_PDCA_HISTORY_LATEST_EVIDENCE_MISMATCH'):
            H.verify_day(control,day=day,view=v,summary=summary)

    def test_encrypted_state_survives_day_rollover_and_feed_replay(self):
        fixture=BridgeTests('test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical')
        fixture.setUp()
        try:
            fixture.seed(saved_view(('2026-11-04','2026-11-07','2026-11-08')))
            at=NOW+timedelta(days=1)
            state=IntradayState()
            b=SavedResultBridge(fixture.repo,now=at,transport=fixture.git,bootstrap=fixture.boot)
            b.prepare(state)
            first=H.latest(state.control)
            self.assertEqual(first['days'],3)
            self.assertEqual(first['revisions'],3)
            b2=SavedResultBridge(fixture.repo,now=at+timedelta(minutes=5),transport=fixture.git,bootstrap=fixture.boot)
            b2.prepare(state)
            self.assertEqual(H.latest(state.control)['revisions'],3)
            fixture.capture(state,day='20261104',at=at)
            b2.publish(state,now=at+timedelta(minutes=5))
            b3=SavedResultBridge(fixture.repo,now=at+timedelta(minutes=10),transport=fixture.git,bootstrap=fixture.boot)
            b3.prepare(state)
            self.assertEqual(H.latest(state.control)['days'],3)
            self.assertEqual(H.latest(state.control)['revisions'],4)
            audit=H.latest(state.control)
            self.assertEqual(audit['model_groups'][0]['hits'],1)
            self.assertEqual(audit['model_groups'][0]['pending'],2)
        finally:fixture.doCleanups()

    def test_invalid_cipher_index_never_silently_resets_old_history(self):
        v=saved_view();s=P.score_view(v,authenticated=True);state={}
        H.record(state,day='2026-11-07',view=v,summary=s)
        before=copy.deepcopy(state)
        state['model_pdca_all_days']['raw_sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'MODEL_PDCA_HISTORY_RAW_SHA_MISMATCH'):
            H.record(state,day='2026-11-07',view=v,summary=s)
        self.assertEqual(state['model_pdca_all_days']['days'],before['model_pdca_all_days']['days'])

if __name__=='__main__':unittest.main()
