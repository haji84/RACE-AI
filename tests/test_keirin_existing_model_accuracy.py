"""Invented snapshots/labels only; no requests or live accuracy assertions."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import unittest

from race_ai import keirin_nationwide_auto_generator as original
from scripts.keirin_note_collect_results import fact_digest
from tests.test_keirin_nationwide_auto_generator import fixture
from race_ai import keirin_existing_model_accuracy as research

NOW=datetime(2030,1,15,tzinfo=timezone.utc)


def row(day,n=7,winning=None):
    snap=fixture(n)
    asof=datetime(2030,1,day,0,59,tzinfo=timezone.utc).isoformat()
    generated=datetime(2030,1,day,1,tzinfo=timezone.utc).isoformat()
    cutoff=datetime(2030,1,day,3,tzinfo=timezone.utc).isoformat()
    rid='203001'+f'{day:02d}'+'9801'
    snap.update(race_id=rid,as_of=asof,published_cutoff_at=cutoff,
        line_groups=[list(range(i,min(i+2,n+1))) for i in range(1,n+1,2)])
    snap['cutoff_source']['captured_at']=asof
    for p in snap['source_pages']:p['captured_at']=asof
    for rider in snap['riders']:rider['recent_form_score']=rider['car']/(n+1)
    prediction=original.generate_A_B(snap,generated_at=generated)
    at=datetime(2030,1,day,4,tzinfo=timezone.utc).isoformat()
    result=dict(schema='RACE_AI_KEIRIN_INDEPENDENT_SECONDARY_RESULT_MATCH_V1',race_id=rid,
        state='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL',winning_triple=winning or [n,n-1,n-2],
        payout_per_100yen=1200,provider_receipts=[dict(provider='Kdreams',
            source_bytes_sha256='a'*64,observed_at=at,
            source_url='https://keirin.kdreams.jp/fictional/racedetail/98'+rid[:8]+'010001/?pageType=result'),
            dict(provider='netkeirin',source_bytes_sha256='b'*64,observed_at=at,
            source_url='https://keirin.netkeiba.com/race/result/?race_id='+rid)],
        official_primary_result_authenticated=False,actual_organizer_cutoff_authenticated=False,
        qualifies_for_formal_settlement=False,captured_at=at,previous_observation_sha256=None)
    result['observation_sha256']=fact_digest(result)
    provenance=dict(cipher_sha256='c'*64,entry_created_at=generated,kind='research',source_commit='d'*40)
    return dict(snapshot=snap,baseline=prediction,result=result,
        forecast_provenance=provenance,result_provenance={**provenance,'kind':'results','entry_created_at':at})


class ExistingModelResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=[row(day) for day in range(1,7)]
        cls.valid=[row(day) for day in (7,8)]
        cls.artifact=research.fit_candidates(cls.train,cls.valid,clock=lambda:NOW)

    def test_baseline_parameters_match_original_A_for_five_through_nine_starters(self):
        for n in range(5,10):
            r=row(1,n)
            for count in (1,8,12):
                with self.subTest(n=n,count=count):
                    self.assertEqual(research.rank_tickets(r['snapshot'],weights=research.DEFAULT_WEIGHTS,
                        generated_at=r['baseline']['generated_at'],ticket_count=count),
                        original.generate_A_B(r['snapshot'],generated_at=r['baseline']['generated_at'],
                            max_tickets=count)['A']['ranked_tickets'])

    def test_tied_and_unmarked_riders_keep_original_lexicographic_order(self):
        r=row(1)
        for rider in r['snapshot']['riders']:
            rider.update(mark_rank='UNMARKED',competition_points=80,recent_form_score=.2,h_count=0,b_count=0)
        expected=original.generate_A_B(r['snapshot'],generated_at=r['baseline']['generated_at'])['A']['ranked_tickets'][:8]
        self.assertEqual(research.rank_tickets(r['snapshot'],generated_at=r['baseline']['generated_at']),expected)

    def test_actual_training_changes_coefficients_and_improves_independent_invented_validation(self):
        artifact=self.artifact
        self.assertEqual(artifact['model_id'],original.MODEL_A)
        self.assertNotEqual(artifact['weights'],list(research.DEFAULT_WEIGHTS))
        self.assertEqual(artifact['validation_baseline']['hits'],0)
        self.assertEqual(artifact['validation_selected']['hits'],2)
        self.assertEqual(artifact['validation_selected']['n'],2)
        self.assertFalse(artifact['calibrated'])
        self.assertFalse(artifact['production_promoted'])

    def test_parameters_and_selection_are_deterministic(self):
        second=research.fit_candidates(deepcopy(self.train),deepcopy(self.valid),clock=lambda:NOW)
        self.assertEqual(second,self.artifact)
        self.assertEqual(self.artifact['trained_examples'],6)
        self.assertEqual(self.artifact['validation_examples'],2)

    def test_training_and_scoring_do_not_mutate_source_or_original(self):
        source=row(1);before=deepcopy(source)
        research.score_records([source])
        research.rank_tickets(source['snapshot'],weights=self.artifact['weights'],generated_at=source['baseline']['generated_at'])
        self.assertEqual(source,before)

    def test_short_or_overlapping_training_validation_are_rejected(self):
        with self.assertRaises(ValueError):research.fit_candidates(self.train[:5],self.valid,clock=lambda:NOW)
        with self.assertRaises(ValueError):research.fit_candidates(self.train,[self.train[0],self.valid[0]],clock=lambda:NOW)
        with self.assertRaises(ValueError):research.fit_candidates([*self.train[:5],self.valid[0]],self.valid,clock=lambda:NOW)

    def test_duplicate_revisions_cannot_increase_denominator(self):
        with self.assertRaises(ValueError):research.score_records([row(1),row(1)])

    def test_training_label_must_be_available_before_first_validation_input(self):
        train=deepcopy(self.train)
        captured=self.valid[0]['snapshot']['as_of']
        train[-1]['result']['captured_at']=captured
        train[-1]['result_provenance']['entry_created_at']=captured
        with self.assertRaisesRegex(ValueError,'TRAIN_LABEL_AFTER_VALIDATION_INPUT'):
            research.fit_candidates(train,self.valid,clock=lambda:NOW)

    def test_held_results_are_not_losses_or_training_labels(self):
        r=row(1);r['result'].update(state='HOLD_RESULT_SOURCE_UNAVAILABLE',winning_triple=None,
            payout_per_100yen=None,provider_receipts=[])
        r['result']['observation_sha256']=fact_digest(r['result'])
        with self.assertRaises(ValueError):research.score_records([r])

    def test_lookahead_input_or_result_identity_mismatch_are_rejected(self):
        r=row(1);r['forecast_provenance']['entry_created_at']=r['snapshot']['published_cutoff_at']
        with self.assertRaises(ValueError):research.score_records([r])
        r=row(1);r['result']['race_id']='203001029801';r['result']['observation_sha256']=fact_digest(r['result'])
        with self.assertRaises(ValueError):research.score_records([r])

    def test_missing_features_invalid_weights_and_noninteger_ticket_counts_are_rejected(self):
        r=row(1)
        for weights in ([float('nan'),.3,.14,.06,.055],[-.5,.3,.14,1.06,.055],[.5,.3,.14,.06,.3],[0,0,0,0,.055]):
            with self.subTest(weights=weights),self.assertRaises(ValueError):
                research.rank_tickets(r['snapshot'],weights=weights,generated_at=r['baseline']['generated_at'])
        for count in (True,0,13):
            with self.assertRaises(ValueError):research.rank_tickets(r['snapshot'],generated_at=r['baseline']['generated_at'],ticket_count=count)
        del r['snapshot']['riders'][0]['competition_points']
        with self.assertRaises(ValueError):research.rank_tickets(r['snapshot'],generated_at=r['baseline']['generated_at'])

    def test_artifact_is_locked_against_tampering_or_other_model_family(self):
        r=row(16);at=datetime(2030,1,16,1,tzinfo=timezone.utc)
        artifact=deepcopy(self.artifact);artifact['weights'][0]+=.01
        with self.assertRaises(ValueError):research.forecast_candidate(r['snapshot'],artifact,clock=lambda:at)
        artifact=deepcopy(self.artifact);artifact['model_id']='invented-new-family'
        artifact['artifact_sha256']=original.digest({k:v for k,v in artifact.items() if k!='artifact_sha256'})
        with self.assertRaises(ValueError):research.forecast_candidate(r['snapshot'],artifact,clock=lambda:at)

    def test_future_shadow_uses_actual_generation_clock_and_equal_eight_ticket_budget(self):
        r=row(16);at=datetime(2030,1,16,1,tzinfo=timezone.utc)
        out=research.forecast_candidate(r['snapshot'],self.artifact,clock=lambda:at)
        self.assertEqual(out['generated_at'],at.isoformat())
        self.assertEqual(len(out['ranked_tickets']),8)
        self.assertEqual(len(out['baseline_ranked_tickets']),8)
        self.assertEqual(out['candidate_sha256'],self.artifact['artifact_sha256'])
        self.assertFalse(out['forward_improvement_proven'])
        self.assertFalse(out['production_promoted'])
        self.assertFalse(out['calibrated'])

    def test_self_inconsistent_artifact_clock_or_extra_test_data_is_rejected(self):
        r=row(16);at=datetime(2030,1,16,1,tzinfo=timezone.utc)
        for field,value in (('created_at','2030-01-01T00:00:00+00:00'),('test_rows',[])):
            with self.subTest(field=field):
                artifact=deepcopy(self.artifact);artifact[field]=value
                artifact['artifact_sha256']=original.digest({k:v for k,v in artifact.items() if k!='artifact_sha256'})
                with self.assertRaises(ValueError):research.forecast_candidate(r['snapshot'],artifact,clock=lambda:at)

    def test_forecast_before_artifact_creation_or_inside_cutoff_margin_is_rejected(self):
        r=row(16)
        for at in (NOW-timedelta(seconds=1),datetime(2030,1,16,2,59,tzinfo=timezone.utc)):
            with self.assertRaises(ValueError):research.forecast_candidate(r['snapshot'],self.artifact,clock=lambda:at)

    def test_future_cutoff_cannot_hide_input_preceding_training(self):
        r=row(16);old='2030-01-01T00:00:00+00:00'
        r['snapshot']['as_of']=old;r['snapshot']['cutoff_source']['captured_at']=old
        for source in r['snapshot']['source_pages']:source['captured_at']=old
        with self.assertRaises(ValueError):
            research.forecast_candidate(r['snapshot'],self.artifact,
                clock=lambda:datetime(2030,1,16,1,tzinfo=timezone.utc))

    def test_fit_has_no_test_label_parameter_or_future_label_access(self):
        with self.assertRaises(TypeError):
            research.fit_candidates(self.train,self.valid,test_rows=[row(9)],clock=lambda:NOW)
        with self.assertRaises(ValueError):
            research.fit_candidates(self.train,self.valid,clock=lambda:datetime(2030,1,7,tzinfo=timezone.utc))


if __name__=='__main__':unittest.main()
