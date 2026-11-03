import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from race_ai.verified_bulk_backtest import BadRecord, choose_results, settle, summarize, safe_triple, run, diagnose_cohort, diagnosis_stage


def forecast(picks, race='ボート:2026-11-03:徳山:1'):
    return dict(race_id=race, forecast_id='a', model_id='test', picks=picks, edition='A',
                frozen_at='2026-11-03T09:00:00+09:00',cutoff_at='2026-11-03T09:10:00+09:00')


def result(payouts, refunded=None, status='SETTLED'):
    return dict(race_id='ボート:2026-11-03:徳山:1', status=status, payouts=payouts,
                refunded_numbers=refunded or [],source_grade='third_party_observed',source_url='https://example.com/result',revision=1)


class MassAuditTests(unittest.TestCase):
    def test_hit_rank_and_roi(self):
        r=settle(forecast(['1-2-3','1-3-2']),result({'1-3-2':1020}))
        self.assertEqual((r['status'],r['hit_rank'],r['gross_yen'],r['received_yen']),('HIT',2,200,1020))
    def test_partial_refund_not_automatic_full_refund(self):
        r=settle(forecast(['1-2-3','4-2-1']),result({'4-2-1':1200},[3]))
        self.assertEqual((r['status'],r['hit_rank'],r['refund_yen'],r['received_yen']),('HIT_PLUS_REFUND',2,100,1300))
    def test_full_refund_not_miss(self):
        r=settle(forecast(['1-2-3','1-3-4']),result({'5-4-6':3300},[1]))
        self.assertEqual((r['status'],r['refund_yen'],r['hit_rank']),('FULL_REFUND',200,None))
        self.assertEqual(summarize([r])['total']['valid_accuracy'],0)
    def test_cancellation(self):
        r=settle(forecast(['1-2-3','1-3-4']),result({},status='CANCELLED'))
        self.assertEqual((r['status'],r['received_yen']),('FULL_REFUND',200))
    def test_unverified_never_scored_as_loss(self):
        r=settle(forecast(['1-2-3']),None)
        self.assertEqual((r['status'],r['received_yen']),('RESULT_UNVERIFIED',None))
    def test_tie_multiple_winning_combinations(self):
        r=settle(forecast(['1-2-3','1-3-2']),result({'1-2-3':500,'1-3-2':750}))
        self.assertEqual((r['status'],r['win_yen'],r['hit_rank']),('HIT',1250,1))
    def test_same_revision_conflict_quarantine(self):
        a=result({'1-2-3':500});b=result({'1-3-2':750})
        idx=choose_results([a,b]);self.assertEqual(idx[a['race_id']]['status'],'UNVERIFIED')
    def test_duplicate_ticket_blocked(self):
        with self.assertRaises(BadRecord):
            settle(forecast(['1-2-3','1-2-3']),result({'1-2-3':100}))
    def test_invalid_ticket_blocked(self):
        with self.assertRaises(BadRecord):safe_triple('1-1-3')
    def test_evidence_timings_not_formal_without_receipt(self):
        r=settle(forecast(['1-2-3']),result({'1-2-3':100}))
        self.assertEqual(r['freeze_status'],'TIMESTAMP_ONLY')
    def test_12_picks_support(self):
        import itertools
        picks=['-'.join(map(str,k)) for k in list(itertools.permutations(range(1,6),3))[:12]]
        r=settle(forecast(picks),result({picks[11]:100}))
        self.assertEqual((r['hit_rank'],r['gross_yen']),(12,1200))
    def test_claimed_receipt_never_counts_as_independently_verified(self):
        f=forecast(['1-2-3'])
        f.update(freeze_evidence='independently_confirmed',
                 source_sha256='a'*64,receipt_url='https://example.com/receipt')
        r=settle(f,result({'1-2-3':100}))
        self.assertEqual(r['freeze_status'],'EXTERNAL_RECEIPT_CLAIM_UNVERIFIED')
        self.assertEqual(summarize([r])['total']['pre_cutoff_evidence_count'],0)
    def test_end_to_end_jsonl_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);ff=td/'forecasts.jsonl';rr=td/'results.jsonl';schedule=td/'schedule.jsonl'
            ff.write_text(json.dumps(forecast(['1-2-3']))+'\n',encoding='utf-8')
            rr.write_text(json.dumps(result({'1-2-3':900}))+'\n',encoding='utf-8')
            schedule.write_text(json.dumps({'race_id':'ボート:2026-11-03:徳山:1'})+'\n',encoding='utf-8')
            out=td/'out';rep=run(ff,rr,out,schedule)
            self.assertEqual(rep['total']['hit_rate'],1)
            self.assertEqual(rep['coverage']['races_without_forecast'],0)
            self.assertTrue((out/'all_forecasts.csv').is_file())
            with self.assertRaises(BadRecord):run(ff,rr,out,schedule)



