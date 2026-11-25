"""Invented sealed-note fixtures; no real forecast or result inputs are read."""
from datetime import datetime, timezone
from hashlib import sha256
import importlib
from itertools import permutations
import json
from math import log
import unittest

from race_ai.keirin_joint_finish import JointFinish
from race_ai.keirin_joint_forecast import build_forecast
from race_ai.keirin_nationwide_auto_generator import canonical, digest
from tests.test_keirin_forward_score import fixtures as result_fixtures


DAY = '2026-11-25'
NOW = datetime(2026, 11, 25, 20, tzinfo=timezone.utc)
GENERATED = DAY+'T05:00:00Z'
CREATED = DAY+'T05:00:00.500000Z'


def entry(value):
    raw=canonical(value)
    return dict(text=raw.decode(), bytes=len(raw), sha256=sha256(raw).hexdigest())


def fixture():
    _, _, roster, results=result_fixtures()
    cars=(1,2,3,4)
    inputs=[]
    for row in roster['races']:
        row['observed_riders']=[dict(number=car) for car in cars]
        inputs.append(dict(race_id=row['race_id'], cutoff_at=row['published_cutoff_at'],
            source_as_of=DAY+'T04:55:00Z', forecast_generated_at=GENERATED,
            roster=[dict(car=car,name='INVENTED PRIVATE RIDER '+str(car),registration=None) for car in cars],
            input=dict(race_id=row['race_id'],line_groups=[[1,2],[3,4]],
                riders=[dict(car=car,competition_points=80+car) for car in cars])))
    source=entry(dict(schema='RACE_AI_KEIRIN_COMPARISON_INPUTS_V1',races=inputs))
    baseline_orders=[(1,2,3),(2,1,3),(1,3,2),(3,1,2),(4,1,2),(4,2,1),(2,3,1),(3,2,1)]
    current_orders=[(3,1,2),(2,1,3),(4,1,2),(4,2,1),(1,2,3),(1,3,2),(2,3,1),(3,2,1)]
    records=[]
    for model,orders in [('baseline-private-model',baseline_orders),('current-private-model',current_orders)]:
        probabilities=dict.fromkeys(permutations(cars,3),0.)
        probabilities.update(zip(orders,(.5,.2,.12,.08,.05,.03,.015,.005),strict=True))
        joint=JointFinish(cars,probabilities)
        records.append([build_forecast(joint,race_id=row['race_id'],generated_at=GENERATED,
            cutoff_at=row['cutoff_at'],source_as_of=row['source_as_of'],model_id=model,
            model_version='invented-identical-weights-v1',input_sha256=digest(row['input']),
            source_packet_sha256=source['sha256'],source_forecast_generated_at=GENERATED,riders=row['roster'])
            for row in inputs])
    note=dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1',formal_model_admission=False,
        production_weight_switch=False,imported_at=GENERATED,dates=[DAY],files={
            f'data/{DAY}/comparison_inputs.json':source,
            f'data/{DAY}/comparison_baselines.json':entry(dict(races=records[0])),
            f'data/{DAY}/comparison_joint_originals.json':entry(dict(races=records[1]))})
    ids=[row['race_id'] for row in inputs]
    publication=dict(schema='KEIRIN_JOINT_COMPARISON_FREEZE_RECEIPT_V1',generated_at=GENERATED,
        original_snapshot_created_at=CREATED,git_readback_at=DAY+'T05:01:00Z',
        cipher_sha256='a'*64,race_ids=ids,races=len(ids),
        cutoffs={row['race_id']:row['cutoff_at'] for row in inputs},
        pre_cutoff_git_readback=True,private_plaintext_uploaded=False,production_weights_promoted=False,
        publication=dict(source_commit='c'*40,state='KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED'))
    witness=dict(state='INDEPENDENT_RUNNER_CIPHER_SHA_READBACK_VERIFIED',archive_commit='c'*40,
        cipher_sha256='a'*64,observed_at=DAY+'T05:02:00Z',registered_comparison_races=len(ids),
        still_pre_cutoff_races=len(ids),plaintext_decrypted=False,private_key_used=False,
        formal_pre_cutoff_original_authenticated=False,action_run=1,job_id=2)
    return note,publication,witness,roster,results


