"""Invented frozen observations exercise sparse native fitting, never coverage."""
from copy import deepcopy
from datetime import datetime
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_learning as learning
from race_ai import all_existing_model_registry as registry
from race_ai.boat_all_model_inputs import shared_snapshot_from_observed
from race_ai.boat_multi_feature_models import FEATURE_RANGES, CONDITIONS, MODEL_IDS as FULL
from race_ai.four_sport_learning import LEARNED_ID, SPARSE_VECTOR_VERSION, fit_training_only
from race_ai.observed_weight_learning import seal
from tests.test_all_existing_model_learning import observed_records
from tests.test_observed_weight_learning import NOW
from tests.test_all_existing_model_matrix import _shift_dates, native_payload


def sparse_records(mid=LEARNED_ID):
    records = []
    for old in observed_records()[::2]:
        row = deepcopy(old)
        row['model_id'] = mid
        row['native_payload'] = dict(snapshot=shared_snapshot_from_observed(old['native_payload']['snapshot']), stage='P0')
        row['input_sha256'] = digest(row['native_payload'])
        records.append(row)
    return records


def full_payload():
    old = observed_records()[0]['native_payload']['snapshot']
    entrants = []
    for p in old['participants']:
        features = {}
        for source, target, scale, offset in (
            ('national_win_rate', 'ability_rating', 10, 0),
            ('motor_top2_rate', 'motor_rating', 1, 0),
            ('recent_mean_finish', 'recent_form_rating', -20, 120),
            ('course_mean_finish', 'course_suitability_rating', -20, 120),
        ):
            if source in p['features']:
                features[target] = p['features'][source]['value']*scale+offset
        entrants.append(dict(lane=p['lane'], participant_id=p['registration_no'], features=features,
            missing={k:'NOT_AVAILABLE' for k in FEATURE_RANGES if k not in features},
            source_ref='synthetic://frozen-source', published_at=None, captured_at=old['as_of']))
    snapshot = dict(schema='RACE_AI_BOAT_MULTI_FEATURE_SNAPSHOT_SPARSE_V1', scope='SYNTHETIC_ONLY',
        race_id=old['race_id'], venue=old['venue'], event_date_jst=old['event_date_jst'],
        sales_cutoff_at=old['sales_cutoff_at'], as_of=old['as_of'], entrants=entrants,
        conditions={}, conditions_missing={k:'NOT_AVAILABLE' for k in CONDITIONS},
        conditions_source=None, conditions_published_at=None, conditions_captured_at=None)
    return dict(snapshot=snapshot, stage='P0')


