"""Real fitting equations on fictional, distinct race outcomes and active rosters."""
from copy import deepcopy
from datetime import timedelta
import itertools
import math
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_observed_pairwise_models import predict_pair, MODEL_IDS
from race_ai import observed_weight_learning as learning
from race_ai.observed_p1_connection import build_bundle
from race_ai.frozen_day_cycle import read_p1
from tests.test_boat_observed_pairwise_models import fixture
from tests import test_observed_weight_learning as legacy_fixtures
from tests.test_observed_p1_connection import inputs, archive

NOW = legacy_fixtures.NOW


def active_dataset():
    rows, results = legacy_fixtures.dataset(12)
    lane_options = ((1, 3, 6), (1, 2, 4, 6), (1, 3, 4, 5, 6), (1, 2, 3, 4, 5, 6))
    for index, observation in enumerate(results):
        lanes = lane_options[index % len(lane_options)]
        snap = deepcopy(rows[index*2]['learning_snapshot'])
        snap['participants'] = [r for r in snap['participants'] if r['lane'] in lanes]
        suite = predict_pair(snap, allow_source=lambda *_: True)
        for row in rows[index*2:index*2+2]:
            model = suite['models'][row['model_id']]
            row.update(learning_snapshot=snap, learning_snapshot_sha256=digest(snap),
                original_json_sha256=digest(suite), model_sha256=model['prediction_sha256'],
                roster={str(r['lane']): r['registration_no'] for r in snap['participants']},
                top8=model['ordered_top8'], ranked=[r['combination'] for r in model['candidates']])
        winner = rows[index*2]['top8'][0]
        observation['data']['top3'] = winner
        observation['data']['payouts'][0]['combination'] = winner
        observation['data']['results'] = [r for r in observation['data']['results'] if r['lane'] in lanes]
    return rows, results


