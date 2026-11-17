"""Fictional storage/observations; real existing fitting and PL equations.

Only the external saved-record reader is simulated. These tests establish no
field accuracy, licence, human reference or actual pre-cutoff receipt.
"""
from copy import deepcopy
from datetime import timedelta
import importlib
from itertools import permutations
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import MODEL_IDS
from race_ai import observed_weight_learning as existing
from tests.test_boat_observed_pairwise_models import fixture
from tests.test_boat_video_connection import controlled_connection
from tests.test_boat_video_learning import controlled_inputs, bind_training_snapshot, reseal_context
from tests.test_frozen_day_cycle import observation
from tests.test_observed_weight_learning import NOW


def seal(document, field):
    document[field] = digest({k: v for k, v in document.items() if k != field})
    return document


def active_video_envelope(envelope, lanes):
    """Restrict a fictional saved context, retaining the original lane numbers."""
    context, receipt = envelope['video_context'], envelope['receipt']
    context['participants'] = [p for p in context['participants'] if p['lane'] in lanes]
    for comparison in context['comparisons'].values():
        comparison['uncertainty_by_lane'] = {lane: error for lane, error in
            comparison['uncertainty_by_lane'].items() if int(lane) in lanes}
    reseal_context(context)
    receipt['digest'] = 'sha256:' + digest({'saved_context': context})
    return dict(context_sha256=context['context_sha256'], id=receipt['id'],
                digest=receipt['digest'], created_at=receipt['created_at'])


class SavedRecords:
    """Test-only stand-in for the caller's authenticated artifact extraction."""
    def __init__(self):
        self.saved = {}

    def put(self, document, at):
        ident = 20000 + len(self.saved)
        receipt = dict(id=ident, created_at=at.isoformat(), expired=False,
                       digest='sha256:' + digest(document),
                       workflow_run=dict(id=ident, head_repository_id=1416489937))
        self.saved[ident] = deepcopy((document, receipt))
        return dict(document=deepcopy(document), receipt=receipt)

    def read(self, receipt, document_sha256):
        document, actual = self.saved[receipt['id']]
        if receipt != actual or digest(document) != document_sha256:
            raise ValueError('fictional external metadata differs')
        return deepcopy(document)


class VideoForwardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, outcomes, contexts, verifier = controlled_inputs(16)
        # Keep all eight real model dimensions observed and nonzero. The
        # coordinator must never erase them to manufacture a weak control.
        for i in range(16):
            snapshot = deepcopy(rows[2*i]['learning_snapshot'])
            template = fixture('P1', research=True)
            for participant, original in zip(snapshot['participants'], template['participants']):
                participant['features'] = original['features']
                participant['missing'] = original['missing']
            bind_training_snapshot(rows[2*i:2*i+2], snapshot)
        # Two fictional, distinct source events. Repeated views from one media
        # file must never be renamed into an unseen evaluation event.
        proofs = {}
        for race, envelope in contexts.items():
            context = envelope['video_context']
            context['media_sha256'] = digest(dict(fictional_source_event=race[9:11]))
            reseal_context(context)
            receipt = envelope['receipt']
            proofs[context['context_sha256']] = dict(context_sha256=context['context_sha256'],
                id=receipt['id'], digest=receipt['digest'], created_at=receipt['created_at'])
        verifier = lambda receipt, sha, at: deepcopy(proofs.get(sha))
        cls.inputs = rows, outcomes, contexts, verifier
        cls.cached = None

    def setUp(self):
        self.records = SavedRecords()
        self.rows, self.outcomes, self.contexts, self.video_verifier = deepcopy(self.inputs)
        entries = {row['race_id']: dict(event_id='meet-' + row['race_id'][9:11],
                    source_group='source-' + row['race_id'][9:11]) for row in self.rows}
        entries['20300401-24-12'] = dict(event_id='unseen-meet', source_group='unseen-video')
        event_map = seal(dict(schema='RACE_AI_BOAT_VIDEO_EVENT_MAP_V1',
            created_at=(NOW-timedelta(minutes=10)).isoformat(), races=entries), 'event_map_sha256')
        self.event_map = self.records.put(event_map, NOW-timedelta(minutes=9))

    def module(self):
        try:
            return importlib.import_module('race_ai.boat_video_forward')
        except ModuleNotFoundError:
            self.fail('missing actual existing-family matched forward coordinator')

    def fit(self, **overrides):
        arguments = dict(rows=self.rows, observations=self.outcomes,
            video_contexts=self.contexts, event_map_context=self.event_map,
            now=NOW, record_reader=self.records.read, video_receipt_verifier=self.video_verifier)
        arguments.update(overrides)
        return self.module().fit_matched(**arguments)

    def active_history(self, lanes):
        proofs = {}
        for index, row in enumerate(self.rows[::2]):
            pair = self.rows[2*index:2*index+2]
            snapshot = deepcopy(row['learning_snapshot'])
            snapshot['participants'] = [p for p in snapshot['participants'] if p['lane'] in lanes]
            roster = {str(p['lane']): p['registration_no'] for p in snapshot['participants']}
            for member in pair:
                member['roster'] = deepcopy(roster)
            bind_training_snapshot(pair, snapshot)
            winner = list(reversed(lanes))[:3]
            self.outcomes[index]['data'] = observation(dict(pair[0], top8=[winner]))['data']
            proof = active_video_envelope(self.contexts[row['race_id']], lanes)
            proofs[proof['context_sha256']] = proof
        self.video_verifier = lambda receipt, sha, at: deepcopy(proofs.get(sha))

    def prepared(self, *, active=None, training=None):
        if training is None:
            if self.__class__.cached is None:
                self.__class__.cached = self.fit()
            training = self.__class__.cached
        training = deepcopy(training)
        training_context = self.records.put(training, NOW+timedelta(seconds=2))
        _, _, inputs, verifier, instant = controlled_connection(training['challenger'])
        self.target = inputs['snapshot']
        self.target_video = dict(video_context=inputs['video_context'], receipt=inputs['video_receipt'])
        self.target_verifier = verifier
        if active is not None:
            self.target['participants'] = [p for p in self.target['participants'] if p['lane'] in active]
            proof = active_video_envelope(self.target_video, active)
            context, receipt = self.target_video['video_context'], self.target_video['receipt']
            self.target_verifier = lambda raw, sha, at: deepcopy(proof) if (
                raw == receipt and sha == context['context_sha256'] and at == self.target['as_of']) else None
        self.instant = instant
        targets = [dict(race_id='20300401-24-12', cutoff_at=self.target['sales_cutoff_at'],
                        roster_sha256=digest({str(p['lane']): p['registration_no']
                                             for p in self.target['participants']}))]
        study = self.module().register_study(training_context, targets,
            now=NOW+timedelta(seconds=5), record_reader=self.records.read)
        return self.records.put(study, NOW+timedelta(seconds=7))

    def forecast(self, study, **overrides):
        arguments = dict(record_reader=self.records.read,
            video_receipt_verifier=self.target_verifier, allow_source=lambda *_: True,
            clock=lambda: self.instant)
        arguments.update(overrides)
        return self.module().forecast(study, self.target, self.target_video, **arguments)

    def result(self, winner):
        row = dict(race_id='20300401-24-12', cutoff_at=self.target['sales_cutoff_at'],
                   top8=[winner], roster={str(p['lane']): p['registration_no']
                                         for p in self.target['participants']})
        outcome = observation(row)
        outcome['source_url'] = 'https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20300401&jcd=24&rno=12'
        outcome['captured_at'] = (existing.ts(row['cutoff_at'])+timedelta(minutes=1)).isoformat()
        return outcome

    def score(self, study, forecasts, outcomes):
        return self.module().score(study, forecasts, outcomes,
            now=NOW+timedelta(hours=2), record_reader=self.records.read,
            video_receipt_verifier=self.target_verifier, allow_source=lambda *_: True)

    def test_control_is_actually_trained_on_identical_unmodified_observations(self):
        before = deepcopy((self.rows, self.outcomes, self.contexts))
        fitted = self.fit()
        self.assertEqual(fitted['state'], 'MATCHED_FITTED_RESEARCH')
        self.assertEqual(fitted['control']['train_races'], 12)
        self.assertEqual(fitted['challenger']['validation_races'], 4)
        self.assertEqual(fitted['control']['train_race_ids'], fitted['challenger']['train_race_ids'])
        self.assertEqual(set(fitted['models']), set(MODEL_IDS))
        for model in MODEL_IDS:
            self.assertNotEqual(fitted['control']['models'][model]['weights'],
                                fitted['control']['models'][model]['base_weights'])
            self.assertTrue(any(w != 0 for w in fitted['challenger']['models'][model]['video_weights']))
        self.assertEqual((self.rows, self.outcomes, self.contexts), before)

    def test_matched_fit_registration_forecast_and_score_keep_all_active_lane_sets(self):
        cases = (((2, 4, 6), 6), ((1, 3, 5, 6), 24),
                 ((1, 2, 4, 5, 6), 60), ((1, 2, 3, 4, 5, 6), 120))
        for lanes, count in cases:
            with self.subTest(lanes=lanes):
                self.rows, self.outcomes, self.contexts, self.video_verifier = deepcopy(self.inputs)
                self.active_history(lanes)
                before = deepcopy((self.rows, self.outcomes, self.contexts))
                try:
                    fitted = self.fit()
                    study = self.prepared(active=lanes, training=fitted)
                    forecast = self.forecast(study)
                    saved = self.records.put(forecast, self.instant+timedelta(seconds=2))
                    outcome = self.records.put(self.result(list(reversed(lanes))[:3]),
                                               NOW+timedelta(minutes=40))
                    comparison = self.score(study, [saved], [outcome])
                except ValueError as error:
                    self.fail('valid active-roster matched pipeline was rejected: ' + str(error))
                self.assertEqual((self.rows, self.outcomes, self.contexts), before)
                self.assertEqual(fitted['state'], 'MATCHED_FITTED_RESEARCH')
                self.assertEqual(fitted['control']['unique_races'], 16)
                self.assertEqual(fitted['control']['train_race_ids'], fitted['challenger']['train_race_ids'])
                self.assertEqual(fitted['control']['validation_race_ids'], fitted['challenger']['validation_race_ids'])
                self.assertEqual(forecast['status'], 'PAIRED_RESEARCH')
                self.assertEqual([p['lane'] for p in forecast['snapshot']['participants']], list(lanes))
                universe = set(permutations(lanes, 3))
                for role in ('control', 'challenger'):
                    self.assertEqual({model['model_id'] for model in forecast[role]}, set(MODEL_IDS))
                    for model in forecast[role]:
                        self.assertEqual(model['candidate_count'], count)
                        self.assertEqual(len(model['candidates']), count)
                        self.assertEqual({tuple(c['combination']) for c in model['candidates']}, universe)
                        self.assertEqual(model['ordered_top8'],
                            [c['combination'] for c in model['candidates'][:8]])
                        self.assertEqual(len(model['ordered_top8']), min(8, count))
                self.assertEqual(comparison['declared_races'], 1)
                self.assertEqual([m['paired_races'] for m in comparison['models']], [1, 1])
                self.assertEqual([m['cases'][0]['state'] for m in comparison['models']], ['PAIRED', 'PAIRED'])
                self.assertFalse(forecast['production_eligible'])
                self.assertFalse(comparison['production_eligible'])
                self.assertFalse(comparison['accuracy_improvement_proven'])

    def test_active_target_rejects_withdrawn_duplicate_and_insufficient_lanes(self):
        study = self.prepared(active=(1, 2, 4, 5, 6))
        original = deepcopy(self.target)
        withdrawn = deepcopy(fixture('P1', research=True)['participants'][2])
        withdrawn['registration_no'] = '4203'
        for change in ('withdrawn', 'duplicate', 'insufficient', 'renumbered', 'registration'):
            self.target = deepcopy(original)
            if change == 'withdrawn':
                self.target['participants'].append(deepcopy(withdrawn))
            elif change == 'duplicate':
                self.target['participants'].append(deepcopy(self.target['participants'][0]))
            elif change == 'insufficient':
                self.target['participants'] = self.target['participants'][:2]
            elif change == 'renumbered':
                self.target['participants'][2]['lane'] = 3
            else:
                self.target['participants'][0]['registration_no'] = '9999'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.forecast(study)

    def test_active_history_rejects_mismatched_or_malformed_snapshot_rosters(self):
        self.active_history((2, 4, 6))
        for change in ('mismatched', 'duplicate', 'insufficient'):
            rows = deepcopy(self.rows)
            if change == 'mismatched':
                rows[0]['roster']['1'] = '4201'
            else:
                snapshot = rows[0]['learning_snapshot']
                if change == 'duplicate':
                    snapshot['participants'].append(deepcopy(snapshot['participants'][0]))
                else:
                    snapshot['participants'] = snapshot['participants'][:2]
                rows[0]['learning_snapshot_sha256'] = digest(snapshot)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.fit(rows=rows)

    def test_active_scoring_rejects_resealed_withdrawn_boat_predictions(self):
        study = self.prepared(active=(1, 2, 4, 5, 6))
        original = self.forecast(study)
        for role in ('control', 'challenger'):
            changed = deepcopy(original)
            model = changed[role][0]
            model['candidates'][0]['combination'] = [1, 2, 3]
            model['ordered_top8'][0] = [1, 2, 3]
            seal(model, 'prediction_sha256')
            seal(changed, 'forecast_sha256')
            saved = self.records.put(changed, self.instant+timedelta(seconds=2))
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'FROZEN_MODEL_REPLAY_CHANGED'):
                self.score(study, [saved], [])

    def test_active_training_rejects_unknown_resealed_control_version(self):
        self.active_history((2, 4, 6))
        fitted = self.fit()
        fitted['control']['models'][MODEL_IDS[0]]['model_version'] = '0.2.0-FITTED-SHADOW-ACTIVE-ROSTER-BYPASS'
        seal(fitted['control'], 'training_sha256')
        fitted['models'] = self.module()._model_pins(fitted['control'], fitted['challenger'])
        seal(fitted, 'training_pair_sha256')
        with self.assertRaisesRegex(ValueError, 'MODEL_VERSION'):
            self.prepared(active=(2, 4, 6), training=fitted)

    def test_no_authenticated_contexts_retains_zero_video_support(self):
        fitted = self.fit(video_contexts={}, video_receipt_verifier=None)
        self.assertEqual(fitted['state'], 'INSUFFICIENT_VIDEO_SUPPORT')
        self.assertEqual(fitted['challenger']['video_admitted_races'], 0)
        saved = self.records.put(fitted, NOW+timedelta(seconds=2))
        with self.assertRaises(ValueError):
            self.module().register_study(saved, [], now=NOW+timedelta(seconds=5),
                                         record_reader=self.records.read)

    def test_four_valid_races_without_video_report_insufficient_support(self):
        try:
            fitted = self.fit(rows=self.rows[:8], observations=self.outcomes[:4],
                              video_contexts={}, video_receipt_verifier=None)
        except ValueError:
            self.fail('valid startup history must report insufficient support, not a fitted-split mismatch')
        self.assertEqual(fitted['state'], 'INSUFFICIENT_VIDEO_SUPPORT')
        self.assertEqual(fitted['control']['unique_races'], 4)
        self.assertEqual(fitted['challenger']['unique_races'], 4)
        self.assertEqual(fitted['challenger']['video_admitted_races'], 0)
        self.assertEqual(fitted['models'], {})

    def test_sparse_fit_reopening_still_rejects_different_admitted_inputs(self):
        try:
            fitted = self.fit(rows=self.rows[:8], observations=self.outcomes[:4],
                              video_contexts={}, video_receipt_verifier=None)
        except ValueError:
            self.fail('cannot verify sparse lineage until normal insufficient input is accepted')
        fitted['control']['source_lineage'][0]['snapshot_sha256'] = 'e'*64
        seal(fitted['control'], 'training_sha256')
        seal(fitted, 'training_pair_sha256')
        saved = self.records.put(fitted, NOW+timedelta(seconds=2))
        with self.assertRaisesRegex(ValueError, 'UNMATCHED_TRAINING_INPUTS'):
            self.module().register_study(saved, [], now=NOW+timedelta(seconds=5),
                                         record_reader=self.records.read)

    def test_training_and_validation_cannot_share_an_event(self):
        changed = deepcopy(self.event_map['document'])
        for entry in changed['races'].values():
            entry['event_id'] = 'same-meet'
        changed = self.records.put(seal(changed, 'event_map_sha256'), NOW-timedelta(minutes=8))
        with self.assertRaises(ValueError):
            self.fit(event_map_context=changed)

    def test_same_source_media_cannot_be_renamed_as_a_new_evaluation_event(self):
        study = self.prepared()
        context = self.target_video['video_context']
        context['media_sha256'] = next(iter(self.contexts.values()))['video_context']['media_sha256']
        reseal_context(context)
        receipt = self.target_video['receipt']
        proof = dict(context_sha256=context['context_sha256'], id=receipt['id'],
                     digest=receipt['digest'], created_at=receipt['created_at'])
        self.target_verifier = lambda *_: deepcopy(proof)
        with self.assertRaises(ValueError):
            self.forecast(study)

    def test_train_validation_media_overlap_rejects_distinct_event_declarations(self):
        media = next(iter(self.contexts.values()))['video_context']['media_sha256']
        proofs = {}
        for envelope in self.contexts.values():
            context, receipt = envelope['video_context'], envelope['receipt']
            context['media_sha256'] = media
            reseal_context(context)
            proofs[context['context_sha256']] = dict(context_sha256=context['context_sha256'],
                id=receipt['id'], digest=receipt['digest'], created_at=receipt['created_at'])
        verifier = lambda receipt, sha, at: deepcopy(proofs.get(sha))
        with self.assertRaisesRegex(ValueError, 'TRAIN_VALIDATION_MEDIA_OVERLAP'):
            self.fit(video_receipt_verifier=verifier)

    def test_reopening_fit_rechecks_per_race_media_separation(self):
        fitted = self.fit()
        lineage = fitted.get('training_video_media_by_race')
        self.assertIsNotNone(lineage, 'frozen fit must retain source media by admitted race')
        train = fitted['control']['train_race_ids'][0]
        holdout = fitted['control']['validation_race_ids'][0]
        lineage[holdout]['media_sha256'] = lineage[train]['media_sha256']
        fitted['training_video_media_sha256'] = sorted({v['media_sha256'] for v in lineage.values()})
        seal(fitted, 'training_pair_sha256')
        saved = self.records.put(fitted, NOW+timedelta(seconds=2))
        with self.assertRaisesRegex(ValueError, 'TRAIN_VALIDATION_MEDIA_OVERLAP'):
            self.module().register_study(saved, [], now=NOW+timedelta(seconds=5),
                                         record_reader=self.records.read)

    def test_event_map_cannot_be_a_self_declared_hash_without_independent_reader(self):
        with self.assertRaises(ValueError):
            self.fit(record_reader=None)

    def test_reader_can_select_exact_record_among_existing_artifact_members(self):
        members = [dict(unrelated='saved private report'), self.event_map['document']]
        def reader(receipt, document_sha256):
            if receipt != self.event_map['receipt']:
                raise ValueError('wrong fictional artifact')
            return next(deepcopy(d) for d in members if digest(d) == document_sha256)
        try:
            fitted = self.fit(video_contexts={}, video_receipt_verifier=None, record_reader=reader)
        except ValueError:
            self.fail('reader must receive the exact document hash to extract an existing artifact member')
        self.assertEqual(fitted['challenger']['video_admitted_races'], 0)

    def test_registration_rejects_a_future_race_from_a_training_event(self):
        fitted = self.fit()
        entry = fitted['event_map_context']['document']['races']['20300401-24-12']
        entry['event_id'] = 'meet-01'
        event_map = seal(fitted['event_map_context']['document'], 'event_map_sha256')
        self.event_map = self.records.put(event_map, NOW-timedelta(minutes=8))
        fitted = self.fit()
        _, _, inputs, _, _ = controlled_connection(fitted['challenger'])
        target = dict(race_id='20300401-24-12', cutoff_at=inputs['snapshot']['sales_cutoff_at'],
            roster_sha256=digest({str(p['lane']): p['registration_no'] for p in inputs['snapshot']['participants']}))
        saved = self.records.put(fitted, NOW+timedelta(seconds=2))
        with self.assertRaises(ValueError):
            self.module().register_study(saved, [target], now=NOW+timedelta(seconds=5),
                                         record_reader=self.records.read)

    def test_actual_equations_emit_both_existing_families_with_matched_control(self):
        study = self.prepared()
        output = self.forecast(study)
        self.assertEqual(output['status'], 'PAIRED_RESEARCH')
        self.assertEqual(len(output['control']), 2)
        self.assertEqual(len(output['challenger']), 2)
        # Independently recorded numerical fixture expectations; both controls
        # cover 5-4-6, while both video challengers replace it with 6-5-2.
        for control, candidate in zip(output['control'], output['challenger']):
            self.assertIn([5, 4, 6], control['ordered_top8'])
            self.assertNotIn([5, 4, 6], candidate['ordered_top8'])
            self.assertIn([6, 5, 2], candidate['ordered_top8'])
            self.assertEqual(control['input_sha256'], candidate['input_sha256'])

    def test_declined_source_never_produces_a_forecast(self):
        study = self.prepared()
        with self.assertRaises(ValueError):
            self.forecast(study, allow_source=lambda *_: False)

    def test_late_synthetic_and_wrong_roster_video_never_reaches_paired_forecast(self):
        study = self.prepared()
        original = deepcopy(self.target_video)
        for change in ('synthetic', 'late', 'roster'):
            self.target_video = deepcopy(original)
            context = self.target_video['video_context']
            if change == 'synthetic':
                context['dataset_status'] = 'SYNTHETIC_ONLY'
            elif change == 'late':
                self.target_video['receipt']['created_at'] = self.target['sales_cutoff_at']
            else:
                context['participants'][0]['registration_number'] = '9999'
            reseal_context(context)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.forecast(study)

    def test_missing_context_does_not_invent_a_candidate_or_drop_declared_case(self):
        study = self.prepared()
        self.target_video = None
        output = self.forecast(study)
        self.assertEqual(output['status'], 'MISSING_VIDEO_CONTEXT')
        self.assertEqual(output['challenger'], [])
        saved = self.records.put(output, self.instant+timedelta(seconds=2))
        outcome = self.records.put(self.result([6, 5, 4]), NOW+timedelta(minutes=40))
        result = self.score(study, [saved], [outcome])
        self.assertEqual(result['declared_races'], 1)
        self.assertTrue(all(m['paired_races'] == 0 for m in result['models']))
        self.assertFalse(result['accuracy_improvement_proven'])

    def test_degraded_and_no_effect_challenger_are_reported_honestly(self):
        study = self.prepared()
        output = self.forecast(study)
        saved = self.records.put(output, self.instant+timedelta(seconds=2))
        for winner, expected in (([5, 4, 6], 'DEGRADED'), ([6, 5, 4], 'NO_EFFECT'),
                                 ([6, 5, 2], 'OBSERVED_GAIN')):
            outcome = self.records.put(self.result(winner), NOW+timedelta(minutes=40))
            with self.subTest(winner=winner):
                result = self.score(study, [saved], [outcome])
                self.assertEqual([m['effect'] for m in result['models']], [expected, expected])
                self.assertEqual([m['paired_races'] for m in result['models']], [1, 1])
                self.assertFalse(result['accuracy_improvement_proven'])
                self.assertFalse(result['production_eligible'])

    def test_distinct_valid_forecasts_change_comparison_proof_with_equal_aggregates(self):
        study = self.prepared()
        first = self.forecast(study)
        second = self.forecast(study, clock=lambda: self.instant+timedelta(seconds=1))
        first_saved = self.records.put(first, self.instant+timedelta(seconds=2))
        second_saved = self.records.put(second, self.instant+timedelta(seconds=3))
        outcome = self.records.put(self.result([6, 5, 4]), NOW+timedelta(minutes=40))
        a = self.score(study, [first_saved], [outcome])
        b = self.score(study, [second_saved], [outcome])
        self.assertNotEqual(a, b, 'comparison must identify the exact counted forecast originals')
        self.assertNotEqual(a['comparison_sha256'], b['comparison_sha256'])
        self.assertNotEqual(a['comparison_inputs_sha256'], b['comparison_inputs_sha256'])
        self.assertEqual([(m['control_hits'], m['challenger_hits']) for m in a['models']], [(1, 1), (1, 1)])
        self.assertEqual([(m['control_hits'], m['challenger_hits']) for m in b['models']], [(1, 1), (1, 1)])
        case = a['models'][0]['cases'][0]
        self.assertEqual(case['forecast_reference']['forecast_sha256'], first['forecast_sha256'])
        self.assertEqual(case['forecast_reference']['document_sha256'], digest(first))
        self.assertEqual(case['forecast_reference']['receipt'], first_saved['receipt'])
        self.assertEqual(case['result_reference']['document_sha256'], digest(outcome['document']))
        self.assertEqual(case['result_reference']['receipt'], outcome['receipt'])
        self.assertEqual(case['result_reference']['source_sha256'], 'b'*64)
        self.assertEqual(case['control_prediction_sha256'], first['control'][0]['prediction_sha256'])
        self.assertEqual(case['challenger_prediction_sha256'], first['challenger'][0]['prediction_sha256'])
        existing.check(a, 'comparison_sha256')
        a['models'][0]['cases'][0]['result_reference']['source_sha256'] = 'd'*64
        with self.assertRaises(ValueError):
            existing.check(a, 'comparison_sha256')

    def test_distinct_saved_official_results_change_comparison_input_proof(self):
        study = self.prepared()
        saved = self.records.put(self.forecast(study), self.instant+timedelta(seconds=2))
        first = self.records.put(self.result([6, 5, 4]), NOW+timedelta(minutes=40))
        updated = self.result([6, 5, 4]); updated['source_sha256'] = 'c'*64
        second = self.records.put(updated, NOW+timedelta(minutes=41))
        a = self.score(study, [saved], [first])
        b = self.score(study, [saved], [second])
        self.assertNotEqual(a, b, 'comparison must identify the exact official result observation')
        self.assertNotEqual(a['comparison_inputs_sha256'], b['comparison_inputs_sha256'])
        self.assertEqual(b['models'][0]['cases'][0]['result_reference']['source_sha256'], 'c'*64)

    def test_unpaired_declared_case_retains_its_saved_result_reference(self):
        study = self.prepared()
        outcome = self.records.put(self.result([6, 5, 4]), NOW+timedelta(minutes=40))
        output = self.score(study, [], [outcome])
        case = output['models'][0]['cases'][0]
        self.assertEqual(case['state'], 'MISSING_FORECAST')
        self.assertIn('result_reference', case, 'missing forecasts must not discard authenticated result lineage')
        self.assertEqual(case['result_reference']['receipt'], outcome['receipt'])
        self.assertIsNone(case['forecast_reference'])

    def test_mutating_or_resealing_a_saved_forecast_never_changes_its_result(self):
        study = self.prepared()
        saved = self.records.put(self.forecast(study), self.instant+timedelta(seconds=2))
        saved['document']['challenger'][0]['ordered_top8'][0] = [1, 2, 3]
        seal(saved['document']['challenger'][0], 'prediction_sha256')
        seal(saved['document'], 'forecast_sha256')
        with self.assertRaises(ValueError):
            self.score(study, [saved], [])

    def test_new_receipt_cannot_make_a_resealed_wrong_model_output_replay(self):
        study = self.prepared()
        output = self.forecast(study)
        output['challenger'][0]['ordered_top8'][0] = [1, 2, 3]
        seal(output['challenger'][0], 'prediction_sha256')
        seal(output, 'forecast_sha256')
        saved = self.records.put(output, self.instant+timedelta(seconds=2))
        with self.assertRaises(ValueError):
            self.score(study, [saved], [])

    def test_independently_saved_mismatched_training_inputs_are_rejected(self):
        fitted = self.fit()
        fitted['control']['source_lineage'][0]['snapshot_sha256'] = 'f'*64
        seal(fitted['control'], 'training_sha256')
        seal(fitted, 'training_pair_sha256')
        saved = self.records.put(fitted, NOW+timedelta(seconds=2))
        with self.assertRaises(ValueError):
            self.module().register_study(saved, [], now=NOW+timedelta(seconds=5),
                                         record_reader=self.records.read)

    def test_saved_training_control_version_cannot_be_swapped_after_registration(self):
        study = self.prepared()
        changed = study['document']['training_context']['document']['control']
        changed['models'][MODEL_IDS[0]]['model_version'] = 'different-version'
        seal(changed, 'training_sha256')
        seal(study['document'], 'study_sha256')
        with self.assertRaises(ValueError):
            self.forecast(study)

    def test_late_forecast_receipt_and_result_before_cutoff_cannot_count(self):
        study = self.prepared()
        output = self.forecast(study)
        late = self.records.put(output, existing.ts(self.target['sales_cutoff_at']))
        with self.assertRaises(ValueError):
            self.score(study, [late], [])
        saved = self.records.put(output, self.instant+timedelta(seconds=2))
        bad = self.result([6, 5, 4])
        bad['captured_at'] = self.target['as_of']
        outcome = self.records.put(bad, NOW+timedelta(minutes=40))
        with self.assertRaises(ValueError):
            self.score(study, [saved], [outcome])

    def test_preregistration_must_precede_native_input_and_completion_must_precede_cutoff(self):
        study = self.prepared()
        late_study = self.records.put(study['document'], existing.ts(self.target['as_of']))
        with self.assertRaises(ValueError):
            self.forecast(late_study)
        times = iter((self.instant, existing.ts(self.target['sales_cutoff_at'])))
        with self.assertRaises(ValueError):
            self.forecast(study, clock=lambda: next(times))

    def test_duplicate_forecasts_and_foreign_official_result_source_are_rejected(self):
        study = self.prepared()
        saved = self.records.put(self.forecast(study), self.instant+timedelta(seconds=2))
        with self.assertRaises(ValueError):
            self.score(study, [saved, saved], [])
        bad = self.result([6, 5, 4]); bad['source_url'] = 'https://example.test/raceresult'
        outcome = self.records.put(bad, NOW+timedelta(minutes=40))
        with self.assertRaises(ValueError):
            self.score(study, [saved], [outcome])
