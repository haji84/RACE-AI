"""Published directory discovery and resumable raw-month catalogs; fictional data."""
from datetime import datetime,timezone
import hashlib
import unittest
from race_ai.boat_history_catalog import published_months,published_days,HistoryMonth
from tests.test_boat_venue_history import archive

NOW='2030-01-01T00:00:00Z'

def menu():return b'<script>var dir="/od2/K/";</script><select><option value="202611">x</option><option value="200501">x</option></select>'
def index(month='202611',days=('04','05')):
    return (f'<script>var dir="/od2/K/{month}/k{month[2:]}";</script>' + ''.join(f'<input type="radio" name="MDAY" value="{d}">' for d in days)).encode()

class CatalogTests(unittest.TestCase):
    def test_only_published_months_and_days_no_endpoint_guessing(self):
        self.assertEqual(published_months(menu()),['200501','202611'])
        self.assertEqual(published_days(index(),month='202611',not_after='2026-11-04'),['2026-11-04'])
        for raw in (b'',index('202610'),index(days=('99',)),index(days=('04','04'))):
            with self.assertRaises(ValueError):published_days(raw,month='202611',not_after='2026-11-05')
    def test_month_progress_roundtrip_and_duplicate_no_double_count(self):
        c=HistoryMonth(month='202611',index_raw=index(),not_after='2026-11-05',roster=['4001'])
        c.record('2026-11-04',archive(),captured_at=NOW)
        c.record('2026-11-04',archive(),captured_at=NOW)
        s=c.summary();self.assertEqual(s['parsed_days'],1);self.assertFalse(s['month_complete'])
        self.assertEqual(c.pending(),['2026-11-05'])
        raw=c.serialize();clone=HistoryMonth.restore(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),month='202611')
        self.assertEqual(clone.summary(),s);self.assertEqual(len(list(clone.archives())),1)
        with self.assertRaises(ValueError):HistoryMonth.restore(raw+b'x',expected_sha256=hashlib.sha256(raw).hexdigest(),month='202611')
        with self.assertRaises(ValueError):HistoryMonth.restore(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),month='200501')
    def test_original_revision_and_reversion_kept_but_latest_selected(self):
        c=HistoryMonth(month='202611',index_raw=index(),not_after='2026-11-05')
        a,b=archive(),archive(18)
        c.record('2026-11-04',a,captured_at=NOW);c.record('2026-11-04',b,captured_at=NOW);c.record('2026-11-04',a,captured_at=NOW)
        self.assertEqual(c.summary()['revision_observations'],3)
        self.assertEqual(list(c.archives())[0]['raw'],a)
        self.assertEqual(c.summary()['unique_archive_bytes'],len(a)+len(b))
    def test_bad_archive_stays_quarantined_missing_is_not_no_race(self):
        c=HistoryMonth(month='202611',index_raw=index(),not_after='2026-11-05')
        c.record('2026-11-04',b'broken',captured_at=NOW)
        c.missing('2026-11-05',captured_at=NOW,http_status=404)
        s=c.summary();self.assertEqual(s['quarantined_days'],1);self.assertEqual(s['missing_days'],1)
        self.assertFalse(s['month_complete']);self.assertEqual(list(c.archives()),[])
        self.assertEqual(c.pending(),[])
