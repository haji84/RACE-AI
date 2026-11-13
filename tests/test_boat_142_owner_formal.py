"""Synthetic, zero-provider-GET tests for owner-approved legacy SP formal scoring."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import unittest

from scripts.boat_142_owner_formal import score_owner_approved, POLICY


def stamp(value):
    return datetime.fromisoformat(value)


def _records():
    all_rows = []
    for i in range(142):
        rid = f'20261112-01-{i+1:02d}'
        cutoff = '2026-11-12T18:00:00+09:00'
        source_cutoff = '2026-11-12T18:01:00+09:00'
        saved = '2026-11-12T17:40:00+09:00'
        predictions = [dict(model_id=m, stage='P0', persisted_at=saved,
                            ordered_top8=[[1,2,3]], cutoff_at=cutoff)
                       for m in ('model-A', 'model-B')]
        row = dict(race_id=rid, sport='boat',event_date_jst='2026-11-12',
                   cutoff_at=cutoff,prediction=predictions[0],
                   comparison_predictions=[predictions[1]],
                   result=dict(status='final'),result_observations=[])
        if i >= 132:
            row['result'] = dict(status='final', source_sha256='a'*64,
                observed_at='2026-11-12T18:04:00+09:00',
                winning_combinations=[[1,2,3]],payout_yen_per_100=900,
                cutoff_reference=dict(
                    basis='RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH',
                    formal_eligible=False,original_cutoff_at=cutoff,
                    result_schedule_cutoff_at=source_cutoff,offset_seconds=60))
            row['result_observations'] = [dict(
                race_id=rid,source_url='https://www.boatrace.jp/owsp/sp/spdata?test',
                source_sha256='a'*64,captured_at='2026-11-12T18:04:00+09:00',
                closed_at=source_cutoff,body_identity_verified=True,
                schedule_binding='SP_EXPLICIT_RACE_HEADER',
                status='AVAILABLE',data=dict(status='settled',
                    confirmed=True,finish_confirmed=True,
                    payouts=[dict(bet_type='trifecta',combination=[1,2,3],
                                  payout_per_100_yen=900)],
                    refund_boats=[]))]
        all_rows.append(row)
    return dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1',
                dataset_status='REAL_REPORTED',records=all_rows)


class FakeF:
    @staticmethod
    def originals_sha(view):
        filtered = [{k:v for k,v in r.items() if k not in
                     ('result','result_observations','result_observation_rejections')}
                    for r in view['records']]
        return hashlib.sha256(json.dumps(filtered,sort_keys=True).encode()).hexdigest()
    @staticmethod
    def inventory_sha(view):
        return hashlib.sha256(json.dumps(
            [(r['race_id'],r['prediction'],r['comparison_predictions'])
             for r in view['records']],sort_keys=True).encode()).hexdigest()
    @classmethod
    def forecast_anchor(cls,view):
        return cls.originals_sha(view)


class FakeD:
    @staticmethod
    def reconciled_status(row):
        result=row['result']
        if result.get('formal_eligible') is False or (
                result.get('cutoff_reference') is not None):
            return 'unsupported'
        return result['status']


class FakeP:
    @staticmethod
    def _saved_clock(prediction,row):
        cutoff=stamp(prediction.get('cutoff_at') or row['cutoff_at'])
        assert stamp(prediction['persisted_at']) < cutoff
        return cutoff
    @staticmethod
    def _result_context(row):
        assert 'cutoff_reference' not in row['result']
        return ('FINAL',{(1,2,3):900},set())
    @classmethod
    def score_view(cls,view,*,authenticated):
        assert authenticated is True
        assert all(FakeD.reconciled_status(r)=='final' for r in view['records'])
        return dict(total_forecasts=284,total_scored=284,unresolved=0,
            model_groups=[dict(model_id=m,forecasts=142,eligible=142,
                               void=0,held=0,pending=0)
                          for m in ('model-A','model-B')])


class OwnerFormalApprovalTests(unittest.TestCase):
    def run_scoring(self,view):
        return score_owner_approved(view,F=FakeF,D=FakeD,P=FakeP)

    def test_all_ten_are_evaluated_but_original_is_immutable(self):
        original=_records()
        reference=deepcopy(original)
        evaluated,score,proof=self.run_scoring(original)
        self.assertEqual(proof['schema'],POLICY)
        self.assertEqual(proof['owner_approved_formal_reference_races'],10)
        self.assertEqual(proof['accepted_result_races'],142)
        self.assertEqual(proof['model_forecasts_scored'],284)
        self.assertEqual(proof['model_unresolved'],0)
        self.assertEqual(Counter(FakeD.reconciled_status(r)
            for r in evaluated['records']),{'final':142})
        self.assertEqual(original,reference)
        self.assertEqual(FakeF.inventory_sha(original),FakeF.inventory_sha(evaluated))
        self.assertTrue(all('cutoff_reference' in r['result']
            for r in original['records'][132:]))
        self.assertTrue(all('cutoff_reference' not in r['result']
            for r in evaluated['records'][132:]))
        self.assertEqual(proof['source_gets'],0)
        self.assertEqual(proof['original_prediction_rewrites'],0)

    def test_mismatched_source_receipt_is_not_formal(self):
        v=_records()
        v['records'][132]['result_observations'][0]['source_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'LATEST_SOURCE_RECEIPT_UNVERIFIED'):
            self.run_scoring(v)

    def test_saved_prediction_after_official_clock_stays_hold(self):
        v=_records()
        v['records'][133]['prediction']['persisted_at']='2026-11-12T18:00:30+09:00'
        with self.assertRaisesRegex(ValueError,'FORECAST_NOT_FROZEN_BEFORE_BOTH'):
            self.run_scoring(v)

    def test_other_nonformal_or_source_gate_cannot_be_bypassed(self):
        v=_records()
        v['records'][132]['result']['formal_eligible']=False
        with self.assertRaisesRegex(ValueError,'OTHER_NONFORMAL_GATE_PRESENT'):
            self.run_scoring(v)
        v=_records()
        v['records'][132]['result_observations'][0]['source_url']='https://invalid.example/path'
        with self.assertRaisesRegex(ValueError,'OFFICIAL_SP_SOURCE_REQUIRED'):
            self.run_scoring(v)
        v=_records()
        v['records'][132]['result_observations'][0]['data']['status']='pending'
        with self.assertRaisesRegex(ValueError,'OFFICIAL_SETTLEMENT_BODY_REQUIRED'):
            self.run_scoring(v)

    def test_result_capture_earlier_than_both_cutoffs_is_rejected(self):
        v=_records()
        v['records'][132]['result']['observed_at']='2026-11-12T17:59:30+09:00'
        v['records'][132]['result_observations'][0]['captured_at']='2026-11-12T17:59:30+09:00'
        with self.assertRaisesRegex(ValueError,'RESULT_OBSERVED_BEFORE_BOTH_CUTOFFS'):
            self.run_scoring(v)

    def test_unexpected_inventory_stops_before_scorer(self):
        v=_records();v['records'].pop()
        with self.assertRaisesRegex(ValueError,'ORIGINAL_RACE_INVENTORY_REQUIRED'):
            self.run_scoring(v)


if __name__=='__main__':
    unittest.main()
