"""Synthetic training summaries exercise lineage/version admission only."""
from copy import deepcopy
from datetime import timedelta
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_derivation as derivation
from race_ai import all_existing_model_learning as learning
from race_ai import all_existing_model_registry as registry
from race_ai import four_sport_learning as ranker
from race_ai.four_sport_learning import LEARNED_ID
from race_ai.observed_weight_learning import seal, ts
from tests.test_all_existing_model_learning import observed_records
from tests.test_observed_weight_learning import NOW
from tests.test_nonboat_sparse_contracts import training_rows


KEY = 'boat/' + LEARNED_ID
V2_SCHEMA = 'RACE_AI_EXISTING_MODEL_INPUT_DERIVATION_V2'
V2_ID = 'NATIVE_OBSERVED_CAPSULE_TO_EXISTING_SPARSE_NATIVE_V2'
V2_BASIS = 'DERIVED_FROM_AUTHENTICATED_PRE_CUTOFF_NATIVE_CAPSULE'


def reseal(training):
    for model in training['models'].values():
        seal(model, 'model_sha256')
    seal(training, 'training_sha256')
    return training


class DerivationLineageV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records = derivation.derive_records(
            observed_records(synthetic=False), now=NOW, include_groups=('shared_learned',))
        cls.v1 = learning.fit(records, now=NOW, allow_source=lambda *args: True,
                              allow_training=lambda *args: True)
        # These are training-summary fixtures, not independent archive receipts.
        # Complete original-record replay is exercised by derivation's tests.
        cls.v2 = deepcopy(cls.v1)
        originals = {row['race_id']: row['input_derivation'] for row in records}
        for line in cls.v2['models'][KEY]['source_lineage']:
            proof = deepcopy(originals[line['race_id']])
            proof.update(schema=V2_SCHEMA, derivation_id=V2_ID,
                         data_availability_basis=V2_BASIS,
                         original_input_receipt_sha256=digest(proof['original_input_receipt']),
                         historical_native_payload_bytes=False)
            line['input_derivation'] = {k: v for k, v in proof.items() if k != 'original_record'}
            line['input_derivation_sha256'] = digest(proof)
        reseal(cls.v2)

    def line(self, training):
        return training['models'][KEY]['source_lineage'][0]

    def test_v2_summary_binds_receipt_without_claiming_historical_native_bytes(self):
        before = deepcopy(self.v2)
        self.assertTrue(learning.verify_training(self.v2))
        self.assertEqual(self.v2, before)
        proof = self.line(self.v2)['input_derivation']
        self.assertEqual(proof['original_input_receipt_sha256'], digest(proof['original_input_receipt']))
        self.assertIs(proof['historical_native_payload_bytes'], False)
        self.assertNotIn('original_record', proof)

    def test_v2_receipt_and_false_flags_cannot_be_rehashed_away(self):
        changes = (
            ('receipt_changed', lambda proof: proof['original_input_receipt'].update(artifact_id=999)),
            ('receipt_hash', lambda proof: proof.update(original_input_receipt_sha256='f' * 64)),
            ('historical_bytes_true', lambda proof: proof.update(historical_native_payload_bytes=True)),
            ('historical_bytes_zero', lambda proof: proof.update(historical_native_payload_bytes=0)),
            ('historical_saved_true', lambda proof: proof.update(derived_payload_saved_before_cutoff=True)),
            ('historical_saved_zero', lambda proof: proof.update(derived_payload_saved_before_cutoff=0)),
        )
        for name, mutate in changes:
            bad = deepcopy(self.v2)
            mutate(self.line(bad)['input_derivation'])
            reseal(bad)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'DERIVATION_LINEAGE'):
                learning.verify_training(bad)

    def test_v2_exact_schema_contract_rejects_missing_extra_and_mixed_version_fields(self):
        changes = (
            ('missing_receipt_hash', lambda proof: proof.pop('original_input_receipt_sha256')),
            ('missing_historical_flag', lambda proof: proof.pop('historical_native_payload_bytes')),
            ('extra', lambda proof: proof.update(unverified=True)),
            ('v1_schema', lambda proof: proof.update(schema=derivation.SCHEMA)),
            ('v1_id', lambda proof: proof.update(derivation_id=derivation.DERIVATION_ID)),
            ('v1_basis', lambda proof: proof.update(data_availability_basis=derivation.AVAILABILITY_BASIS)),
        )
        for name, mutate in changes:
            bad = deepcopy(self.v2)
            mutate(self.line(bad)['input_derivation'])
            reseal(bad)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'DERIVATION_LINEAGE'):
                learning.verify_training(bad)

    def test_v2_keeps_original_clock_source_and_native_input_bindings(self):
        changes = (
            ('payload', lambda proof, line: proof.update(native_input_sha256='a' * 64)),
            ('as_of', lambda proof, line: proof.update(original_as_of=line['cutoff_at'])),
            ('cutoff', lambda proof, line: proof.update(original_cutoff_at=line['as_of'])),
            ('saved', lambda proof, line: proof.update(original_input_saved_at=line['cutoff_at'])),
            ('before_save', lambda proof, line: proof.update(
                derived_at=(ts(line['input_saved_at'])-timedelta(seconds=1)).isoformat())),
            ('after_creation', lambda proof, line: proof.update(derived_at=(NOW+timedelta(seconds=1)).isoformat())),
            ('original_model', lambda proof, line: proof.update(original_model_id=LEARNED_ID)),
            ('source_hash', lambda proof, line: proof.update(original_snapshot_sha256='invalid')),
        )
        for name, mutate in changes:
            bad = deepcopy(self.v2)
            line = self.line(bad)
            mutate(line['input_derivation'], line)
            reseal(bad)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'DERIVATION_LINEAGE_BINDING'):
                learning.verify_training(bad)

    def test_v1_summary_remains_accepted_with_its_exact_old_fieldset(self):
        before = deepcopy(self.v1)
        self.assertTrue(learning.verify_training(self.v1))
        self.assertEqual(self.v1, before)
        for field, value in (('original_input_receipt_sha256', 'a' * 64),
                             ('historical_native_payload_bytes', False)):
            bad = deepcopy(self.v1)
            self.line(bad)['input_derivation'][field] = value
            reseal(bad)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'DERIVATION_LINEAGE'):
                learning.verify_training(bad)

    def test_v2_cannot_claim_an_observed_original_was_itself_a_derived_target(self):
        bad = learning.fit(observed_records(synthetic=False), now=NOW,
                           allow_source=lambda *args: True, allow_training=lambda *args: True)
        model = next(iter(bad['models'].values()))
        line = model['source_lineage'][0]
        proof = deepcopy(self.line(self.v2)['input_derivation'])
        proof['native_input_sha256'] = line['input_sha256']
        line.update(input_derivation=proof, input_derivation_sha256='a' * 64,
                    input_save_semantics='ORIGINAL_OBSERVATION_AVAILABILITY_BOUND')
        reseal(bad)
        with self.assertRaisesRegex(ValueError, 'DERIVATION_LINEAGE_BINDING'):
            learning.verify_training(bad)

    def test_v1_cannot_claim_an_observed_original_was_itself_a_derived_target(self):
        bad = learning.fit(observed_records(synthetic=False), now=NOW,
                           allow_source=lambda *args: True, allow_training=lambda *args: True)
        line = next(iter(bad['models'].values()))['source_lineage'][0]
        proof = deepcopy(self.line(self.v1)['input_derivation'])
        proof['native_input_sha256'] = line['input_sha256']
        line.update(input_derivation=proof, input_derivation_sha256='a' * 64,
                    input_save_semantics='ORIGINAL_OBSERVATION_AVAILABILITY_BOUND')
        reseal(bad)
        with self.assertRaisesRegex(ValueError, 'DERIVATION_LINEAGE_BINDING'):
            learning.verify_training(bad)


