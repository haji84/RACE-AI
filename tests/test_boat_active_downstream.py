"""Active saved outputs and explicit absent-result identities remain immutable."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import itertools
import json
import math
import unittest
import zipfile

from race_ai.actions_contract import digest
from race_ai.boat_ab_shadow import build_pair, _digest
from race_ai.boat_ab_result_audit import score_pair
from race_ai.boat_observed_pairwise_models import predict_pair
from race_ai.frozen_day_cycle import read_p0, settle
from race_ai.private_cycle_projection import project_state
from race_ai.all_race_top8_target import all_race_top8_target
from tests.test_boat_observed_pairwise_models import fixture
from tests.test_boat_ab_shadow import fixture as ab_source
from tests.test_boat_ab_result_audit import fixture as ab_original
from tests.test_private_cycle_projection import saved_state, seal
from tests.test_frozen_day_cycle import sample, observation
from tests.test_all_race_top8_target import evidence, audit

ROSTERS = ((1, 3, 6), (1, 2, 4, 6), (1, 3, 4, 5, 6), (1, 2, 3, 4, 5, 6))


def saved(lanes):
    state, document = saved_state()
    snap = fixture(research=True)
    snap['participants'] = [r for r in snap['participants'] if r['lane'] in lanes]
    document['predictions'] = [predict_pair(snap, allow_source=lambda *_: True)]
    body = json.dumps(document, sort_keys=True, separators=(',', ':')).encode()
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as archive:
        archive.writestr('forecasts.json', body)
    _, _, receipt = sample()
    raw = raw.getvalue()
    receipt['digest'] = 'sha256:'+hashlib.sha256(raw).hexdigest()
    document, rows = read_p0(raw, receipt, expected_day='2030-04-01')
    state.update(rows=rows, receipts=[])
    return seal(state), document


def outcome(row, *, extra=()):
    winner = deepcopy(row['top8'][0])
    order = winner+[int(n) for n in row['roster'] if int(n) not in winner]
    results = [dict(lane=n, racer_registration_id=row['roster'][str(n)],
                    race_id=row['race_id'], finish_status='FINISHED', finish=order.index(n)+1)
               for n in sorted(map(int, row['roster']))]
    results += [dict(lane=n, racer_registration_id=str(4000+n), race_id=row['race_id'],
                     finish_status='ABSENT', finish=None) for n in extra]
    return dict(race_id=row['race_id'], status='AVAILABLE', body_identity_verified=True,
        closed_at=row['cutoff_at'], captured_at='2030-04-01T02:10:00Z', source_sha256='b'*64,
        data=dict(status='settled', confirmed=True, finish_confirmed=True, refund_boats=[],
            top3=winner, results=results, payouts=[dict(bet_type='trifecta', combination=winner,
                payout_per_100_yen=1230)]))


def with_proof(row, lanes, *, kind='withdrawn_participants'):
    row['withdrawn_lanes'] = list(lanes)
    people = [dict(number=n, registration_no=str(4000+n), race_id=row['race_id']) for n in lanes]
    if kind == 'withdrawn_participants':
        row['withdrawn_participants'] = people
    else:
        people = [dict(number=int(n), registration_no=pid, race_id=row['race_id'])
                  for n,pid in row['roster'].items()]+people
        row['saved_participant_rosters'] = [dict(race_id=row['race_id'], participants=people)]


class ActiveDownstreamTests(unittest.TestCase):
    def test_projected_saved_native_active_rankings_and_results_preserve_originals(self):
        for lanes in ROSTERS:
            with self.subTest(lanes=lanes):
                state, document = saved(lanes)
                state['observations'] = [outcome(state['rows'][0])]
                seal(state)
                before = deepcopy((state, document))
                view = project_state(state, dataset_status='SYNTHETIC_ONLY', original_documents=[document])
                row = view['records'][0]
                self.assertEqual([p['number'] for p in row['participants']], list(lanes))
                self.assertEqual(row['result']['status'], 'final')
                self.assertEqual(row['result_observation_rejections'], [])
                for projected, original in zip([row['prediction']]+row['comparison_predictions'], state['rows']):
                    self.assertEqual(projected['prediction_sha256'], original['model_sha256'])
                    self.assertEqual(projected['ordered_candidates'], original['ranked'])
                    self.assertEqual(len(projected['ordered_top8']), min(8, math.perm(len(lanes), 3)))
                self.assertEqual((state, document), before)

    def test_active_forecasts_accept_proven_absent_extras_and_keep_raw_result(self):
        for kind in ('withdrawn_participants', 'saved_participant_rosters'):
            with self.subTest(kind=kind):
                state, _ = saved((1, 2, 3, 4, 5))
                for row in state['rows']:
                    with_proof(row, (6,), kind=kind)
                result = outcome(state['rows'][0], extra=(6,))
                state['observations'] = [result]
                seal(state)
                projected = project_state(state, dataset_status='SYNTHETIC_ONLY')['records'][0]
                self.assertEqual(projected['result']['status'], 'final')
                self.assertEqual(projected['result_observation_rejections'], [])
                self.assertEqual(projected['result_observations'], [result])
                self.assertEqual(projected['withdrawn_lanes'], [6])
                self.assertEqual([p['number'] for p in projected['participants']], [1, 2, 3, 4, 5])

    def test_native_proof_identity_fields_are_normalized_only_in_display_metadata(self):
        state, _ = saved((1, 2, 3, 4, 5))
        for row in state['rows']:
            with_proof(row, (6,))
            person = row['withdrawn_participants'][0]
            person.update(lane=person.pop('number'), racer_registration_id=person.pop('registration_no'))
            row['saved_participant_rosters'] = [dict(race_id=row['race_id'], participants=[
                dict(lane=n, racer_registration_id=str(4000+n)) for n in range(1, 7)])]
        seal(state)
        original = deepcopy(state)
        row = project_state(state, dataset_status='SYNTHETIC_ONLY')['records'][0]
        self.assertEqual(row['withdrawn_participants'][0]['number'], 6)
        self.assertEqual(row['withdrawn_participants'][0]['registration_no'], '4006')
        self.assertTrue(all('number' in p and 'registration_no' in p
                            for snapshot in row['saved_participant_rosters'] for p in snapshot['participants']))
        self.assertEqual(state, original)

    def test_unknown_or_conflicting_extra_result_identities_never_become_winners(self):
        for mutation in ('no_proof', 'bare_lane', 'wrong_registration', 'wrong_race', 'not_absent', 'missing_active', 'withdrawn_winner'):
            state, _ = saved((1, 2, 3, 4, 5))
            for row in state['rows']:
                with_proof(row, (6,))
                if mutation == 'no_proof':
                    row.pop('withdrawn_lanes'); row.pop('withdrawn_participants')
                elif mutation == 'bare_lane':
                    row.pop('withdrawn_participants')
            result = outcome(state['rows'][0], extra=(6,))
            extra = result['data']['results'][-1]
            if mutation == 'wrong_registration': extra['racer_registration_id'] = '4999'
            if mutation == 'wrong_race': extra['race_id'] = '20300401-01-02'
            if mutation == 'not_absent': extra.update(finish=6, finish_status='FINISHED')
            if mutation == 'missing_active': result['data']['results'].pop(0)
            if mutation == 'withdrawn_winner':
                result['data']['top3'] = [6, 1, 2]
                result['data']['payouts'][0]['combination'] = [6, 1, 2]
            state['observations'] = [result]
            seal(state)
            with self.subTest(mutation=mutation):
                row = project_state(state, dataset_status='SYNTHETIC_ONLY')['records'][0]
                self.assertEqual(row['result']['status'], 'unsupported')
                self.assertEqual(row['result']['winning_combinations'], [])
                with self.assertRaises(ValueError):
                    settle(state['rows'][0], result)

    def test_boolean_result_lane_cannot_equal_a_real_physical_lane(self):
        state, _ = saved((1, 3, 6))
        for row in state['rows']:
            with_proof(row, (2, 4, 5))
        result = outcome(state['rows'][0], extra=(2, 4, 5))
        result['data']['top3'] = deepcopy(result['data']['top3'])
        result['data']['top3'][result['data']['top3'].index(1)] = True
        state['observations'] = [result]
        seal(state)
        projected = project_state(state, dataset_status='SYNTHETIC_ONLY')['records'][0]
        self.assertEqual(projected['result']['status'], 'unsupported')
        with self.assertRaises(ValueError):
            settle(state['rows'][0], result)

    def test_settlement_ignores_only_proven_withdrawn_refunds_outside_saved_tickets(self):
        state, _ = saved((1, 3, 6))
        row = state['rows'][0]
        with_proof(row, (2, 4, 5))
        result = outcome(row, extra=(2, 4, 5))
        result['data']['refund_boats'] = [2, 4, 5]
        original = deepcopy((row, result))
        verdict = settle(row, result)
        self.assertEqual((verdict['state'], verdict['stake_yen'], verdict['net_yen']), ('HIT', 600, 630))
        self.assertEqual((row, result), original)
        result['data']['refund_boats'].append(1)
        self.assertEqual(settle(row, result)['state'], 'REFUND_REVIEW_REQUIRED')

    def test_active_learning_snapshot_roster_and_tickets_remain_bound(self):
        state, _ = saved((1, 3, 6))
        row = state['rows'][0]
        snap = fixture(research=True)
        snap['participants'] = [r for r in snap['participants'] if r['lane'] in (1, 3, 6)]
        row.update(learning_snapshot=snap, learning_snapshot_sha256=digest(snap))
        seal(state)
        projected = project_state(state, dataset_status='SYNTHETIC_ONLY')['records'][0]['prediction']
        self.assertEqual(projected['input_sha256'], digest(snap))
        for mutation in ('ranking', 'registration'):
            broken = deepcopy(state)
            if mutation == 'ranking': broken['rows'][0]['ranked'][0] = [1, 2, 3]
            else: broken['rows'][0]['roster']['3'] = '4001'
            seal(broken)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                project_state(broken, dataset_status='SYNTHETIC_ONLY')

    def test_later_explicit_withdrawal_retains_both_prior_rosters_and_predictions(self):
        full, _ = saved((1, 2, 3, 4, 5, 6))
        smaller, _ = saved((1, 2, 3, 4, 5))
        first, second = full['rows'][0], smaller['rows'][1]
        with_proof(second, (6,))
        full['rows'] = [first, second]
        full['observations'] = [outcome(second, extra=(6,))]
        seal(full)
        originals = deepcopy(full['rows'])
        row = project_state(full, dataset_status='SYNTHETIC_ONLY')['records'][0]
        self.assertEqual([p['number'] for p in row['participants']], [1, 2, 3, 4, 5])
        self.assertEqual(row['withdrawn_lanes'], [6])
        self.assertEqual(row['result']['status'], 'final')
        self.assertEqual([len(p['ordered_candidates']) for p in [row['prediction']]+row['comparison_predictions']], [120, 60])
        self.assertEqual(full['rows'], originals)
        for source in full['rows']:
            source.pop('withdrawn_lanes', None); source.pop('withdrawn_participants', None)
        seal(full)
        with self.assertRaises(ValueError):
            project_state(full, dataset_status='SYNTHETIC_ONLY')

    def test_six_projection_audit_and_target_outputs_remain_byte_identical(self):
        state, document = saved_state()
        state['receipts'] = []
        state['observations'] = [observation(state['rows'][0])]
        seal(state)
        self.assertEqual(digest(project_state(state, dataset_status='SYNTHETIC_ONLY', original_documents=[document])),
                         'f87f5430a07179727f8975d70157af6035cdd7a96e71d88a83b6d7f4f16dfe44')
        self.assertEqual(digest(score_pair(ab_original(), '1-2-3', '2030-11-03T13:34:00+09:00',
                                          '2030-11-03T13:16:00+09:00')),
                         'c3f2fe5aabaabffd5dcbff392f717d3cab63bd187a234c99c10c402ec98ad6ed')
        self.assertEqual(digest(audit(*evidence())),
                         'f5bf93bd47664b064afcc93b0cd7d6e165e476b6323e7085fe26be01547bae55')


class ActiveAuditsTests(unittest.TestCase):
    def test_ab_result_audit_checks_each_active_universe(self):
        for lanes in ROSTERS:
            source = ab_source()
            source['boats'] = [r for r in source['boats'] if r['lane'] in lanes]
            pair = build_pair(source, '2030-11-03T13:18:00+09:00')
            original = ab_original()
            original.update(race_id=pair['race_id'], cutoff_at=pair['cutoff_at'], paired_forecast=pair)
            winner = '-'.join(map(str, lanes[:3]))
            with self.subTest(lanes=lanes):
                report = score_pair(original, winner, '2030-11-03T13:34:00+09:00', '2030-11-03T13:19:00+09:00')
                self.assertEqual(len(report['models']), 2)
                self.assertTrue(all(len(r['top8']) == min(8, math.perm(len(lanes), 3)) for r in report['models']))
                if len(lanes) < 6:
                    with self.assertRaises(ValueError):
                        score_pair(original, '1-2-3', '2030-11-03T13:34:00+09:00', '2030-11-03T13:19:00+09:00')

    def test_all_race_target_accepts_actual_active_forecast_and_stake(self):
        for lanes in ROSTERS:
            state, _ = saved(lanes)
            original = state['rows'][0]
            result = outcome(original)
            schedule = [dict(race_id=original['race_id'], cutoff_at=original['cutoff_at'])]
            with self.subTest(lanes=lanes):
                report = all_race_top8_target([original], schedule, [result], now=datetime(2030, 4, 1, 8, tzinfo=timezone.utc),
                                              expected_models={original['model_id']})
                self.assertEqual(report['eligible_normal_final_races'], 1)
                projected = next(r for r in report['per_forecast'] if r['stage'] == original['stage'])
                self.assertEqual(projected['state'], 'HIT')
                self.assertEqual(projected['top8'], original['top8'])
                if len(lanes) == 3:
                    self.assertEqual(projected['stake_yen'], 600)
                    self.assertIsNone(report['exact_ticket_count'])

    def test_ready_roster_proof_is_not_suppressed_by_another_models_missing_proof(self):
        state, _ = saved((1, 3, 6))
        unproven, proven = state['rows']
        with_proof(proven, (2, 4, 5))
        result = outcome(proven, extra=(2, 4, 5))
        report = all_race_top8_target(state['rows'], [dict(race_id=proven['race_id'], cutoff_at=proven['cutoff_at'])],
            [result], now=datetime(2030, 4, 1, 8, tzinfo=timezone.utc),
            expected_models={r['model_id'] for r in state['rows']})
        self.assertEqual(report['eligible_normal_final_races'], 1)
        forecasts = {r['model_id']:r for r in report['per_forecast'] if r['stage'] == 'P0'}
        self.assertEqual(forecasts[proven['model_id']]['state'], 'HIT')
        self.assertEqual(forecasts[unproven['model_id']]['state'], 'NO_PRE_CUTOFF_FORECAST')


if __name__ == '__main__':
    unittest.main()
