"""Fictional claimed outcomes; no external authority is manufactured."""
from copy import deepcopy
import unittest
from race_ai.actions_contract import digest
try:
    from race_ai.observed_pair_comparison import compare_research_pairs, ComparisonError
except ImportError:
    compare_research_pairs = None
    ComparisonError = ValueError

MODELS = ('boat-observed-pairwise-factor-v1','boat-observed-pairwise-start-v1')
DAY='2030-01-15'
def fixture():
    rows=[dict(race_id=f'boat:{DAY}:boatrace-jcd-14:{n}',sport='boat',venue='boatrace-jcd-14',
        race_no=n,race_revision=1,sales_cutoff_at=DAY+'T10:00:00+09:00') for n in range(1,4)]
    plan=dict(schema='RACE_AI_OBSERVED_PAIR_PLAN_V1',declared_at=DAY+'T07:00:00+09:00',
        event_date_jst=DAY,model_ids=list(MODELS),result_revision_policy='LATEST_SUPPLIED_REVISION',records=rows)
    outcomes=[dict(race_id=r['race_id'],status='FINAL',trifecta_offered=True,
        payouts=[dict(combination=[1,2,3],yen_per_100=600)],refund_status='NONE',revision_no=1,
        confirmed_at=DAY+'T11:00:00+09:00',source_ref='https://example.org/fictional-result') for r in rows]
    snapshot=dict(race_id=rows[0]['race_id'],race_revision=1,as_of=DAY+'T08:00:00+09:00',
        sales_cutoff_at=rows[0]['sales_cutoff_at'],stage='P0',synthetic_value=1)
    context=dict(race_id=snapshot['race_id'],stage='P0',as_of=snapshot['as_of'],snapshot_sha256=digest(snapshot))
    return plan,[context],[dict(snapshot=snapshot,suite=fake_predict(snapshot))],outcomes

def fake_predict(snapshot,*,allow_source=None):
    models={m:dict(model_id=m,model_version='0.1.0-UNTRAINED',
        race_id=snapshot['race_id'],race_revision=snapshot['race_revision'],stage=snapshot['stage'],
        as_of=snapshot['as_of'],sales_cutoff_at=snapshot['sales_cutoff_at'],snapshot_sha256=digest(snapshot),
        ordered_top8=[[1,2,3]] if i==0 else [[3,2,1]],score_discriminating=True,
        official_prediction=False,result_or_cutoff_proof_eligible=False)
        for i,m in enumerate(MODELS)}
    return dict(schema='RACE_AI_BOAT_OBSERVED_PAIRWISE_SUITE_V1',models=models,
        race_id=snapshot['race_id'],race_revision=snapshot['race_revision'],stage=snapshot['stage'],
        as_of=snapshot['as_of'],sales_cutoff_at=snapshot['sales_cutoff_at'],snapshot_sha256=digest(snapshot),
        official_prediction=False,result_or_cutoff_proof_eligible=False)

