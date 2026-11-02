"""Fictional only. Independent outcomes, immutability and missing-denominator tests."""
import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.evaluation_result_revision_bridge import (
    BATCH, SCOPE, ResultLinkError, _digest, link_result_revisions,
    research_score_existing_seal,
)
from race_ai.evaluation_result_revision_cli import main

DAY='2030-01-05'
BOAT=f'boat:{DAY}:boatrace-jcd-01:1'
KEIRIN=f'keirin:{DAY}:example-keirin:2'
HORSE=f'horse_jra:{DAY}:example-jra:3'


def bridge():
    rows=[]
    for race,sport,number in [(BOAT,'boat',1),(KEIRIN,'keirin',2),(HORSE,'horse_jra',3)]:
        rows.append({'race_id':race,'sport':sport,'event_date_jst':DAY,
                     'venue':race.split(':')[2],'race_no':number,'archive_slots':[]})
    return {'schema':'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1',
            'mode':'OFFLINE_RESEARCH_COVERAGE_LINK','event_date_jst':DAY,
            'records':rows,'official_completeness_verified':False,
            'source_rights_verified':False,
            'external_pre_cutoff_receipts_verified':False,'formal_hit_at_8_all':None}


def label(rid=BOAT,**updates):
    host=('www.boatrace.jp' if rid==BOAT else
          'keirin.jp' if rid==KEIRIN else 'www.jra.go.jp')
    row={'race_id':rid,'revision':1,'previous_observation_sha256':None,
         'observed_at':'2030-01-05T15:00:00+09:00',
         'source_id':'OFFICIAL','source_url':f'https://{host}/result/fixture',
         'source_sha256':'a'*64,'source_published_at':None,
         'provider_revision_ref':None,'status':'FINAL_NORMAL',
         'winning_triples':[[1,2,3]],
         'payouts_100yen':[{'triple':[1,2,3],'yen':1234}],
         'refund_status':'NONE'}
    row.update(updates)
    return row


def batch(*rows):
    return {'schema':BATCH,'scope':SCOPE,'event_date_jst':DAY,
            'observations':[copy.deepcopy(v) for v in rows]}


