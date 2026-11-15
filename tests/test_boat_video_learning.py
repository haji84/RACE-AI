"""Controlled fictional math and trust-boundary tests; no real video evidence."""
from copy import deepcopy
from datetime import timedelta
import importlib
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import MODEL_IDS, WEIGHTS, predict_pair
from race_ai import observed_weight_learning as existing
from tests import test_observed_weight_learning as observed_fixtures

dataset, NOW = observed_fixtures.dataset, observed_fixtures.NOW
from tests.test_boat_video_model_context import fixture as raw_video_fixture


def module(test):
    try:
        return importlib.import_module('race_ai.boat_video_learning')
    except ModuleNotFoundError:
        test.fail('optional video parameter fitting for existing families is missing')


def reseal_context(value):
    value.pop('context_sha256', None)
    value['context_sha256'] = digest(value)
    return value


def as_p1(snapshot):
    """Keep a constant official exhibition observation so P1 is structurally valid."""
    snapshot = deepcopy(snapshot)
    snapshot['stage'] = 'P1'
    for participant in snapshot['participants']:
        participant['features']['exhibition_time_seconds'] = dict(value=6.9, sample_n=None,
            source_id=snapshot['race_source_id'], transform_id='official_exhibition_time_seconds_v1')
        participant['missing'].pop('exhibition_time_seconds', None)
    return snapshot


def bind_training_snapshot(rows, snapshot):
    suite = predict_pair(snapshot, allow_source=lambda *_: True)
    for row in rows:
        model = suite['models'][row['model_id']]
        row.update(stage=snapshot['stage'], model_sha256=model['prediction_sha256'],
            original_json_sha256=digest(suite), top8=deepcopy(model['ordered_top8']),
            ranked=[deepcopy(item['combination']) for item in model['candidates']],
            learning_snapshot=deepcopy(snapshot), learning_snapshot_sha256=digest(snapshot))


def controlled_inputs(count=12):
    """A simulated authenticated reader is test input, never a real receipt claim."""
    from race_ai.boat_video_model_context import prepare_video_context
    from tests.test_boat_video_model_context import AS_OF
    report, evidence = raw_video_fixture()
    template = prepare_video_context(report, evidence, race_id=report['race_id'],
        cutoff_at=report['cutoff_at'], roster=report['roster'], as_of=AS_OF)
    rows, observations = dataset(count)
    contexts, proofs = {}, {}
    for index, row in enumerate(rows[::2]):
        snap = row['learning_snapshot']
        # Remove the original eight signals to isolate learned video direction.
        for participant in snap['participants']:
            participant['missing'] = dict.fromkeys(existing.FEATURES, 'MISSING')
            participant['features'] = {}
        snap = as_p1(snap)
        bind_training_snapshot(rows[2 * index:2 * index + 2], snap)
        context = deepcopy(template)
        instant = existing.ts(snap['as_of'])
        context.update(race_id=row['race_id'], cutoff_at=row['cutoff_at'],
            as_of=(instant-timedelta(minutes=1)).isoformat(),
            source_captured_at=(instant-timedelta(minutes=5)).isoformat(),
            analysis_started_at=(instant-timedelta(minutes=4)).isoformat(),
            analysis_completed_at=(instant-timedelta(minutes=3)).isoformat(),
            evidence_created_at=(instant-timedelta(minutes=2)).isoformat())
        for participant in context['participants']:
            participant['registration_number'] = row['roster'][str(participant['lane'])]
        reseal_context(context)
        receipt = dict(id=1000 + index, created_at=(instant-timedelta(seconds=30)).isoformat(),
            digest='sha256:' + digest({'saved_context': context}), expired=False,
            workflow_run={'head_repository_id': 1416489937})
        contexts[row['race_id']] = dict(video_context=context, receipt=receipt)
        proofs[context['context_sha256']] = dict(context_sha256=context['context_sha256'],
            id=receipt['id'], digest=receipt['digest'], created_at=receipt['created_at'])
        observation = observations[index]
        observation['data']['top3'] = [6, 5, 4]
        observation['data']['payouts'][0]['combination'] = [6, 5, 4]
    def verifier(receipt, context_sha256, as_of):
        # This map stands in for bytes independently obtained by a trusted caller.
        return deepcopy(proofs.get(context_sha256))
    return rows, observations, contexts, verifier


