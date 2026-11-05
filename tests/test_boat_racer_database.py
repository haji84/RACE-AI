"""Synthetic database population, revision and availability contracts."""
from datetime import datetime,timedelta,timezone
import hashlib
import unittest
from race_ai.boat_racer_database import RacerDatabase
from race_ai.boat_racer_term import term_info
from tests.test_boat_racer_term import record
from tests.test_boat_entry_observations import uncompressed_lzh,daily_pair

NOW=datetime(2030,1,1,tzinfo=timezone.utc)

def term_archive(raw=None):return uncompressed_lzh(raw or record()+b'\n'+record('4002'),'fan2604.txt')

class DatabaseTests(unittest.TestCase):
    def setUp(self):self.at=NOW;self.db=RacerDatabase(clock=lambda:self.at)
    def add(self,raw=None):
        return self.db.import_term(term_archive(raw),term='2026-2',source_url=term_info('2026-2')['source_url'],captured_at=NOW.isoformat())
    def test_all_population_and_indexed_lookup_and_immutable_sources(self):
        self.add();s=self.db.summary()
        self.assertEqual(s['term_racers'],2);self.assertEqual(s['course_rows'],12)
        row=self.db.lookup('4002',as_of=NOW.isoformat(),allow_source=lambda *a:True)
        self.assertEqual(row['racer_id'],'4002');self.assertEqual(row['national_win_rate'],7.56)
        self.assertIsNone(self.db.lookup('4999',as_of=NOW.isoformat(),allow_source=lambda *a:True))
        self.add();self.assertEqual(self.db.summary()['sources'],1)
        with self.assertRaises(Exception):self.db.db.execute('DELETE FROM sources')
    def test_no_historical_availability_or_permission_fabrication(self):
        self.add()
        with self.assertRaises(ValueError):self.db.lookup('4001',as_of=(NOW-timedelta(days=1)).isoformat(),allow_source=lambda *a:True)
        with self.assertRaises(ValueError):self.db.lookup('4001',as_of=NOW.isoformat())
        with self.assertRaises(ValueError):self.db.import_term(term_archive(),term='2026-2',source_url='https://example.test/file',captured_at=NOW.isoformat())
    def test_serialized_restore_counts_exact_hash_tamper_and_open_clock(self):
        self.add();raw=self.db.serialize();sha=hashlib.sha256(raw).hexdigest()
        self.at+=timedelta(hours=1)
        other=RacerDatabase.restore(raw,expected_sha256=sha,clock=lambda:self.at)
        self.assertEqual(other.summary(),self.db.summary())
        with self.assertRaises(ValueError):other.lookup('4001',as_of=NOW.isoformat(),allow_source=lambda *a:True)
        with self.assertRaises(ValueError):RacerDatabase.restore(raw+b'tamper',expected_sha256=sha)
    def test_revised_term_is_append_only_latest_available_source(self):
        self.add();self.at+=timedelta(hours=1)
        raw=record().replace(b'0756',b'0800')+b'\n'+record('4002')
        self.db.import_term(term_archive(raw),term='2026-2',source_url=term_info('2026-2')['source_url'],captured_at=self.at.isoformat())
        self.assertEqual(self.db.summary()['sources'],2)
        self.assertEqual(self.db.lookup('4001',as_of=self.at.isoformat(),allow_source=lambda *a:True)['national_win_rate'],8)
        self.assertEqual(self.db.summary()['term_versions'],4)
    def test_official_daily_results_all_rows_and_no_unknown_career_completeness(self):
        _,k=daily_pair();raw=uncompressed_lzh(k,'K261104.TXT')
        self.add();self.db.import_results(raw,day='2026-11-04',source_url='https://www1.mbrace.or.jp/od2/K/202611/k261104.lzh',captured_at=NOW.isoformat())
        s=self.db.summary();self.assertEqual(s['history_starts'],18);self.assertEqual(s['history_racers'],6)
        self.assertEqual(s['known_racer_ids'],6);self.assertFalse(s['all_career_history_complete'])
        rows=self.db.history('4001',before_day='2030-01-01',as_of=NOW.isoformat(),allow_source=lambda *a:True)
        self.assertEqual(len(rows),3);self.assertEqual(rows[-1]['race_id'],'20261104-17-03')
        self.assertEqual(len(self.db.history('4001',before_day='2026-11-04',as_of=NOW.isoformat(),allow_source=lambda *a:True)),0)

    def test_jst_result_day_does_not_use_utc_calendar_for_availability(self):
        _,text=daily_pair();text=text.replace(b'2026/11/04',b'2030/01/02')
        raw=uncompressed_lzh(text,'K300102.TXT');self.at=datetime(2030,1,1,23,50,tzinfo=timezone.utc)
        self.db.import_results(raw,day='2030-01-02',source_url='https://www1.mbrace.or.jp/od2/K/203001/k300102.lzh',captured_at=self.at.isoformat())

    def test_latest_term_revision_controls_membership_and_earlier_available_asof(self):
        self.add();first=NOW.isoformat();self.at+=timedelta(hours=1)
        self.db.import_term(term_archive(record()),term='2026-2',source_url=term_info('2026-2')['source_url'],captured_at=self.at.isoformat())
        self.assertIsNone(self.db.lookup('4002',as_of=self.at.isoformat(),allow_source=lambda *a:True))
        self.assertEqual(self.db.summary()['term_racers'],1)
        self.assertIsNotNone(self.db.lookup('4002',as_of=first,allow_source=lambda *a:True))

    def test_return_to_older_content_requires_explicit_revision_review(self):
        self.add();self.at+=timedelta(hours=1)
        newer=record().replace(b'0756',b'0800')+b'\n'+record('4002')
        self.db.import_term(term_archive(newer),term='2026-2',source_url=term_info('2026-2')['source_url'],captured_at=self.at.isoformat())
        self.at+=timedelta(hours=1)
        with self.assertRaisesRegex(ValueError,'REVISION_REVIEW'):
            self.db.import_term(term_archive(),term='2026-2',source_url=term_info('2026-2')['source_url'],captured_at=self.at.isoformat())