class JointForwardScoreTests(unittest.TestCase):
    def setUp(self):
        self.note,self.publication,self.witness,self.roster,self.results=fixture()
        self.reseal()

    def api(self):
        try:
            module=importlib.import_module('scripts.keirin_joint_forward_score')
        except ModuleNotFoundError:
            self.fail('The joint-to-existing-forward-score adapter is not implemented.')
        return module.score_joint

    def reseal(self):
        self.note_raw=canonical(self.note)
        self.expected=sha256(self.note_raw).hexdigest()
        self.publication['original_note_sha256']=self.expected

    def mutate_file(self,name,change):
        key=f'data/{DAY}/{name}'
        document=json.loads(self.note['files'][key]['text'])
        change(document)
        self.note['files'][key]=entry(document)
        self.reseal()

    def score(self,**kwargs):
        return self.api()(self.note_raw,canonical(self.publication),canonical(self.witness),
            canonical(self.roster),canonical(self.results),expected_note_sha256=self.expected,
            clock=lambda:NOW,**kwargs)

    def test_existing_primary_score_and_nested_points_use_only_matched_top_three(self):
        before=self.note_raw
        report=self.score()
        self.assertEqual((report['registered'],report['matched'],report['tickets_per_arm']),(6,3,12))
        self.assertEqual((report['published_hits'],report['trial_hits']),(3,2))
        self.assertEqual(report['result_states'],dict(matched=3,held=1,pending=1,missing=1))
        self.assertEqual(report['lost'],['202611256202'])
        self.assertEqual(report['trifecta_by_points']['1']['published_hits'],1)
        self.assertEqual(report['trifecta_by_points']['1']['trial_hits'],1)
        self.assertEqual(report['trifecta_by_points']['4']['trial_hits'],2)
        self.assertEqual(report['trifecta_by_points']['8']['trial_hits'],3)
        self.assertEqual(report['exacta_top2'],dict(matched=3,tickets_per_arm=6,published_hits=2,trial_hits=2))
        self.assertEqual(self.note_raw,before)

    def test_derived_receipt_preserves_real_creation_and_normalization_clocks_without_flow_promotion(self):
        report=self.score()
        self.assertEqual(report['receipt_frozen_at'],CREATED)
        self.assertEqual(report['receipt_normalized_at'],NOW.isoformat())
        self.assertIn('DERIVED',report['receipt_timestamp_semantics'])
        self.assertIn('POST_CUTOFF',report['receipt_timestamp_semantics'])
        self.assertEqual(report['original_note_sha256'],self.expected)
        self.assertEqual(report['original_plaintext_authentication'],'PENDING_RSA_READBACK')
        self.assertEqual(report['flow_state'],'NO_PRE_CUTOFF_FLOW_ORIGINAL')
        self.assertIs(report['formalPR71'],False)
        self.assertIs(report['accuracy_improvement_proven'],False)
        serialized=json.dumps(report)
        for private in ('INVENTED PRIVATE RIDER','baseline-private-model','current-private-model','rank_probabilities','trifectas','winning_3t'):
            self.assertNotIn(private,serialized)

    def test_external_note_identity_and_receipt_note_identity_are_required(self):
        with self.assertRaisesRegex(ValueError,'NOTE_SHA256'):
            self.api()(self.note_raw,canonical(self.publication),canonical(self.witness),canonical(self.roster),
                canonical(self.results),expected_note_sha256='f'*64,clock=lambda:NOW)
        self.publication['original_note_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'NOTE_SHA256'):
            self.score()

    def test_nested_entry_bytes_and_sha_cannot_be_substituted(self):
        for field,value in [('bytes',1),('sha256','f'*64)]:
            with self.subTest(field=field):
                self.setUp()
                self.note['files'][f'data/{DAY}/comparison_baselines.json'][field]=value
                self.reseal()
                with self.assertRaisesRegex(ValueError,'ENTRY_'):
                    self.score()

    def test_source_packet_bytes_and_canonical_input_identity_are_bound(self):
        self.mutate_file('comparison_inputs.json',lambda doc:doc['races'][0]['input']['riders'][0].update(competition_points=99))
        with self.assertRaisesRegex(ValueError,'SOURCE_PACKET_SHA256'):
            self.score()
        self.setUp()
        self.mutate_file('comparison_joint_originals.json',lambda doc:doc['races'][0].update(input_sha256='f'*64))
        with self.assertRaisesRegex(ValueError,'INPUT_SHA256|PAIRED_'):
            self.score()

    def test_late_generation_or_witness_is_not_a_pre_cutoff_prediction(self):
        for name in ('comparison_baselines.json','comparison_joint_originals.json'):
            self.mutate_file(name,lambda doc:[row.update(generated_at=DAY+'T05:00:01Z') for row in doc['races']])
        with self.assertRaisesRegex(ValueError,'LATE_FORECAST'):
            self.score()
        self.setUp()
        self.witness['observed_at']=DAY+'T07:00:00Z'
        with self.assertRaisesRegex(ValueError,'PRE_CUTOFF'):
            self.score()

    def test_a_missing_comparison_race_cannot_shrink_the_registered_cohort(self):
        for name in ('comparison_baselines.json','comparison_joint_originals.json','comparison_inputs.json'):
            with self.subTest(name=name):
                self.setUp()
                self.mutate_file(name,lambda doc:doc['races'].pop())
                with self.assertRaisesRegex(ValueError,'COHORT'):
                    self.score()

    def test_missing_outcomes_remain_unscored_without_changing_the_cohort(self):
        self.results['races']=[]
        report=self.score()
        self.assertEqual((report['registered'],report['matched'],report['tickets_per_arm']),(6,0,0))
        self.assertEqual(report['result_states'],dict(missing=6))
        self.assertEqual(report['exacta_top2']['matched'],0)
        self.assertEqual(report['trifecta_by_points']['8']['trial_hits'],0)

    def test_probability_scores_use_only_confirmed_ordered_results_and_are_opt_in(self):
        public = self.score()
        private = self.score(include_probability_metrics=True)
        evaluation = private.pop('probability_evaluation')
        self.assertEqual(private, public)
        self.assertEqual(evaluation['matched'], 3)
        self.assertIs(evaluation['full_finish_verified'], False)
        baseline = evaluation['published']
        trifecta = baseline['ordered_trifecta']
        self.assertAlmostEqual(trifecta['brier'], 0.79445)
        self.assertAlmostEqual(trifecta['log_loss'], -(log(.08) + log(.5) + log(.2)) / 3)
        self.assertEqual(trifecta['zero_probability_outcomes'], 0)
        four = baseline['trifecta_top_n']['4']
        self.assertAlmostEqual(four['mean_probability'], .9)
        self.assertEqual(four['hits'], 3)
        self.assertAlmostEqual(four['brier'], .01)
        self.assertEqual([bin['count'] for bin in four['bins']], [0, 0, 0, 0, 3])
        self.assertEqual(evaluation['trial']['trifecta_top_n']['4']['hits'], 2)
        self.assertEqual(baseline['exacta_top_2']['hits'], 2)
        self.assertEqual(set(baseline['by_rank']), {'1', '2', '3'})
        self.assertNotIn('20261125620', json.dumps(evaluation))

    def test_zero_probability_outcomes_are_counted_and_empty_denominators_stay_null(self):
        matched = self.results['races'][0]['comparison']
        matched['winning_3t'], matched['winning_2t'] = [1, 2, 4], [1, 2]
        report = self.score(include_probability_metrics=True)['probability_evaluation']
        for side in ('published', 'trial'):
            triple = report[side]['ordered_trifecta']
            self.assertEqual(triple['zero_probability_outcomes'], 1)
            self.assertIsNone(triple['log_loss'])
            self.assertIsNotNone(triple['brier'])

        self.results['races'] = []
        empty = self.score(include_probability_metrics=True)['probability_evaluation']
        self.assertEqual(empty['matched'], 0)
        self.assertIsNone(empty['published']['ordered_trifecta']['brier'])
        self.assertIsNone(empty['published']['trifecta_top_n']['1']['mean_probability'])

    def test_arm_identity_and_original_distribution_consistency_are_enforced(self):
        for change in (lambda row:row.update(model_version='different-weights'),
                       lambda row:row['riders'][0].update(name='SOMEONE ELSE')):
            with self.subTest(change=change):
                self.setUp()
                self.mutate_file('comparison_joint_originals.json',lambda doc:change(doc['races'][0]))
                with self.assertRaisesRegex(ValueError,'PAIRED_|RIDER_IDENTITY'):
                    self.score()
        self.setUp()
        self.mutate_file('comparison_joint_originals.json',lambda doc:doc['races'][0]['trifectas'][0].update(probability=.99))
        with self.assertRaises(ValueError):
            self.score()

    def test_archive_identity_and_import_clock_cannot_borrow_another_witness(self):
        self.witness['cipher_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'ARCHIVE'):
            self.score()
        self.setUp()
        self.note['imported_at']=DAY+'T05:00:00.100000Z'
        self.reseal()
        with self.assertRaisesRegex(ValueError,'IMPORT_CLOCK'):
            self.score()


if __name__=='__main__':
    unittest.main()
