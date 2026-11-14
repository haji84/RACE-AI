"""Invented owner decisions and encrypted research candidates; no external I/O."""
import base64
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai.existing_model_coverage import catalog
from tests.test_boat_venue_learning import NOW, POINTER
from tests.test_boat_venue_research import SOURCE, CONTENT, B_RIGHTS
from tests.test_boat_venue_history_handoff import MemoryGit


class AllModelOwnerDecisionTests(unittest.TestCase):
    def setUp(self):
        self.owner = base64.b64encode(os.urandom(32)).decode()
        self.environment = patch.dict(os.environ, RACE_AI_STATE_KEY=self.owner)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.refs = [('https://www.boatrace.jp/fictional/frozen-input', B_RIGHTS)]

    def arguments(self, **changes):
        from race_ai.all_existing_model_registry import registry_sha256
        values = dict(source_pointer=deepcopy(SOURCE), state_content_sha256=CONTENT,
            dataset_pointer=deepcopy(POINTER), source_refs=deepcopy(self.refs),
            intake_sha256='d'*64, registry_sha256=registry_sha256(), now=NOW)
        values.update(changes)
        return values

    def issue(self, **changes):
        from race_ai.all_existing_model_research import issue_decision
        return issue_decision(**self.arguments(**changes), expires_at=NOW+timedelta(days=30))

    def test_decision_binds_all_existing_families_and_applicable_cells(self):
        from race_ai.all_existing_model_research import verify_decision
        record = self.issue()
        decision = record['decision']
        self.assertEqual(decision['purpose'], 'EXISTING_ALL_FAMILIES_SHADOW_FIT')
        self.assertEqual(decision['registered_model_ids'], [r['model_id'] for r in catalog()])
        self.assertEqual(decision['model_cells'], sorted(sport+'/'+row['model_id']
            for row in catalog() for sport in row['applicable_sports']))
        self.assertEqual(len(decision['model_cells']), 31)
        self.assertEqual(verify_decision(record, **self.arguments()), digest(record))
        for field in ('provider_permission_confirmed', 'production_promoted',
                      'commercial_use_permitted', 'public_raw_data_permitted'):
            self.assertIs(decision[field], False)
        self.assertNotIn('source_refs', decision)

    def test_every_private_intake_pointer_and_source_set_is_bound(self):
        from race_ai.all_existing_model_research import verify_decision
        record = self.issue()
        source = deepcopy(SOURCE); source['source_commit'] = 'f'*40
        dataset = deepcopy(POINTER); dataset['source_commit'] = 'f'*40
        variants = [dict(source_pointer=source), dict(dataset_pointer=dataset),
            dict(state_content_sha256='f'*64), dict(intake_sha256='f'*64),
            dict(registry_sha256='f'*64),
            dict(source_refs=self.refs+[('https://www.boatrace.jp/fictional/another', B_RIGHTS)])]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_decision(record, **self.arguments(**change))

    def test_old_two_family_decision_is_never_widened(self):
        from race_ai.all_existing_model_research import verify_decision
        from race_ai.boat_venue_research import issue_owner_research_decision
        arguments = self.arguments()
        old = issue_owner_research_decision(**{k:v for k,v in arguments.items()
            if k not in ('intake_sha256', 'registry_sha256')}, expires_at=NOW+timedelta(days=30))
        with self.assertRaises(ValueError):
            verify_decision(old, **arguments)

    def test_tampering_wrong_owner_future_and_expiry_are_rejected(self):
        from race_ai.all_existing_model_research import verify_decision
        record = self.issue()
        forged = deepcopy(record); forged['mac'] = '0'*64
        altered = deepcopy(record); altered['decision']['model_cells'].pop()
        for candidate in (forged, altered):
            with self.assertRaises(ValueError):
                verify_decision(candidate, **self.arguments())
        for moment in (NOW-timedelta(microseconds=1), NOW+timedelta(days=30)):
            with self.assertRaises(ValueError):
                verify_decision(record, **self.arguments(now=moment))
        with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode()):
            with self.assertRaises(ValueError):
                verify_decision(record, **self.arguments())

    def test_signed_wrong_scope_and_omitted_fields_still_fail(self):
        from race_ai.all_existing_model_research import verify_decision, _mac
        record = self.issue()
        for field, value in (('purpose', 'EXISTING_TWO_FAMILY_SHADOW_FIT'),
                             ('instruction_ref', 'OWNER_INSTRUCTION_20261107_PERSONAL_RESEARCH'),
                             ('production_promoted', True), ('model_cells', [])):
            bad = deepcopy(record); bad['decision'][field] = value
            bad['mac'] = _mac(bad['decision'])
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_decision(bad, **self.arguments())
        bad = deepcopy(record); bad['decision'].pop('intake_sha256')
        with self.assertRaises(ValueError):
            verify_decision(bad, **self.arguments())

    def test_invalid_sources_hashes_and_missing_key_fail_closed(self):
        numeric_source = deepcopy(SOURCE); numeric_source['source_commit'] = int('1'*40)
        numeric_dataset = deepcopy(POINTER); numeric_dataset['source_commit'] = int('1'*40)
        for change in (dict(source_refs=[]), dict(intake_sha256='d'*63),
                       dict(intake_sha256=True), dict(registry_sha256='D'*64),
                       dict(state_content_sha256=int('1'*64)),
                       dict(source_pointer=numeric_source), dict(dataset_pointer=numeric_dataset),
                       dict(source_refs=[('https://example.org/unreviewed', B_RIGHTS)]),
                       dict(source_refs=[(self.refs[0][0], 'UNREVIEWED_RIGHTS')])):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.issue(**change)
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''):
            with self.assertRaisesRegex(ValueError, 'OWNER_STATE_KEY_REQUIRED'):
                self.issue()

    def test_missing_key_precedes_scope_inspection_for_issuing_and_verifying(self):
        from race_ai.all_existing_model_research import issue_decision, verify_decision
        arguments = dict(source_pointer=None, state_content_sha256=None, dataset_pointer=None,
            source_refs=None, intake_sha256=None, registry_sha256=None, now=NOW)
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''), patch(
                'race_ai.all_existing_model_research._bound',
                side_effect=AssertionError('missing key must fail before scope inspection')):
            with self.assertRaisesRegex(ValueError, 'OWNER_STATE_KEY_REQUIRED'):
                issue_decision(**arguments, expires_at=NOW+timedelta(days=1))
            with self.assertRaisesRegex(ValueError, 'OWNER_STATE_KEY_REQUIRED'):
                verify_decision(None, **arguments)

    def test_existing_current_html_scope_is_exact_and_does_not_widen_legacy_decisions(self):
        from race_ai.all_existing_model_research import _source_refs, verify_decision
        from race_ai.observed_p1_connection import RIGHTS as html_rights
        from race_ai.boat_venue_research import issue_owner_research_decision
        html = ('https://www.boatrace.jp/owpc/pc/race/racelist', html_rights)
        sources = self.refs+[html, html]
        record = self.issue(source_refs=sources)
        self.assertEqual(_source_refs(sources), sorted(self.refs+[html]))
        self.assertEqual(record['decision']['source_refs_sha256'], digest(sorted(self.refs+[html])))
        self.assertEqual(verify_decision(record, **self.arguments(source_refs=list(reversed(sources)))),
                         digest(record))
        old_args = {k:v for k,v in self.arguments(source_refs=sources).items()
                    if k not in ('intake_sha256', 'registry_sha256')}
        with self.assertRaises(ValueError):
            issue_owner_research_decision(**old_args, expires_at=NOW+timedelta(days=1))
        for url, rights in (
                (html[0], 'UNREVIEWED_HTML_RIGHTS'),
                ('https://example.org/owpc/pc/race/racelist', html_rights),
                ('https://www.boatrace.jp.attacker.invalid/race', html_rights),
                ('https://user@www.boatrace.jp/race', html_rights),
                ('https://www.boatrace.jp/race#private', html_rights),
                ('https://raw.githubusercontent.com/another-owner/RACE-AI/source.json', html_rights)):
            with self.subTest(url=url, rights=rights), self.assertRaises(ValueError):
                self.issue(source_refs=self.refs+[(url, rights)])


class AllModelEncryptedCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai.all_existing_model_learning import fit
        from tests.test_all_existing_model_learning import observed_records
        records = observed_records()
        # One genuinely supported cell exercises dynamic retention counts; the
        # other thirty cells remain visible in the authenticated readiness map.
        selected = records[0]['model_id']
        cls.training = fit([row for row in records if row['model_id'] == selected], now=NOW)
        if len(cls.training['models']) != 1:
            raise AssertionError('synthetic one-family intake must fit exactly one cell')
        cls.unfitted = fit([], now=NOW)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = base64.b64encode(os.urandom(32)).decode()
        environment = patch.dict(os.environ, RACE_AI_STATE_KEY=self.owner)
        environment.start(); self.addCleanup(environment.stop)
        self.payload = self.payload_for(self.training)
        self.candidate = self.root/'candidate'
        from race_ai.boat_venue_learning import seal_candidate
        seal_candidate(self.payload, self.candidate)

    def payload_for(self, training):
        return dict(training=deepcopy(training), excluded=[], summary=dict(
            schema='RACE_AI_ALL_EXISTING_MODEL_TRAINING_COUNTS_V1', state=training['state'],
            registered_model_count=len(training['registered_model_ids']),
            registered_cell_count=len(training['model_states']), fitted_model_count=len(training['models']),
            training_sha256=training['training_sha256'], production_promoted=False,
            actual_purchases=False, plaintext_published=False))

    def archive(self, folder=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('learning.enc', 'learning.json', 'summary.json'):
                archive.writestr(name, ((folder or self.candidate)/name).read_bytes())
        return output.getvalue()

    def receipt(self, raw, name='all-existing-model-learning-99-1'):
        return dict(id=700, name=name, expired=False, size_in_bytes=len(raw),
            digest='sha256:'+hashlib.sha256(raw).hexdigest(),
            created_at=(NOW+timedelta(seconds=2)).isoformat(),
            expires_at=(NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=99, repository_id=1416489937,
                head_repository_id=1416489937, head_sha='a'*40))

    def context(self, raw, receipt):
        from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
        from race_ai.github_freeze_receipt import BASE
        def actual_metadata(url):
            self.assertEqual(url, BASE+'/actions/artifacts/700')
            return deepcopy(receipt)
        return context_from_encrypted_artifact(raw, 700, now=NOW+timedelta(minutes=1),
                                               _fetch=actual_metadata)

    def test_actual_registry_candidate_roundtrips_without_public_parameters(self):
        from race_ai.boat_venue_learning import read_candidate
        from race_ai.observed_weight_learning import verify_training
        self.assertIs(verify_training(self.training), True)
        self.assertEqual(read_candidate(self.candidate), self.payload)
        public = b''.join((self.candidate/name).read_bytes()
                          for name in ('learning.json', 'summary.json'))
        for private in (b'parameters', b'base_parameters', b'participants', b'source_url', b'ordered_top8'):
            self.assertNotIn(private, public)

    def test_one_fitted_cell_retains_exact_ciphertext_and_dynamic_readback_count(self):
        from race_ai.boat_venue_learning import read_candidate
        from race_ai.boat_venue_learning_handoff import publish_learning_candidate, restore_learning_candidate
        git = MemoryGit()
        pointer = publish_learning_candidate(self.candidate, self.root, transport=git)
        restored = self.root/'restored'
        status = restore_learning_candidate(pointer, restored, self.root, transport=git)
        self.assertEqual(status['fitted_model_count'], 1)
        self.assertEqual(read_candidate(restored), self.payload)
        self.assertEqual(git.trees[git.current]['unrelated.enc'], b'preserve')
        for name in ('learning.enc', 'learning.json', 'summary.json'):
            self.assertEqual((restored/name).read_bytes(), (self.candidate/name).read_bytes())

    def test_actual_artifact_context_preserves_registry_subset_and_legacy_prefix(self):
        raw = self.archive()
        for name in ('all-existing-model-learning-99-1', 'boat-venue-learning-99-1'):
            context = self.context(raw, self.receipt(raw, name))
            self.assertEqual(context['training'], self.training)
            self.assertEqual(len(context['training']['models']), 1)
            self.assertEqual(len(context['training']['model_states']), 31)

    def test_wrong_key_and_tampered_ciphertext_fail_before_metadata_or_git(self):
        from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
        from race_ai.boat_venue_learning_handoff import publish_learning_candidate
        raw = self.archive()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode()), patch(
                'race_ai.boat_venue_learning_handoff.GitStateRepository',
                side_effect=AssertionError('must authenticate before Git')):
            with self.assertRaises(ValueError):
                context_from_encrypted_artifact(raw, 700, now=NOW+timedelta(minutes=1),
                    _fetch=lambda _: self.fail('wrong key must fail before metadata'))
            with self.assertRaises(ValueError):
                publish_learning_candidate(self.candidate, self.root)
        cipher = self.candidate/'learning.enc'
        original = cipher.read_bytes(); cipher.write_bytes(original[:-1]+bytes([original[-1]^1]))
        with self.assertRaises(ValueError):
            context_from_encrypted_artifact(self.archive(), 700, now=NOW+timedelta(minutes=1),
                _fetch=lambda _: self.fail('tampered cipher must fail before metadata'))

    def test_unfitted_registry_is_retained_locally_but_cannot_become_a_fitted_context(self):
        from race_ai.boat_venue_learning import seal_candidate, read_candidate
        from race_ai.boat_venue_learning_handoff import publish_learning_candidate
        from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
        folder = self.root/'held'; payload = self.payload_for(self.unfitted)
        seal_candidate(payload, folder)
        self.assertEqual(read_candidate(folder), payload)
        with patch('race_ai.boat_venue_learning_handoff.GitStateRepository',
                   side_effect=AssertionError('unfitted candidate must fail before Git')):
            with self.assertRaisesRegex(ValueError, 'FITTED'):
                publish_learning_candidate(folder, self.root)
        with self.assertRaisesRegex(ValueError, 'FITTED'):
            context_from_encrypted_artifact(self.archive(folder), 700, now=NOW+timedelta(minutes=1),
                _fetch=lambda _: self.fail('unfitted candidate must fail before metadata'))

    def test_unknown_or_tampered_cell_is_rejected_even_with_new_outer_hash(self):
        from race_ai.boat_venue_learning import seal_candidate
        from race_ai.observed_weight_learning import seal
        for kind in ('foreign', 'parameters'):
            payload = deepcopy(self.payload); training = payload['training']
            key = next(iter(training['models']))
            if kind == 'foreign':
                training['models']['boat/unregistered-model'] = training['models'].pop(key)
            else:
                training['models'][key]['parameters']['unknown-coefficient'] = 1.0
            seal(training, 'training_sha256')
            payload['summary']['training_sha256'] = training['training_sha256']
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                seal_candidate(payload, self.root/('invalid-'+kind))

    def test_rehashed_candidate_cannot_forge_native_support_cohorts_or_readiness(self):
        from race_ai.boat_venue_learning import seal_candidate
        from race_ai.observed_weight_learning import seal
        kinds = ('base', 'unsupported', 'support-type', 'cohort-ids', 'cohort-count',
                 'orphan-fitted-state', 'provider-claim', 'empty-state')
        for kind in kinds:
            payload = deepcopy(self.payload if kind != 'empty-state' else self.payload_for(self.unfitted))
            training = payload['training']
            model = next(iter(training['models'].values()), None)
            if model is not None:
                parameter = next(iter(model['parameters']))
                if kind == 'base':
                    model['base_parameters'][parameter] += .01
                elif kind == 'unsupported':
                    model['parameter_support_train'][parameter] = 0
                    model['parameters'][parameter] = model['base_parameters'][parameter]+.01
                elif kind == 'support-type':
                    model['parameter_support_train'][parameter] = True
                elif kind == 'cohort-ids':
                    model['train_race_ids'] = []
                elif kind == 'cohort-count':
                    model['unique_races'] = 800
                elif kind == 'orphan-fitted-state':
                    missing = next(key for key in training['model_states'] if key not in training['models'])
                    training['model_states'][missing]['state'] = 'FITTED_SHADOW_ONLY'
                elif kind == 'provider-claim':
                    training['provider_permission_confirmed'] = True
                seal(model, 'model_sha256')
            if kind == 'empty-state':
                training['state'] = 'UNRECOGNIZED_STATE'
            seal(training, 'training_sha256')
            payload['summary']['training_sha256'] = training['training_sha256']
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                seal_candidate(payload, self.root/('forged-'+kind))

    def test_rehashed_lineage_retains_actual_clock_order_and_alias_uniqueness(self):
        from race_ai.boat_venue_learning import seal_candidate
        from race_ai.existing_model_dispatch import _race_key
        from race_ai.observed_weight_learning import seal
        for kind in ('late-save', 'future-result', 'split-clock', 'alias-duplicate'):
            payload = deepcopy(self.payload); training = payload['training']
            model = next(iter(training['models'].values())); lineage = model['source_lineage']
            if kind == 'late-save':
                lineage[0]['input_saved_at'] = lineage[0]['cutoff_at']
            elif kind == 'future-result':
                lineage[-1]['result_captured_at'] = (NOW+timedelta(seconds=1)).isoformat()
            elif kind == 'split-clock':
                train_id = model['train_race_ids'][-1]; valid_id = model['validation_race_ids'][0]
                at = next(row['result_captured_at'] for row in lineage if row['race_id'] == valid_id)
                next(row for row in lineage if row['race_id'] == train_id)['result_captured_at'] = at
            else:
                model['train_race_ids'][1] = _race_key(model['train_race_ids'][0], model['sport'])
            seal(model, 'model_sha256'); seal(training, 'training_sha256')
            payload['summary']['training_sha256'] = training['training_sha256']
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                seal_candidate(payload, self.root/('clock-'+kind))

    def test_invented_operator_records_reuse_and_bind_the_original_observed_fitter(self):
        from race_ai.all_existing_model_learning import fit, verify_training
        from tests.test_all_existing_model_learning import observed_records
        from race_ai.observed_weight_learning import seal
        records = observed_records(synthetic=False)
        # These are still invented fixtures. Explicit test callbacks exercise
        # the operator contract without claiming external source admission.
        fitted = fit(records, now=NOW, allow_source=lambda *args: True,
                     allow_training=lambda *args: True)
        self.assertIs(verify_training(fitted), True)
        for model in fitted['models'].values():
            native = model['native_training']
            self.assertEqual(native['schema'], 'RACE_AI_EXISTING_OBSERVED_WEIGHT_FIT_V1')
            self.assertEqual(native['train_races'], model['train_races'])
            self.assertEqual(native['validation_races'], model['validation_races'])
        model = next(iter(fitted['models'].values())); native = model['native_training']
        native['models'][model['model_id']]['weights'][0] += .001
        seal(native, 'training_sha256'); seal(model, 'model_sha256'); seal(fitted, 'training_sha256')
        with self.assertRaisesRegex(ValueError, 'NATIVE_TRAINING_BINDING'):
            verify_training(fitted)

    def test_new_schema_actual_metadata_requires_head_bytes_repository_and_clock(self):
        raw = self.archive(); good = self.receipt(raw)
        invalid = []
        for value in (None, 'main', 'F'*40, True):
            receipt = deepcopy(good); receipt['workflow_run']['head_sha'] = value
            invalid.append(receipt)
        for field, value in (('id', 701), ('expired', True), ('digest', 'sha256:'+'0'*64),
                             ('size_in_bytes', len(raw)+1), ('name', 'all-existing-model-learning-'),
                             ('expires_at', NOW.isoformat()),
                             ('created_at', (NOW-timedelta(seconds=2)).isoformat())):
            invalid.append(dict(good, **{field:value}))
        foreign = deepcopy(good); foreign['workflow_run']['repository_id'] = 1
        invalid.append(foreign)
        for receipt in invalid:
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                self.context(raw, receipt)


if __name__ == '__main__':
    unittest.main()
