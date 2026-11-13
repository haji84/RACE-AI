"""Synthetic, source-free BOAT result coverage accounting, no provider GET."""
import unittest
from scripts.boat_142_coverage import summarize


def view(n=4, *, day='2026-11-12'):
    records=[]
    for i in range(n):
        predictions=[dict(stage='P0',model_id='model-A'),dict(stage='P0',model_id='model-B')]
        records.append(dict(
            race_id=f'20261112-01-{i+1:02d}',sport='boat',
            event_date_jst=day,prediction=predictions[0],
            comparison_predictions=[predictions[1]]))
    return dict(dataset_status='REAL_REPORTED',records=records)


def score(*,forecasts=4,eligible=1,pending=2,held=1):
    groups=[]
    for model in ('model-A','model-B'):
        groups.append(dict(model_id=model,stage='P0',version=None,variant=None,
                           forecasts=forecasts,eligible=eligible,hits=0,
                           misses=eligible,void=0,pending=pending,held=held,
                           unresolved_reasons=({'HOLD_NO_FORMAL_RESULT':held} if held else {})))
    return dict(schema='RACE_AI_RETAINED_MODEL_PDCA_AUDIT_V1',
                source='AES_AUTHENTICATED_SAVED_VIEW_ONLY',
                model_groups=groups,total_forecasts=2*forecasts,
                total_scored=2*eligible,unresolved=2*(pending+held),
                actual_purchases=False,rewrote_predictions=False,
                no_provider_requests=True)


