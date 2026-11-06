"""Synthetic active rosters retain physical lanes and saved-original identities."""
from copy import deepcopy
import itertools
import math
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_live_feature_shadow import build_live_feature_shadow
from race_ai.boat_multi_feature_models import run_models
from race_ai.boat_observed_pairwise_models import predict_pair
from race_ai.boat_tactical_scenarios import predict_tactical_shadow
from race_ai.observed_p1_connection import build_bundle
from race_ai import frozen_day_cycle as frozen
from tests.test_boat_ab_shadow import fixture as ab_fixture
from tests.test_boat_live_feature_shadow import fixture as live_fixture
from tests.test_boat_multi_feature_models import fixture as multi_fixture
from tests.test_boat_observed_pairwise_models import fixture as observed_fixture
from tests.test_boat_tactical_scenarios import inputs as tactical_inputs, FORECAST_AT
from tests.test_observed_p1_connection import inputs as p1_inputs, AT, archive


ROSTERS = ((1, 3, 6), (1, 2, 4, 6), (1, 3, 4, 5, 6), (1, 2, 3, 4, 5, 6))


def retain(rows, lanes):
    return [r for r in rows if r['lane'] in lanes]


class ActiveEntrantModelsTests(unittest.TestCase):
    def assert_distribution(self, rows, lanes, *, ticket='ticket'):
        combinations = [tuple(map(int, r[ticket].split('-'))) if ticket == 'ticket'
                        else tuple(r[ticket]) for r in rows]
        self.assertEqual(set(combinations), set(itertools.permutations(lanes, 3)))
        self.assertEqual(len(combinations), math.perm(len(lanes), 3))
        self.assertAlmostEqual(math.fsum(r['score'] for r in rows), 1.0, places=10)

    def test_ab_and_live_rank_only_confirmed_physical_lanes(self):
        for lanes in ROSTERS:
            with self.subTest(lanes=lanes):
                base, extra, at = live_fixture()
                base['boats'] = retain(base['boats'], lanes)
                extra['participants'] = retain(extra['participants'], lanes)
                pair = build_pair(base, at)
                live = build_live_feature_shadow(base, extra, at)
                for model in [*pair['models'], live]:
                    self.assert_distribution(model['full_120'], lanes)
                    self.assertEqual(model['top8'], model['full_120'][:8])
                    self.assertEqual(len(model['top8']), min(8, math.perm(len(lanes), 3)))
                self.assertEqual([r['lane'] for r in live['features']], list(lanes))

    def test_observed_coverage_and_utilities_follow_actual_roster(self):
        for lanes in ROSTERS:
            with self.subTest(lanes=lanes):
                snapshot = observed_fixture('P1')
                snapshot['participants'] = retain(snapshot['participants'], lanes)
                out = predict_pair(snapshot)
                self.assertEqual(out['coverage']['possible_feature_value_count'], len(lanes) * 8)
                self.assertEqual(out['coverage']['possible_pair_count'], math.comb(len(lanes), 2) * 8)
                for model in out['models'].values():
                    self.assert_distribution(model['candidates'], lanes, ticket='combination')
                    self.assertEqual([r['lane'] for r in model['utilities']], list(lanes))
                    self.assertTrue(all(r['observed_comparisons'] == (len(lanes)-1)*8
                                        for r in model['utilities']))
                    self.assertTrue(all(r['completion_lower'] == r['utility'] == r['completion_upper']
                                        for r in model['utilities']))

    def test_multi_feature_models_accept_active_roster_without_renumbering(self):
        for lanes in ROSTERS:
            with self.subTest(lanes=lanes):
                snapshot = multi_fixture()
                snapshot['entrants'] = retain(snapshot['entrants'], lanes)
                for model in run_models(snapshot).values():
                    self.assert_distribution(model['candidates'], lanes, ticket='combination')
                    self.assertEqual(len(model['ordered_top8']), min(8, math.perm(len(lanes), 3)))

    def test_tactical_assigns_courses_to_active_entrants_and_retains_frames(self):
        for lanes in ROSTERS[:-1]:
            with self.subTest(lanes=lanes):
                source, histories, venue = tactical_inputs()
                source['boats'] = retain(source['boats'], lanes)
                identities = {row['racer_id'] for row in source['boats']}
                histories = [r for r in histories if r['racer_id'] in identities]
                out = predict_tactical_shadow(source, histories, venue, FORECAST_AT)
                self.assert_distribution(out['full_120'], lanes)
                self.assertEqual(out['main_top8'], out['full_120'][:8])
                self.assertEqual(out['entry_scenario_count'], math.factorial(len(lanes)))
                self.assertTrue(all(set(r['courses']) == set(range(1, len(lanes)+1))
                                    for r in out['top_entry_scenarios']))
                self.assertEqual([r['lane'] for r in out['racer_history_sample_sizes']], list(lanes))

    def test_short_roster_still_requires_every_active_exhibition(self):
        for missing in (None, 0, float('nan')):
            source = ab_fixture()
            source['boats'] = retain(source['boats'], (1, 3, 6))
            source['boats'][1]['exhibition_time_seconds'] = missing
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                build_pair(source, '2030-11-03T13:18:00+09:00')

    def test_three_entrants_with_extreme_valid_strengths_still_normalize(self):
        source = ab_fixture()
        source['boats'] = retain(source['boats'], (1, 3, 6))
        for row in source['boats']:
            row.update(national_win_rate=10. if row['lane'] == 1 else 0.,
                       exhibition_time_seconds=4. if row['lane'] == 1 else 12.)
        for model in build_pair(source, '2030-11-03T13:18:00+09:00')['models']:
            self.assert_distribution(model['full_120'], (1, 3, 6))

    def test_invalid_rosters_and_provenance_still_fail_closed(self):
        mutations = (
            lambda s: s.update(boats=s['boats'][:2]),
            lambda s: s['boats'][1].update(lane=s['boats'][0]['lane']),
            lambda s: s['boats'][1].update(lane=True),
            lambda s: s['boats'][1].update(lane=7),
            lambda s: s['boats'][1].update(racer_id=s['boats'][0]['racer_id']),
            lambda s: s['boats'][1].update(racer_id='４００３'),
            lambda s: s.update(program_source_sha256='invalid'),
            lambda s: s.update(captured_at=s['cutoff_at']),
        )
        for mutate in mutations:
            source = ab_fixture()
            source['boats'] = retain(source['boats'], (1, 3, 6))
            mutate(source)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                build_pair(source, '2030-11-03T13:18:00+09:00')
        for field, value in (('participant_id', '4001'), ('lane', True), ('lane', 7)):
            snapshot = multi_fixture()
            snapshot['entrants'][1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                run_models(snapshot)

    def test_complete_six_entrant_originals_remain_byte_identical(self):
        base, extra, at = live_fixture()
        source, histories, venue = tactical_inputs()
        pbase, pextra, proof = p1_inputs()
        cases = (
            (build_pair(ab_fixture(), '2030-11-03T13:18:00+09:00'),
             '1a93d946299615f30b009a8b66cb6da07448ed8fec2867d5b4c3f57811b8bad1'),
            (build_live_feature_shadow(base, extra, at),
             'e13106f426fb16aed7abb772f82456e9a7d5e9d76704f7c76ba6ec29e5fb4f45'),
            (run_models(multi_fixture()),
             '19a91bfdb8f6656dd5ba6bf38053cd1056135ba5cf4dbd608a67c888a68af25e'),
            (predict_pair(observed_fixture('P1')),
             '25684fdb24e5505c199e2c02fa3ffba896a6626ede2638c67d5144034249f081'),
            (predict_tactical_shadow(source, histories, venue, FORECAST_AT),
             'd5c44d339175e637a96f2a2ac90cf17ecbc9c328cb48c136f80a6b70b4f65c4f'),
            (build_bundle(pbase, pextra, AT, **proof, owner_reviewed=True),
             '41e6e8c73bd93bb77c5abe8db7f5e053703a70de4bf46a0866833eedd55f80d9'),
        )
        for value, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(digest(value), expected)


class ActiveFrozenOriginalTests(unittest.TestCase):
    def saved_rows(self, lanes):
        base, extra, proof = p1_inputs()
        base['boats'] = retain(base['boats'], lanes)
        extra['participants'] = retain(extra['participants'], lanes)
        pair = build_pair(base, AT)
        live = build_live_feature_shadow(base, extra, AT)
        bundle = build_bundle(base, extra, AT, **proof, owner_reviewed=True)
        doc = dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1', paired_forecasts=[pair],
                   additional_official_feature_shadows=[live], observed_pairwise_p1_bundles=[bundle])
        raw, receipt = archive(doc)
        return frozen.read_p1(raw, receipt)[1]

    def test_saved_five_models_bind_active_roster_and_score_actual_ticket_stake(self):
        for lanes in ROSTERS:
            with self.subTest(lanes=lanes):
                rows = self.saved_rows(lanes)
                self.assertEqual(len(rows), 5)
                for row in rows:
                    self.assertEqual(set(row['roster']), set(map(str, lanes)))
                    self.assertEqual(len(row['top8']), min(8, math.perm(len(lanes), 3)))
                row = rows[0]
                winner = row['top8'][0]
                observation = dict(race_id=row['race_id'], status='AVAILABLE', body_identity_verified=True,
                    closed_at=row['cutoff_at'], captured_at='2030-04-01T02:10:00Z', source_sha256='c'*64,
                    data=dict(status='settled', confirmed=True, finish_confirmed=True, refund_boats=[],
                        top3=winner, results=[dict(lane=n, racer_registration_id=row['roster'][str(n)],
                            finish_status='FINISHED') for n in lanes], payouts=[dict(bet_type='trifecta',
                            combination=winner, payout_per_100_yen=1230)]))
                original = deepcopy(row)
                verdict = frozen.settle(row, observation)
                self.assertEqual(verdict['state'], 'HIT')
                self.assertEqual(verdict['stake_yen'], min(8, math.perm(len(lanes), 3))*100)
                self.assertEqual(verdict['net_yen'], 1230-verdict['stake_yen'])
                self.assertEqual(row, original)
                observation['data'].update(status='cancelled', confirmed=True)
                refund = frozen.settle(row, observation)
                self.assertEqual(refund['received_yen'], verdict['stake_yen'])

    def test_rank_check_rejects_roster_subset_and_boolean_tickets(self):
        ranked = [list(t) for t in itertools.permutations((1, 3, 6), 3)]
        frozen.rank_check(ranked, ranked, lanes=(1, 3, 6))
        for invalid in (ranked[:-1], [[True, 3, 6]]+ranked[1:]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                frozen.rank_check(invalid, invalid[:8], lanes=(1, 3, 6))
        with self.assertRaises(ValueError):
            frozen.rank_check(ranked, ranked, lanes=(1, 2, 3, 6))
        boolean_top = [[True, 3, 6]]+ranked[1:]
        with self.assertRaises(ValueError):
            frozen.rank_check(ranked, boolean_top, lanes=(1, 3, 6))

    def test_saved_official_identity_rejects_wrong_venue_and_nonexistent_date(self):
        for race_id in ('boat:2030-04-01:boatrace-jcd-25:1',
                        'boat:2030-02-30:boatrace-jcd-01:1'):
            with self.subTest(race_id=race_id), self.assertRaises(ValueError):
                frozen.official_id(race_id)

    def test_p1_extra_source_cannot_add_unsupported_or_missing_racers(self):
        for mutation in ('missing', 'foreign', 'leak'):
            base, extra, proof = p1_inputs()
            base['boats'] = retain(base['boats'], (1, 3, 6))
            extra['participants'] = retain(extra['participants'], (1, 3, 6))
            if mutation == 'missing':
                extra['participants'].pop()
            elif mutation == 'foreign':
                extra['participants'][0]['racer_id'] = '9999'
            else:
                extra['participants'][0]['odds'] = 10
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                build_bundle(base, extra, AT, **proof, owner_reviewed=True)


if __name__ == '__main__':
    unittest.main()