class HistoricalPDCADiagnosticsTest(unittest.TestCase):
    def _f(self, picks):
        return {**forecast(picks), 'cohort': 'morning'}

    def test_failed_winner_pair_and_third(self):
        picks=['1-2-3','1-3-2']
        self.assertEqual(diagnosis_stage(picks, '5-2-3'), 'FIRST_NOT_COVERED')
        self.assertEqual(diagnosis_stage(picks, '1-4-3'), 'SECOND_PAIR_NOT_COVERED')
        self.assertEqual(diagnosis_stage(picks, '1-2-5'), 'THIRD_NOT_COVERED')

    def test_missed_high_payout_is_not_zero_payout(self):
        report=diagnose_cohort([self._f(['1-2-3','1-3-2'])], [result({'5-2-3':84690})])
        total=report['total']
        self.assertEqual(total['payout_bands']['10000_PLUS'], {'races':1, 'hits':0})
        self.assertEqual(total['failure_stage_counts']['FIRST_NOT_COVERED'], 1)
        self.assertEqual((total['gross_yen'],total['received_yen']),(200,0))

    def test_full_refund_not_scored_as_failure(self):
        report=diagnose_cohort([self._f(['1-2-3','1-3-2'])], [result({'2-4-1':2000},[1])])
        self.assertEqual(report['total']['scorable'],0)
        self.assertEqual(report['total']['full_refunds'],1)
        self.assertEqual(report['total']['received_yen'],200)

    def test_unknown_result_stays_out_of_denominator(self):
        report=diagnose_cohort([self._f(['1-2-3'])], [])
        self.assertEqual(report['total']['scorable'],0)
        self.assertEqual(report['total']['source_grade_counts']['unverified'],1)

    def test_duplicate_cohort_rejected(self):
        first=self._f(['1-2-3'])
        with self.assertRaises(BadRecord):
            diagnose_cohort([first,{**first,'forecast_id':'different'}], [])

    def test_updated_cohort_does_not_replace_morning(self):
        first=self._f(['1-2-3'])
        later={**first,'cohort':'updated'}
        report=diagnose_cohort([first,later],[result({'1-2-3':500})])
        self.assertEqual(report['total']['forecasts'],1)
        self.assertFalse(report['total']['future_accuracy_gain_proved'])




class BulkPDCAIntegrationTest(unittest.TestCase):
    def test_bulk_run_embeds_nonpromoting_morning_pdca(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ff=root/'forecasts.jsonl'
            rr=root/'results.jsonl'
            f={**forecast(['1-2-3','1-3-2']), 'cohort':'morning'}
            ff.write_text(json.dumps(f)+'\\n',encoding='utf8')
            rr.write_text(json.dumps(result({'5-2-3':84690}))+'\\n',encoding='utf8')
            rep=run(ff,rr,root/'out')
            self.assertEqual(rep['morning_pdca']['total']['payout_bands']['10000_PLUS']['hits'],0)
            self.assertEqual(rep['morning_pdca']['total']['failure_stage_counts']['FIRST_NOT_COVERED'],1)
            self.assertFalse(rep['morning_pdca']['total']['future_accuracy_gain_proved'])



if __name__ == '__main__':unittest.main()

