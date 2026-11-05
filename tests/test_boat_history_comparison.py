from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tests.test_boat_observed_pairwise_models import fixture,absent
from tests.test_boat_history_store import archives,DAY
from race_ai.boat_history_store import HistoryStore

NOW='2026-11-06T01:30:00+09:00'


def current():
    snapshot=fixture(research=True)
    snapshot.update(race_id='boat:2026-11-06:boatrace-jcd-17:1',event_date_jst='2026-11-06',venue='boatrace-jcd-17',
        as_of='2026-11-06T01:10:00+09:00',sales_cutoff_at='2026-11-06T10:59:00+09:00')
    snapshot['sources'][0].update(published_at=None,captured_at='2026-11-06T01:00:00+09:00',evidence_basis='CAPTURED_BY_CLAIM')
    for lane in range(1,7):
        for name in ('recent_mean_finish','recent_mean_st','course_mean_finish','course_mean_st'):
            absent(snapshot,lane,name,'NO_PRIOR_SAMPLES')
    return snapshot


class HistoryComparisonTests(unittest.TestCase):
    def setUp(self):
        try:from race_ai import boat_history_comparison as comparison
        except ImportError:comparison=None
        self.assertIsNotNone(comparison,'prospective history pair preparation is missing')
        self.c=comparison;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=HistoryStore(Path(self.tmp.name)/'history.sqlite');self.addCleanup(self.store.close)
        raw,proof=archives();self.store.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])

    def pair(self):return self.c.prepare_pair(current(),self.store,NOW)

    def test_equal_current_inputs_asof_and_existing_models_with_only_recent_history_added(self):
        snap=current();original=deepcopy(snap)
        pair=self.c.prepare_pair(snap,self.store,NOW)
        a=pair['baseline']['snapshot'];b=pair['history']['snapshot']
        self.assertEqual(a['as_of'],b['as_of']);self.assertEqual(a['as_of'],'2026-11-05T16:30:00+00:00')
        self.assertEqual(snap,original)
        self.assertNotIn('recent_mean_finish',a['participants'][0]['features'])
        self.assertEqual(b['participants'][0]['features']['recent_mean_finish']['value'],7/3)
        self.assertEqual(b['participants'][0]['features']['recent_mean_finish']['sample_n'],3)
        self.assertNotIn('course_mean_finish',b['participants'][0]['features'])
        for left,right in zip(a['participants'],b['participants']):
            self.assertEqual(left['features']['national_win_rate'],right['features']['national_win_rate'])
        self.assertEqual(set(pair['baseline']['suite']['models']),set(pair['history']['suite']['models']))
        self.assertTrue(all(len(m['ordered_top8'])==8 for v in ('baseline','history') for m in pair[v]['suite']['models'].values()))
        self.assertFalse(pair['independent_pre_cutoff_receipt_verified'])

    def test_newly_captured_history_cannot_repair_an_old_forecast(self):
        snap=current();snap['as_of']='2026-11-04T10:00:00+09:00';snap['sales_cutoff_at']='2026-11-04T11:00:00+09:00'
        with self.assertRaises(ValueError):self.c.prepare_pair(snap,self.store,NOW)
        early=current();early['as_of']='2026-11-05T17:00:00+09:00'
        early['sources'][0]['captured_at']='2026-11-05T16:00:00+09:00'
        pair=self.c.prepare_pair(early,self.store,'2026-11-05T08:30:00+00:00')
        self.assertEqual(pair['history_coverage']['participants_with_recent_finish'],0)

    def test_tampering_cannot_change_tickets_after_pair_preparation(self):
        pair=self.pair();pair['history']['suite']['models'][next(iter(pair['history']['suite']['models']))]['ordered_top8'][0]=[1,2,3]
        with self.assertRaises(ValueError):self.c.verify_pair(pair)

    def test_private_frozen_pair_is_create_only_and_read_back_is_verified(self):
        pair=self.pair();p=Path(self.tmp.name)/'pair.json'
        self.c.freeze_pair(pair,p)
        self.assertEqual(self.c.load_pair(p),pair)
        other=self.c.prepare_pair(current(),self.store,'2026-11-06T01:31:00+09:00')
        with self.assertRaises(ValueError):self.c.freeze_pair(other,p)

    def test_resealed_omitted_history_window_cannot_support_existing_features(self):
        from race_ai.actions_contract import digest
        pair=self.pair();pair['history_evidence']['windows']['4001']=[]
        pair['pair_sha256']=digest({k:v for k,v in pair.items() if k!='pair_sha256'})
        with self.assertRaises(ValueError):self.c.verify_pair(pair)

    def test_one_shared_later_result_scores_both_without_promotion(self):
        pair=self.pair()
        obs=dict(race_id='20261106-17-01',body_identity_verified=True,status='AVAILABLE',
            closed_at='2026-11-06T10:59:00+09:00',captured_at='2026-11-06T11:10:00+09:00',source_sha256='f'*64,
            data=dict(status='settled',confirmed=True,finish_confirmed=True,refund_boats=[],top3=[6,5,4],
                results=[dict(lane=i,racer_registration_id=str(4000+i),finish_status='FINISHED',finish=7-i) for i in range(1,7)],
                payouts=[dict(bet_type='trifecta',combination=[6,5,4],payout_per_100_yen=1200)]))
        out=self.c.score_pair(pair,obs,'2026-11-06T12:00:00+09:00')
        self.assertEqual(len(out['models']),2)
        self.assertTrue(all(r['baseline_hit'] is True for r in out['models']))
        self.assertTrue(all(r['stake_yen_per_variant']==800 for r in out['models']))
        self.assertFalse(out['accuracy_improvement_proven'])
        self.assertFalse(out['auto_promoted'])
        obs['captured_at']='2026-11-06T10:00:00+09:00'
        with self.assertRaises(ValueError):self.c.score_pair(pair,obs,'2026-11-06T12:00:00+09:00')