class VideoLearningTests(unittest.TestCase):
    def test_current_exhibition_video_cannot_bypass_the_p0_feature_contract(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        snapshot = deepcopy(rows[0]['learning_snapshot'])
        snapshot['stage'] = 'P0'
        for participant in snapshot['participants']:
            for feature in ('exhibition_time_seconds', 'exhibition_start_seconds'):
                participant['features'].pop(feature, None)
                participant['missing'][feature] = 'NOT_YET_PUBLISHED'
        # This is a valid P0 input even though its supplied timestamp is later
        # than the separately available exhibition report and frozen receipt.
        suite = predict_pair(snapshot, allow_source=lambda *_: True)
        self.assertEqual(suite['stage'], 'P0')
        context = contexts[rows[0]['race_id']]['video_context']
        self.assertLess(existing.ts(context['as_of']), existing.ts(snapshot['as_of']))
        with self.assertRaises(ValueError):
            learning.video_vectors(snapshot, context)
        bind_training_snapshot(rows[:2], snapshot)
        with self.assertRaises(ValueError):
            learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        without_video = learning.video_vectors(snapshot, None)
        self.assertTrue(all(vector[-4:] == [0.] * 4 for vector in without_video.values()))

    def test_p0_history_keeps_base_features_but_supplies_no_video_train_support(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        for index in range(4):
            pair = rows[2*index:2*index+2]
            snapshot = deepcopy(pair[0]['learning_snapshot'])
            snapshot['stage'] = 'P0'
            for participant in snapshot['participants']:
                participant['features'].pop('exhibition_time_seconds')
                participant['missing']['exhibition_time_seconds'] = 'NOT_YET_PUBLISHED'
            bind_training_snapshot(pair, snapshot)
            contexts.pop(pair[0]['race_id'])
        training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        self.assertEqual(training['state'], 'FITTED_VIDEO_EXPERIMENTAL')
        self.assertEqual(training['unique_races'], 12)
        self.assertEqual(training['video_admitted_races'], 8)
        self.assertEqual(training['observed_phase_counts'], {'P0': 4, 'P1': 8})
        self.assertEqual(set(training['feature_support_train'].values()), {5})
        self.assertIsNone(learning.verify_video_training(training))

    def test_resealed_video_training_cannot_claim_a_p0_exhibition_source(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        training['source_lineage'][0]['phase'] = 'P0'
        existing.seal(training, 'training_sha256')
        with self.assertRaises(ValueError):
            learning.verify_video_training(training)

    def test_frozen_context_can_precede_its_receipt_and_later_model_snapshot(self):
        learning = module(self)
        rows, observations, contexts, _ = controlled_inputs()
        proofs = {}
        for row in rows[::2]:
            envelope = contexts[row['race_id']]
            context = envelope['video_context']
            context['as_of'] = (existing.ts(row['as_of'])-timedelta(minutes=1)).isoformat()
            reseal_context(context)
            receipt = envelope['receipt']
            proofs[context['context_sha256']] = dict(context_sha256=context['context_sha256'],
                id=receipt['id'], digest=receipt['digest'], created_at=receipt['created_at'])
            self.assertLess(existing.ts(context['as_of']), existing.ts(receipt['created_at']))
            self.assertLess(existing.ts(receipt['created_at']), existing.ts(row['as_of']))
        before = deepcopy(contexts)
        verifier = lambda receipt, sha, as_of: deepcopy(proofs[sha])
        try:
            vector = learning.video_vectors(rows[0]['learning_snapshot'], contexts[rows[0]['race_id']]['video_context'])
            training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        except ValueError as exc:
            self.fail('legitimate independently frozen prior context was rejected: ' + str(exc))
        self.assertEqual(training['state'], 'FITTED_VIDEO_EXPERIMENTAL')
        self.assertNotEqual(vector[1][-4:], [0.] * 4)
        self.assertEqual(contexts, before)

    def test_whole_second_receipt_floor_allows_fractional_context_with_prior_upper_bound(self):
        learning = module(self)
        rows, observations, contexts, _ = controlled_inputs()
        proofs = {}
        for envelope in contexts.values():
            context, receipt = envelope['video_context'], envelope['receipt']
            context['as_of'] = (existing.ts(receipt['created_at'])+timedelta(microseconds=500000)).isoformat()
            reseal_context(context)
            proofs[context['context_sha256']] = dict(context_sha256=context['context_sha256'],
                id=receipt['id'], digest=receipt['digest'], created_at=receipt['created_at'])
        training = learning.fit_with_video(rows, observations, contexts, now=NOW,
            receipt_verifier=lambda receipt, sha, as_of: deepcopy(proofs[sha]))
        self.assertEqual(training['state'], 'FITTED_VIDEO_EXPERIMENTAL')
        self.assertIsNone(learning.verify_video_training(training))

    def test_video_receipt_cannot_predate_context_or_coincide_with_model_as_of(self):
        learning = module(self)
        rows, observations, contexts, _ = controlled_inputs()
        race_id = rows[0]['race_id']
        own_as_of = contexts[race_id]['video_context']['as_of']
        for saved in (rows[0]['as_of'],
                      (existing.ts(rows[0]['as_of'])-timedelta(microseconds=500000)).isoformat(),
                      (existing.ts(own_as_of)-timedelta(seconds=2)).isoformat()):
            bad = deepcopy(contexts)
            bad[race_id]['receipt']['created_at'] = saved
            proofs = {envelope['video_context']['context_sha256']:
                dict(context_sha256=envelope['video_context']['context_sha256'],
                    id=envelope['receipt']['id'], digest=envelope['receipt']['digest'],
                    created_at=envelope['receipt']['created_at']) for envelope in bad.values()}
            with self.subTest(saved=saved), self.assertRaises(ValueError):
                learning.fit_with_video(rows, observations, bad, now=NOW,
                    receipt_verifier=lambda receipt, sha, as_of: deepcopy(proofs[sha]))

    def test_future_context_as_of_is_rejected_without_changing_its_seal(self):
        learning = module(self)
        rows, _, contexts, _ = controlled_inputs()
        context = contexts[rows[0]['race_id']]['video_context']
        context['as_of'] = (existing.ts(rows[0]['as_of'])+timedelta(seconds=1)).isoformat()
        reseal_context(context)
        before = deepcopy(context)
        with self.assertRaises(ValueError):
            learning.video_vectors(rows[0]['learning_snapshot'], context)
        self.assertEqual(context, before)

    def test_unverified_contexts_cannot_fit_or_self_attest_with_json(self):
        learning = module(self)
        rows, observations, contexts, _ = controlled_inputs()
        for envelope in contexts.values():
            envelope['authenticated'] = True
        out = learning.fit_with_video(rows, observations, contexts, now=NOW)
        self.assertEqual(out['state'], 'INSUFFICIENT_VIDEO_SUPPORT')
        self.assertEqual(out['video_admitted_races'], 0)
        self.assertTrue(all(m['video_weights'] == [0.] * 4 for m in out['models'].values()))
        self.assertFalse(out['auto_promoted'])
        self.assertFalse(out['accuracy_improvement_proven'])

    def test_outcomes_learn_a_direction_in_same_families_without_mutating_inputs(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        before = deepcopy((rows, observations, contexts, WEIGHTS))
        out = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        self.assertEqual(out['state'], 'FITTED_VIDEO_EXPERIMENTAL')
        self.assertEqual(out['source_family_ids'], list(MODEL_IDS))
        self.assertEqual(out['unique_races'], 12)
        self.assertEqual(out['train_races'], 9)
        self.assertEqual(out['validation_races'], 3)
        self.assertTrue(all(m['video_weights'][-1] > 0 for m in out['models'].values()))
        self.assertTrue(all(len(m['weights']) == 12 and m['model_version'] == '0.3.0-VIDEO-EXPERIMENTAL'
                            for m in out['models'].values()))
        self.assertEqual((rows, observations, contexts, WEIGHTS), before)
        self.assertIsNone(learning.verify_video_training(out))
        self.assertTrue(learning.replay_video_training(out, rows, observations, contexts,
            now=NOW, receipt_verifier=verifier))

    def test_raw_radius_gets_no_fixed_better_worse_direction(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        up = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        for result in observations:
            result['data']['top3'] = [1, 2, 3]
            result['data']['payouts'][0]['combination'] = [1, 2, 3]
        down = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        for mid in MODEL_IDS:
            self.assertGreater(up['models'][mid]['video_weights'][0], 0)
            self.assertLess(down['models'][mid]['video_weights'][0], 0)

    def test_holdout_and_simultaneous_outcomes_never_change_training_coefficients(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        observations[8]['captured_at'] = observations[9]['captured_at']
        out = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        self.assertEqual(out['train_races'], 8)
        self.assertEqual(out['validation_races'], 4)
        changed = deepcopy(observations)
        for result in changed[8:]:
            result['data']['top3'] = [1, 2, 3]
            result['data']['payouts'][0]['combination'] = [1, 2, 3]
        again = learning.fit_with_video(rows, changed, contexts, now=NOW, receipt_verifier=verifier)
        for mid in MODEL_IDS:
            self.assertEqual(out['models'][mid]['weights'], again['models'][mid]['weights'])

    def test_minimum_support_is_four_train_races_not_holdout_or_duplicate_families(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        allowed = {r['race_id'] for r in rows[::2][:3]} | {r['race_id'] for r in rows[::2][-3:]}
        contexts = {rid: value for rid, value in contexts.items() if rid in allowed}
        out = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        self.assertEqual(out['state'], 'INSUFFICIENT_VIDEO_SUPPORT')
        self.assertTrue(all(value == 3 for value in out['feature_support_train'].values()))
        self.assertTrue(all(m['video_weights'] == [0.] * 4 for m in out['models'].values()))

    def test_future_results_and_ineligible_official_results_reuse_existing_admission(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        observations[0]['captured_at'] = (NOW+timedelta(seconds=1)).isoformat()
        observations[1]['data']['results'][0]['racer_registration_id'] = '9999'
        observations[2]['data']['refund_boats'] = [1]
        out = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        self.assertEqual(out['unique_races'], 9)
        self.assertEqual(len(out['excluded_races']), 3)

    def test_context_race_roster_source_units_and_external_receipt_must_bind(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        rid = rows[0]['race_id']
        cases = []
        bad = deepcopy(contexts); bad[rid]['video_context']['participants'][0]['registration_number'] = '9999'; cases.append(bad)
        bad = deepcopy(contexts); bad[rid]['video_context']['media_sha256'] = 'f' * 64; cases.append(bad)
        bad = deepcopy(contexts); bad[rid]['video_context']['participants'][0]['feature_cells']['straight_mean_speed']['unit'] = 'm/s'; cases.append(bad)
        bad = deepcopy(contexts); bad[rid]['video_context']['race_id'] = rows[2]['race_id']; cases.append(bad)
        bad = deepcopy(contexts); bad[rid]['receipt']['created_at'] = rows[0]['cutoff_at']; cases.append(bad)
        for bad in cases:
            reseal_context(bad[rid]['video_context'])
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                learning.fit_with_video(rows, observations, bad, now=NOW, receipt_verifier=verifier)

    def test_future_or_synthetic_input_cannot_train_even_with_receipt_callback(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        future = deepcopy(rows); future[0]['server_saved_at'] = (NOW+timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            learning.fit_with_video(future, observations, contexts, now=NOW, receipt_verifier=verifier)
        synthetic = deepcopy(rows)
        synthetic[0]['learning_snapshot']['scope'] = 'SYNTHETIC_ONLY'
        synthetic[0]['learning_snapshot_sha256'] = digest(synthetic[0]['learning_snapshot'])
        with self.assertRaises(ValueError):
            learning.fit_with_video(synthetic, observations, contexts, now=NOW, receipt_verifier=verifier)

    def test_trusted_reader_callback_cannot_mutate_the_bound_training_inputs(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        expected = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        def mutating_reader(receipt, context_sha256, as_of):
            rows[0]['learning_snapshot']['participants'][0]['registration_no'] = '9999'
            return verifier(receipt, context_sha256, as_of)
        try:
            actual = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=mutating_reader)
        except ValueError as exc:
            self.fail('reader mutation reached already-bound input: ' + str(exc))
        self.assertEqual(actual, expected)

    def test_resealed_training_policy_cannot_change_the_signed_feature_contract(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        training['training_policy']['video_weight_min'] = 0.
        existing.seal(training, 'training_sha256')
        with self.assertRaises(ValueError):
            learning.verify_video_training(training)

    def test_result_roster_cannot_rebind_features_to_different_registered_participants(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        for row in rows[:2]:
            row['roster']['1'] = '9999'
        observations[0]['data']['results'][0]['racer_registration_id'] = '9999'
        with self.assertRaises(ValueError):
            learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)

    def test_overlapping_intervals_give_no_contrast_or_training_support(self):
        learning = module(self)
        rows, observations, contexts, _ = controlled_inputs()
        proofs = {}
        for envelope in contexts.values():
            context = envelope['video_context']
            for comparison in context['comparisons'].values():
                comparison['uncertainty_by_lane'] = dict.fromkeys(map(str, range(1, 7)), 1.)
            for participant in context['participants']:
                for cell in participant['feature_cells'].values():
                    cell.update(value=10. + participant['lane'] * .00001, uncertainty=1.)
            reseal_context(context)
            receipt = envelope['receipt']
            proofs[context['context_sha256']] = dict(context_sha256=context['context_sha256'],
                id=receipt['id'], digest=receipt['digest'], created_at=receipt['created_at'])
        vector = learning.video_vectors(rows[0]['learning_snapshot'], contexts[rows[0]['race_id']]['video_context'])
        self.assertTrue(all(vector[lane][-4:] == [0.] * 4 for lane in range(1, 7)),
                        'uncertainty-overlapping measurements acquired a learned ordering')
        out = learning.fit_with_video(rows, observations, contexts, now=NOW,
            receipt_verifier=lambda receipt, sha, as_of: deepcopy(proofs[sha]))
        self.assertEqual(out['state'], 'INSUFFICIENT_VIDEO_SUPPORT')
        self.assertEqual(set(out['feature_support_train'].values()), {0})
        self.assertTrue(all(model['video_weights'] == [0.] * 4 for model in out['models'].values()))

    def test_only_interval_separated_pairs_contribute_with_six_divisor_and_zero_sum(self):
        learning = module(self)
        rows, _, contexts, _ = controlled_inputs()
        context = contexts[rows[0]['race_id']]['video_context']
        values = (10., 11., 14., 14., 14., 14.)
        context['comparisons']['straight']['uncertainty_by_lane'] = dict.fromkeys(map(str, range(1, 7)), 1.)
        for participant, value in zip(context['participants'], values):
            participant['feature_cells']['straight_mean_speed'].update(value=value, uncertainty=1.)
        reseal_context(context)
        vector = learning.video_vectors(rows[0]['learning_snapshot'], context)
        self.assertAlmostEqual(vector[1][-1], -4/6)
        self.assertAlmostEqual(vector[2][-1], -3/6)
        for lane in range(3, 7):
            self.assertAlmostEqual(vector[lane][-1], 1.75/6)
        self.assertAlmostEqual(sum(vector[lane][-1] for lane in range(1, 7)), 0.)

    def test_tiny_spans_and_extreme_finite_units_keep_bounded_exact_contrasts(self):
        learning = module(self)
        rows, _, contexts, _ = controlled_inputs()
        context = contexts[rows[0]['race_id']]['video_context']
        for phase in ('straight', 'exit'):
            context['comparisons'][phase]['uncertainty_by_lane'] = dict.fromkeys(map(str, range(1, 7)), 0.)
        for participant in context['participants']:
            lane = participant['lane']
            participant['feature_cells']['straight_mean_speed'].update(value=lane * 1.e-320, uncertainty=0.)
            participant['feature_cells']['exit_speed_trend'].update(
                value=(-1.e308 if lane == 1 else 1.e308 if lane == 2 else 0.), uncertainty=0.)
        reseal_context(context)
        vector = learning.video_vectors(rows[0]['learning_snapshot'], context)
        self.assertAlmostEqual(vector[1][-1], -.5)
        self.assertAlmostEqual(vector[6][-1], .5)
        self.assertAlmostEqual(vector[1][-3], -.5)
        self.assertAlmostEqual(vector[2][-3], .5)
        self.assertTrue(all(-1 <= value <= 1 for row in vector.values() for value in row[-4:]))

    def test_resealed_training_timestamps_must_follow_actual_lineage_availability(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        training['created_at'] = training['data_available_until'] = rows[0]['as_of']
        existing.seal(training, 'training_sha256')
        with self.assertRaises(ValueError):
            learning.verify_video_training(training)

    def test_resealed_lineage_receipts_must_precede_cutoff_and_creation(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        for field in ('input_saved_at', 'video_receipt_proof', 'ambiguous_video_receipt'):
            bad = deepcopy(training)
            lineage = bad['source_lineage'][0]
            if field == 'ambiguous_video_receipt':
                lineage['video_receipt_proof']['created_at'] = (existing.ts(lineage['input_as_of'])-
                    timedelta(microseconds=500000)).isoformat()
            elif field == 'video_receipt_proof':
                lineage[field]['created_at'] = lineage['cutoff_at']
            else:
                lineage[field] = lineage['cutoff_at']
            existing.seal(bad, 'training_sha256')
            with self.subTest(field=field), self.assertRaises(ValueError):
                learning.verify_video_training(bad)

    def test_resealed_unsupported_original_feature_coefficients_remain_frozen(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        self.assertEqual(training['base_feature_support_train']['national_win_rate'], 0)
        training['models'][MODEL_IDS[0]]['weights'][0] = 4.
        existing.seal(training, 'training_sha256')
        with self.assertRaises(ValueError):
            learning.verify_video_training(training)

    def test_zero_video_coefficients_are_exact_baseline_equations(self):
        learning = module(self)
        rows, _, contexts, _ = controlled_inputs()
        snap = rows[0]['learning_snapshot']
        x = learning.video_vectors(snap, contexts[rows[0]['race_id']]['video_context'])
        from race_ai.four_sport_learning import _all_triples
        for mid in MODEL_IDS:
            self.assertEqual(_all_triples(x, list(WEIGHTS[mid])+[0.] * 4),
                             _all_triples(existing.vectors(snap), list(WEIGHTS[mid])))
        self.assertAlmostEqual(x[1][-1], -.5)
        self.assertAlmostEqual(x[6][-1], .5)

    def test_prior_frozen_artifact_generates_only_experimental_existing_family_shadows(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        snapshot, _ = observed_fixtures.LearningTests().future()
        snapshot = as_p1(snapshot)
        suite = predict_pair(snapshot, allow_source=lambda *_: True)
        v = deepcopy(next(iter(contexts.values())))
        instant = existing.ts(snapshot['as_of'])
        v['video_context'].update(race_id='20300401-24-12',
            as_of=(instant-timedelta(minutes=1)).isoformat(), cutoff_at=snapshot['sales_cutoff_at'],
            source_captured_at=(instant-timedelta(minutes=5)).isoformat(),
            analysis_started_at=(instant-timedelta(minutes=4)).isoformat(),
            analysis_completed_at=(instant-timedelta(minutes=3)).isoformat(),
            evidence_created_at=(instant-timedelta(minutes=2)).isoformat())
        reseal_context(v['video_context'])
        v['receipt']['created_at'] = (instant-timedelta(seconds=30)).isoformat()
        proof = dict(context_sha256=v['video_context']['context_sha256'], id=v['receipt']['id'],
                     digest=v['receipt']['digest'], created_at=v['receipt']['created_at'])
        callback = lambda *_: deepcopy(proof)
        frozen = dict(training=training, receipt=dict(id=700, created_at=(NOW+timedelta(seconds=2)).isoformat(),
            digest='sha256:'+'a' * 64, expired=False, workflow_run={'head_repository_id': 1416489937}))
        out = learning.make_video_shadows(snapshot, suite, frozen, v, receipt_verifier=callback)
        self.assertEqual(len(out), 2)
        self.assertEqual({record['model_id'] for record in out}, set(MODEL_IDS))
        self.assertTrue(all(record['variant'] == 'LEARNED_VIDEO_EXPERIMENTAL' and
            len(record['candidates']) == 120 and len(record['ordered_top8']) == 8 and
            record['calibrated'] is False and record['production_eligible'] is False for record in out))
        self.assertEqual(out, learning.make_video_shadows(snapshot, suite, frozen, v, receipt_verifier=callback))
        self.assertEqual(learning.make_video_shadows(snapshot, suite, frozen, v), [])
        frozen['receipt']['created_at'] = snapshot['as_of']
        with self.assertRaises(ValueError):
            learning.make_video_shadows(snapshot, suite, frozen, v, receipt_verifier=callback)

    def test_resealed_invalid_training_parameters_and_target_training_are_rejected(self):
        learning = module(self)
        rows, observations, contexts, verifier = controlled_inputs()
        training = learning.fit_with_video(rows, observations, contexts, now=NOW, receipt_verifier=verifier)
        bad = deepcopy(training); bad['models'][MODEL_IDS[0]]['video_weights'][0] = 5.
        existing.seal(bad, 'training_sha256')
        with self.assertRaises(ValueError):
            learning.verify_video_training(bad)
        snap = rows[0]['learning_snapshot']; suite = predict_pair(snap, allow_source=lambda *_: True)
        context = dict(training=training, receipt=dict(id=700, created_at=rows[0]['as_of'],
            digest='sha256:'+'a'*64, expired=False, workflow_run={'head_repository_id': 1416489937}))
        with self.assertRaises(ValueError):
            learning.make_video_shadows(snap, suite, context, contexts[rows[0]['race_id']], receipt_verifier=verifier)


if __name__ == '__main__':
    unittest.main()
