"""Real AES in-memory Git and fictional official layout, no real private keys."""
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch
from race_ai import retained_model_pdca_audit as A,saved_view_feed as F
from tests.test_racer_result_bridge import saved_view
from tests.test_boat_sp_settlement import document,no_contest_document
from tests.intraday_fixture import packet
from tests.test_racer_daily import NOW


class HistoricalModelPdcaAudit(unittest.TestCase):
    def view(self):return saved_view()
    def capture(self,view,*,doc=None,captured=None):
        at=captured or NOW+timedelta(minutes=2)
        raw,receipt=packet(doc or document(),captured=at.isoformat())
        return F.update_view(view,[],captures=[(raw,receipt)],synced_at=at.isoformat())

    def test_unsettled_forecast_never_counts_as_miss_or_spends_money(self):
        v=self.view();saved=deepcopy(v)
        result=A.score_view(v,authenticated=True);g=result['model_groups'][0]
        self.assertEqual((g['forecasts'],g['eligible'],g['pending'],g['misses'],g['stake_yen']),(1,0,1,0,0))
        self.assertEqual(v,saved)

    def test_real_original_raw_sha_result_pair_yields_exact_hit_and_payout(self):
        v=self.capture(self.view());g=A.score_view(v,authenticated=True)['model_groups'][0]
        self.assertEqual(g['forecasts'],1)
        self.assertEqual(g['eligible'],1)
        self.assertEqual((g['hits'],g['misses'],g['hit_rate']),(1,0,1.0))
        self.assertEqual(g['stake_yen'],800)
        self.assertEqual(g['returned_yen'],1250)
        self.assertEqual(g['net_yen'],450)
        self.assertEqual(g['roi'],1250/800)
        self.assertFalse(g['actual_purchases'])

    def test_authenticated_view_calls_the_existing_bulk_scoring_engine(self):
        from race_ai import verified_bulk_backtest as B
        view=self.capture(self.view())
        with patch.object(B,'settle',wraps=B.settle) as existing:
            g=A.score_view(view,authenticated=True)['model_groups'][0]
        existing.assert_called_once()
        self.assertEqual((g['eligible'],g['hits'],g['stake_yen'],g['returned_yen'],g['net_yen']),
                         (1,1,800,1250,450))

    def test_unknown_or_reference_only_result_does_not_call_existing_scorer(self):
        from race_ai import verified_bulk_backtest as B
        view=self.capture(self.view())
        view['records'][0]['result']['cutoff_reconciliation']={'formal_eligible':False}
        with patch.object(B,'settle',side_effect=AssertionError('formal score forbidden')) as existing:
            g=A.score_view(view,authenticated=True)['model_groups'][0]
        existing.assert_not_called()
        self.assertEqual((g['eligible'],g['held'],g['stake_yen']),(0,1,0))

    def test_existing_bulk_engine_handles_multiwinning_official_trifecta(self):
        from race_ai import verified_bulk_backtest as B
        view=self.view()
        document_with_two_winners=document()
        d=document_with_two_winners['maindata']
        d['teiinfolist'][1]['chk']='1'
        d['teiinfolist'][2]['chk']='3'
        d['infolist3t']=[
            dict(winno='1-2-3',dividend='1250円'),
            dict(winno='2-1-3',dividend='1500円')]
        view=self.capture(view,doc=document_with_two_winners)
        with patch.object(B,'settle',wraps=B.settle) as existing:
            result=A.score_view(view,authenticated=True)
        existing.assert_called_once()
        g=result['model_groups'][0]
        self.assertEqual(g['eligible'],1)
        self.assertEqual(g['hits']+g['misses'],1)
        self.assertEqual(g['net_yen'],g['returned_yen']-g['stake_yen'])

    def test_full_refund_of_every_saved_ticket_is_not_a_miss(self):
        v=self.view()
        v['records'][0]['prediction']['ordered_top8']=[
            [6,1,2],[6,1,3],[6,2,1]]
        d=document()
        d['maindata']['teiinfolist'][-1]['chk']='欠'
        d['maindata']['stinfolist'][0].update(csdisp='0',st='')
        d['maindata']['returnlist']=['6']
        v=self.capture(v,doc=d)
        from race_ai import verified_bulk_backtest as B
        with patch.object(B,'settle',wraps=B.settle) as existing:
            g=A.score_view(v,authenticated=True)['model_groups'][0]
        existing.assert_called_once()
        self.assertEqual((g['void'],g['eligible'],g['hits'],g['misses']),
                         (1,0,0,0))
        self.assertEqual((g['stake_yen'],g['returned_yen'],g['refund_yen'],g['net_yen']),
                         (300,300,300,0))

    def test_forecast_excluding_first_place_has_safely_classified_miss(self):
        v=self.view();v['records'][0]['prediction']['ordered_top8']=[[2,1,3],[2,3,1],[3,1,2],[3,2,1],[4,1,2]]
        v=self.capture(v);g=A.score_view(v,authenticated=True)['model_groups'][0]
        self.assertEqual((g['eligible'],g['hits'],g['misses']),(1,0,1))
        self.assertEqual(g['miss_reasons'],{'FIRST_PLACE_NOT_SELECTED':1})
        self.assertEqual(g['net_yen'],-500)

    def test_cancelled_refunds_money_but_not_hit_rate_denominator(self):
        v=self.capture(self.view(),doc=no_contest_document());g=A.score_view(v,authenticated=True)['model_groups'][0]
        self.assertEqual((g['void'],g['eligible'],g['hits'],g['misses']),(1,0,0,0))
        self.assertEqual((g['stake_yen'],g['returned_yen'],g['refund_yen'],g['net_yen']),(800,800,800,0))
        self.assertIsNone(g['hit_rate'])

    def test_latest_reference_only_result_is_unscored_and_no_money(self):
        v=self.capture(self.view());r=v['records'][0]['result']
        r['cutoff_reconciliation']={'formal_eligible':False,'basis':'REFERENCE_ONLY'}
        g=A.score_view(v,authenticated=True)['model_groups'][0]
        self.assertEqual((g['held'],g['eligible'],g['stake_yen']),(1,0,0))

    def test_legacy_cutoff_reference_never_counts_as_formal_hit(self):
        view=self.capture(self.view())
        result=view['records'][0]['result']
        result['cutoff_reference']={'formal_eligible':False,
            'basis':'RAW_OFFICIAL_PAGE_SAME_ROSTER_SAVED_BEFORE_BOTH'}
        score=A.score_view(view,authenticated=True,include_private_due=True)
        item=score['model_groups'][0]
        self.assertEqual((item['held'],item['eligible'],item['hits'],item['stake_yen']),(1,0,0,0))
        self.assertEqual(score['_private_due_race_ids'],[view['records'][0]['race_id']])

    def test_latest_source_mismatch_is_held_with_zero_scorable_stake(self):
        v=self.capture(self.view());v['records'][0]['result']['source_sha256']='f'*64
        g=A.score_view(v,authenticated=True)['model_groups'][0]
        self.assertEqual((g['held'],g['eligible'],g['stake_yen']),(1,0,0))
        self.assertEqual(g['unresolved_reasons'],{'HOLD_SOURCE_RECEIPT_UNVERIFIED':1})

    def test_prediction_saved_after_cutoff_does_not_inflate_hit_rate(self):
        v=self.view();v['records'][0]['prediction']['persisted_at']='2026-11-07T10:01:00+09:00'
        v=self.capture(v);g=A.score_view(v,authenticated=True)['model_groups'][0]
        self.assertEqual((g['held'],g['eligible'],g['hits'],g['stake_yen']),(1,0,0,0))

    def test_historical_git_result_bridge_to_model_pdca_on_prior_day(self):
        from tests.test_racer_result_bridge import BridgeTests
        from race_ai.racer_intraday import IntradayState
        fixture=BridgeTests('test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical')
        fixture.setUp()
        try:
            fixture.view=saved_view(('2026-11-04','2026-11-07','2026-11-08'))
            fixture.seed(fixture.view)
            at=NOW+timedelta(days=1)
            state=IntradayState()
            from race_ai.racer_result_bridge import SavedResultBridge
            first=SavedResultBridge(fixture.repo,now=at,transport=fixture.git,bootstrap=fixture.boot)
            first.prepare(state)
            self.assertEqual(first.backfill_day,'2026-11-04')
            first.publish(state,now=at)
            fixture.capture(state,day='20261104',at=at)
            new=SavedResultBridge(fixture.repo,now=at+timedelta(minutes=5),transport=fixture.git,bootstrap=fixture.boot)
            new.prepare(state)
            new.publish(state,now=at+timedelta(minutes=5))
            _,_,_,v=F.current_view(fixture.git,fixture.boot)
            old=dict(v,records=[r for r in v['records'] if r['event_date_jst']=='2026-11-04'])
            summary=A.score_view(old,authenticated=True)
            self.assertEqual((summary['total_forecasts'],summary['total_scored']), (1,1))
            self.assertEqual(summary['model_groups'][0]['hits'],1)
            self.assertEqual(summary['model_groups'][0]['net_yen'],450)
            # Immutable source is saved before independent feed publication.
            # The next control/save cycle acknowledges the new final projection.
            third=SavedResultBridge(fixture.repo,now=at+timedelta(minutes=10),transport=fixture.git,bootstrap=fixture.boot)
            third.prepare(state)
            self.assertNotIn('2026-11-04',state.control['result_due_ledger']['pending_days'])
        finally:
            fixture.doCleanups()

    def test_model_hold_stays_backlogged_even_when_official_result_is_final(self):
        from tests.test_racer_result_bridge import BridgeTests
        from race_ai.racer_intraday import IntradayState
        from race_ai.racer_result_bridge import SavedResultBridge
        fixture=BridgeTests('test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical')
        fixture.setUp()
        try:
            finalized=self.capture(fixture.view)
            finalized['records'][0]['prediction']['persisted_at']='2026-11-07T10:01:00+09:00'
            fixture.seed(finalized)
            state=IntradayState()
            bridge=SavedResultBridge(fixture.repo,now=NOW+timedelta(minutes=3),transport=fixture.git,bootstrap=fixture.boot)
            bridge.prepare(state)
            self.assertEqual(bridge.ledger_summary['model_pdca_formal_holds'],1)
            self.assertEqual(bridge.ledger_summary['pending'],1)
            self.assertEqual(state.control['result_due_ledger']['pending_days']['2026-11-07']['u'],'1')
            self.assertEqual(bridge.targets()[0]['pending'],False,'a valid final must never trigger unnecessary refetch')
            report=state.control['model_pdca_recent_audit']['days'][0]['summary']
            self.assertEqual(report['model_groups'][0]['held'],1)
            self.assertEqual(report['model_groups'][0]['hits'],0)
            self.assertEqual(report['model_groups'][0]['stake_yen'],0)
            self.assertNotIn('_private_due_race_ids',str(report))
            self.assertEqual(F.current_view(fixture.git,fixture.boot)[3]['records'][0]['result']['status'],'final')
            bridge.publish(state,now=NOW+timedelta(minutes=3))
            self.assertEqual(F.current_view(fixture.git,fixture.boot)[3]['records'][0]['prediction'],finalized['records'][0]['prediction'])
        finally:
            fixture.doCleanups()

    def test_private_model_pdca_snapshot_survives_encrypted_git_state_restart(self):
        from tests.test_racer_result_bridge import BridgeTests
        from tests.test_racer_intraday_handoff import FixtureGit
        from race_ai.racer_result_bridge import SavedResultBridge
        from race_ai.racer_intraday_handoff import load_intraday,save_intraday
        from race_ai.boat_pdca_github_handoff import TRANSFER_REF
        fixture=BridgeTests('test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical')
        fixture.setUp()
        try:
            final=self.capture(fixture.view)
            fixture.seed(final)
            raw_remote=FixtureGit(fixture.repo,ref=TRANSFER_REF)
            root_sha=raw_remote.commit({'state/other-original.enc':b'UNMODIFIED'},None)
            raw_remote.push(root_sha,None)
            key=bytes(range(32));at=NOW+timedelta(minutes=3)
            loaded=load_intraday(fixture.repo,initialize=True,key=key,transport=raw_remote,now=at)
            bridge=SavedResultBridge(fixture.repo,now=at,transport=fixture.git,bootstrap=fixture.boot)
            bridge.prepare(loaded['state'])
            snapshot=loaded['state'].control['model_pdca_recent_audit']
            self.assertEqual(snapshot['schema'],'RACE_AI_PRIVATE_MODEL_PDCA_SNAPSHOT_V1')
            self.assertEqual(snapshot['days'][0]['summary']['total_scored'],1)
            self.assertEqual(snapshot['days'][0]['summary']['model_groups'][0]['net_yen'],450)
            original_view=F.current_view(fixture.git,fixture.boot)[3]
            out=save_intraday(loaded,catalogue_sha256='a'*64,now=at,key=key)
            ciphertext=raw_remote.read(out['source_commit'],out['cipher_path'],16*1024*1024)
            self.assertNotIn(b'INVENTED_TEST_ONLY',ciphertext)
            fresh=load_intraday(fixture.repo,key=key,transport=raw_remote,now=at+timedelta(minutes=1))
            self.assertEqual(fresh['state'].control['model_pdca_recent_audit'],snapshot)
            self.assertEqual(F.current_view(fixture.git,fixture.boot)[3],original_view)
            self.assertEqual(raw_remote.read(out['source_commit'],'state/other-original.enc',100),b'UNMODIFIED')
        finally:
            fixture.doCleanups()

    def test_synthetic_dataset_or_unverified_scope_cannot_create_formal_hit(self):
        view=self.capture(self.view())
        view['dataset_status']='SYNTHETIC_ONLY'
        with self.assertRaisesRegex(ValueError,'RETAINED_MODEL_PDCA_REAL_DATASET_REQUIRED'):
            A.score_view(view,authenticated=True)
        view['dataset_status']='REAL_REPORTED'
        view['records'][0]['scope']='synthetic'
        with self.assertRaisesRegex(ValueError,'RETAINED_MODEL_PDCA_REAL_RACE_SCOPE_REQUIRED'):
            A.score_view(view,authenticated=True)

    def test_authentication_is_mandatory_before_scoring(self):
        with self.assertRaisesRegex(ValueError,'RETAINED_MODEL_PDCA_AUTHENTICATED_INPUT_REQUIRED'):
            A.score_view(self.view(),authenticated=False)

    def test_independent_replay_no_result_mutation_or_duplicate_model_count(self):
        v=self.capture(self.view());v['records'][0]['comparison_predictions']=[deepcopy(v['records'][0]['prediction'])]
        saved=deepcopy(v)
        first=A.score_view(v,authenticated=True)
        second=A.score_view(v,authenticated=True)
        self.assertEqual(first,second)
        self.assertEqual(first['total_forecasts'],1)
        self.assertEqual(v,saved)


if __name__=='__main__':unittest.main()
