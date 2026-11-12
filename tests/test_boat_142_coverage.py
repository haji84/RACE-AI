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
