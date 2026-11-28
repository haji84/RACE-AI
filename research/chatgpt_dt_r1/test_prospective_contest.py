"""Synthetic contracts only; these fixtures are not real contest evidence."""
from copy import deepcopy
import importlib
import unittest

from research.chatgpt_dt_r1 import comparison, policy
from research.chatgpt_dt_r1.test_calibration_policy_comparison import forecast


IDS = ('official-and-research-ensemble-v1', 'keirin-conditional-order-trees-v1', 'chatgpt-dt-r1')
EQUAL_IDS = ('official-ab-equal-weight-v1', *IDS[1:])
ROLES = ('existing-integrated', 'codex-independent', 'chatgpt-dt-r1')
RID = '203001152401'
DAY = '2030-01-15'


def fixture(ids=IDS, recipe=None):
    if recipe is None:
        recipe = {'current_arm_weights': {'A': .25, 'B': .25}, 'research_weight': .5,
                  'research_allocation': 'equal_available_families_equal_members'}
    participants = {
        model_id: {'role': role, 'model_sha256': str(i + 1) * 64,
                   'artifact_sha256': str(i + 4) * 64, 'code_commit': 'a' * 40,
                   'feature_schema_sha256': str(i + 7) * 64,
                   'policy_sha256': policy.digest({'version': 'dt-r1-fixed-k-v1', 'market': 'trifecta',
                                                  'k': 1, 'tie_break': 'cars_ascending'})}
        for i, (model_id, role) in enumerate(zip(ids, ROLES))}
    participants[ids[0]]['integration_recipe'] = deepcopy(recipe)
    contract = {'schema': 'dt-r1-prospective-contest-v2', 'frozen_at': DAY + 'T08:00:00Z',
                'participants': participants, 'expected_integration_recipe': deepcopy(recipe)}
    registry = {'race_id': RID, 'day': DAY, 'cohort': 'prospective', 'cutoff_at': DAY + 'T10:30:00Z',
                'input_sha256': 'c' * 64, 'field_size': 3,
                'history_snapshot_sha256': 'd' * 64, 'dataset_snapshot_sha256': 'e' * 64,
                'context_snapshot_sha256': 'f' * 64, 'context_as_of': DAY + 'T09:00:00Z',
                'input_snapshot_sha256': '0' * 64, 'input_frozen_at': DAY + 'T09:01:00Z'}
    rows = []
    receipts = {RID: {}}
    for i, model_id in enumerate(ids):
        f = forecast(RID, DAY, model_id, 'prospective')
        f.update(model_sha256=participants[model_id]['model_sha256'],
                 feature_schema_sha256=participants[model_id]['feature_schema_sha256'],
                 feature_input_sha256=str(i + 1) * 64,
                 shared_evidence_sha256=policy.shared_evidence_digest(registry),
                 prediction_at=DAY + f'T10:0{i}:00Z', cutoff_at=registry['cutoff_at'])
        f['selection'] = policy.fixed_selection(f, 1)
        rows.append(f)
        receipts[RID][model_id] = {
            'schema': 'dt-r1-prospective-original-v2', 'contract_sha256': policy.digest(contract),
            'race_id': RID, 'day': DAY, 'model_id': model_id,
            'registry_sha256': policy.digest(registry), 'input_snapshot_sha256': registry['input_snapshot_sha256'],
            'input_sha256': registry['input_sha256'], 'shared_evidence_sha256': f['shared_evidence_sha256'],
            'input_as_of': registry['context_as_of'], 'input_frozen_at': registry['input_frozen_at'],
            'generated_at': f['prediction_at'], 'sealed_at': DAY + f'T10:0{i}:20Z',
            'readback_at': DAY + f'T10:0{i}:40Z', 'cutoff_at': registry['cutoff_at'],
            'model_sha256': f['model_sha256'], 'forecast_sha256': policy.digest(f),
            'original_cipher_sha256': str(i + 3) * 64,
            'source_receipt_sha256': 'a' * 64, 'readback_receipt_sha256': str(i + 4) * 64}
    outcome = {'race_id': RID, 'day': DAY, 'status': 'settled', 'top3': [1, 2, 3], 'field_size': 3}
    return contract, registry, rows, receipts, outcome


