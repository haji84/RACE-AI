"""Independent synthetic cloud durability and size-boundary regressions."""
import copy
from datetime import datetime, timedelta
import itertools
import unittest

from tests import test_race_cloud_store as fixtures
from tests import test_race_update_merge as merge_fixtures


class RaceCloudReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RaceCloudTests()
        self.fixture.setUp()
        self.store = self.fixture.store
        self.race = self.fixture.program
        self.client = self.fixture.client
        self.helper = merge_fixtures.RaceUpdateMergeTests()

    def request(self, record):
        record['rights_review'] = self.fixture.record['rights_review']
        self.helper.rehash(record)
        return {'publication_review': record['rights_review'], 'bundle': {
            'schema_version': 1, 'race_id': self.race['race_id'], 'records': [record],
            'latest': {record['kind']: record['snapshot_id']}}}

    def test_receipt_clock_is_measured_after_immutable_observation_readback(self):
        raw_key, _ = self.store.paths(self.race['race_id'], self.fixture.record['snapshot_id'])
        events = []
        original_get, original_put = self.client.get, self.client.put

        def get(key, **kwargs):
            result = original_get(key, **kwargs)
            if key == raw_key and result is not None:
                events.append('durable-readback')
            return result

        def put(key, raw, **kwargs):
            result = original_put(key, raw, **kwargs)
            if key == raw_key:
                events.append('immutable-put')
            return result

        def clock():
            events.append('clock')
            self.assertEqual(events[:2], ['immutable-put', 'durable-readback'])
            return fixtures.NOW

        self.client.get, self.client.put = get, put
        self.fixture.publish(clock=clock)
        self.assertEqual(events[:3], ['immutable-put', 'durable-readback', 'clock'])

    def test_raw_orphan_retry_after_close_cannot_gain_pre_race_cloud_eligibility(self):
        record = self.fixture.record
        raw_key, _ = self.store.paths(self.race['race_id'], record['snapshot_id'])
        self.client.data[raw_key] = self.store.canonical(record)
        late = datetime.fromisoformat(self.race['closed_at']) + timedelta(seconds=1)
        self.fixture.publish(now=late)
        receipt = self.fixture.read(late)['records'][0]
        self.assertTrue(record['storage_eligible_pre_race'])
        self.assertFalse(receipt['cloud_eligible_pre_race'])
        self.assertEqual(datetime.fromisoformat(receipt['cloud_saved_at']), late)

    def test_midnight_after_immutable_write_preserves_previous_current_manifest(self):
        report = self.fixture.publish()
        previous = self.client.data[report['pathname']]
        record = copy.deepcopy(self.fixture.record)
        record.update(captured_at='2026-10-15T23:58:00+09:00',
            available_at='2026-10-15T23:58:00+09:00', saved_at='2026-10-15T23:58:01+09:00',
            eligible_pre_race=False, storage_eligible_pre_race=False)
        request = self.request(record)
        before = datetime.fromisoformat('2026-10-15T23:59:59+09:00')
        after = datetime.fromisoformat('2026-10-16T00:00:00+09:00')
        with self.assertRaises(ValueError):
            self.fixture.publish(request, now=before, clock=lambda: after)
        self.assertEqual(self.client.data[report['pathname']], previous)
        self.assertEqual(self.fixture.read(before)['latest']['beforeinfo'], self.fixture.record['snapshot_id'])

    def test_aggregate_response_cap_preserves_current_when_individual_records_fit(self):
        self.fixture.publish()
        odds = self.helper.observation('odds3t')
        # Leading zeroes are valid decimal odds. Each immutable version and its
        # request fit, but multiple individually valid kinds can exceed the API cap.
        odds['data']['odds'][0]['odds'] = '0' * 235000 + '1.00'
        odds_request = self.request(odds)
        self.assertLess(len(self.store.canonical(odds_request)), self.store.MAX_BYTES)
        self.fixture.publish(odds_request)
        key = self.store.paths(self.race['race_id'])
        previous = self.client.data[key]

        result = self.helper.observation('raceresult', capture='2026-10-15T09:00:00+09:00',
            saved='2026-10-15T09:01:00+09:00')
        markets = {'trifecta': (3, False), 'trio': (3, True), 'exacta': (2, False),
            'quinella': (2, True), 'quinella_place': (2, True), 'win': (1, False), 'place': (1, False)}
        payouts = []
        for kind, (size, unordered) in markets.items():
            combinations = itertools.combinations(range(1, 7), size) if unordered else itertools.permutations(range(1, 7), size)
            for combination in combinations:
                payouts.append({'bet_type': kind, 'combination': list(combination), 'payout_per_100_yen': 100})
        result['data'].update(payouts=payouts[:200], available_market_types=list(markets),
            verified_market_types=[], winning_coverage_status={kind: 'INCOMPLETE' for kind in markets},
            confirmed=False, settlement_ready=False)
        result_request = self.request(result)
        late = datetime.fromisoformat('2026-10-15T09:02:00+09:00')
        self.store.validate_current_record(result, self.race, late)
        self.assertLess(len(self.store.canonical(result_request)), self.store.MAX_BYTES)
        with self.assertRaisesRegex(ValueError, 'RACE_API_RESPONSE_TOO_LARGE'):
            self.fixture.publish(result_request, now=late)
        self.assertEqual(self.client.data[key], previous)
        self.assertLessEqual(len(self.store.canonical(self.fixture.read(late))), self.store.MAX_BYTES)


if __name__ == '__main__':
    unittest.main()