class CoverageTests(unittest.TestCase):
    def test_fifty_of_142_is_hold_without_inventing_losses(self):
        value=view(4)
        states={r['race_id']:s for r,s in zip(value['records'],
                                              ('final','pending','missing','unsupported'))}
        result=summarize(value,states,score(),day='2026-11-12',
                         expected_races=142,expected_p0=284)
        self.assertEqual(result['status'],'BOAT_142_COVERAGE_HOLD')
        self.assertEqual(result['confirmed_result_races'],1)
        self.assertEqual(result['unconfirmed_result_races'],3)
        self.assertEqual(result['model_scored_forecasts'],2)
        self.assertEqual(result['unresolved_p0_forecasts'],6)
        self.assertEqual(result['official_source_requests'],0)
        self.assertNotIn('20261112-01-01',str(result))

    def test_exact_coverage_requires_all_results_and_all_original_models_scored(self):
        value=view(2)
        states={r['race_id']:'final' for r in value['records']}
        report=score(forecasts=2,eligible=2,pending=0,held=0)
        done=summarize(value,states,report,day='2026-11-12',
                       expected_races=2,expected_p0=4)
        self.assertEqual(done['status'],'BOAT_142_COVERAGE_COMPLETE')
        report['model_groups'][0]['held']=1
        with self.assertRaisesRegex(ValueError,'MODEL_ACCOUNTING_INVALID'):
            summarize(value,states,report,day='2026-11-12',
                      expected_races=2,expected_p0=4)

    def test_model_hold_reasons_are_exact_count_only_and_fail_closed(self):
        value=view(4)
        states={r['race_id']:'unsupported' for r in value['records']}
        report=score()
        result=summarize(value,states,report,day='2026-11-12',
                         expected_races=142,expected_p0=284)
        self.assertEqual(result['model_groups'][0]['unresolved_reasons'],
                         {'HOLD_NO_FORMAL_RESULT':1})
        report['model_groups'][0]['unresolved_reasons']={'HOLD_BAD!!':1}
        with self.assertRaisesRegex(ValueError,'MODEL_HOLD_REASON_INVALID'):
            summarize(value,states,report,day='2026-11-12',
                      expected_races=142,expected_p0=284)
        report['model_groups'][0]['unresolved_reasons']={'HOLD_NO_FORMAL_RESULT':2}
        with self.assertRaisesRegex(ValueError,'MODEL_HOLD_REASON_TOTAL_MISMATCH'):
            summarize(value,states,report,day='2026-11-12',
                      expected_races=142,expected_p0=284)

    def test_unsupported_reasons_are_counted_once_per_race_without_ids(self):
        value=view(2)
        value['records'][0]['result_observation_rejections']=[
            dict(reason='RESULT_WINNER_INVALID',captured_at='private-capture',
                 source_sha256='private-sha'),
            dict(reason='RESULT_PAYOUT_INVALID',captured_at='private-newer')]
        value['records'][1]['result']=dict(status='final',formal_eligible=False)
        states={r['race_id']:'unsupported' for r in value['records']}
        report=score(forecasts=2,eligible=0,pending=0,held=2)
        outcome=summarize(value,states,report,day='2026-11-12',
                          expected_races=2,expected_p0=4)
        self.assertEqual(outcome['unsupported_reason_counts'],
                         {'REFERENCE_ONLY_NOT_FORMAL':1,'RESULT_PAYOUT_INVALID':1})
        self.assertEqual(sum(outcome['unsupported_reason_counts'].values()),2)
        self.assertNotIn('private-capture',str(outcome))
        self.assertNotIn('private-sha',str(outcome))
        self.assertNotIn('20261112-01-01',str(outcome))

    def test_reference_only_flags_are_counted_once_without_private_refs(self):
        value=view(4)
        records=value['records']
        records[0]['result']=dict(status='final',
                                  cutoff_reference=dict(private='hidden-a'))
        records[1]['result']=dict(status='final',formal_eligible=False)
        records[2]['result']=dict(
            status='final',cutoff_reconciliation=dict(
                formal_eligible=False,private='hidden-b'))
        records[3]['result']=dict(status='unsupported')
        states={r['race_id']:'unsupported' for r in records}
        report=score(forecasts=4,eligible=0,pending=0,held=4)
        out=summarize(value,states,report,day='2026-11-12',
                      expected_races=4,expected_p0=8)
        self.assertEqual(out['reference_only_gate_counts'],{
            'LEGACY_CUTOFF_REFERENCE':1,
            'EXPLICIT_FORMAL_ELIGIBLE_FALSE':1,
            'CUTOFF_RECONCILIATION_FORMAL_FALSE':1})
        self.assertEqual(out['unsupported_reason_counts'],{
            'REFERENCE_ONLY_NOT_FORMAL':3,'UNSUPPORTED_UNCLASSIFIED':1})
        self.assertEqual(sum(out['reference_only_gate_counts'].values()),3)
        self.assertNotIn('hidden-a',str(out))
        self.assertNotIn('hidden-b',str(out))
        self.assertNotIn('20261112-01-',str(out))

    def test_legacy_reference_proof_is_count_only_and_never_upgrades_scoring(self):
        value = view(1)
        row = value['records'][0]
        for p in [row['prediction'], *row['comparison_predictions']]:
            p['persisted_at'] = '2026-11-12T17:40:00+09:00'
        row['result'] = dict(status='final', source_sha256='a' * 64,
            observed_at='2026-11-12T18:05:00+09:00',
            cutoff_reference=dict(
                basis='RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH',
                offset_seconds=60,
                original_cutoff_at='2026-11-12T18:00:00+09:00',
                result_schedule_cutoff_at='2026-11-12T18:01:00+09:00',
                race_identifier='private-value-never-print',
                formal_eligible=False))
        row['result_observations'] = [dict(
            captured_at='2026-11-12T18:05:00+09:00', source_sha256='a'*64,
            body_identity_verified=True, status='AVAILABLE',
            data=dict(confirmed=True, status='settled', finish_confirmed=True,
                      private_details='private-secret'))]
        statuses = {row['race_id']: 'unsupported'}
        report = score(forecasts=1,eligible=0,pending=0,held=1)
        actual = summarize(value,statuses,report,day='2026-11-12',
                           expected_races=1,expected_p0=2)
        self.assertEqual(actual['legacy_reference_basis_counts'],
            {'RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH':1})
        self.assertEqual(actual['legacy_reference_offset_bands'],
            {'OFFSET_LE_60S':1})
        self.assertEqual(actual['legacy_reference_receipt_checks'],
            {'RECEIPT_MATCHED_SETTLEMENT_BODY':1})
        self.assertEqual(actual['legacy_reference_timing_checks'],
            {'FORECASTS_BEFORE_BOTH_AND_RESULT_AFTER_BOTH':1})
        self.assertEqual(actual['confirmed_result_races'],0)
        self.assertEqual(actual['model_held_forecasts'],2)
        for secret in ('private-value-never-print','private-secret',row['race_id'],
                       '2026-11-12T18:00:00+09:00'):
            self.assertNotIn(secret,str(actual))
        # An old source receipt with different digest fails classification.
        row['result_observations'][0]['source_sha256'] = 'b'*64
        actual = summarize(value,statuses,report,day='2026-11-12',
                           expected_races=1,expected_p0=2)
        self.assertEqual(actual['legacy_reference_receipt_checks'],
                         {'RECEIPT_MISMATCH_OR_INCOMPLETE':1})
        self.assertEqual(actual['confirmed_result_races'],0)

    def test_unknown_reference_basis_and_bad_times_do_not_leak_originals(self):
        value=view(1);row=value['records'][0]
        row['result']=dict(status='final',cutoff_reference=dict(
            basis='PRIVATE_SOURCE_LINK',offset_seconds=float('nan'),
            original_cutoff_at='secret time',result_schedule_cutoff_at='unknown'))
        report=score(forecasts=1,eligible=0,pending=0,held=1)
        out=summarize(value,{row['race_id']:'unsupported'},report,
                      day='2026-11-12',expected_races=1,expected_p0=2)
        self.assertEqual(out['legacy_reference_basis_counts'],
                         {'REFERENCE_BASIS_UNKNOWN':1})
        self.assertEqual(out['legacy_reference_offset_bands'],
                         {'OFFSET_UNKNOWN':1})
        self.assertEqual(out['legacy_reference_timing_checks'],
                         {'CHRONOLOGY_UNKNOWN':1})
        self.assertNotIn('PRIVATE_SOURCE_LINK',str(out))
        self.assertNotIn('secret time',str(out))

    def test_missing_race_duplicate_race_and_wrong_score_fail_closed(self):
        value=view(2)
        states={r['race_id']:'final' for r in value['records']}
        report=score(forecasts=2,eligible=2,pending=0,held=0)
        with self.assertRaisesRegex(ValueError,'STATUS_INVENTORY_INVALID'):
            summarize(value,{},report,day='2026-11-12',
                      expected_races=2,expected_p0=4)
        value['records'].append(value['records'][0])
        with self.assertRaisesRegex(ValueError,'RACE_INVENTORY_INVALID'):
            summarize(value,states,report,day='2026-11-12',
                      expected_races=2,expected_p0=4)


if __name__=='__main__':
    unittest.main()