class ActiveObservedLearningTests(unittest.TestCase):
    def test_vectors_use_active_entrant_contrasts_and_divisor(self):
        snap = fixture(all_missing=True)
        snap['participants'] = [r for r in snap['participants'] if r['lane'] in (1, 3, 6)]
        for row in snap['participants']:
            row['features']['national_win_rate'] = dict(value=row['lane'], sample_n=None,
                source_id='fixture-program', transform_id='official_B_national_win_rate_points_v1')
            row['missing'].pop('national_win_rate')
        values = learning.vectors(snap)
        self.assertEqual(set(values), {1, 3, 6})
        for lane, expected in ((1, -7/30), (3, -1/30), (6, 4/15)):
            self.assertAlmostEqual(values[lane][0], expected)
            self.assertEqual(values[lane][1:], [0.]*7)

    def test_mixed_active_rosters_fit_without_repeating_or_padding_outcomes(self):
        rows, observations = active_dataset()
        before = deepcopy((rows, observations))
        trained = learning.fit_from_verified(rows, observations, now=NOW)
        self.assertEqual(trained['state'], 'FITTED_SHADOW_ONLY')
        self.assertEqual(trained['unique_races'], 12)
        self.assertEqual(trained['train_races'], 9)
        self.assertEqual(trained['validation_races'], 3)
        for model in trained['models'].values():
            self.assertEqual(model['training']['stake_yen'], 6600)
            self.assertEqual(model['holdout']['stake_yen'], 2400)
        self.assertEqual((rows, observations), before)
        changed = deepcopy(observations)
        for result in changed[-3:]:
            result['data']['top3'] = result['data']['top3'][::-1]
            result['data']['payouts'][0]['combination'] = result['data']['top3']
        alternative = learning.fit_from_verified(rows, changed, now=NOW)
        for mid in MODEL_IDS:
            self.assertEqual(trained['models'][mid]['weights'], alternative['models'][mid]['weights'])

    def test_fitted_six_entrant_artifact_scores_small_physical_roster(self):
        helper = legacy_fixtures.LearningTests()
        context = helper.context()
        snapshot, _ = helper.future()
        snapshot['participants'] = [r for r in snapshot['participants'] if r['lane'] in (1, 3, 6)]
        baseline = predict_pair(snapshot, allow_source=lambda *_: True)
        output = learning.make_shadows(snapshot, baseline, context)
        self.assertEqual(len(output), 2)
        for row in output:
            self.assertEqual(row['candidate_count'], 6)
            self.assertEqual(len(row['ordered_top8']), 6)
            self.assertEqual({tuple(r['combination']) for r in row['candidates']},
                             set(itertools.permutations((1, 3, 6), 3)))
            self.assertAlmostEqual(math.fsum(r['score'] for r in row['candidates']), 1.)
            self.assertEqual(row['model_version'], '0.2.0-FITTED-SHADOW-ACTIVE-ROSTER')
        context['receipt']['created_at'] = snapshot['as_of']
        with self.assertRaises(ValueError):
            learning.make_shadows(snapshot, baseline, context)

    def test_complete_six_generated_training_and_shadow_bytes_are_unchanged(self):
        rows, observations = legacy_fixtures.dataset()
        trained = learning.fit_from_verified(rows, observations, now=NOW)
        self.assertEqual(digest(trained), '9c6a75a5394cbf14c22ea2889c2555b07c006b7042229e00fa60a4a3300edf9d')
        helper = legacy_fixtures.LearningTests()
        snap, suite = helper.future()
        self.assertEqual(digest(learning.vectors(snap)),
                         '55777409fa2d154b8bc77e174dc6e64cf74be43de3c007f1fcf6645b5afa3610')
        self.assertEqual(digest(learning.make_shadows(snap, suite, helper.context())),
                         '71a7754ffd6d559dea5163e6442eb66af192683b5204e5e9767a6d0a8828736b')

    def test_saved_active_learned_rows_roundtrip_and_use_actual_pair_stake(self):
        base, extra, proof = inputs()
        base['race_id'] = extra['race_id'] = '20300401-24-12'
        at = (NOW+timedelta(minutes=10)).isoformat()
        before = (NOW+timedelta(minutes=9)).isoformat()
        base['cutoff_at'] = '2030-04-01T17:30:00+09:00'
        base['captured_at'] = extra['observed_at'] = before
        proof.update(program_captured_at=(NOW+timedelta(minutes=8)).isoformat(), preview_captured_at=before)
        for key in ('program_url', 'preview_url'):
            proof[key] = proof[key].replace('jcd=01', 'jcd=24').replace('rno=1', 'rno=12')
        base['boats'] = [r for r in base['boats'] if r['lane'] in (1, 3, 6)]
        extra['participants'] = [r for r in extra['participants'] if r['lane'] in (1, 3, 6)]
        bundle = build_bundle(base, extra, at, **proof, owner_reviewed=True)
        context = legacy_fixtures.LearningTests().context()
        shadows = learning.make_shadows(bundle['snapshot'], bundle['suite'], context)
        doc = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1', paired_forecasts=[],
            observed_pairwise_p1_bundles=[bundle], learned_pairwise_shadows=shadows)
        raw, receipt = archive(doc, saved=(NOW+timedelta(minutes=11)).isoformat())
        parsed, baselines = read_p1(raw, receipt)
        rows = learning.read_shadow_rows(parsed, receipt, baselines)
        self.assertEqual(len(rows), 2)
        winner = rows[0]['top8'][0]
        result = dict(race_id=base['race_id'], status='AVAILABLE', body_identity_verified=True,
            closed_at=base['cutoff_at'], captured_at=(NOW+timedelta(minutes=40)).isoformat(),
            source_sha256='c'*64, data=dict(status='settled', confirmed=True, finish_confirmed=True,
                refund_boats=[], top3=winner, results=[dict(lane=n, racer_registration_id=str(4000+n),
                finish_status='FINISHED') for n in (1, 3, 6)], payouts=[dict(bet_type='trifecta',
                combination=winner, payout_per_100_yen=1230)]))
        scored = learning.score_shadows(rows, baselines, [result])
        self.assertEqual(scored['paired_forecasts'], 2)
        for model in scored['scoreboard']:
            self.assertEqual(model['candidate_roi'], 1230/600)
            self.assertEqual(model['baseline_roi'], 1230/600)


if __name__ == '__main__':
    unittest.main()
