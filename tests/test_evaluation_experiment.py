"""Fictional races; expected denominators and hit counts are hand derived."""
import copy
import unittest
from race_ai.actions_contract import digest
from race_ai.evaluation_experiment import EvaluationError, validate_plan, seal_predictions, score_seal


def plan():
    p = {'schema':'RACE_AI_EVALUATION_PLAN_V1','experiment_id':'fictional-1',
      'declared_at':'2030-01-01T00:00:00Z','mode':'RETROSPECTIVE_RESEARCH',
      'cohort_rule':'all fictional scheduled races','discovery_sha256':'d'*64,
      'windows':{'train_end':'2030-01-02','validation_end':'2030-01-03','test_end':'2030-01-05'},
      'seen_race_ids':[], 'stages':['P0'], 'result_source_ids':['OFFICIAL'],
      'models':[{'model_id':m,'version':'1','code_sha256':m*64,
                 'artifact_sha256':None,'trained_until':None,'created_at':None} for m in ('a','b')],
      'comparison_groups':[['a','b']],
      'feature_policy':{'schema_id':'fictional-ratings-v1','transform_sha256':'9'*64,'allowed_fields':['historical_rating']},
      'races':[{'race_id':'r'+str(i),'sport':'boat','venue':'fixture','race_no':1,'event_date_jst':f'2030-01-0{i}',
                'cutoff_at':f'2030-01-0{i}T03:00:00Z','participants':[1,2,3,4,5,6]} for i in (2,3,4,5)]}
    p['eligibility']=[{'race_id':r['race_id'],'stage':'P0','model_id':m['model_id'],
                      'eligible':True,'reason':None} for r in p['races'] for m in p['models']]
    return p


def payload(p=None):
    p=p or plan();contexts=[];outputs=[]
    for race in p['races']:
        for stage in p['stages']:
            ctx={'race_id':race['race_id'],'stage':stage,
                 'as_of':race['event_date_jst']+'T02:00:00Z',
                 'features':{'historical_rating':[1,2,3,4,5,6]},
                 'sources':[{'source_id':'B','sha256':'e'*64,
                             'captured_at':race['event_date_jst']+'T01:00:00Z','published_at':None}]}
            contexts.append(ctx)
            for model in p['models']:
                outputs.append({'race_id':race['race_id'],'stage':stage,'model_id':model['model_id'],
                  'context_sha256':digest(ctx),'code_sha256':model['code_sha256'],
                  'artifact_sha256':model['artifact_sha256'],
                  'generated_at':'2030-01-06T00:00:00Z','status':'PREDICTED',
                  'top8':[[1,2,3]],'reason':None})
    return contexts,outputs


def sealed():
    p=plan();c,o=payload(p)
    # r4/b unforecast, r5 result unknown. Both remain in their cohorts.
    o[5].update(status='NO_FORECAST',top8=[],reason='MISSING_INPUT')
    return seal_predictions(p,c,o,sealed_at='2030-01-06T00:00:01Z')


def labels():
    return [{'race_id':r,'revision':1,'status':'FINAL','winning_triples':[[1,2,3]],
             'source_id':'OFFICIAL','source_sha256':'f'*64,'observed_at':'2030-01-06T00:01:00Z'}
            for r in ('r2','r3','r4')]


