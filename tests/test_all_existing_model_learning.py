"""Invented frozen inputs and separate outcomes; never live accuracy evidence."""
from copy import deepcopy
from datetime import timedelta
import importlib
import unittest

from race_ai.actions_contract import digest
from tests.test_boat_venue_learning import venue_data
from tests.test_observed_weight_learning import NOW


def observed_records(n=8,*,synthetic=True):
    from race_ai.all_existing_model_learning import records_from_observed
    rows,observations=venue_data(n)
    records=records_from_observed(rows,observations)
    if synthetic:
        for record in records:
            record['scope']='SYNTHETIC_ONLY'
            record['native_payload']['scope']='SYNTHETIC_ONLY'
            record['native_payload']['snapshot']['scope']='SYNTHETIC_ONLY'
            record.pop('observed_row',None);record.pop('observed_result',None)
            record['input_sha256']=digest(record['native_payload'])
    return records


class AllExistingModelLearningTests(unittest.TestCase):
    def modules(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_registry'),
                             'all native families need one real parameter registry')
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_learning'),
                             'all native families need a supervised training entry point')
        return (importlib.import_module('race_ai.all_existing_model_registry'),
                importlib.import_module('race_ai.all_existing_model_learning'))

    def test_registry_covers_all_sixteen_families_and_thirty_one_applicable_cells(self):
        registry,learning=self.modules()
        cells=registry.cells()
        self.assertEqual(len(cells),31)
        self.assertEqual(len({v['model_id'] for v in cells}),16)
        self.assertTrue(all(v['trainable'] and v['parameters'] for v in cells))
        self.assertEqual({s:sum(v['sport']==s for v in cells)
                          for s in ('boat','keirin','autorace','horse')},
                         {'boat':15,'keirin':5,'autorace':6,'horse':5})

    def test_real_missing_members_remain_visible_and_do_not_borrow_observed_inputs(self):
        registry,learning=self.modules();records=observed_records();before=deepcopy(records)
        fitted=learning.fit(records,now=NOW)
        learning.verify_training(fitted)
        self.assertEqual(len(fitted['model_states']),31)
        self.assertEqual(len(fitted['models']),2)
        self.assertEqual(fitted['state'],'FITTED_SHADOW_ONLY')
        self.assertEqual(sum(v['state']=='INPUT_MISSING' for v in fitted['model_states'].values()),29)
        self.assertEqual(records,before)
        for value in fitted['models'].values():
            self.assertEqual(value['train_races'],6);self.assertEqual(value['validation_races'],2)
        self.assertFalse(fitted['auto_promoted'])

    def test_holdout_label_changes_do_not_change_fitted_coefficients(self):
        _,learning=self.modules();records=observed_records();changed=deepcopy(records)
        last=sorted({r['race_id'] for r in changed})[-2:]
        for row in changed:
            if row['race_id'] in last:row['result']['ordered_top3']=[6,5,4]
        a=learning.fit(records,now=NOW);b=learning.fit(changed,now=NOW)
        self.assertEqual({k:v['parameters'] for k,v in a['models'].items()},
                         {k:v['parameters'] for k,v in b['models'].items()})

    def test_live_training_needs_separate_training_admission(self):
        _,learning=self.modules();fitted=learning.fit(observed_records(synthetic=False),now=NOW,
                                                    allow_source=lambda *args:True)
        self.assertFalse(fitted['models'])
        self.assertEqual({v['state'] for k,v in fitted['model_states'].items()
                          if 'boat-observed-' in k},{'HOLD_MODEL_TRAINING_PERMISSION'})

    def test_duplicate_conflicting_future_and_tampered_inputs_never_expand_cohort(self):
        _,learning=self.modules();records=observed_records()
        one=learning.fit(records+deepcopy(records),now=NOW)
        self.assertEqual({v['unique_races'] for v in one['models'].values()},{8})
        for kind in ('hash','future','duplicate'):
            bad=deepcopy(records)
            if kind=='hash':bad[0]['input_sha256']='f'*64
            elif kind=='future':bad[0]['result']['captured_at']=(NOW+timedelta(days=1)).isoformat()
            else:
                duplicate=deepcopy(bad[0]);duplicate['result']['ordered_top3']=list(reversed(duplicate['result']['ordered_top3']));bad.append(duplicate)
            with self.subTest(kind=kind),self.assertRaises(ValueError):learning.fit(bad,now=NOW)


if __name__=='__main__':unittest.main()
