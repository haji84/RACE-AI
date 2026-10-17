"""Synthetic tests for research forecasts and immutable temporal evaluation."""
import importlib
import json
import math
import sqlite3
import unittest
from unittest.mock import patch

from race_ai.core import connect


RACE = '20261015-18-01'
BEFORE = '2026-10-15T02:00:00+00:00'
ASOF = '2026-10-15T02:10:00+00:00'
GENERATED = '2026-10-15T02:11:00+00:00'
SAVED = '2026-10-15T02:12:00+00:00'
START = '2026-10-15T03:00:00+00:00'
AFTER = '2026-10-15T03:05:00+00:00'
LATER = '2026-10-15T03:10:00+00:00'


def inputs(**overrides):
    return dict(race_id=RACE, race_start_at=START, as_of=ASOF, generated_at=GENERATED,
                model_id='uniform-research', model_version='1', selection_reason='synthetic uniform baseline',
                boats=[dict(lane=lane, strength=1, available_at=BEFORE, captured_at=BEFORE,
                            generated_at=BEFORE, source_ref='synthetic-uniform', feature_kind='uniform_baseline')
                       for lane in range(1, 7)], **overrides)


def official(top3=(1, 2, 3), **overrides):
    base = dict(race_id=RACE, race_start_at=START, status='settled', confirmed=True,
                available_at=AFTER, captured_at=AFTER, source_ref='synthetic-official',
                top3=list(top3), payouts=[])
    base.update(overrides)
    return base


class PredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.p = importlib.import_module('race_ai.prediction')
        except ModuleNotFoundError:
            cls.p = None

    def setUp(self):
        self.assertIsNotNone(self.p, 'research prediction foundation must exist')
        self.db = connect(':memory:')
        self.addCleanup(self.db.close)

    def build(self, data=None):
        return self.p.build_prediction(data or inputs())

    def save(self, forecast=None, at=SAVED):
        with patch.object(self.p, '_now', return_value=self.p._time(at)):
            return self.p.save_prediction(self.db, forecast or self.build())

    def save_result(self, value=None, at=AFTER):
        with patch.object(self.p, '_now', return_value=self.p._time(at)):
            return self.p.save_result_revision(self.db, value or official())

    def test_uniform_joint_distribution_and_all_position_marginals(self):
        forecast = self.p.plackett_luce({lane: 1 for lane in range(1, 7)})
        self.assertEqual(len(forecast['triples']), 120)
        self.assertEqual(len({tuple(row['combination']) for row in forecast['triples']}), 120)
        self.assertAlmostEqual(sum(row['probability'] for row in forecast['triples']), 1, places=12)
        for row in forecast['triples']:
            self.assertAlmostEqual(row['probability'], 1 / 120, places=14)
        for lane in forecast['marginals']:
            for name in ('first', 'second', 'third', 'fourth', 'fifth', 'sixth'):
                self.assertAlmostEqual(lane[name + '_probability'], 1 / 6, places=12)
            self.assertAlmostEqual(lane['top3_probability'], 0.5, places=12)

    def test_conditional_order_probability_uses_remaining_strengths(self):
        forecast = self.p.plackett_luce({1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1})
        first = next(row for row in forecast['triples'] if row['combination'] == [1, 2, 3])
        self.assertAlmostEqual(first['probability'], (6 / 21) * (5 / 15) * (4 / 10), places=14)
        self.assertGreater(forecast['marginals'][0]['first_probability'], forecast['marginals'][-1]['first_probability'])

    def test_invalid_or_missing_boats_and_nonfinite_strengths_rejected(self):
        for strengths in ({1: 1}, {lane: 0 for lane in range(1, 7)},
                          {lane: float('nan') for lane in range(1, 7)},
                          {lane: -1 for lane in range(1, 7)},
                          {lane: float('inf') for lane in range(1, 7)},
                          {lane: True for lane in range(1, 7)}):
            with self.subTest(strengths=strengths), self.assertRaises(self.p.PredictionError):
                self.p.plackett_luce(strengths)

    def test_prediction_stays_unvalidated_without_purchase_recommendations(self):
        forecast = self.build()
        self.assertTrue(forecast['research_only'])
        self.assertEqual(forecast['validation_status'], 'UNVALIDATED')
        self.assertEqual(forecast['purchase_decision'], 'skip')
        self.assertEqual(forecast['purchase_recommendations'], [])
        self.assertEqual(forecast['selection_reason'], 'synthetic uniform baseline')
        self.assertEqual(len(forecast['explanations']), 6)
        self.assertEqual(forecast, self.build())

    def test_all_evidence_times_and_prediction_cutoff_are_enforced(self):
        for field in ('available_at', 'captured_at', 'generated_at'):
            data = inputs()
            data['boats'][0][field] = GENERATED
            with self.subTest(field=field), self.assertRaises(self.p.PredictionError):
                self.build(data)
        for changes in ({'as_of': AFTER}, {'generated_at': START}, {'generated_at': BEFORE},
                        {'as_of': '2026-10-15T02:10:00'}):
            data = inputs()
            data.update(changes)
            with self.subTest(changes=changes), self.assertRaises(self.p.PredictionError):
                self.build(data)

    def test_subsecond_future_evidence_is_not_truncated_into_cutoff(self):
        data = inputs()
        data['boats'][0]['captured_at'] = '2026-10-15T02:10:00.001+00:00'
        with self.assertRaises(self.p.PredictionError):
            self.build(data)

    def test_current_race_result_actual_st_or_actual_course_is_rejected(self):
        for name in ('actual_st', 'actual_entry_course', 'finish', 'payout_yen', 'final_odds'):
            data = inputs()
            data['boats'][0][name] = 1
            with self.subTest(field=name), self.assertRaises(self.p.PredictionError):
                self.build(data)

    def test_save_is_immutable_idempotent_and_requires_pre_start_clock(self):
        saved = self.save()
        self.assertEqual(saved['version_id'], self.save()['version_id'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM prediction_versions').fetchone()[0], 1)
        changed = inputs()
        changed['generated_at'] = '2026-10-15T02:11:30+00:00'
        changed['boats'][0]['strength'] = 2
        second = self.save(self.build(changed))
        self.assertNotEqual(second['version_id'], saved['version_id'])
        for statement in ('UPDATE prediction_versions SET model_id="changed"', 'DELETE FROM prediction_versions'):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(statement)
        with self.assertRaises(self.p.PredictionError):
            self.save(self.build(changed), at=START)

    def test_save_rejects_tampered_distribution_and_future_generation(self):
        tampered = self.build()
        tampered['triples'][0]['probability'] = 0.8
        with self.assertRaises(self.p.PredictionError):
            self.save(tampered)
        with self.assertRaises(self.p.PredictionError):
            self.save(at=ASOF)

    def test_json_export_reproduces_saved_payload_and_hash(self):
        saved = self.save()
        exported = self.p.export_prediction(self.db, saved['version_id'])
        self.assertEqual(json.loads(exported), self.build())
        self.assertEqual(exported, self.p.export_prediction(self.db, saved['version_id']))

    def test_result_corrections_append_revisions_without_changing_forecasts(self):
        saved = self.save()
        before = self.p.export_prediction(self.db, saved['version_id'])
        first = self.save_result()
        self.assertEqual(first['revision_id'], self.save_result()['revision_id'])
        corrected = official((2, 1, 3), available_at=LATER, captured_at=LATER)
        second = self.save_result(corrected, at=LATER)
        self.assertEqual(second['revision_no'], 2)
        self.assertEqual(second['supersedes_id'], first['revision_id'])
        self.assertEqual(before, self.p.export_prediction(self.db, saved['version_id']))
        for statement in ('UPDATE result_revisions SET revision_no=4', 'DELETE FROM result_revisions'):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(statement)

    def test_results_require_confirmed_post_start_available_evidence(self):
        for changes in ({'confirmed': False}, {'available_at': BEFORE}, {'captured_at': BEFORE},
                        {'available_at': LATER}, {'top3': [1, 1, 2]}, {'source_ref': ''}):
            with self.subTest(changes=changes), self.assertRaises(self.p.PredictionError):
                self.save_result(official(**changes))

    def test_uniform_brier_logloss_and_calibration_sample_counts(self):
        self.save()
        self.save_result()
        report = self.p.evaluate_predictions(self.db, as_of=LATER)
        model = report['models'][0]
        self.assertEqual(model['race_count'], 1)
        self.assertEqual(model['ticket_count'], 120)
        self.assertAlmostEqual(model['multiclass_brier'], 119 / 120, places=12)
        self.assertAlmostEqual(model['log_loss'], math.log(120), places=12)
        self.assertEqual(sum(b['sample_count'] for b in model['calibration']), 120)
        self.assertEqual(sum(b['positive_count'] for b in model['calibration']), 1)
        self.assertEqual(model['validation_status'], 'UNVALIDATED')

    def test_evaluation_uses_only_result_revision_known_at_cutoff(self):
        data = inputs()
        data['boats'][0]['strength'] = 6
        self.save(self.build(data))
        self.save_result()
        first = self.p.evaluate_predictions(self.db, as_of=AFTER)['models'][0]['log_loss']
        self.save_result(official((2, 1, 3), available_at=LATER, captured_at=LATER), at=LATER)
        before = self.p.evaluate_predictions(self.db, as_of=AFTER)['models'][0]['log_loss']
        after = self.p.evaluate_predictions(self.db, as_of=LATER)['models'][0]['log_loss']
        self.assertEqual(first, before)
        self.assertNotEqual(first, after)

    def test_pending_and_unsupported_outcomes_are_reported_not_silently_dropped(self):
        self.save()
        pending = self.p.evaluate_predictions(self.db, as_of=AFTER)
        self.assertEqual(pending['excluded'][0]['reason'], 'no_result_at_cutoff')
        self.save_result(official(status='dead_heat'))
        excluded = self.p.evaluate_predictions(self.db, as_of=LATER)
        self.assertEqual(excluded['excluded'][0]['reason'], 'unsupported_result:dead_heat')
        self.assertEqual(excluded['models'], [])

    def test_comparison_requires_shared_races_and_equal_information_cutoffs(self):
        self.save()
        other = inputs()
        other['model_id'] = 'other-research'
        other['boats'][0]['strength'] = 2
        self.save(self.build(other))
        self.save_result()
        comparison = self.p.compare_models(self.db, ['uniform-research', 'other-research'], as_of=LATER)
        self.assertEqual(comparison['common_race_ids'], [RACE])
        self.assertEqual(len(comparison['models']), 2)
        for model in comparison['models']:
            self.assertEqual(model['race_count'], 1)

    def test_history_baseline_excludes_current_future_and_post_cutoff_records(self):
        from race_ai.core import source
        sha = source(self.db, 'K', b'synthetic-history', 'fixture.txt', BEFORE, BEFORE)
        rows = [('past', '2026-10-14T03:00:00+00:00', BEFORE, BEFORE, 1),
                (RACE, BEFORE, BEFORE, BEFORE, 1),
                ('future-race', AFTER, BEFORE, BEFORE, 1),
                ('future-capture', BEFORE, BEFORE, AFTER, 1)]
        for race, race_at, available, capture, finish in rows:
            self.db.execute('INSERT INTO starts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (race, 1, '4001', 1, .1, 'OK', finish, race_at, available, capture, sha))
        entries = [dict(lane=lane, racer_id=str(4000 + lane), predicted_course=lane) for lane in range(1, 7)]
        built = self.p.build_history_baseline(self.db, race_id=RACE, entries=entries,
            race_start_at=START, as_of=ASOF, generated_at=GENERATED)
        self.assertEqual(built['explanations'][0]['sample_n'], 1)
        self.assertEqual(built['explanations'][1]['sample_n'], 0)
        self.assertIn('4002', built['uncertainty']['missing_racer_history'])

    def test_latest_history_revision_is_selected_before_racer_course_filtering(self):
        from race_ai.core import source
        old = source(self.db, 'K', b'old-history', 'old.txt', BEFORE, BEFORE)
        newer_time = '2026-10-15T02:05:00+00:00'
        new = source(self.db, 'K', b'new-history', 'new.txt', newer_time, newer_time)
        for sha, stamp, course in ((old, BEFORE, 1), (new, newer_time, 2)):
            self.db.execute('INSERT INTO starts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('past-correction', 1, '4001', course, .1, 'OK', 1,
                 '2026-10-14T03:00:00+00:00', stamp, stamp, sha))
        entries = [dict(lane=lane, racer_id=str(4000 + lane), predicted_course=lane) for lane in range(1, 7)]
        built = self.p.build_history_baseline(self.db, race_id=RACE, entries=entries,
            race_start_at=START, as_of=ASOF, generated_at=GENERATED)
        self.assertEqual(built['explanations'][0]['sample_n'], 0)

    def test_invalid_timestamp_offsets_and_huge_strengths_have_controlled_errors(self):
        bad = inputs()
        bad['as_of'] = '2026-10-15T02:10:00+01:99'
        with self.assertRaises(self.p.PredictionError):
            self.build(bad)
        with self.assertRaises(self.p.PredictionError):
            self.p.plackett_luce({lane: 10 ** 1000 for lane in range(1, 7)})
        for invalid in ([[]], [True, 'valid']):
            with self.subTest(model_ids=invalid), self.assertRaises(self.p.PredictionError):
                self.p.compare_models(self.db, invalid, as_of=LATER)

    def test_model_comparison_excludes_different_information_cutoffs(self):
        self.save()
        other = inputs()
        other['model_id'] = 'other-research'
        other['as_of'] = '2026-10-15T02:10:30+00:00'
        self.save(self.build(other))
        self.save_result()
        report = self.p.compare_models(self.db, ['uniform-research', 'other-research'], as_of=LATER)
        self.assertEqual(report['common_race_ids'], [])
        self.assertEqual(report['models'], [])
        self.assertEqual(report['excluded'][0]['reason'], 'information_cutoff_mismatch')

    def test_history_scenario_requires_distinct_racers_and_predicted_courses(self):
        for key in ('racer_id', 'predicted_course'):
            entries = [dict(lane=lane, racer_id=str(4000 + lane), predicted_course=lane) for lane in range(1, 7)]
            entries[1][key] = entries[0][key]
            with self.subTest(key=key), self.assertRaises(self.p.PredictionError):
                self.p.build_history_baseline(self.db, race_id=RACE, entries=entries,
                    race_start_at=START, as_of=ASOF, generated_at=GENERATED)


if __name__ == '__main__':
    unittest.main()
