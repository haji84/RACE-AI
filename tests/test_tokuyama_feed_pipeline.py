import tempfile
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from race_ai.tokuyama_feed_pipeline import run_pipeline
from tests.test_tokuyama_day_worker import DAY, NOW, rights


class FeedPipelineTests(unittest.TestCase):
    def test_default_dryrun_does_not_fetch_create_store_or_upload(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('race_ai.tokuyama_feed_pipeline.collect_tokuyama_day') as collector:
            store = Path(directory) / 'must-not-be-created'
            result = run_pipeline(day=DAY, index_rights=rights(), detail_rights=[], approval={}, store=store)
            self.assertEqual(result['status'], 'DRY_RUN')
            self.assertEqual(result['maximum_source_requests'], 13)
            self.assertFalse(store.exists())
            collector.assert_not_called()

    def test_explicit_execute_with_unknown_rights_never_calls_network(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('race_ai.tokuyama_day_worker.fetch_index') as transport:
            store = Path(directory) / 'not-created'
            result = run_pipeline(day=DAY, index_rights=[], detail_rights=[], approval={},
                                  store=store, execute=True, now=NOW)
            self.assertEqual(result['status'], 'SOURCE_RIGHTS_BLOCKED')
            self.assertFalse(store.exists())
            transport.assert_not_called()

    def test_upload_flag_requires_explicit_execution(self):
        with self.assertRaises(ValueError):
            run_pipeline(day=DAY, index_rights=[], detail_rights=[], approval={},
                         store=Path('.'), upload_blob=True)

    def test_missing_publication_approval_does_not_create_store(self):
        from tests.test_day_snapshot_publisher import sample
        candidate = sample(DAY.isoformat())
        with tempfile.TemporaryDirectory() as directory, \
             patch('race_ai.tokuyama_feed_pipeline.collect_tokuyama_day', return_value={'status': 'NORMALIZED_REQUIRES_PUBLICATION_APPROVAL', 'snapshot': candidate}):
            store = Path(directory) / 'not-created'
            result = run_pipeline(day=DAY, index_rights=[], detail_rights=[], approval={},
                                  store=store, execute=True, now=NOW)
            self.assertEqual(result['status'], 'PUBLICATION_BLOCKED')
            self.assertFalse(store.exists())

    def test_synthetic_source_to_private_sdk_to_today_api_contract(self):
        from urllib.parse import parse_qs, urlsplit
        from race_ai.tokuyama_day_worker import FetchResponse, endpoint as index_endpoint
        from race_ai.official_racelist_adapter import endpoint as detail_endpoint
        from race_ai.official_racelist_worker import source_scope
        from race_ai.venue_source_rights import RightsRecord
        from tests.test_official_racelist_adapter import fixture
        from tests.test_tokuyama_day_worker import html
        from tests.test_today_blob_reader import api
        calls = []
        def index_transport(url, **bounds):
            calls.append(url)
            return FetchResponse(html(), url, 200, 'text/html')
        def detail_transport(url, **bounds):
            calls.append(url)
            n = int(parse_qs(urlsplit(url).query)['rno'][0])
            body = fixture(number=n)
            for lane in range(1, 7):
                body = body.replace(f'選手 {lane}', f'選手{n}-{lane}')
            return FetchResponse(body.encode(), url, 200, 'text/html')
        detail_rights = [RightsRecord('18', 'facts_ingest', 'allowed', source_scope('18'),
                                     NOW.isoformat(), 'synthetic rights only', 'test reviewer')]
        def permission(url):
            return dict(redistribution_authorized=True, source_url=url,
                        evidence_reference='synthetic permission only', reviewed_by='test reviewer')
        approval = permission(index_endpoint(DAY))
        approval['source_approvals'] = [permission(detail_endpoint(DAY, '18', n)) for n in range(1, 13)]
        class MemoryBlob:
            def put(self, key, raw, **options):
                self.raw, self.key, self.options = raw, key, options
                return SimpleNamespace(pathname=key)
            def get(self, key, **options):
                return SimpleNamespace(pathname=self.key, content=self.raw, size=len(self.raw),
                    status_code=200, content_type='application/json',
                    url='https://fixture.private.blob.vercel-storage.com/' + self.key)
            def close(self):
                pass
        client = MemoryBlob()
        with tempfile.TemporaryDirectory() as directory:
            result = run_pipeline(day=DAY, index_rights=rights(), detail_rights=detail_rights,
                approval=approval, store=Path(directory), execute=True, upload_blob=True,
                now=NOW, index_transport=index_transport, detail_transport=detail_transport,
                blob_client=client)
            self.assertEqual(result['status'], 'BLOB_ROUNDTRIP_VERIFIED')
            self.assertEqual(len(calls), 13)
            self.assertEqual(client.options['access'], 'private')
            self.assertFalse(client.options['add_random_suffix'])
            self.assertTrue(client.options['overwrite'])
            with patch.dict(os.environ, {'RACE_AI_FEED_APPROVED': '1', 'BLOB_READ_WRITE_TOKEN': 'synthetic-token'}, clear=True), \
                 patch.object(api, 'utc_now', return_value=NOW), \
                 patch.object(api, 'create_blob_client', return_value=client):
                status, data = api.load_feed()
            self.assertEqual(status, 200)
            self.assertEqual((data['races'], data['complete_six_boat_races']), (12, 12))
            self.assertEqual(len(data['sources']), 13)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