class ComparisonTests(unittest.TestCase):
    def run_fixture(self,parts=None,predictor=fake_predict):
        self.assertIsNotNone(compare_research_pairs,'missing same-race comparison implementation')
        return compare_research_pairs(*(parts or fixture()),predict_pair=predictor)

    def test_full_denominator_includes_unforecast_and_separates_informative(self):
        out=self.run_fixture()
        self.assertEqual(out['claimed_eligible_denominator'],3)
        a=out['stages']['P0']['models'][MODELS[0]]
        self.assertEqual((a['output_count'],a['informative_count'],a['hit_at_8_count']),(1,1,1))
        self.assertEqual(a['research_hit_at_8_all'],1/3)
        self.assertEqual(a['output_coverage'],1/3)
        self.assertEqual(out['stages']['P0']['paired_subset']['count'],1)
        self.assertIsNone(out['formal_hit_at_8_all'])
        self.assertFalse(out['external_freeze_verified'])

    def test_no_cases_retains_every_target(self):
        p,c,k,r=fixture();out=self.run_fixture((p,[],[],r))
        self.assertEqual(out['target_race_count'],3)
        self.assertEqual(out['stages']['P0']['models'][MODELS[0]]['research_hit_at_8_all'],0)

    def test_same_race_both_models_use_same_actual_result_revision(self):
        p,c,k,r=fixture();v=deepcopy(r[0]);v.update(revision_no=2,confirmed_at=DAY+'T11:30:00+09:00',
            payouts=[dict(combination=[3,2,1],yen_per_100=800)])
        r.append(v);out=self.run_fixture((p,c,k,r))
        self.assertEqual(out['stages']['P0']['models'][MODELS[0]]['hit_at_8_count'],0)
        self.assertEqual(out['stages']['P0']['models'][MODELS[1]]['hit_at_8_count'],1)
        self.assertEqual(out['races'][0]['result_revision'],2)

    def test_uninformative_predictions_have_separate_coverage(self):
        p,c,k,r=fixture()
        def neutral(s,**kw):
            x=fake_predict(s)
            for m in x['models'].values():m['score_discriminating']=False
            return x
        k[0]['suite']=neutral(k[0]['snapshot']);out=self.run_fixture((p,c,k,r),neutral)
        a=out['stages']['P0']['models'][MODELS[0]]
        self.assertEqual(a['output_count'],1);self.assertEqual(a['informative_count'],0)
        self.assertEqual(a['uninformative_count'],1)

    def test_distinct_stage_never_fills_missing_stage(self):
        p,c,k,r=fixture();s=k[0]['snapshot'];s['stage']='P1';s['as_of']=DAY+'T09:00:00+09:00'
        c[0].update(stage='P1',as_of=s['as_of'],snapshot_sha256=digest(s));k[0]['suite']=fake_predict(s)
        out=self.run_fixture((p,c,k,r))
        self.assertEqual(out['stages']['P0']['paired_subset']['count'],0)
        self.assertEqual(out['stages']['P1']['paired_subset']['count'],1)
        self.assertEqual(out['within_model_stage_comparison'][MODELS[0]]['paired_race_count'],0)

    def test_wrong_context_asof_hash_revision_or_race_rejected(self):
        for key,value in [('as_of',DAY+'T09:00:00+09:00'),('snapshot_sha256','f'*64),('race_id','other')]:
            p,c,k,r=fixture();c[0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.run_fixture((p,c,k,r))
        p,c,k,r=fixture();k[0]['snapshot']['race_revision']=2
        c[0]['snapshot_sha256']=digest(k[0]['snapshot']);k[0]['suite']=fake_predict(k[0]['snapshot'])
        with self.assertRaises(ValueError):self.run_fixture((p,c,k,r))

    def test_rewritten_ticket_and_missing_model_are_rejected(self):
        for mode in ('ticket','missing','official'):
            p,c,k,r=fixture()
            if mode=='ticket':k[0]['suite']['models'][MODELS[0]]['ordered_top8']=[[6,5,4]]
            if mode=='missing':k[0]['suite']['models'].pop(MODELS[1])
            if mode=='official':k[0]['suite']['official_prediction']=True
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.run_fixture((p,c,k,r))

    def test_postcutoff_undeclared_and_duplicate_cases_rejected(self):
        p,c,k,r=fixture();c[0]['as_of']=p['records'][0]['sales_cutoff_at']
        with self.assertRaises(ValueError):self.run_fixture((p,c,k,r))
        p,c,k,r=fixture()
        with self.assertRaises(ValueError):self.run_fixture((p,c,k+k,r))
        with self.assertRaises(ValueError):self.run_fixture((p,[],k,r))

    def test_invalid_result_and_earlier_than_cutoff_are_rejected(self):
        for field,value in [('confirmed_at',DAY+'T09:00:00+09:00'),('revision_no',2)]:
            p,c,k,r=fixture();r[0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.run_fixture((p,c,k,r))

    def test_result_cancellation_changes_denominator_not_original_inputs(self):
        p,c,k,r=fixture();before=deepcopy((p,c,k,r));out=self.run_fixture((p,c,k,r))
        self.assertEqual((p,c,k,r),before)
        v=deepcopy(r[0]);v.update(status='VOID',payouts=[],revision_no=2,confirmed_at=DAY+'T12:00:00+09:00')
        r.append(v);out=self.run_fixture((p,c,k,r))
        self.assertEqual(out['claimed_eligible_denominator'],2)
        self.assertEqual(out['target_race_count'],3)

    def test_prediction_callback_cannot_mutate_bound_snapshot(self):
        p,c,k,r=fixture();before=deepcopy(k)
        def bad(s,**kw):
            out=fake_predict(s);s['synthetic_value']=999;return out
        with self.assertRaises(ValueError):self.run_fixture((p,c,k,r),bad)
        self.assertEqual(k,before)

    def test_empty_eligible_returns_none_never_perfect_accuracy(self):
        p,c,k,r=fixture();out=self.run_fixture((p,c,k,[]))
        self.assertEqual(out['claimed_eligible_denominator'],0)
        self.assertIsNone(out['stages']['P0']['models'][MODELS[0]]['research_hit_at_8_all'])

    def test_model_object_key_order_does_not_change_comparison(self):
        p,c,k,r=fixture();original=self.run_fixture((p,c,k,r))
        k[0]['suite']['models']=dict(reversed(list(k[0]['suite']['models'].items())))
        self.assertEqual(self.run_fixture((p,c,k,r)),original)

    def test_boat_results_cannot_include_nonexistent_lanes(self):
        p,c,k,r=fixture();r[0]['payouts'][0]['combination']=[7,8,9]
        with self.assertRaises(ValueError):self.run_fixture((p,c,k,r))

if __name__=='__main__':unittest.main()
