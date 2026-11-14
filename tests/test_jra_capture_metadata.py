"""Invented JRA GET receipts; no source service, owner key or environment use."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib.util
import unittest

from race_ai import manual_official_capture as capture
from tests.test_manual_official_capture import Clock, Response, manifest, DAY

URL = 'https://www.jra.go.jp/JRADB/accessD.html?CNAME=fictional-published-card'
RAW = '<html><body>架空の出馬表</body></html>'.encode()


class JraCaptureMetadataTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        import tempfile
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.clock = Clock()

    def collect(self, urls=None, *, headers=None):
        urls = [URL] if urls is None else urls
        clock = self.clock
        class ObservedResponse(Response):
            def read(self, count=-1):
                clock.advance(2)
                return super().read(count)
            def close(self):
                if not self.closed: clock.advance(1)
                super().close()
        def get(request, timeout):
            clock.advance(1)
            return ObservedResponse(RAW, url=request.full_url, headers={
                'Content-Type':'text/html; charset=UTF-8', 'Date':'Mon, 01 Apr 2030 01:00:01 GMT',
                'Set-Cookie':'fictional-private-cookie', **(headers or {})})
        capture.collect_once(urls, execution_day=DAY, terms_manifest=manifest(urls), cache_dir=self.root/'cache',
            clock=clock.now, opener=get, sleeper=clock.sleep, monotonic=clock.monotonic)
        return capture._load(self.root/'cache'), {url:RAW for url in urls}

    def build(self, cache, bodies):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.jra_capture_metadata'), 'pure JRA sidecar helper is missing')
        from race_ai.jra_capture_metadata import build_jra_http_metadata
        return build_jra_http_metadata(cache, bodies)

    def test_capture_records_actual_request_headers_and_body_clocks_without_sensitive_headers(self):
        cache, _ = self.collect(); source = cache['captures'][URL]
        self.assertIn('http_metadata', source, 'request/header/body observations must be retained at capture time')
        actual = source['http_metadata']
        self.assertEqual(actual['attempt_no'], 1)
        self.assertEqual(actual['fetched_at'], '2030-04-01T01:00:00+00:00')
        self.assertEqual(actual['headers_received_at'], '2030-04-01T01:00:01+00:00')
        self.assertEqual(actual['response_received_at'], '2030-04-01T01:00:03+00:00')
        self.assertEqual(cache['attempts'][0]['finished_at'], '2030-04-01T01:00:04+00:00')
        self.assertEqual(actual['headers'], [['Content-Type','text/html; charset=UTF-8'],['Date','Mon, 01 Apr 2030 01:00:01 GMT']])
        self.assertEqual(actual['source_sha256'], sha256(RAW).hexdigest())
        self.assertEqual(actual['byte_count'], len(RAW)); self.assertNotIn('fictional-private-cookie', str(actual))

    def test_pure_unique_join_returns_the_existing_original_metadata_document_unchanged(self):
        cache, bodies = self.collect(); before = deepcopy((cache,bodies)); out = self.build(cache,bodies)
        self.assertEqual(out['state'], 'READY_ORIGINAL_METADATA'); self.assertEqual((cache,bodies),before)
        self.assertEqual(out['document']['schema'], 'RACE_AI_MANUAL_OFFICIAL_ORIGINAL_METADATA_V1')
        self.assertEqual(out['document']['execution_day'], DAY)
        actual = out['document']['metadata_by_url'][URL]
        self.assertEqual(actual, dict(source_url=URL, final_url=URL, status=200, byte_count=len(RAW),
            source_sha256=sha256(RAW).hexdigest(), fetched_at='2030-04-01T01:00:00+00:00',
            headers_received_at='2030-04-01T01:00:01+00:00',response_received_at='2030-04-01T01:00:03+00:00',
            headers={'Content-Type':'text/html; charset=UTF-8','Date':'Mon, 01 Apr 2030 01:00:01 GMT'}))
        from scripts.all_existing_model_official_freeze import bind_metadata
        self.assertEqual(bind_metadata(RAW,cache['captures'][URL],actual),actual)
        self.assertEqual(out['source_requests'],0); self.assertFalse(out['independent_receipt_verified'])
        self.assertFalse(out['clocks_rewritten']); self.assertFalse(out['headers_rewritten'])

    def test_historical_metadata_remains_valid_but_cannot_gain_missing_http_observations(self):
        cache,bodies=self.collect();cache['captures'][URL].pop('http_metadata',None)
        capture._validate_cache(cache)
        self.assertEqual(self.build(cache,bodies)['state'],'HOLD')
        cache['attempts']=[];cache['captures'][URL]['capture_origin']='IMPORTED_PRIOR_CAPTURE'
        capture._validate_cache(cache)
        self.assertEqual(self.build(cache,bodies)['state'],'HOLD')

    def test_missing_or_inconsistent_original_facts_hold_instead_of_backfilling(self):
        mutations=('start','headers_clock','body_clock','header_missing','charset_missing','charset_unsupported','mime','duplicate_header',
                   'duplicate_length','encoding','status','status_type','size_type','url','day','bytes','hash','attempt','duplicate_attempt','missing_body')
        for mutation in mutations:
            # One original collection is copied: the helper itself is pure.
            if not hasattr(self,'original'):self.original=self.collect()
            cache,bodies=deepcopy(self.original);source=cache['captures'][URL]
            actual=source.get('http_metadata',{})
            if mutation=='start':actual['fetched_at']='2030-04-01T00:59:59+00:00'
            elif mutation=='headers_clock':actual.pop('headers_received_at',None)
            elif mutation=='body_clock':actual['response_received_at']=cache['attempts'][0]['finished_at']
            elif mutation=='header_missing':actual['headers']=[]
            elif mutation=='charset_missing':actual['headers']=[['Content-Type','text/html']];source['content_type']='text/html'
            elif mutation=='charset_unsupported':actual['headers']=[['Content-Type','text/html; charset=windows-1252']];source['content_type']='text/html; charset=windows-1252'
            elif mutation=='mime':actual['headers']=[['Content-Type','application/json; charset=UTF-8']];source['content_type']='application/json; charset=UTF-8'
            elif mutation=='duplicate_header':actual.setdefault('headers',[]).append(['content-type','text/html; charset=UTF-8'])
            elif mutation=='duplicate_length':actual['headers'] += [['Content-Length',str(len(RAW))],['content-length',str(len(RAW))]]
            elif mutation=='encoding':actual['headers'].append(['Content-Encoding','gzip'])
            elif mutation=='status':actual['status']=403
            elif mutation=='status_type':actual['status']=200.0
            elif mutation=='size_type':actual['byte_count']=float(len(RAW))
            elif mutation=='url':actual['source_url']=URL+'-other'
            elif mutation=='day':actual['headers_received_at']='2030-04-02T01:00:01+00:00'
            elif mutation=='bytes':bodies[URL]+=b'changed'
            elif mutation=='hash':source['source_sha256']='f'*64
            elif mutation=='attempt':actual['attempt_no']=2
            elif mutation=='duplicate_attempt':cache['attempts'].append(deepcopy(cache['attempts'][0]))
            elif mutation=='missing_body':bodies={}
            out=self.build(cache,bodies)
            with self.subTest(mutation=mutation):self.assertEqual(out['state'],'HOLD');self.assertIsNone(out['document'])

    def test_two_sources_require_distinct_actual_attempt_positions(self):
        second=URL+'-second';cache,bodies=self.collect([URL,second])
        self.assertEqual(self.build(cache,bodies)['state'],'READY_ORIGINAL_METADATA')
        cache['captures'][second].setdefault('http_metadata',{})['attempt_no']=1
        self.assertEqual(self.build(cache,bodies)['state'],'HOLD')

    def test_duplicate_actual_headers_are_retained_for_audit_but_hold_the_sidecar(self):
        from email.message import Message
        def get(request, timeout):
            response=Response(RAW,url=request.full_url);response.headers=Message()
            response.headers['Content-Type']='text/html; charset=UTF-8'
            response.headers['content-type']='text/html; charset=shift_jis'
            return response
        report=capture.collect_once([URL],execution_day=DAY,terms_manifest=manifest([URL]),cache_dir=self.root/'duplicates',
            clock=self.clock.now,opener=get,sleeper=self.clock.sleep,monotonic=self.clock.monotonic)
        cache=capture._load(self.root/'duplicates')
        self.assertEqual(report['captured_sources'],1)
        self.assertEqual(cache['captures'][URL]['http_metadata']['headers'],
            [['Content-Type','text/html; charset=UTF-8'],['content-type','text/html; charset=shift_jis']])
        self.assertEqual(self.build(cache,{URL:RAW})['state'],'HOLD')

    def test_redirected_capture_remains_readable_but_cannot_be_relabelled_as_a_direct_jra_get(self):
        from urllib.error import HTTPError
        final='https://www.jra.go.jp/fictional-published-card'
        def get(request, timeout):
            if request.full_url==URL:raise HTTPError(URL,302,'fixture',{'Location':final},None)
            return Response(RAW,url=request.full_url)
        capture.collect_once([URL],execution_day=DAY,terms_manifest=manifest([URL]),cache_dir=self.root/'redirect',
            clock=self.clock.now,opener=get,sleeper=self.clock.sleep,monotonic=self.clock.monotonic)
        stored=capture.read_capture(self.root/'redirect',URL)
        self.assertEqual(stored['metadata']['final_url'],final)
        self.assertEqual(stored['metadata']['http_metadata']['source_url'],final)
        self.assertEqual(self.build(capture._load(self.root/'redirect'),{URL:RAW})['state'],'HOLD')


if __name__ == '__main__': unittest.main()
