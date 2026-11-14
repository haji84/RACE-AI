"""Retire new seller work without invalidating immutable legacy records."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from race_ai import existing_model_coverage as policy
from race_ai import existing_model_dispatch as dispatch
from race_ai import all_existing_model_registry as registry
from race_ai import all_existing_model_learning as learning
from tests.test_all_existing_model_matrix import native_records, NOW

SELLER = 'seller-shadow-v1-20261104'
LEGACY_REGISTRY_SHA = '07da538c97be334845f268a10fb0d7676d3b2cdcd7a3a922b0f7d7d798aaf3f6'

def legacy_training():
    # Only invented fixtures emulate the policy before the owner's deletion.
    with patch.object(policy, 'RETIRED_MODEL_IDS', frozenset(), create=True):
        return learning.fit(native_records(SELLER, 'boat'), now=NOW)

def legacy_dispatch():
    row = native_records(SELLER, 'boat')[-1]
    info = registry.identity(SELLER, 'boat', row['native_payload'], race_id=row['race_id'])
    schedule = [dict(race_id=row['race_id'], sport='boat', stage='P0',
                     cutoff_at=info['race_cutoff_at'])]
    inputs = {row['race_id']: {'P0': {'seller': row['native_payload']}}}
    with patch.object(policy, 'RETIRED_MODEL_IDS', frozenset(), create=True):
        old = dispatch.dispatch(schedule, inputs, now=row['as_of'])
    originals = [s for s in old['slots']
                 if s['model_id'] == SELLER and s['status'] == 'GENERATED_UNATTESTED']
    if len(originals) != 1:
        raise AssertionError('invented pre-retirement original is missing')
    return schedule, inputs, row['as_of'], originals

class SellerRetirementTests(unittest.TestCase):
    def test_new_dispatch_omits_seller_even_with_complete_inputs(self):
        schedule, inputs, now, _ = legacy_dispatch()
        before = deepcopy(inputs)
        report = dispatch.dispatch(schedule, inputs, now=now)
        self.assertNotIn(SELLER, {s['model_id'] for s in report['slots']})
        self.assertEqual(len(report['slots']), 15)
        self.assertFalse(any(i['native_group'] == 'seller' for i in report['native_invocations']))
        self.assertEqual(inputs, before)
        with patch.object(dispatch, 'seller_generate', side_effect=AssertionError('retired inference')):
            self.assertEqual(dispatch.dispatch(schedule, inputs, now=now), report)

    def test_legacy_original_is_retained_exactly_without_a_current_slot(self):
        schedule, inputs, now, originals = legacy_dispatch()
        before = deepcopy(originals)
        with patch.object(dispatch, 'seller_generate', side_effect=AssertionError('legacy rerank')):
            report = dispatch.dispatch(schedule, inputs, now=now, originals=originals)
        self.assertEqual(report['retained_originals'], before)
        self.assertEqual(originals, before)
        self.assertNotIn(SELLER, {s['model_id'] for s in report['slots']})

    def test_active_catalog_excludes_only_the_seller(self):
        self.assertEqual(registry.registry_sha256(), LEGACY_REGISTRY_SHA)
        self.assertEqual({m['model_id'] for m in policy.active_catalog()},
                         {m['model_id'] for m in policy.catalog()} - {SELLER})
        self.assertEqual(len(policy.active_catalog()), 15)
        self.assertEqual({c['cell_key'] for c in registry.active_cells()},
                         {c['cell_key'] for c in registry.cells()} - {'boat/' + SELLER})
        self.assertEqual(len(registry.active_cells()), 30)

    def test_new_training_never_fits_or_admits_retired_inputs(self):
        rows = native_records(SELLER, 'boat')
        before = deepcopy(rows)
        def forbidden(*args):
            raise AssertionError('retired source admission or fit')
        trained = learning.fit(rows, now=NOW, allow_source=forbidden, allow_training=forbidden)
        self.assertNotIn('boat/' + SELLER, trained['models'])
        self.assertEqual(trained['model_states']['boat/' + SELLER]['state'], 'RETIRED_BY_OWNER')
        self.assertTrue(learning.verify_training(trained))
        self.assertEqual(rows, before)

    def test_exact_pre_retirement_training_still_verifies(self):
        trained = legacy_training()
        self.assertEqual(trained['training_sha256'],
                         '7dac5429028041070af0534e09ef2701987544027dfc656084c83847c9237fb8')
        self.assertTrue(learning.verify_training(trained))
        self.assertEqual(registry.registry_sha256(), LEGACY_REGISTRY_SHA)

    def test_old_training_cannot_reactivate_a_new_seller_forecast(self):
        trained = legacy_training()
        row = native_records(SELLER, 'boat')[-1]
        with self.assertRaisesRegex(ValueError, 'MODEL_RETIRED'):
            learning.forecast_pair(trained, 'boat/' + SELLER, row['native_payload'], now=NOW)

    def test_current_coverage_omits_retired_deficits(self):
        active = policy.coverage([], {'boat': 1}, active_only=True)
        self.assertEqual(active['model_family_count'], 15)
        self.assertNotIn(SELLER, {m['model_id'] for m in active['models']})
        self.assertEqual(policy.coverage([], {'boat': 1})['model_family_count'], 16)

    def test_new_projection_does_not_reinsert_a_missing_retired_slot(self):
        from race_ai.dispatch_product_projection import project_dispatch
        schedule, inputs, now, _ = legacy_dispatch()
        report = dispatch.dispatch(schedule, inputs, now=now)
        view = project_dispatch(report, dataset_status='SYNTHETIC_ONLY')
        self.assertEqual(report['retired_model_ids'], [SELLER])
        for row in view['records']:
            self.assertEqual(len(row['dispatch_slots']), 15)
            self.assertNotIn(SELLER, {slot['model_id'] for slot in row['dispatch_slots']})

    def test_historical_projection_retains_its_original_catalog_shape(self):
        from race_ai.dispatch_product_projection import project_dispatch
        schedule, inputs, now, _ = legacy_dispatch()
        with patch.object(policy, 'RETIRED_MODEL_IDS', frozenset()):
            report = dispatch.dispatch(schedule, inputs, now=now)
        before = deepcopy(report)
        self.assertNotIn('retired_model_ids', report)
        view = project_dispatch(report, dataset_status='SYNTHETIC_ONLY')
        self.assertTrue(all(len(row['dispatch_slots']) == 16 for row in view['records']))
        self.assertEqual(report, before)

    def test_web_catalog_matches_current_targets(self):
        source = (Path(__file__).parents[1] / 'web/existing-model-catalog.js').read_text()
        catalog = json.loads(source.split('const catalog = ', 1)[1].split(';\n', 1)[0])
        self.assertEqual(len(catalog['models']), 15)
        self.assertNotIn(SELLER, {m['model_id'] for m in catalog['models']})
        self.assertEqual({m['model_id'] for m in catalog['models']},
                         {m['model_id'] for m in policy.active_catalog()})

if __name__ == '__main__':
    unittest.main()
