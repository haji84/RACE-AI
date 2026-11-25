"""Invented, dated SQLite starts exercise the existing HistoryBook authority."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


DAY = '2026-11-25'
NOW = datetime(2026, 11, 25, 16, tzinfo=timezone.utc)
TARGET = '202611269801'
KNOWLEDGE = '2026-11-25T17:00:00+00:00'
MERGED_AT = datetime(2026, 11, 25, 17, 1, tzinfo=timezone.utc)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(value):
    return sha256(value).hexdigest()


def database(path, starts):
    with sqlite3.connect(path) as con:
        con.executescript('''
        CREATE TABLE races(race_date TEXT,venue_code TEXT,rno INTEGER,is_girls INTEGER,fetched_at TEXT);
        CREATE TABLE entries(race_date TEXT,venue_code TEXT,rno INTEGER,kumiban INTEGER,racer_name TEXT,kyu TEXT,prefecture TEXT,racer_class TEXT,fetched_at TEXT);
        CREATE TABLE results(race_date TEXT,venue_code TEXT,rno INTEGER,kumiban INTEGER,racer_name TEXT,rank TEXT,is_incident INTEGER,fetched_at TEXT);
        CREATE TABLE line_predictions(race_date TEXT,venue_code TEXT,rno INTEGER,kumiban INTEGER,line_no INTEGER,position_in_line INTEGER,line_size INTEGER,role TEXT);
        ''')
        for day, first_place in starts:
            key = (day, '21', 1)
            con.execute('INSERT INTO races VALUES(?,?,?,?,?)', (*key, 0, '2026-11-25T12:00:00'))
            order = [1, 2, 3, 4, 5]
            order.remove(first_place)
            order.insert(0, first_place)
            for car in range(1, 6):
                name = f'Invented rider {car}'
                con.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?)',
                            (*key, car, name, str(99 + car), '東京', 'S2', '2026-11-25T12:00:00'))
                con.execute('INSERT INTO results VALUES(?,?,?,?,?,?,?,?)',
                            (*key, car, name, str(order.index(car) + 1), 0, '2026-11-25T12:00:00'))
                line, position, size = (1, car, 3) if car <= 3 else (car - 2, 1, 1)
                con.execute('INSERT INTO line_predictions VALUES(?,?,?,?,?,?,?,?)',
                            (*key, car, line, position, size, 'published'))
    path.chmod(0o600)


class RiderHistoryLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.paths = [self.root / 'earlier.db', self.root / 'recent.db']
        self.days = [('20261025', 1), ('20261026', 2), ('20261120', 3),
                     ('20261121', 4), ('20261122', 5), ('20261123', 1), ('20261124', 2)]
        database(self.paths[0], self.days[:3])
        database(self.paths[1], self.days[3:])
        self.registry = dict(schema='KEIRIN_OFFICIAL_CURRENT_REGISTRY_V1', complete=True,
            scope='NEW_CURRENT_SOURCE_KNOWLEDGE_NOT_BACKDATED_ORIGINAL_INPUT',
            retrieval_started_at=DAY + 'T15:00:00+00:00',
            retrieval_completed_at=DAY + 'T15:01:00+00:00',
            riders=[dict(registration=f'{14000 + car:06d}', name=f'Invented rider {car}',
                prefecture_or_country='東京都', cohort=99 + car, **{'class': 'S2'},
                source_url='https://keirin.jp/sp/racersearchresult?dppg=1&seibetuCD=1',
                source_sha256='a' * 64, captured_at=DAY + 'T15:00:30+00:00')
                for car in range(1, 6)])
        self.refresh_manifest()

    def module(self):
        name = 'scripts.keirin_rider_history_ledger'
        self.assertIsNotNone(importlib.util.find_spec(name), 'The dated-start ledger projection is missing.')
        return importlib.import_module(name)

    def refresh_manifest(self):
        self.manifest = dict(schema='KEIRIN_PUBLIC_GITHUB_DOWNLOAD_V1',
            started_at=DAY + 'T12:00:00+00:00', completed_at=DAY + 'T12:01:00+00:00',
            sources=[dict(file=p.name, sha256=digest(p.read_bytes()), bytes=p.stat().st_size,
                url='https://raw.githubusercontent.com/example/data/' + 'b' * 40 + '/data/' + p.name)
                for p in self.paths])

    def build(self, **options):
        registry_raw, manifest_raw = encode(self.registry), encode(self.manifest)
        return self.module().build_ledger(self.paths, registry_raw, manifest_raw,
            expected_registry_sha256=digest(registry_raw), expected_manifest_sha256=digest(manifest_raw),
            as_of_day=DAY, clock=lambda: NOW, **options)

    def read(self, raw, **options):
        return self.module().read_ledger(raw, expected_sha256=digest(raw),
            knowledge_as_of=KNOWLEDGE, target_race_id=TARGET, clock=lambda: MERGED_AT, **options)

    def test_pinned_roundtrip_retains_dated_starts_and_unknown_measurements(self):
        before = [digest(path.read_bytes()) for path in self.paths]
        raw, report = self.build()
        book, restored = self.read(raw)
        self.assertEqual(report['numeric_finish_records'], 35)
        self.assertEqual(restored['numeric_finish_records'], 35)
        stats = book.finish_history('014001', race_id=TARGET)
        self.assertEqual(stats['periods']['all']['observed_count'], 7)
        self.assertEqual(stats['periods']['1_month']['observed_count'], 6)
        self.assertEqual(stats['last_starts'][5]['observed_count'], 5)
        self.assertEqual(stats['last_starts'][5]['first_observed_day'], '2026-11-20')
        self.assertEqual([digest(path.read_bytes()) for path in self.paths], before)
        unknown = book.series['014001', 'all', None].window(999999, 999999)[1]
        self.assertTrue((unknown == 0).all())
        private = json.loads(raw)
        self.assertFalse(private['historical_as_of_authenticated'])
        for value in ('Invented rider', 'expected_finish', 'speed', 'method_known', 'sb_mark'):
            self.assertNotIn(value, raw.decode())
        self.assertNotIn('014001', json.dumps(report))
        self.assertNotIn('202611242101', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