class RevisionJoinTests(unittest.TestCase):
    def test_missing_kept_and_formal_null(self):
        result=link_result_revisions(bridge(),[batch(label())])
        self.assertEqual(result['listed_races'],3)
        self.assertEqual(result['latest_observation_states'],
                         {'FINAL_NORMAL':1,'NO_RESULT_OBSERVATION':2})
        self.assertEqual(result['latest_observation_states_by_sport']['boat'],{'FINAL_NORMAL':1})
        for field in ('official_hit1','official_hit8_all','official_complete_denominator',
                      'official_prediction_capture_rate','actual_purchase_roi','brier','log_loss'):
            self.assertIsNone(result[field])
        self.assertFalse(result['private_archive_mutated'])
        self.assertNotIn('winning_triples',str(result))

    def test_real_append_not_rewrite(self):
        old=label(status='PENDING',winning_triples=[],payouts_100yen=[],refund_status='UNKNOWN')
        fresh=label(revision=2,previous_observation_sha256=_digest(old),
                    provider_revision_ref='fictional-v2',
                    observed_at='2030-01-05T16:00:00+09:00')
        report=link_result_revisions(bridge(),[batch(old),batch(fresh)])
        row=next(r for r in report['records'] if r['race_id']==BOAT)
        self.assertEqual(row['revision_count'],2)
        self.assertEqual(row['latest_claimed_status'],'FINAL_NORMAL')
        self.assertEqual(row['latest_observation_sha256'],_digest(fresh))
        self.assertEqual(old['status'],'PENDING')

    def test_hash_forgery_and_missing_revisions_rejected(self):
        old=label(status='PENDING',winning_triples=[],payouts_100yen=[],refund_status='UNKNOWN')
        wrong=label(revision=2,previous_observation_sha256='f'*64,
                    provider_revision_ref='fictional-v2')
        with self.assertRaisesRegex(ResultLinkError,'REVISION_CHAIN_HASH_MISMATCH'):
            link_result_revisions(bridge(),[batch(old,wrong)])
        wrong['revision']=3
        with self.assertRaisesRegex(ResultLinkError,'MISSING_OR_DUPLICATE_REVISION'):
            link_result_revisions(bridge(),[batch(old,wrong)])

    def test_changed_source_digest_supports_separate_observation(self):
        old=label(status='PENDING',winning_triples=[],payouts_100yen=[],refund_status='UNKNOWN')
        new=label(revision=2,previous_observation_sha256=_digest(old),
                  observed_at='2030-01-05T16:00:00+09:00',source_sha256='b'*64)
        self.assertEqual(link_result_revisions(bridge(),[batch(old),batch(new)])['result_observations'],2)

    def test_foreign_provider_and_pretend_authority_blocked(self):
        with self.assertRaisesRegex(ResultLinkError,'NON_PROVIDER_SOURCE_URL'):
            link_result_revisions(bridge(),[batch(label(source_url='https://invalid-boatrace.jp/result'))])
        with self.assertRaisesRegex(ResultLinkError,'UNLISTED_RACE_OR_REVISION'):
            link_result_revisions(bridge(),[batch(label(rid='boat:2030-01-05:other:1'))])
        x=bridge();x['source_rights_verified']=True
        with self.assertRaisesRegex(ResultLinkError,'UNTRUSTED_BRIDGE_AUTHORITY'):
            link_result_revisions(x,[batch()])
        x=batch(label());x['scope']='PROVIDER_APPROVED'
        with self.assertRaisesRegex(ResultLinkError,'BATCH_SCOPE_OR_DATE'):
            link_result_revisions(bridge(),[x])

    def test_refunds_special_and_unavailable_never_made_misses(self):
        special=label(status='UNSUPPORTED_SPECIAL',winning_triples=[],
                      payouts_100yen=[],refund_status='UNKNOWN')
        unavailable=label(rid=KEIRIN,status='SOURCE_UNAVAILABLE',
                          source_sha256=None,winning_triples=[],
                          payouts_100yen=[],refund_status='UNKNOWN')
        result=link_result_revisions(bridge(),[batch(special,unavailable)])
        self.assertEqual(result['latest_observation_states']['SOURCE_UNAVAILABLE'],1)
        self.assertEqual(result['latest_observation_states']['UNSUPPORTED_SPECIAL'],1)
        self.assertIsNone(result['official_hit8_all'])
        with self.assertRaisesRegex(ResultLinkError,'INCONSISTENT_NORMAL_RESULT'):
            link_result_revisions(bridge(),[batch(label(refund_status='FULL'))])
        with self.assertRaisesRegex(ResultLinkError,'UNSCORABLE_RESULT_HAS_WINNERS'):
            link_result_revisions(bridge(),[batch(label(status='UNSUPPORTED_SPECIAL'))])

    def test_payouts_exact_and_deadheat_tickets(self):
        for amounts in ([{'triple':[1,2,4],'yen':1234}],
                        [{'triple':[1,2,3],'yen':-1}],
                        [{'triple':[1,2,3],'yen':1234.5}]):
            with self.subTest(amounts=amounts),self.assertRaises(ResultLinkError):
                link_result_revisions(bridge(),[batch(label(payouts_100yen=amounts))])
        result=link_result_revisions(bridge(),[batch(label(
            winning_triples=[[1,2,3],[1,3,2]],
            payouts_100yen=[{'triple':[1,2,3],'yen':150},
                            {'triple':[1,3,2],'yen':230}]))])
        self.assertEqual(result['latest_observation_states']['FINAL_NORMAL'],1)

    def test_future_publication_and_before_date_rejected(self):
        with self.assertRaisesRegex(ResultLinkError,'SOURCE_PUBLICATION_AFTER_OBSERVATION'):
            link_result_revisions(bridge(),[batch(label(
                source_published_at='2030-01-05T15:01:00+09:00'))])
        with self.assertRaisesRegex(ResultLinkError,'RESULT_OBSERVED_BEFORE_RACE_DATE'):
            link_result_revisions(bridge(),[batch(label(
                observed_at='2030-01-04T23:00:00+09:00'))])

    def test_cli_private_create_only(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work);p=root/'bridge.json';q=root/'batch.json';out=root/'out.json'
            p.write_text(json.dumps(bridge()),encoding='utf-8')
            q.write_text(json.dumps(batch(label())),encoding='utf-8')
            args=['--bridge',str(p),'--observation-batch',str(q),'--output',str(out)]
            with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),2)
                self.assertEqual(main(args),3)
            saved=json.loads(out.read_text(encoding='utf-8'))
            self.assertFalse(saved['formal_result_authority'])
            self.assertIsNone(saved['formal_hit_at_8_all'])

    def test_research_seal_uses_existing_scorer_and_keeps_missing_models(self):
        from race_ai.actions_contract import digest
        from race_ai.evaluation_experiment import seal_predictions
        plan={'schema':'RACE_AI_EVALUATION_PLAN_V1','experiment_id':'offline-fixture',
              'declared_at':'2030-01-01T00:00:00Z','mode':'RETROSPECTIVE_RESEARCH',
              'cohort_rule':'fictional boat','discovery_sha256':'d'*64,
              'windows':{'train_end':'2030-01-02','validation_end':'2030-01-03','test_end':DAY},
              'seen_race_ids':[],'stages':['P0'],'result_source_ids':['OFFICIAL'],
              'models':[{'model_id':name,'version':'1','code_sha256':letter*64,
                         'artifact_sha256':None,'trained_until':None,'created_at':None}
                        for name,letter in (('m1','a'),('m2','b'))],
              'comparison_groups':[['m1','m2']],
              'feature_policy':{'schema_id':'fixture','transform_sha256':'9'*64,
                                'allowed_fields':['rating']},
              'races':[{'race_id':'original-boat','sport':'boat','venue':'boatrace-jcd-01',
                        'race_no':1,'event_date_jst':DAY,'cutoff_at':'2030-01-05T03:00:00Z',
                        'participants':[1,2,3,4,5,6]}]}
        plan['eligibility']=[{'race_id':'original-boat','stage':'P0','model_id':name,
                             'eligible':True,'reason':None} for name in ('m1','m2')]
        ctx={'race_id':'original-boat','stage':'P0','as_of':'2030-01-05T02:00:00Z',
             'features':{'rating':[1,2,3,4,5,6]},
             'sources':[{'source_id':'HIST','sha256':'e'*64,
                         'captured_at':'2030-01-05T01:00:00Z','published_at':None}]}
        outs=[{'race_id':'original-boat','stage':'P0','model_id':name,
               'context_sha256':digest(ctx),'code_sha256':letter*64,
               'artifact_sha256':None,'generated_at':'2030-01-06T00:00:00Z',
               'status':'PREDICTED' if name=='m1' else 'NO_FORECAST',
               'top8':[[1,2,3]] if name=='m1' else [],
               'reason':None if name=='m1' else 'MISSING_INPUT'}
              for name,letter in (('m1','a'),('m2','b'))]
        seal=seal_predictions(plan,[ctx],outs,sealed_at='2030-01-06T00:00:01Z')
        original=copy.deepcopy(seal)
        joined=bridge()
        joined['records'][0]['archive_slots']=[
            {'source':'VERIFIED_LOCAL_EVALUATION_SEAL','archive_sha256':seal['seal_sha256'],
             'archive_race_id':'original-boat','stage':'P0','model_id':name,
             'model_version':'1','forecast_state':status}
            for name,status in (('m1','PREDICTED'),('m2','NO_FORECAST'))]
        scored=research_score_existing_seal(joined,[batch(label())],seal)
        summary={r['model_id']:r for r in scored['models']}
        self.assertEqual((summary['m1']['known_results'],summary['m1']['hit8']),(1,1))
        self.assertEqual((summary['m2']['known_results'],summary['m2']['hit8']),(1,0))
        self.assertEqual(summary['m2']['missing_prediction_known'],1)
        self.assertIsNone(scored['formal_hit_at_8_all'])
        self.assertEqual(seal,original)
        joined['records'][0]['archive_slots'].pop()
        with self.assertRaisesRegex(ResultLinkError,'INCOMPLETE_ARCHIVE_MODEL_BINDING'):
            research_score_existing_seal(joined,[batch(label())],seal)


if __name__=='__main__':
    unittest.main()
