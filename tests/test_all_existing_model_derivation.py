"""Fictional frozen observations; derivation is not a new old save receipt."""
from copy import deepcopy
from datetime import timedelta
import importlib
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import FEATURE_TRANSFORMS, predict_pair
from race_ai.all_existing_model_learning import records_from_observed
from tests.test_observed_weight_learning import dataset, NOW


def originals(stage='P0', *, separate_sources=False):
    rows, results = dataset(1)
    if stage == 'P1':
        for row in rows:
            snapshot = deepcopy(row['learning_snapshot'])
            snapshot['stage'] = 'P1'
            exhibition_source = 'fixture-program'
            if separate_sources:
                from race_ai.observed_weight_learning import ts
                at = ts(snapshot['as_of'])
                snapshot['sources'][0].update(captured_at=(at-timedelta(minutes=2)).isoformat(),
                                               published_at=(at-timedelta(minutes=2)).isoformat())
                preview = deepcopy(snapshot['sources'][0])
                preview.update(source_id='fixture-beforeinfo', source_url='https://example.test/beforeinfo',
                               source_sha256='b'*64, published_at=None,
                               captured_at=(at-timedelta(minutes=1)).isoformat(), evidence_basis='CAPTURED_BY_CLAIM')
                snapshot['sources'].append(preview)
                exhibition_source = 'fixture-beforeinfo'
            for entrant in snapshot['participants']:
                for name, value in (('exhibition_time_seconds', 6.75), ('exhibition_start_seconds', .13)):
                    entrant['missing'].pop(name, None)
                    entrant['features'][name] = dict(value=value, sample_n=None, source_id=exhibition_source,
                                                     transform_id=FEATURE_TRANSFORMS[name])
            suite = predict_pair(snapshot, allow_source=lambda *args: True)
            prediction = suite['models'][row['model_id']]
            row.update(stage='P1', learning_snapshot=snapshot, learning_snapshot_sha256=digest(snapshot),
                       model_sha256=prediction['prediction_sha256'], original_json_sha256=digest(suite),
                       top8=prediction['ordered_top8'], ranked=[p['combination'] for p in prediction['candidates']])
    return records_from_observed(rows, results)


def analysis(ref, rights, purpose):
    return purpose == 'analysis'


def training(ref, rights, purpose):
    return purpose == 'model_training'


class ExistingModelDerivationTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_derivation'),
                             'frozen observed originals need an explicit derivation bridge')
        return importlib.import_module('race_ai.all_existing_model_derivation')

    def test_p0_six_native_cells_preserve_original_availability_without_invented_features(self):
        adapter = self.module(); source = originals(); before = deepcopy(source)
        derived = adapter.derive_records(source + deepcopy(source), now=NOW)
        self.assertEqual(len(derived), 6)
        self.assertEqual(source, before)
        self.assertEqual(len({r['model_id'] for r in derived}), 6)
        for row in derived:
            self.assertEqual(row['stage'], 'P0')
            self.assertEqual(row['as_of'], source[0]['as_of'])
            self.assertEqual(row['input_saved_at'], source[0]['input_saved_at'])
            self.assertEqual(row['input_receipt'], source[0]['input_receipt'])
            self.assertEqual(row['result'], source[0]['result'])
            proof = row['input_derivation']
            self.assertEqual(proof['data_availability_basis'], 'DERIVED_FROM_INDEPENDENT_PRE_CUTOFF_ORIGINAL')
            self.assertIs(proof['derived_payload_saved_before_cutoff'], False)
            self.assertEqual(proof['derived_at'], NOW.isoformat())
            self.assertTrue(adapter.verify_derivation(row, now=NOW, allow_source=analysis, allow_training=training))
            snapshot = row['native_payload']['snapshot']
            if 'entrants' in snapshot:
                self.assertEqual(snapshot['conditions'], {})
                for entrant in snapshot['entrants']:
                    self.assertEqual(set(entrant['features']), {'ability_rating', 'motor_rating'})
                    self.assertIn('recent_form_rating', entrant['missing'])
                    self.assertIn('exhibition_time_seconds', entrant['missing'])
                self.assertEqual(snapshot['entrants'][0]['features'], {'ability_rating': 10, 'motor_rating': 10})
            else:
                self.assertEqual(snapshot['participants'][0]['features']['ability']['value'], .1)
                self.assertEqual(snapshot['environment'], {})
                self.assertIn('stamina', snapshot['participants'][0]['missing'])
        self.assertEqual(adapter.derive_records(list(reversed(source)), now=NOW), derived)

    def test_p1_full_uses_only_retained_measurements_and_original_source_clocks(self):
        adapter = self.module(); source = originals('P1')
        derived = adapter.derive_records(source, now=NOW, include_groups=('boat_full',))
        self.assertEqual(len(derived), 2)
        original = source[0]['native_payload']['snapshot']
        for row in derived:
            entrant = row['native_payload']['snapshot']['entrants'][0]
            self.assertEqual(entrant['features'], dict(ability_rating=10, motor_rating=10,
                                                      exhibition_time_seconds=6.75, exhibition_start_seconds=.13))
            self.assertEqual(entrant['captured_at'], original['sources'][0]['captured_at'])
            self.assertEqual(entrant['source_ref'], original['sources'][0]['source_url'])
            self.assertIn('start_consistency_rating', entrant['missing'])
            self.assertTrue(adapter.verify_derivation(row, now=NOW+timedelta(seconds=5),
                                                       allow_source=analysis, allow_training=training))

    def test_p1_exhibition_lineage_keeps_later_preview_source_without_refreshing_clocks(self):
        adapter = self.module(); source = originals('P1', separate_sources=True)
        record = adapter.derive_records(source, now=NOW, include_groups=('boat_full',))[0]
        original = source[0]['native_payload']['snapshot']
        program, preview = original['sources']
        entrant = record['native_payload']['snapshot']['entrants'][0]
        self.assertEqual(entrant['source_ref'], program['source_url'])
        self.assertEqual(entrant['captured_at'], preview['captured_at'])
        self.assertIsNone(entrant['published_at'])
        lineage = record['native_payload']['feature_lineage']['1']
        self.assertEqual(lineage['ability_rating']['source_ref'], program['source_url'])
        self.assertEqual(lineage['exhibition_time_seconds']['source_ref'], 'https://example.test/beforeinfo')
        self.assertEqual(lineage['exhibition_time_seconds']['source_sha256'], 'b'*64)
        self.assertEqual(lineage['exhibition_time_seconds']['captured_at'], preview['captured_at'])
        self.assertTrue(adapter.verify_derivation(record, now=NOW, allow_source=analysis, allow_training=training))
        bad = deepcopy(record)
        bad['native_payload']['feature_lineage']['1']['exhibition_time_seconds']['source_sha256'] = 'c'*64
        bad['input_sha256'] = digest(bad['native_payload'])
        bad['input_derivation']['native_input_sha256'] = bad['input_sha256']
        with self.assertRaises(ValueError):
            adapter.verify_derivation(bad, now=NOW, allow_source=analysis, allow_training=training)

    def test_latest_original_is_selected_once_and_equal_time_conflicts_fail(self):
        adapter = self.module(); p0 = originals(); p1 = originals('P1')
        derived = adapter.derive_records(p0+p1, now=NOW)
        self.assertEqual(len(derived), 6)
        self.assertEqual({row['stage'] for row in derived}, {'P1'})
        self.assertEqual({row['input_derivation']['original_snapshot_sha256'] for row in derived},
                         {p1[0]['observed_row']['learning_snapshot_sha256']})
        conflict = deepcopy(p0[0]['observed_row'])
        snapshot = conflict['learning_snapshot']
        snapshot['participants'][0]['features']['national_win_rate']['value'] = 8
        conflict['learning_snapshot_sha256'] = digest(snapshot)
        changed = records_from_observed([conflict], [p0[0]['observed_result']])
        with self.assertRaises(ValueError): adapter.derive_records(p0+changed, now=NOW)

    def test_equal_time_original_conflicts_do_not_depend_on_archive_order(self):
        adapter = self.module(); p0 = originals(); p1 = originals('P1')
        conflict = deepcopy(p0[0]['observed_row'])
        conflict['learning_snapshot']['participants'][0]['features']['national_win_rate']['value'] = 8
        conflict['learning_snapshot_sha256'] = digest(conflict['learning_snapshot'])
        changed = records_from_observed([conflict], [p0[0]['observed_result']])
        for records in (p0+changed+p1, p1+p0+changed):
            with self.subTest(first_stage=records[0]['stage']), self.assertRaises(ValueError):
                adapter.derive_records(records, now=NOW)

    def test_derived_inputs_execute_native_equations_and_keep_probability_mass(self):
        adapter = self.module()
        from race_ai import all_existing_model_registry as registry
        from race_ai.boat_multi_feature_models import run_models
        from race_ai.four_sport_model_suite import run_suite
        for record in adapter.derive_records(originals(), now=NOW):
            snapshot = record['native_payload']['snapshot']
            if registry.group(record['model_id']) == 'boat_full':
                prediction = run_models(snapshot)[record['model_id']]
            else:
                prediction = run_suite(snapshot, allow_source=analysis)['models'][record['model_id']]
            self.assertEqual(len(prediction['candidates']), 120)
            self.assertAlmostEqual(sum(row['score'] for row in prediction['candidates']), 1.)

    def test_unsupported_groups_and_nested_derivations_are_rejected(self):
        adapter = self.module()
        with self.assertRaises(ValueError):
            adapter.derive_records(originals(), now=NOW, include_groups=('boat_tactical',))
        nested = adapter.derive_records(originals(), now=NOW)[0]
        with self.assertRaises(ValueError): adapter.derive_records([nested], now=NOW)

    def test_optional_ranker_reuses_sparse_snapshot_without_inventing_result_publication(self):
        adapter = self.module()
        derived = adapter.derive_records(originals(), now=NOW,
                                         include_groups=('shared', 'shared_learned', 'boat_full'))
        self.assertEqual(len(derived), 7)
        ranker = next(r for r in derived if r['model_id'] == 'multisport-chronological-ranker-v1')
        self.assertIsNone(ranker['result']['published_at'])
        self.assertTrue(adapter.verify_derivation(ranker, now=NOW, allow_source=analysis, allow_training=training))

    def test_rehashed_derived_tampering_cannot_change_value_roster_clock_or_feature_set(self):
        adapter = self.module()
        baseline = next(r for r in adapter.derive_records(originals(), now=NOW)
                        if r['model_id'] == 'multisport-factor-interaction-v1')
        for kind in ('value', 'roster', 'feature', 'clock', 'hash', 'precutoff', 'derived_at', 'receipt'):
            bad = deepcopy(baseline); snapshot = bad['native_payload']['snapshot']
            if kind == 'value': snapshot['participants'][0]['features']['ability']['value'] = .2
            elif kind == 'roster': snapshot['participants'][0]['identity'] = '9999'
            elif kind == 'feature':
                snapshot['participants'][0]['features']['stamina'] = deepcopy(snapshot['participants'][0]['features']['ability'])
                snapshot['participants'][0]['missing'].pop('stamina')
            elif kind == 'clock': snapshot['race']['as_of'] = (NOW-timedelta(minutes=1)).isoformat()
            elif kind == 'hash': bad['input_sha256'] = 'f'*64
            elif kind == 'precutoff': bad['input_derivation']['derived_payload_saved_before_cutoff'] = True
            elif kind == 'derived_at': bad['input_derivation']['derived_at'] = (NOW+timedelta(seconds=1)).isoformat()
            else: bad['input_receipt']['artifact_id'] = 999
            if kind in ('value', 'roster', 'feature', 'clock'):
                bad['input_sha256'] = digest(bad['native_payload'])
                bad['input_derivation']['native_input_sha256'] = bad['input_sha256']
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                adapter.verify_derivation(bad, now=NOW, allow_source=analysis, allow_training=training)

    def test_rehashed_original_must_still_match_retained_observed_proof(self):
        adapter = self.module(); baseline = adapter.derive_records(originals(), now=NOW)[0]
        for kind in ('value', 'snapshot_hash', 'result', 'receipt', 'late_save'):
            bad = deepcopy(baseline); original = bad['input_derivation']['original_record']
            if kind == 'value':
                original['native_payload']['snapshot']['participants'][0]['features']['national_win_rate']['value'] = 8
                original['input_sha256'] = digest(original['native_payload'])
            elif kind == 'snapshot_hash': original['observed_row']['learning_snapshot_sha256'] = 'f'*64
            elif kind == 'result': original['result']['ordered_top3'] = [1, 2, 3]
            elif kind == 'receipt': original['input_receipt']['artifact_id'] = 999
            else: original['input_saved_at'] = original['cutoff_at']
            bad['input_derivation']['original_record_sha256'] = digest(original)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                adapter.verify_derivation(bad, now=NOW, allow_source=analysis, allow_training=training)

    def test_analysis_admission_cannot_supply_training_admission(self):
        adapter = self.module(); derived = adapter.derive_records(originals(), now=NOW)
        with self.assertRaises(ValueError): adapter.verify_derivation(derived[0], now=NOW)
        with self.assertRaises(ValueError):
            adapter.verify_derivation(derived[0], now=NOW, allow_source=analysis,
                                       allow_training=lambda *args: False)


if __name__ == '__main__': unittest.main()
