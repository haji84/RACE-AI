"""Synthetic HTTP/cache tests; fixture keys never used for real sources."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from race_ai.teiai_collection import HistoryCache
from race_ai.source_retry_policy import SourceWait

NOW=datetime(2030,3,31,0,tzinfo=timezone.utc)
URL='https://boatrace-db.jp/api/racer/4001/results/'

class Response:
    status=200
    headers={'Content-Type':'text/csv'}
    def __init__(self,url=URL,raw=b'fictional secret raw'):self.url=url;self.raw=raw
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def geturl(self):return self.url
    def read(self,n):return self.raw[:n]

class Client:
    calls=0
    def open(self,req,timeout):self.calls+=1;return Response(req.full_url)

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'cache.sqlite'
        self.key=os.urandom(32);self.at=NOW;self.client=Client()
        self.cache=HistoryCache.initialize(self.path,self.key,clock=lambda:self.at)
    def tearDown(self):self.tmp.cleanup()
    def get(self,url=URL,**kw):
        return self.cache.fetch(url,allow_source=lambda u,p:True,opener=self.client,**kw)
    def test_encrypted_restore_and_no_duplicate_get(self):
        a=self.get();self.assertEqual(a['raw'],b'fictional secret raw')
        self.assertNotIn(a['raw'],self.path.read_bytes())
        self.cache=HistoryCache(self.path,self.key,clock=lambda:self.at)
        self.assertEqual(self.get(),a);self.assertEqual(self.client.calls,1)
        self.assertEqual(a['published_at'],None)
    def test_quota_global_per_jst_day_persists_restart_and_error_consumes(self):
        for pid in ('4001','4002','4003'):self.get(URL.replace('4001',pid))
        self.cache=HistoryCache(self.path,self.key,clock=lambda:self.at)
        with self.assertRaisesRegex(SourceWait,'TEIAI_DAILY_LIMIT'):self.get(URL.replace('4001','4004'))
        self.assertEqual(self.client.calls,3)
    def test_rights_redirect_and_bad_key_fail_before_returning_data(self):
        with self.assertRaises(ValueError):self.cache.fetch(URL,allow_source=None,opener=self.client)
        self.assertEqual(self.client.calls,0)
        self.get()
        with self.assertRaises(ValueError):HistoryCache(self.path,os.urandom(32),clock=lambda:self.at).fetch(URL,allow_source=lambda u,p:True,opener=self.client)
        with self.assertRaises(ValueError):self.get(URL+'?alternate=1')
    def test_429_retry_after_persists_without_inline_retry(self):
        class Limited:
            def open(_,req,timeout):raise HTTPError(URL,429,'limit',{'Retry-After':'3600'},None)
        with self.assertRaises(SourceWait):self.get(opener_override=Limited())
        self.cache=HistoryCache(self.path,self.key,clock=lambda:self.at)
        with self.assertRaises(SourceWait):self.get()
        self.assertEqual(self.client.calls,0)
    def test_network_error_safe_wait_and_corrupt_ciphertext_stop(self):
        class Offline:
            def open(_,req,timeout):raise URLError('no network')
        with self.assertRaises(SourceWait):self.get(opener_override=Offline())
        self.at+=timedelta(hours=1);self.get()
        with sqlite3.connect(self.path) as db:db.execute("UPDATE versions SET payload=?",(b'broken',))
        with self.assertRaises(ValueError):self.get()
        self.assertEqual(self.client.calls,1)
    def test_missing_state_does_not_initialize_silently(self):
        with self.assertRaises(ValueError):HistoryCache(Path(self.tmp.name)/'missing.sqlite',self.key)
    def test_expiry_is_stop_and_no_implicit_long_term_retention(self):
        self.get();self.at+=timedelta(days=8)
        with self.assertRaisesRegex(ValueError,'RETENTION'):self.get()
    def test_content_type_empty_or_size_change_is_recorded_failure(self):
        class Empty:
            def open(_,req,timeout):return Response(raw=b'')
        with self.assertRaises(ValueError):self.get(opener_override=Empty())
        with self.assertRaises(SourceWait):self.get()

    def test_wrong_key_uncached_url_and_tampered_ledger_stop_before_get(self):
        self.get()
        other=HistoryCache(self.path,os.urandom(32),clock=lambda:self.at)
        with self.assertRaises(ValueError):other.fetch(URL.replace('4001','4002'),allow_source=lambda *a:True,opener=self.client)
        self.assertEqual(self.client.calls,1)
        with sqlite3.connect(self.path) as db:db.execute('DELETE FROM attempts')
        with self.assertRaises(ValueError):self.get(URL.replace('4001','4002'))
        self.assertEqual(self.client.calls,1)

    def test_stored_time_is_after_commit_not_request_end(self):
        times=iter([NOW,NOW+timedelta(seconds=1),NOW+timedelta(seconds=2),NOW+timedelta(seconds=3)])
        self.cache.clock=lambda:next(times)
        doc=self.get()
        self.assertEqual(doc['captured_at'],(NOW+timedelta(seconds=1)).isoformat())
        self.assertEqual(doc['stored_at'],(NOW+timedelta(seconds=3)).isoformat())

    def test_concurrent_reservation_blocks_second_get(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        entered=Event();release=Event()
        class Slow:
            def open(_,req,timeout):entered.set();release.wait(3);return Response(req.full_url)
        with ThreadPoolExecutor(max_workers=2) as pool:
            job=pool.submit(self.get,opener_override=Slow())
            self.assertTrue(entered.wait(2))
            try:
                other=HistoryCache(self.path,self.key,clock=lambda:self.at)
                with self.assertRaisesRegex(SourceWait,'TEIAI_INTERRUPTED_REQUEST_REVIEW'):
                    other.fetch(URL,allow_source=lambda *a:True,opener=self.client)
            finally:release.set()
            self.assertEqual(job.result()['raw'],b'fictional secret raw')
        self.assertEqual(self.client.calls,0)

    def test_retention_metadata_tamper_is_authenticated(self):
        with sqlite3.connect(self.path) as db:db.execute("UPDATE meta SET expires_at='2099-01-01T00:00:00Z'")
        with self.assertRaisesRegex(ValueError,'AUTHENTICATION'):self.get()
        self.assertEqual(self.client.calls,0)