def nonboat_sparse_records(sport):
    records = []
    size = 7 if sport == 'keirin' else 3
    for native in training_rows(sport, 8):
        snapshot = native['snapshot']
        snapshot['participants'] = snapshot['participants'][:size]
        payload = dict(snapshot=snapshot, stage='P1', scope='SYNTHETIC_ONLY')
        info = registry.identity(LEARNED_ID, sport, payload)
        result = deepcopy(native['result'])
        result.update(sport=sport, identity_verified=True, roster=info['roster'],
                      payout_per_100_yen=1500, refund_numbers=[])
        records.append(dict(model_id=LEARNED_ID, sport=sport, race_id=info['race_id'],
            stage=info['stage'], scope=info['scope'], as_of=info['as_of'],
            cutoff_at=info['cutoff_at'], native_payload=payload, input_sha256=digest(payload),
            input_saved_at=(ts(info['as_of'])+timedelta(seconds=1)).isoformat(),
            input_receipt=dict(kind='SYNTHETIC_ONLY', independently_attested=False), result=result))
    return records


class SportSpecificSparseTrainingVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training = {sport: learning.fit(nonboat_sparse_records(sport), now=NOW)
                        for sport in ('keirin', 'autorace', 'horse')}

    def test_actual_native_sparse_fits_verify_with_their_own_sport_versions(self):
        for sport, training in self.training.items():
            with self.subTest(sport=sport):
                model = training['models'][sport+'/'+LEARNED_ID]
                versions = ranker.sparse_versions(sport)
                self.assertEqual(model['native_training']['vector_version'], versions['vector_version'])
                self.assertEqual(model['native_training']['model_version'], versions['train_only_version'])
                self.assertEqual((model['train_races'], model['validation_races']), (6, 2))
                self.assertTrue(learning.verify_training(training))

    def test_boat_only_native_derivation_cannot_be_attached_to_another_sport(self):
        original = derivation.derive_records(observed_records(synthetic=False), now=NOW,
                                             include_groups=('shared_learned',))[0]['input_derivation']
        for sport, training in self.training.items():
            bad = deepcopy(training)
            line = bad['models'][sport+'/'+LEARNED_ID]['source_lineage'][0]
            proof = deepcopy(original)
            proof.update(schema=V2_SCHEMA, derivation_id=V2_ID, data_availability_basis=V2_BASIS,
                original_input_receipt_sha256=digest(proof['original_input_receipt']),
                historical_native_payload_bytes=False, native_input_sha256=line['input_sha256'],
                original_as_of=line['as_of'], original_cutoff_at=line['cutoff_at'],
                original_input_saved_at=line['input_saved_at'])
            line.update(input_derivation={k:v for k,v in proof.items() if k != 'original_record'},
                input_derivation_sha256=digest(proof),
                input_save_semantics='ORIGINAL_OBSERVATION_AVAILABILITY_BOUND')
            reseal(bad)
            with self.subTest(sport=sport), self.assertRaisesRegex(ValueError, 'DERIVATION_LINEAGE_BINDING'):
                learning.verify_training(bad)

    def test_boat_only_v1_derivation_cannot_be_attached_to_another_sport(self):
        original = derivation.derive_records(observed_records(synthetic=False), now=NOW,
                                             include_groups=('shared_learned',))[0]['input_derivation']
        for sport, training in self.training.items():
            bad = deepcopy(training)
            line = bad['models'][sport+'/'+LEARNED_ID]['source_lineage'][0]
            proof = deepcopy(original)
            proof.update(native_input_sha256=line['input_sha256'], original_as_of=line['as_of'],
                original_cutoff_at=line['cutoff_at'], original_input_saved_at=line['input_saved_at'])
            line.update(input_derivation={k:v for k,v in proof.items() if k != 'original_record'},
                input_derivation_sha256=digest(proof),
                input_save_semantics='ORIGINAL_OBSERVATION_AVAILABILITY_BOUND')
            reseal(bad)
            with self.subTest(sport=sport), self.assertRaisesRegex(ValueError, 'DERIVATION_LINEAGE_BINDING'):
                learning.verify_training(bad)

    def test_other_sport_dense_and_chronological_tags_cannot_relabel_train_only_fits(self):
        for sport, training in self.training.items():
            wrong = 'horse' if sport != 'horse' else 'keirin'
            versions = ranker.sparse_versions(wrong)
            bad_tags = (
                ('vector_version', versions['vector_version']),
                ('model_version', versions['train_only_version']),
                ('vector_version', ranker.SPARSE_VECTOR_VERSION),
                ('model_version', ranker.SPARSE_TRAIN_ONLY_VERSION),
                ('vector_version', ranker.VECTOR_VERSION),
                ('model_version', ranker.TRAIN_ONLY_VERSION),
                ('model_version', ranker.sparse_versions(sport)['chronological_version']),
            )
            for field, value in bad_tags:
                bad = deepcopy(training)
                native = bad['models'][sport+'/'+LEARNED_ID]['native_training']
                native[field] = value
                seal(native, 'model_sha256')
                reseal(bad)
                with self.subTest(sport=sport, field=field, value=value), self.assertRaisesRegex(
                        ValueError, 'NATIVE_TRAINING_BINDING'):
                    learning.verify_training(bad)


if __name__ == '__main__':
    unittest.main()
