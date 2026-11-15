"""Synthetic receipt-bound cash-label projection; no source or real key."""
from copy import deepcopy
from datetime import datetime,timezone
import importlib
import base64
import os
from unittest.mock import patch
import importlib.util
import unittest

NOW=datetime(2030,2,3,0,10,tzinfo=timezone.utc)

class CashObservationTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_cash_pdca'), 'cash PDCA connector is absent')
        return importlib.import_module('race_ai.all_existing_model_cash_pdca')

    def pair(self,sport='horse'):
        return {'pair':{'sport':sport,'race_id':f'{sport}:2030-02-02:'+('jra-03' if sport=='horse' else 'boatrace-jcd-01')+':11',
            'race_cutoff_at':'2030-02-02T23:59:00+09:00','cutoff_at':'2030-02-02T23:59:00+09:00',
            'baseline_normalized':{'roster':{'1':'one','2':'two','3':'three'}},'learned_normalized':{'roster':{'1':'one','2':'two','3':'three'}}}}

    def label(self,status='settled'):
        return dict(race_id=self.pair()['pair']['race_id'],sport='horse',status=status,ordered_top3=[3,1,2] if status=='settled' else [],
            roster={'1':'one','2':'two','3':'three'},captured_at='2030-02-03T00:00:00+09:00',source_sha256='a'*64,
            identity_verified=True,payout_per_100_yen=1230 if status=='settled' else None,refund_numbers=[],
            published_at=None,closed_at='2030-02-02T23:59:00+09:00',source_ref='https://www.jra.go.jp/fixture',source_rights_ref='synthetic',reason='NORMAL')

    def test_only_normal_cash_teacher_projects_exact_existing_fields_and_preserves_full_context(self):
        api=self.module();value=self.label();context={'observations':[value]};original=deepcopy(context)
        labels,counts=api._cash_observations([context],[self.pair()],now=NOW)
        self.assertEqual(set(labels[0]),{'race_id','sport','status','ordered_top3','roster','captured_at','source_sha256','identity_verified','payout_per_100_yen','refund_numbers'})
        self.assertEqual(labels[0]['ordered_top3'],[3,1,2]);self.assertEqual(labels[0]['payout_per_100_yen'],1230)
        self.assertEqual(counts['matched_cash_result_count'],1);self.assertEqual(context,original)

    def test_pending_special_and_typed_order_only_never_become_cash_losses(self):
        api=self.module()
        for status in ('pending','special','rank_confirmed'):
            with self.subTest(status=status):
                labels,counts=api._cash_observations([{'observations':[self.label(status)]}],[self.pair()],now=NOW)
                self.assertEqual(labels,[]);self.assertEqual(counts['outside_normal_cash_result_state_counts'],{status:1})

    def test_duplicate_cross_artifact_race_revisions_are_rejected_even_if_identical(self):
        api=self.module();context={'observations':[self.label()]}
        with self.assertRaisesRegex(ValueError,'DUPLICATE_RESULT_REVISION'):
            api._cash_observations([context,deepcopy(context)],[self.pair()],now=NOW)

    def test_wrong_roster_or_closed_clock_is_rejected_before_projection(self):
        api=self.module()
        for change in ({'roster':{'1':'different','2':'two','3':'three'}},{'closed_at':'2030-02-02T23:58:00+09:00'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                api._cash_observations([{'observations':[dict(self.label(),**change)]}],[self.pair()],now=NOW)

    def test_per_partition_public_counts_do_not_label_other_cash_cells_outside_scope(self):
        api=self.module()
        admission=dict(scope='SYNTHETIC_ONLY',artifact_id=1,artifact_digest='sha256:'+'a'*64,
            workflow_run_id=4,head_sha='b'*40,training_sha256='c'*64,forecast_partition_count=19)
        context=dict(source_admission=admission,candidate_cell_count=19,origin=dict(origin_metadata={'id':2,'digest':'sha256:'+'d'*64},
            generation={'forecast_counts_by_sport':{'boat':14,'horse':5}}),projection_counts={})
        result=api._summary(context,[],0)
        self.assertEqual(result['outside_cash_forecast_count'],0)
        self.assertNotIn('scoreboard',result)

    def test_order_only_thirty_scope_cannot_be_extended_by_unsigned_cash_manifest(self):
        api=self.module()
        # Must fail on scope before touching any untrusted bytes or receipts.
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode()):
            with self.assertRaisesRegex(ValueError,'ORDER_ONLY_CANDIDATE_CASH_SCOPE_REQUIRES_SEPARATE_OWNER_DECISION'):
                api.admit_sources(None,None,None,None,[],now=NOW,expected_native_run_id=42,
                    expected_native_head_sha='a'*40,candidate_cell_count=30)

    def test_private_cash_reader_also_rejects_order_only_thirty_scope(self):
        api=self.module();context={'candidate_cell_count':30}
        from race_ai.actions_contract import digest
        payload=dict(schema=api.SCHEMA,training=None,summary={},evaluated_at=NOW.isoformat(),cash_score=None,
            source_context=context,source_context_sha256=digest(context))
        with self.assertRaisesRegex(ValueError,'ORDER_ONLY_CANDIDATE_CASH_SCOPE_REQUIRES_SEPARATE_OWNER_DECISION'):
            api.verify_private_cash_pdca(payload)

if __name__=='__main__':unittest.main()
