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
    def test_restore_authenticates_quarantined_raw_archive_too(self):
        c=HistoryMonth(month='202611',index_raw=index(),not_after='2026-11-05')
        c.record('2026-11-04',b'broken',captured_at=NOW)
        with c.db:c.db.execute('UPDATE archives SET raw=?',(b'tampered',))
        raw=c.serialize()
        with self.assertRaises(ValueError):HistoryMonth.restore(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),month='202611')

    def test_publication_placeholder_stays_pending_with_preserved_raw_bytes(self):
        from tests.test_boat_entry_observations import uncompressed_lzh
        raw=uncompressed_lzh('STARTK\n01KBGN\nボートレース桐生\nデータは、この場の全レース終了後に登録されます。\n01KEND\nENDK'.encode('cp932'),'K261104.TXT')
        c=HistoryMonth(month='202611',index_raw=index(days=('04',)),not_after='2026-11-05')
        c.record('2026-11-04',raw,captured_at=NOW)
        self.assertEqual(c._heads()[0][3],'PARTIAL_SOURCE')
        self.assertEqual(c.pending(),[])
        self.assertEqual(c.summary()['partial_source_days'],1)
        self.assertEqual(c.summary()['pending_days'],0)
        self.assertFalse(c.summary()['month_complete'])
        self.assertEqual(len(list(c.archives())),1)

    def test_reanalysis_uses_retained_bytes_and_preserves_original_observation(self):
        from unittest.mock import patch
        import race_ai.boat_history_catalog as catalog
        c=HistoryMonth(month='202611',index_raw=index(days=('04',)),not_after='2026-11-05')
        raw=archive()
        with patch.object(catalog,'parse_archive',side_effect=ValueError('OLD_PARSER')),patch.object(catalog,'OFFICIAL_K_PARSER_REVISION',1):
            c.record('2026-11-04',raw,captured_at=NOW)
        before=c.db.execute('SELECT * FROM observations').fetchall()
        self.assertTrue(c.reparse('2026-11-04',parsed_at='2030-01-02T00:00:00Z'))
        self.assertEqual(c.db.execute('SELECT * FROM observations ORDER BY id LIMIT 1').fetchall(),before)
        self.assertEqual(c.summary()['revision_observations'],2)
        self.assertEqual(c.summary()['parsed_days'],1)
        self.assertEqual(c.summary()['quarantined_days'],0)
        self.assertEqual(list(c.archives())[0]['raw'],raw)
        self.assertEqual(list(c.archives())[0]['captured_at'],NOW)
        event=c.db.execute('SELECT parsed_at,parser_revision FROM parse_events ORDER BY observation_id DESC LIMIT 1').fetchone()
        self.assertEqual(event,('2030-01-02T00:00:00Z',catalog.OFFICIAL_K_PARSER_REVISION))
        self.assertFalse(c.reparse('2026-11-04',parsed_at='2030-01-03T00:00:00Z'))
        self.assertEqual(c.summary()['revision_observations'],2)

    def test_reanalysis_requires_existing_hash_bound_source_and_later_clock(self):
        c=HistoryMonth(month='202611',index_raw=index(),not_after='2026-11-05')
        c.record('2026-11-04',archive(),captured_at=NOW)
        with self.assertRaises(ValueError):c.reparse('2026-11-04',parsed_at='2029-12-31T00:00:00Z')
        with self.assertRaises(ValueError):c.reparse('2026-11-05',parsed_at=NOW)
        with c.db:c.db.execute('UPDATE archives SET raw=?',(b'corrupt',))
        with self.assertRaises(ValueError):c.reparse('2026-11-04',parsed_at='2030-01-02T00:00:00Z')

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