class EvaluationExperimentTests(unittest.TestCase):
    def test_unrepresentable_numeric_feature_rejected_cleanly(self):
        p=plan();c,o=payload(p);c[0]['features']['historical_rating']=[10**1000]
        for out in o:
            if out['race_id']==c[0]['race_id']:out['context_sha256']=digest(c[0])
        with self.assertRaises(EvaluationError):
            seal_predictions(p,c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_four_sports_have_separate_denominators(self):
        p=plan()
        for race,sport,n in zip(p['races'],('boat','keirin','autorace','horse'),(6,7,8,18)):
            race.update(sport=sport,participants=list(range(1,n+1)))
        c,o=payload(p)
        report=score_seal(seal_predictions(p,c,o,sealed_at='2030-01-06T00:00:01Z'),labels())
        self.assertEqual(set(report['by_sport']),{'boat','keirin','autorace','horse'})
        self.assertEqual([report['by_sport'][s][0]['known_results']for s in ('boat','keirin','autorace','horse')],[1,1,1,0])
        self.assertIsNone(report['by_sport']['horse'][0]['hit8_all_known'])

    def test_same_races_and_split_counts_keep_missing_and_unknown(self):
        report=score_seal(sealed(),labels())
        a,b=report['models']
        self.assertEqual((a['cohort'],a['known_results'],a['unknown_results'],a['hit8']), (4,3,1,3))
        self.assertEqual((b['known_results'],b['missing_prediction_known'],b['hit8']), (3,1,2))
        self.assertEqual(b['hit8_all_known'],2/3)
        self.assertEqual(report['comparisons'][0]['race_ids'],['r2','r3','r4','r5'])
        self.assertEqual(report['comparisons'][0]['known_results'],3)
        self.assertEqual(report['comparisons'][0]['models'][1]['missing_prediction_known'],1)
        self.assertEqual(report['successful_prediction_intersections'][0]['race_ids'],['r2','r3','r5'])
        self.assertEqual(report['split_counts'],{'train':1,'validation':1,'test':2})
        self.assertIsNone(report['formal_hit_at_8_all'])

    def test_complete_matrix_required(self):
        c,o=payload();o.pop()
        with self.assertRaises(EvaluationError):seal_predictions(plan(),c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_different_model_context_rejected(self):
        c,o=payload();o[1]['context_sha256']='0'*64
        with self.assertRaises(EvaluationError):seal_predictions(plan(),c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_context_with_result_or_nested_odds_rejected(self):
        for bad in ('result','odds','market_implied_win_probability','popularity'):
            c,o=payload();c[0]['features']={'nested':{bad:1}}
            with self.subTest(bad=bad),self.assertRaises(EvaluationError):
                seal_predictions(plan(),c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_undeclared_projection_field_or_nested_hidden_label_rejected(self):
        for features in ({'finish_position':1},{'odds_rank':1},{'historical_rating':{'renamed_label':1}}):
            c,o=payload();c[0]['features']=features
            with self.subTest(features=features),self.assertRaises(EvaluationError):
                seal_predictions(plan(),c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_feature_ineligible_model_cannot_emit_a_prediction(self):
        p=plan();p['eligibility'][0].update(eligible=False,reason='MISSING_FEATURE')
        c,o=payload(p)
        with self.assertRaises(EvaluationError):seal_predictions(p,c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_source_after_asof_or_cutoff_rejected(self):
        for key,value in [('captured_at','2030-01-02T02:01:00Z'),('published_at','2030-01-02T01:01:00Z')]:
            c,o=payload();c[0]['sources'][0][key]=value
            with self.subTest(key=key),self.assertRaises(EvaluationError):
                seal_predictions(plan(),c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_overlapping_split_or_seen_final_race_rejected(self):
        p=plan();p['windows']['validation_end']=p['windows']['train_end']
        with self.assertRaises(EvaluationError):validate_plan(p)
        p=plan();p['seen_race_ids']=['r4']
        with self.assertRaises(EvaluationError):validate_plan(p)

    def test_same_jst_day_not_split_between_train_and_test(self):
        p=plan();p['races'][0]['cutoff_at']='2030-01-01T23:59:00Z'
        checked=validate_plan(p)
        self.assertEqual(checked['races'][0]['event_date_jst'],'2030-01-02')
        p['races'][0]['cutoff_at']='2030-01-01T03:00:00Z'
        with self.assertRaises(EvaluationError):validate_plan(p)

    def test_model_version_or_artifact_switch_rejected(self):
        c,o=payload();o[0]['code_sha256']='f'*64
        with self.assertRaises(EvaluationError):seal_predictions(plan(),c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_fitted_model_cannot_overlap_validation_or_test(self):
        p=plan();p['models'][0].update(artifact_sha256='1'*64,
            trained_until='2030-01-04T00:00:00Z',created_at='2030-01-04T01:00:00Z')
        with self.assertRaises(EvaluationError):validate_plan(p)

    def test_retroactive_claim_cannot_be_promoted_by_local_timestamp(self):
        p=plan();p['mode']='PROSPECTIVE_LOCAL';c,o=payload(p)
        with self.assertRaises(EvaluationError):seal_predictions(p,c,o,sealed_at='2030-01-06T00:00:01Z')

    def test_local_prospective_still_needs_external_authority(self):
        p=plan();p['mode']='PROSPECTIVE_LOCAL';p['races']=p['races'][2:3]
        p['eligibility']=[e for e in p['eligibility'] if e['race_id']=='r4']
        c,o=payload(p)
        for row in o:row['generated_at']='2030-01-04T02:01:00Z'
        s=seal_predictions(p,c,o,sealed_at='2030-01-04T02:01:01Z')
        report=score_seal(s,[labels()[2]])
        self.assertFalse(report['independent_pre_cutoff_proof'])
        self.assertIsNone(report['formal_hit_at_8_all'])

    def test_tampered_seal_rejected(self):
        s=sealed();s['outputs'][0]['top8']=[[6,5,4]]
        with self.assertRaises(EvaluationError):score_seal(s,labels())

    def test_labels_cannot_add_race_or_source(self):
        for key,value in [('race_id','extra'),('source_id','UNDECLARED')]:
            ls=labels();ls[0][key]=value
            with self.subTest(key=key),self.assertRaises(EvaluationError):score_seal(sealed(),ls)

    def test_official_revision_correction_changes_scores_not_predictions(self):
        s=sealed();before=digest(s);ls=labels()
        revised=copy.deepcopy(ls[0]);revised.update(revision=2,winning_triples=[[6,5,4]],observed_at='2030-01-06T00:02:00Z')
        result=score_seal(s,ls+[revised])
        self.assertEqual(result['models'][0]['hit8'],2)
        self.assertEqual(digest(s),before)

    def test_duplicate_or_time_reversing_revision_rejected(self):
        ls=labels()
        with self.assertRaises(EvaluationError):score_seal(sealed(),ls+[ls[0]])
        r=copy.deepcopy(ls[0]);r.update(revision=2,observed_at='2030-01-05T00:00:00Z')
        with self.assertRaises(EvaluationError):score_seal(sealed(),ls+[r])

    def test_cancellation_distinct_from_unknown_or_missed_forecast(self):
        ls=labels();ls[0].update(status='CANCELLED',winning_triples=[])
        row=score_seal(sealed(),ls)['models'][0]
        self.assertEqual((row['known_results'],row['excluded_results'],row['unknown_results']),(2,1,1))
        self.assertEqual(row['hit8_all_known'],1.0)

    def test_max_eight_unique_tickets_with_real_participants(self):
        c,o=payload();o[0]['top8']=[[1,2,3],[1,2,3]]
        with self.assertRaises(EvaluationError):seal_predictions(plan(),c,o,sealed_at='2030-01-06T00:00:01Z')


if __name__=='__main__':unittest.main()