class ProspectiveContestTests(unittest.TestCase):
    def setUp(self):
        try:
            self.subject = importlib.import_module('research.chatgpt_dt_r1.prospective_contest')
        except ModuleNotFoundError:
            self.subject = None
        self.assertIsNotNone(self.subject, 'prospective v2 admission is missing')
        self.use_fixture()

    def use_fixture(self, ids=IDS, recipe=None):
        self.ids = ids
        self.contract, self.registry, self.rows, self.receipts, self.outcome = fixture(ids, recipe)
        self.expected_sha = policy.digest(self.contract)
        # The fake authority recognises only these immutable synthetic originals.
        # It does not sign arbitrary caller-provided content.
        self.trusted = {m: self.payload(self.rows[i], self.receipts[RID][m]) for i, m in enumerate(self.ids)}

    def payload(self, row, receipt):
        return deepcopy({'schema': 'dt-r1-prospective-reverify-v2', 'contract': self.contract,
                         'registry': self.registry, 'forecast': row, 'receipt': receipt})

    def verifier(self, payload):
        expected = self.trusted[payload['forecast']['model_id']]
        if payload != expected:
            return {'verified': False}
        return {'verified': True, 'independent': True, 'verifier': 'SYNTHETIC_FIXTURE_ONLY',
                'payload_sha256': policy.digest(payload), 'receipt_sha256': 'b' * 64,
                'model_manifest_verified': True, 'input_snapshot_verified': True,
                'original_readback_verified': True}

    def compare(self, **kwargs):
        options = dict(expected_model_ids=self.ids, bootstrap_samples=10,
                       prospective_contract=self.contract, expected_prospective_contract_sha256=self.expected_sha,
                       prospective_receipts=self.receipts, prospective_verifier=self.verifier)
        options.update(kwargs)
        return comparison.compare_models(self.rows, [self.outcome], [self.registry], **options)

    def reason(self, report, model_id=None):
        return report['all_target']['models'][model_id or self.ids[0]]['hold_reasons']

    def use_equal_weight_fixture(self):
        self.use_fixture(EQUAL_IDS, {'current_arm_weights': {'A': .5, 'B': .5},
                                     'research_weight': 0, 'research_allocation': 'none'})

    def test_ab_each_half_replays_three_distinct_pre_cutoff_originals(self):
        self.use_equal_weight_fixture()
        before = deepcopy(self.rows)
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 1)
        self.assertEqual(report['prospective_contract']['admitted_forecasts'], 3)
        self.assertEqual(set(report['all_target']['models']), set(EQUAL_IDS))
        self.assertEqual(len({row['prediction_at'] for row in self.rows}), 3)
        self.assertEqual(self.rows, before)
        self.assertFalse(report['prospective_evidence']['formal_comparison_verified'])

    def test_ab_each_half_cannot_be_relabelled_as_the_legacy_ensemble(self):
        self.use_fixture(IDS, {'current_arm_weights': {'A': .5, 'B': .5},
                               'research_weight': 0, 'research_allocation': 'none'})
        self.assertIn('PROSPECTIVE_V2_EXISTING_INTEGRATED_RECIPE_INVALID', self.reason(self.compare()))

    def test_legacy_research_weights_cannot_be_relabelled_as_ab_each_half(self):
        self.use_fixture(EQUAL_IDS)
        self.assertIn('PROSPECTIVE_V2_EXISTING_INTEGRATED_RECIPE_INVALID', self.reason(self.compare()))

    def test_ab_each_half_requires_exact_weights_and_no_research_marker(self):
        variants = [
            (.6, .4, 0, 'none', 'INTEGRATION_RECIPE_INVALID'),
            (.5, .5, 1e-13, 'none', 'INTEGRATION_RECIPE_INVALID'),
            (.5, .5, 0, 'equal_available_families_equal_members', 'EXISTING_INTEGRATED_RECIPE_INVALID'),
        ]
        for a, b, research, allocation, reason in variants:
            with self.subTest(a=a, b=b, research=research, allocation=allocation):
                self.use_fixture(EQUAL_IDS, {'current_arm_weights': {'A': a, 'B': b},
                                             'research_weight': research, 'research_allocation': allocation})
                report = self.compare()
                self.assertEqual(report['prospective_contract']['admitted_forecasts'], 0)
                self.assertIn('PROSPECTIVE_V2_' + reason, self.reason(report))

    def test_ab_each_half_rejects_legacy_policy_in_the_expected_manifest(self):
        self.use_equal_weight_fixture()
        legacy_contract, *_ = fixture()
        self.contract['expected_integration_recipe'] = legacy_contract['expected_integration_recipe']
        self.expected_sha = policy.digest(self.contract)
        self.assertIn('PROSPECTIVE_V2_INTEGRATED_RECIPE_MISMATCH', self.reason(self.compare()))

    def test_v2_contract_cannot_declare_both_integrated_models(self):
        self.use_equal_weight_fixture()
        legacy_contract, *_ = fixture()
        self.contract['participants'][IDS[0]] = legacy_contract['participants'][IDS[0]]
        ids = (*EQUAL_IDS, IDS[0])
        with self.assertRaisesRegex(policy.PolicyError, 'EXACT_PARTICIPANT_IDENTITIES_REQUIRED'):
            self.subject.checked_contract(self.contract, policy.digest(self.contract), ids)

    def test_ab_each_half_rejects_rank_only_forecast(self):
        self.use_equal_weight_fixture()
        self.rows[0]['trifectas'] = [{'cars': [1, 2, 3]}]
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertEqual(report['all_target']['eligible_n'], 1)
        self.assertEqual(report['prospective_contract']['admitted_forecasts'], 2)
        self.assertIn('INVALID_PROBABILITY', self.reason(report))

    def test_ab_each_half_rejects_self_digested_probabilities_absent_from_the_original(self):
        self.use_equal_weight_fixture()
        model_id = EQUAL_IDS[0]
        row = self.rows[0]
        for market in ('trifectas', 'exactas'):
            row[market][0]['probability'], row[market][1]['probability'] = .20, .50
        row['selection'] = policy.fixed_selection(row, 1)
        self.receipts[RID][model_id]['forecast_sha256'] = policy.digest(row)
        report = self.compare()
        self.assertEqual(report['prospective_contract']['admitted_forecasts'], 2)
        self.assertIn('PROSPECTIVE_V2_EXTERNAL_REVERIFICATION_FAILED', self.reason(report))

    def test_ab_each_half_cannot_override_the_pinned_contract_or_share_a_model_hash(self):
        self.use_equal_weight_fixture()
        self.contract['participants'][EQUAL_IDS[0]]['model_sha256'] = self.rows[1]['model_sha256']
        self.assertIn('PROSPECTIVE_V2_EXTERNAL_CONTRACT_SHA_MISMATCH', self.reason(self.compare()))
        self.expected_sha = policy.digest(self.contract)
        self.assertIn('PROSPECTIVE_V2_DISTINCT_MODEL_MANIFESTS_REQUIRED', self.reason(self.compare()))


    def test_v2_matches_common_frozen_input_without_rewriting_generation_clocks(self):
        before = deepcopy(self.rows)
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 1)
        self.assertEqual(report['prospective_contract']['admitted_forecasts'], 3)
        self.assertEqual(report['prospective_contract']['clock_basis'], 'IMMUTABLE_INPUT_SNAPSHOT_AND_ACTUAL_ORIGINAL_CLOCKS')
        self.assertEqual(self.rows, before)
        self.assertFalse(report['source_attested'])  # Official outcomes still require their existing admission.
        self.assertIsNone(report['verdict']['winner'])
        for model_id in IDS:
            self.assertEqual(report['all_target']['models'][model_id]['trifecta']['hit_at']['1']['hits'], 1)

    def test_legacy_v1_keeps_exact_prediction_clock_requirement(self):
        report = comparison.compare_models(self.rows, [self.outcome], [self.registry],
                                           expected_model_ids=IDS, bootstrap_samples=10)
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertEqual(report['common_cohort']['exclusion_reasons']['PREDICTION_AT_MISMATCH'], 1)

    def test_no_external_verifier_cannot_upgrade_self_declared_receipts(self):
        report = self.compare(prospective_verifier=None)
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertEqual(report['all_target']['eligible_n'], 1)
        self.assertIn('PROSPECTIVE_V2_INDEPENDENT_VERIFIER_REQUIRED', self.reason(report))

    def test_changed_forecast_cannot_reuse_verified_original_receipt(self):
        self.rows[0]['trifectas'][0]['probability'], self.rows[0]['trifectas'][1]['probability'] = .2, .5
        self.rows[0]['exactas'][0]['probability'], self.rows[0]['exactas'][1]['probability'] = .2, .5
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertIn('PROSPECTIVE_V2_FORECAST_DIGEST_MISMATCH', self.reason(report))

    def test_missing_rival_stays_missing_and_other_models_remain_scoreable(self):
        self.rows.pop()
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertEqual(report['all_target']['models'][IDS[0]]['forecast_n'], 1)
        self.assertEqual(report['all_target']['models'][IDS[2]]['forecast_n'], 0)
        self.assertEqual(report['all_target']['models'][IDS[2]]['trifecta']['hit_at']['1']['n'], 1)

    def test_exact_15_minute_boundary_accepted_but_later_readback_held(self):
        receipt = self.receipts[RID][IDS[0]]
        receipt['readback_at'] = DAY + 'T10:15:00Z'
        self.trusted[IDS[0]] = self.payload(self.rows[0], receipt)
        self.assertEqual(self.compare()['common_cohort']['eligible_n'], 1)
        receipt['readback_at'] = DAY + 'T10:15:00.000001Z'
        self.trusted[IDS[0]] = self.payload(self.rows[0], receipt)
        report = self.compare()
        self.assertIn('PROSPECTIVE_V2_ORIGINAL_CLOCK_ORDER', self.reason(report))

    def test_late_source_freeze_and_backdated_seal_are_rejected_even_by_permissive_authority(self):
        for key, value in [('input_frozen_at', DAY + 'T10:01:00Z'),
                           ('sealed_at', DAY + 'T09:59:00Z'), ('generated_at', DAY + 'T09:59:00Z')]:
            with self.subTest(key=key):
                original = deepcopy(self.receipts)
                self.receipts[RID][IDS[0]][key] = value
                self.trusted[IDS[0]] = self.payload(self.rows[0], self.receipts[RID][IDS[0]])
                report = self.compare()
                self.assertEqual(report['common_cohort']['eligible_n'], 0)
                self.assertEqual(report['all_target']['models'][IDS[0]]['forecast_n'], 0)
                self.assertIn('PROSPECTIVE_V2_' + ('ORIGINAL_CLOCK_ORDER' if key == 'sealed_at' else 'ORIGINAL_CLOCK_BINDING'),
                              self.reason(report))
                self.receipts = original

    def test_declared_hash_does_not_override_external_contract_pin(self):
        self.contract['participants'][IDS[1]]['model_sha256'] = 'f' * 64
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertIn('PROSPECTIVE_V2_EXTERNAL_CONTRACT_SHA_MISMATCH', self.reason(report))

    def test_actual_integrated_recipe_cannot_satisfy_incompatible_ab_each_half_request(self):
        self.contract['expected_integration_recipe'] = {
            'current_arm_weights': {'A': .5, 'B': .5}, 'research_weight': 0,
            'research_allocation': 'equal_available_families_equal_members'}
        self.expected_sha = policy.digest(self.contract)
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertIn('PROSPECTIVE_V2_INTEGRATED_RECIPE_MISMATCH', self.reason(report))

    def test_official_ab_cannot_masquerade_as_integrated_entrant(self):
        self.contract['participants']['official_A'] = self.contract['participants'].pop(IDS[0])
        self.expected_sha = policy.digest(self.contract)
        report = self.compare()
        self.assertIn('PROSPECTIVE_V2_EXACT_PARTICIPANT_IDENTITIES_REQUIRED', self.reason(report))

    def test_changed_source_snapshot_is_not_accepted_on_matching_card_hash(self):
        self.receipts[RID][IDS[0]]['input_snapshot_sha256'] = 'a' * 64
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 0)
        self.assertIn('PROSPECTIVE_V2_INPUT_SNAPSHOT_MISMATCH', self.reason(report))

    def test_echoing_bool_or_digest_is_not_independent_reverification(self):
        for verifier in (lambda payload: True,
                         lambda payload: {'verified': True, 'independent': True,
                                          'payload_sha256': policy.digest(payload)}):
            report = self.compare(prospective_verifier=verifier)
            self.assertEqual(report['common_cohort']['eligible_n'], 0)
            self.assertIn('PROSPECTIVE_V2_EXTERNAL_REVERIFICATION_FAILED', self.reason(report))

    def retrospective(self):
        registry = {'race_id': 'old', 'day': '2030-01-14', 'cohort': 'retrospective', 'input_sha256': 'c' * 64}
        rows = [forecast('old', '2030-01-14', model_id) for model_id in IDS]
        for i, row in enumerate(rows):
            row['model_sha256'] = self.contract['participants'][IDS[i]]['model_sha256']
            row['feature_schema_sha256'] = self.contract['participants'][IDS[i]]['feature_schema_sha256']
        outcome = {'race_id': 'old', 'day': '2030-01-14', 'status': 'settled', 'top3': [1, 2, 3], 'field_size': 3}
        return registry, rows, outcome

    def test_invalid_v2_contract_never_certifies_legacy_retrospective_rows(self):
        self.registry, self.rows, self.outcome = self.retrospective()
        self.expected_sha = 'f' * 64
        report = self.compare()
        self.assertEqual(report['common_cohort']['eligible_n'], 1)
        self.assertEqual(report['prospective_contract']['status'], 'HOLD')
        self.assertEqual(report['prospective_contract']['admitted_forecasts'], 0)
        self.assertEqual(report['prospective_contract']['prospective_forecasts_supplied'], 0)
        self.assertFalse(report['prospective_evidence']['formal_comparison_verified'])
        self.assertEqual(report['common_cohort']['cohort_counts'], {'retrospective': 1})

    def test_mixed_cohorts_keep_legacy_rules_and_never_pool_v2_evidence(self):
        old_registry, old_rows, old_outcome = self.retrospective()
        report = comparison.compare_models(self.rows + old_rows, [self.outcome, old_outcome],
            [self.registry, old_registry], expected_model_ids=IDS, bootstrap_samples=10,
            prospective_contract=self.contract, expected_prospective_contract_sha256=self.expected_sha,
            prospective_receipts=self.receipts, prospective_verifier=self.verifier)
        self.assertEqual(report['common_cohort']['eligible_n'], 2)
        self.assertEqual(report['common_cohort']['cohort_counts'], {'prospective': 1, 'retrospective': 1})
        self.assertEqual(report['prospective_contract']['admitted_forecasts'], 3)
        self.assertEqual(report['prospective_contract']['prospective_forecasts_supplied'], 3)
        self.assertEqual({row['cohort'] for row in report['paired_bootstrap']}, {'prospective', 'retrospective'})


if __name__ == '__main__':
    unittest.main()
