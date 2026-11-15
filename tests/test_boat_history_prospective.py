"""Invented forecasts/results/GitHub responses; never live PDCA evidence."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.boat_history_comparison import prepare_pair,freeze_pair
from race_ai.boat_history_store import HistoryStore,instant
from race_ai.github_freeze_receipt import BASE,ANCHOR_SCHEMA
from tests.test_boat_history_store import archives,DAY
from tests.test_boat_history_comparison import current,NOW
from tests.test_boat_pdca_state import result


class ProspectiveHistoryTests(unittest.TestCase):
    def test_merge_uses_newer_admitted_version_even_when_older_head_is_preserved(self):
        from race_ai.boat_pdca_state import PdcaState
        from race_ai.boat_history_store import wire
        from race_ai.boat_history_prospective import verify_retained_trials
        a=PdcaState.create(self.root/'older.sqlite',mode='production');b=PdcaState.create(self.root/'newer.sqlite',mode='production')
        name='prospective-admissions/'+self.pair['pair_sha256']+'.json'
        newer=result(self.pair);newer['captured_at']='2026-11-06T11:20:00+09:00';newer['source_sha256']='e'*64
        newer['data']['payouts'][0]['payout_per_100_yen']=1500
        for state,obs in ((a,result(self.pair)),(b,newer)):
            state.retain_pair(self.path);state.score(self.pair['pair_sha256'],obs,'2026-11-06T12:00:00+09:00')
            with state.db:state._put(name,wire(self.admit(obs)).encode())
        a.merge_from(b);b.close();a.materialize(self.root/'union')
        out=verify_retained_trials(a,self.root/'union','2026-11-06T12:00:00+09:00')
        self.assertEqual(out['admitted_summary']['result_revisions'],2)
        self.assertEqual(out['admitted_summary']['unique_races'],1)
        self.assertEqual(out['admitted_summary']['models'][0]['baseline_received_yen'],1500)
        later=result(self.pair);later['captured_at']='2026-11-06T11:30:00+09:00';later['source_sha256']='d'*64
        a.score(self.pair['pair_sha256'],later,'2026-11-06T12:00:00+09:00')
        with self.assertRaises(ValueError):verify_retained_trials(a,self.root/'union','2026-11-06T12:00:00+09:00')
        a.close()

    def test_owner_retained_admission_replays_result_binding_without_network(self):
        from race_ai.boat_pdca_state import PdcaState
        from race_ai.boat_history_store import wire
        from race_ai.boat_history_prospective import verify_retained_trials
        state=PdcaState.create(self.root/'journal.sqlite',mode='production');state.retain_pair(self.path)
        state.score(self.pair['pair_sha256'],result(self.pair),'2026-11-06T12:00:00+09:00')
        report=self.admit();name='prospective-admissions/'+self.pair['pair_sha256']+'.json'
        with state.db:state._put(name,wire(report).encode())
        state.materialize(self.root/'materialized')
        out=verify_retained_trials(state,self.root/'materialized','2026-11-06T12:00:00+09:00')
        self.assertEqual(out['admitted_prospective_races'],1);self.assertFalse(out['external_receipts_rechecked_live'])
        from race_ai.actions_contract import digest
        report['models'][0]['baseline_received_yen']+=1;report.pop('report_sha256');report['report_sha256']=digest(report)
        with state.db:state._put(name,wire(report).encode())
        with self.assertRaises(ValueError):verify_retained_trials(state,self.root/'materialized','2026-11-06T12:00:00+09:00')
        state.close()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);store=HistoryStore(self.root/'history.sqlite')
        raw,proof=archives();store.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
        self.pair=prepare_pair(current(),store,NOW);store.close()
        self.path=self.root/'pair.json';freeze_pair(self.pair,self.path,clock=lambda:instant(NOW))
        self.receipt={'run_id':9001,'path':'audit/freezes/2026-11-06/fictional-history.json'}
        self.run={'id':9001,'event':'push','repository':{'full_name':'haji84/RACE-AI'},'head_sha':'a'*40,'created_at':'2026-11-05T16:31:00Z'}
        self.anchor={'schema':ANCHOR_SCHEMA,'race_id':self.pair['race_id'],'prediction_sha256':self.pair['pair_sha256'],'cutoff_at':self.pair['cutoff_at']}

    def fetch(self,url):
        if url==BASE+'/actions/runs/9001':return self.run
        if url.endswith('?ref='+'a'*40):return {'type':'file','encoding':'base64','content':base64.b64encode(json.dumps(self.anchor).encode()).decode()}
        raise AssertionError('unexpected endpoint')

    def admit(self,observation=None):
        from race_ai.boat_history_prospective import admit_pair_result
        return admit_pair_result(self.path,observation or result(self.pair),self.receipt,'2026-11-06T12:00:00+09:00',_fetch=self.fetch)

    def test_external_witness_admits_one_race_and_replay_does_not_multiply_stakes(self):
        from race_ai.boat_history_prospective import summarize_trials
        original=self.path.read_bytes();report=self.admit()
        self.assertTrue(report['prospective_metric_eligible'])
        self.assertTrue(report['independent_pre_cutoff_receipt_verified'])
        self.assertEqual(self.path.read_bytes(),original)
        self.assertFalse(self.pair['independent_pre_cutoff_receipt_verified'])
        summary=summarize_trials([report,deepcopy(report)])
        self.assertEqual(summary['unique_races'],1)
        self.assertTrue(all(row['scored']==1 and row['baseline_stake_yen']==800 for row in summary['models']))
        self.assertFalse(summary['accuracy_improvement_proven'])

    def test_late_or_foreign_or_wrong_hash_witness_is_not_admitted(self):
        original_run=deepcopy(self.run);original_anchor=deepcopy(self.anchor)
        for mutate in (lambda:self.run.update(created_at='2026-11-06T03:00:00Z'),
                       lambda:self.run.update(repository={'full_name':'foreign/repo'}),
                       lambda:self.anchor.update(prediction_sha256='f'*64)):
            self.run=deepcopy(original_run);self.anchor=deepcopy(original_anchor);mutate()
            with self.assertRaises(ValueError):self.admit()

    def test_special_result_is_preserved_and_excluded_from_normal_metrics(self):
        obs=result(self.pair);obs['data']['refund_boats']=[1]
        report=self.admit(obs)
        self.assertTrue(report['independent_pre_cutoff_receipt_verified'])
        self.assertFalse(report['prospective_metric_eligible'])

    def test_latest_result_revision_counts_once_and_equal_clock_conflict_stops(self):
        from race_ai.boat_history_prospective import summarize_trials
        a=self.admit();obs=result(self.pair);obs['source_sha256']='e'*64;obs['captured_at']='2026-11-06T11:20:00+09:00'
        obs['data']['payouts'][0]['payout_per_100_yen']=1500;b=self.admit(obs)
        summary=summarize_trials([a,b,b]);self.assertEqual(summary['unique_races'],1)
        self.assertTrue(all(row['baseline_received_yen']==1500 for row in summary['models']))
        obs['captured_at']=a['result_captured_at'];conflict=self.admit(obs)
        with self.assertRaises(ValueError):summarize_trials([a,conflict])