class SparseNativeLearningTests(unittest.TestCase):
    def test_captured_only_alias_labels_fit_real_sparse_vectors_and_native_source_hashes(self):
        rows = sparse_records()
        fitted = learning.fit(rows, now=NOW)
        learning.verify_training(fitted)
        model = fitted['models']['boat/'+LEARNED_ID]
        self.assertEqual((model['train_races'], model['validation_races']), (6, 2))
        self.assertEqual(model['native_training']['vector_version'], SPARSE_VECTOR_VERSION)
        self.assertIn('observed_ability', model['parameters'])
        self.assertEqual(model['parameter_support_train']['observed_stamina'], 0)
        self.assertEqual(model['parameters']['observed_stamina'], 0)
        native_rows = []
        for row in rows[:6]:
            result = {k: row['result'][k] for k in ('race_id','status','ordered_top3','published_at',
                'captured_at','source_ref','source_rights_ref','source_sha256')}
            result['race_id'] = row['native_payload']['snapshot']['race']['race_id']
            native_rows.append(dict(snapshot=row['native_payload']['snapshot'], result=result))
        native = fit_training_only(native_rows, sport='boat', train_end_at=rows[5]['result']['captured_at'], now=lambda:NOW)
        self.assertEqual(model['native_training']['training_data_sha256'], native['training_data_sha256'])
        self.assertIsNotNone(model['holdout']['mean_log_loss'])

    def test_sparse_holdout_labels_do_not_fit_and_rehashed_contract_tampering_rejects(self):
        rows=sparse_records();fitted=learning.fit(rows,now=NOW)
        changed=deepcopy(rows)
        for row in changed[-2:]:row['result']['ordered_top3']=[6,5,4]
        other=learning.fit(changed,now=NOW)
        key='boat/'+LEARNED_ID
        self.assertEqual(fitted['models'][key]['parameters'],other['models'][key]['parameters'])
        for field,value in (('input_schema','RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1'),
                            ('parameter_contract_sha256','f'*64)):
            bad=deepcopy(fitted);bad['models'][key][field]=value
            seal(bad['models'][key],'model_sha256');seal(bad,'training_sha256')
            with self.subTest(field=field),self.assertRaises(ValueError):learning.verify_training(bad)

    def test_sparse_holdout_native_label_clock_and_source_hash_are_validated_before_scoring(self):
        for field,value in (('published_at','2031-01-01T00:00:00+00:00'),('source_sha256','invalid')):
            rows=sparse_records();rows[-1]['result'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):learning.fit(rows,now=NOW)

    def test_sparse_candidate_and_baseline_generate_actual_future_native_pair(self):
        fitted=learning.fit(sparse_records(),now=NOW);key='boat/'+LEARNED_ID
        payload=_shift_dates(sparse_records()[0]['native_payload'],1)
        payload['learned_model']=deepcopy(fitted['models'][key]['native_training'])
        at=datetime.fromisoformat(payload['snapshot']['race']['as_of'])
        pair=learning.forecast_pair(fitted,key,payload,now=at)
        self.assertEqual(pair['stage'],'P0')
        self.assertTrue(pair['learned']['trained'])
        self.assertEqual(len(pair['learned_normalized']['ranked']),120)
        self.assertAlmostEqual(sum(x['score'] for x in pair['learned']['candidates']),1)
        with self.assertRaises(ValueError):learning.forecast_pair(fitted,key,sparse_records()[0]['native_payload'],now=NOW)

    def test_dense_registry_pin_and_dense_parameter_contract_remain_accepted(self):
        self.assertEqual(registry.registry_sha256(),'07da538c97be334845f268a10fb0d7676d3b2cdcd7a3a922b0f7d7d798aaf3f6')
        self.assertNotIn('observed_ability',registry.specs(LEARNED_ID,'boat'))

    def test_explicit_sparse_full_p0_runs_but_dense_full_p0_stays_rejected(self):
        payload=full_payload();at=payload['snapshot']['as_of']
        for mid in FULL:
            self.assertEqual(registry.identity(mid,'boat',payload)['stage'],'P0')
            out=registry.predict(mid,'boat',payload,at=at)
            self.assertEqual(len(out['candidates']),120)
            self.assertAlmostEqual(sum(x['score'] for x in out['candidates']),1)
            dense=native_payload(mid,'boat');dense['stage']='P0'
            with self.assertRaises(ValueError):registry.validate_payload(mid,'boat',dense,at=dense['snapshot']['as_of'])

    def test_sparse_full_p0_originals_survive_cutoff_but_dense_original_cannot_be_relabeled_p0(self):
        from race_ai.existing_model_dispatch import dispatch
        payload=full_payload();snap=payload['snapshot'];rid=snap['race_id']
        schedule=[dict(race_id=rid,sport='boat',stage='P0',cutoff_at=snap['sales_cutoff_at'])]
        first=dispatch(schedule,{rid:{'P0':{'boat_full':payload}}},now=snap['as_of'])
        originals=[slot for slot in first['slots'] if slot['model_id'] in FULL]
        self.assertTrue(all(slot['status']=='GENERATED_UNATTESTED' for slot in originals))
        saved=deepcopy(originals)
        reused=dispatch(schedule,{},now=snap['sales_cutoff_at'],originals=originals)
        self.assertEqual(sum(slot['status']=='ORIGINAL_REUSED' for slot in reused['slots']),2)
        self.assertEqual(originals,saved)
        dense=native_payload(FULL[0],'boat');race=dense['snapshot']
        dense_schedule=[dict(race_id=race['race_id'],sport='boat',stage='P1',cutoff_at=race['sales_cutoff_at'])]
        generated=dispatch(dense_schedule,{race['race_id']:{'P1':{'boat_full':dense}}},now=race['as_of'])
        original=next(slot for slot in generated['slots'] if slot['model_id']==FULL[0])
        original['stage']='P0';dense_schedule[0]['stage']='P0'
        with self.assertRaises(ValueError):dispatch(dense_schedule,{},now=race['sales_cutoff_at'],originals=[original])

    def test_derived_fit_lineage_names_original_availability_without_backdating_payload_save(self):
        from race_ai.all_existing_model_derivation import derive_records
        records=derive_records(observed_records(synthetic=False),now=NOW,include_groups=('shared_learned',))
        fitted=learning.fit(records,now=NOW,allow_source=lambda *args:True,allow_training=lambda *args:True)
        learning.verify_training(fitted)
        model=fitted['models']['boat/'+LEARNED_ID]
        line=model['source_lineage'][0]
        proof=line['input_derivation']
        self.assertIs(proof['derived_payload_saved_before_cutoff'],False)
        self.assertEqual(proof['derived_at'],NOW.isoformat())
        self.assertEqual(proof['original_input_saved_at'],line['input_saved_at'])
        self.assertEqual(proof['native_input_sha256'],line['input_sha256'])
        self.assertNotIn('original_record',proof)
        bad=deepcopy(fitted);bad['models']['boat/'+LEARNED_ID]['source_lineage'][0]['input_derivation']['derived_payload_saved_before_cutoff']=True
        seal(bad['models']['boat/'+LEARNED_ID],'model_sha256');seal(bad,'training_sha256')
        with self.assertRaises(ValueError):learning.verify_training(bad)


if __name__=='__main__':unittest.main()
