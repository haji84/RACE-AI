"""Read-only settlement API with real validation and synthetic storage."""
import copy
from datetime import timedelta
from io import BytesIO
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.test_live_evaluation_contract import NOW
from tests.test_race_cloud_store import Blob
from tests.test_settlement_contract import complete_fixture
from web.race_contract import canonical


ROOT = Path(__file__).resolve().parents[1]


class ClosingBlob(Blob):
    def __init__(self):
        super().__init__()
        self.closes = 0
        self.reads = []

    def get(self, key, **kwargs):
        self.reads.append((key, kwargs))
        return super().get(key, **kwargs)

    def close(self):
        self.closes += 1


class SettlementApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            with patch.object(sys, 'path', [str(ROOT / 'web')] + sys.path):
                cls.api = importlib.import_module('api.settlement')
        except ModuleNotFoundError:
            cls.api = None

    def setUp(self):
        self.assertIsNotNone(self.api, 'read-only settlement API must exist')
        self.bundle, self.race = complete_fixture()
        self.feed = dict(venues=[dict(races=[self.race])])
        self.client = ClosingBlob()
        self.seed(self.bundle)
        self.environment = patch.dict('os.environ', {'BLOB_READ_WRITE_TOKEN': 'synthetic-secret'})
        self.environment.start(); self.addCleanup(self.environment.stop)
        for target, value in [('utc_now', NOW), ('load_feed', (200, self.feed)), ('create_blob_client', self.client)]:
            patcher = patch.object(self.api, target, return_value=value)
            patcher.start(); self.addCleanup(patcher.stop)

    def seed(self, bundle):
        manifest = {key: value for key, value in bundle.items() if key != 'records'}
        self.client.data['race-ai/races/' + self.race['race_id'] + '.json'] = canonical(manifest)
        for receipt in bundle['records']:
            record = receipt['record']; snapshot = record['snapshot_id']
            self.client.data[f"race-ai/observations/{self.race['race_id']}/{snapshot}.json"] = canonical(record)
            self.client.data[f"race-ai/receipts/{self.race['race_id']}/{snapshot}.json"] = canonical(receipt)

    def handler(self, path):
        handler = object.__new__(self.api.handler)
        handler.path = path; handler.wfile = BytesIO(); handler.response_headers = {}
        handler.send_response = lambda status: setattr(handler, 'status', status)
        handler.send_header = lambda key, value: handler.response_headers.update({key: value})
        handler.end_headers = lambda: None
        return handler

    def test_real_store_receipt_chain_served_without_writes_or_purchase_fields(self):
        before = copy.deepcopy(self.client.data)
        handler = self.handler('/api/settlement?race_id=' + self.race['race_id'])
        handler.do_GET()
        self.assertEqual(handler.status, 200)
        report = json.loads(handler.wfile.getvalue())
        self.assertEqual(report['status'], 'SETTLEMENT_READY')
        self.assertEqual(report['race_id'], '20261015-18-01')
        self.assertEqual(report['as_of'], '2026-10-15T00:10:00.000000+00:00')
        self.assertEqual(report['result_proof']['snapshot_id'], self.bundle['latest']['raceresult'])
        self.assertEqual(len(report['markets']), 7)
        self.assertFalse({'bets', 'ledger', 'stake_yen', 'purchase_id'} & set(report))
        self.assertEqual(self.client.data, before)
        self.assertEqual(self.client.puts, [])
        self.assertEqual(self.client.closes, 1)
        self.assertEqual(len(self.client.reads), 3)
        self.assertTrue(all(options['use_cache'] is False and options['access'] == 'private' for _, options in self.client.reads))
        self.assertEqual(handler.response_headers['Cache-Control'], 'no-store')
        self.assertEqual(handler.response_headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(handler.response_headers['X-Robots-Tag'], 'noindex')
        self.assertEqual(int(handler.response_headers['Content-Length']), len(handler.wfile.getvalue()))

    def test_query_duplicate_extra_blank_or_client_asof_never_reads_store(self):
        for query in ['', '?race_id', '?race_id=', '?race_id=x&race_id=y', '?race_id=x&as_of=x', '?other=x']:
            with self.subTest(query=query), patch.object(self.api, 'load_settlement') as load:
                handler = self.handler('/api/settlement' + query); handler.do_GET()
                self.assertEqual(handler.status, 400)
                self.assertEqual(json.loads(handler.wfile.getvalue()), {'error': 'SETTLEMENT_QUERY_INVALID'})
                load.assert_not_called()
                self.assertEqual(handler.response_headers['Cache-Control'], 'no-store')

    def test_absent_result_returns_informative_empty_report(self):
        self.client.data.clear()
        status, report = self.api.load_settlement(self.race['race_id'])
        self.assertEqual(status, 200)
        self.assertEqual(report['status'], 'RESULT_NOT_OBTAINED')
        self.assertEqual(report['markets'], [])
        self.assertIsNone(report['result_proof'])
        self.assertEqual(self.client.closes, 1)

    def test_absent_day_program_never_creates_client(self):
        with patch.object(self.api, 'load_feed', return_value=(503, {})), patch.object(self.api, 'create_blob_client') as create:
            self.assertEqual(self.api.load_settlement(self.race['race_id']), (503, {'error': 'DAY_PROGRAM_UNAVAILABLE'}))
            create.assert_not_called()

    def test_current_day_program_membership_required_before_store_access(self):
        for race_id in ['../secrets', '20261014-18-01', '20261015-25-01', '20261015-18-13', '20261015-18-02']:
            with self.subTest(race_id=race_id), patch.object(self.api, 'create_blob_client') as create:
                self.assertEqual(self.api.load_settlement(race_id), (422, {'error': 'SETTLEMENT_DATA_REJECTED'}))
                create.assert_not_called()

    def test_corrupt_raw_receipt_or_missing_immutable_object_rejected_and_closed(self):
        for mode in ['invalid_json', 'duplicate_json', 'conflicting_receipt', 'missing_object', 'oversized_object']:
            self.client.data.clear(); self.seed(self.bundle); self.client.closes = 0
            key = next(key for key in self.client.data if '/observations/' in key)
            if mode == 'invalid_json': self.client.data[key] = b'{private secret'
            elif mode == 'duplicate_json': self.client.data[key] = b'{"schema_version":1,"schema_version":1}'
            elif mode == 'missing_object': del self.client.data[key]
            elif mode == 'oversized_object': self.client.data[key] = b'x' * 256001
            else:
                raw = json.loads(self.client.data[key]); raw['source_sha256'] = 'b' * 64
                self.client.data[key] = canonical(raw)
            with self.subTest(mode=mode):
                self.assertEqual(self.api.load_settlement(self.race['race_id']), (422, {'error': 'SETTLEMENT_DATA_REJECTED'}))
                self.assertEqual(self.client.closes, 1)

    def test_storage_failure_and_client_creation_failure_are_sanitized(self):
        with patch.object(self.client, 'get', side_effect=OSError('synthetic-secret-private-body')):
            self.assertEqual(self.api.load_settlement(self.race['race_id']), (503, {'error': 'SETTLEMENT_STORE_UNAVAILABLE'}))
        self.assertEqual(self.client.closes, 1)
        with patch.object(self.api, 'create_blob_client', side_effect=OSError('synthetic-secret')):
            self.assertEqual(self.api.load_settlement(self.race['race_id']), (503, {'error': 'SETTLEMENT_STORE_UNAVAILABLE'}))

    def test_midnight_during_store_read_rejects_mixed_days_and_closes_client(self):
        midnight = NOW.replace(hour=0, minute=0, second=0) + timedelta(days=1)
        with patch.object(self.api, 'utc_now', side_effect=[NOW, NOW, midnight]), patch.object(self.api, 'build_settlement_report') as build:
            self.assertEqual(self.api.load_settlement(self.race['race_id']), (422, {'error': 'SETTLEMENT_DATA_REJECTED'}))
            build.assert_not_called()
        self.assertEqual(self.client.closes, 1)

    def test_response_is_bounded_and_close_failure_cannot_hide_data_rejection(self):
        with patch.object(self.api, 'build_settlement_report', return_value={'padding': 'x' * 256001}), patch.object(self.client, 'close', side_effect=OSError('close-secret')):
            self.assertEqual(self.api.load_settlement(self.race['race_id']), (422, {'error': 'SETTLEMENT_DATA_REJECTED'}))

    def test_each_storage_read_uses_actual_server_clock(self):
        # Clock progresses during the approved feed and storage reads; a client
        # supplied timestamp is never used to freeze settlement freshness.
        final = NOW + timedelta(seconds=2)
        with patch.object(self.api, 'utc_now', side_effect=[NOW, NOW + timedelta(seconds=1), final]):
            status, report = self.api.load_settlement(self.race['race_id'])
        self.assertEqual(status, 200)
        self.assertEqual(report['as_of'], '2026-10-15T00:10:02.000000+00:00')


if __name__ == '__main__': unittest.main()
