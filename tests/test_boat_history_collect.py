from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from contextlib import redirect_stdout
from unittest.mock import patch
import io
import json
import tempfile
import unittest

from tests.test_boat_history_store import archives,DAY,CAP,ASOF
from race_ai.boat_history_store import HistoryStore


class CollectorTests(unittest.TestCase):
    def setUp(self):
        try:from scripts import boat_history_collect as collector
        except ImportError:collector=None
        self.assertIsNotNone(collector,'private resumable official collector is missing')
        self.c=collector;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=HistoryStore(self.root/'history.sqlite');self.addCleanup(self.store.close)
        self.raw,self.sources=archives();self.calls=[]

    def fetch(self,url):
        self.calls.append(url)
        for kind,meta in self.sources.items():
            if url==meta['source_url']:return self.raw[kind],meta['captured_at']
        raise AssertionError('unexpected source')

    def test_saved_raw_bytes_and_metadata_resume_without_replacing_capture_clock(self):
        first=self.c.collect_day(DAY,self.root,self.store,fetch=self.fetch)
        second=self.c.collect_day(DAY,self.root,self.store,fetch=self.fetch)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(first['normal_races'],3);self.assertTrue(second['reused'])
        self.assertEqual(self.store.racer_profile('4001',ASOF)['starts'],3)
        self.assertEqual(len(list((self.root/'captures').glob('*.lzh'))),2)

    def test_403_and_429_stop_before_other_sources_and_preserve_server_wait(self):
        from race_ai.source_retry_policy import SourceWait
        for code in (403,429):
            root=self.root/str(code);root.mkdir(mode=0o700)
            def denied(url):raise HTTPError(url,code,'denied',{'Retry-After':'600'},None)
            with self.subTest(code=code),self.assertRaises(SourceWait) as failure:
                self.c.collect_day(DAY,root,self.store,fetch=denied)
            self.assertEqual(failure.exception.state,'AUTHORIZATION_WAIT' if code==403 else 'RATE_LIMIT_WAIT')
        self.assertEqual(self.store.inventory()['distinct_days'],0)

    def test_404_is_an_explicit_historical_gap_never_an_empty_success(self):
        def missing(url):raise HTTPError(url,404,'not found',{},None)
        result=self.c.collect_day(DAY,self.root,self.store,fetch=missing)
        self.assertEqual(result['status'],'HISTORICAL_ARCHIVE_UNAVAILABLE')
        self.assertEqual(self.store.inventory()['distinct_days'],0)

    def test_tampered_cached_bytes_are_not_silently_downloaded_or_used(self):
        self.c.collect_day(DAY,self.root,self.store,fetch=self.fetch)
        path=next((self.root/'captures').glob('K*.lzh'));path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'CAPTURE'):
            self.c.collect_day(DAY,self.root,self.store,fetch=self.fetch)
        self.assertEqual(len(self.calls),2)

    def test_cli_records_a_parse_gap_without_exposing_source_payload(self):
        out=io.StringIO()
        argv=['collect','--start','2026-11-04','--end','2026-11-04','--private-dir',str(self.root)]
        with patch('sys.argv',argv),patch.object(self.c,'collect_day',side_effect=ValueError('private-source-body')),redirect_stdout(out):
            status=self.c.main()
        result=json.loads((self.root/'collection-report.json').read_text())
        self.assertEqual(result['days'][0]['status'],'PARSE_REVIEW_REQUIRED')
        self.assertFalse(result['complete'])
        self.assertNotIn('private-source-body',out.getvalue())
        self.assertEqual(status,2)

    def test_cli_persists_incomplete_report_when_source_wait_stops_the_range(self):
        from race_ai.source_retry_policy import SourceWait
        argv=['collect','--start','2026-11-04','--end','2026-11-04','--private-dir',str(self.root)]
        with patch('sys.argv',argv),patch.object(self.c,'collect_day',side_effect=SourceWait('HTTP_RATE_LIMIT',state='RATE_LIMIT_WAIT')),redirect_stdout(io.StringIO()):
            status=self.c.main()
        result=json.loads((self.root/'collection-report.json').read_text())
        self.assertFalse(result['complete']);self.assertEqual(status,2)
        self.assertEqual(result['days'][0]['status'],'RATE_LIMIT_WAIT')
