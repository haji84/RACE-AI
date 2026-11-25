"""Invented, dated SQLite starts exercise the existing HistoryBook authority."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


DAY = '2026-11-25'
NOW = datetime(2026, 11, 25, 16, tzinfo=timezone.utc)
TARGET = '202611269801'
CORRECTED_RACE = '202611242101'
NEW_RACE = '202611252101'
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
        params = dict(expected_sha256=digest(raw), knowledge_as_of=KNOWLEDGE,
                      target_race_id=TARGET, clock=lambda: MERGED_AT)
        return self.module().read_ledger(raw, **(params | options))

    def projection(self, race_id, *, corrected=False, knowledge=KNOWLEDGE, target_day='2026-11-26'):
        day = datetime.strptime(race_id[:8], '%Y%m%d').date().isoformat()
        proof = dict(evidence_sha256='c'*64, cipher_sha256='d'*64, source_sha256='e'*64,
                     cutoff_at=day+'T06:00:00Z', source_updated_at=day+'T06:05:00Z',
                     source_observed_at=day+'T06:06:00Z', sealed_at=day+'T06:07:00Z')
        revisions = [proof]
        places = range(1, 6)
        if corrected:
            revisions.append(dict(proof, evidence_sha256='1'*64, cipher_sha256='2'*64,
                                  source_sha256='3'*64, source_updated_at=day+'T08:00:00Z',
                                  source_observed_at=day+'T08:01:00Z', sealed_at=day+'T08:02:00Z'))
            places = (None, 1, 2, 3, 4)
        finishes = [dict(car=car, registration_id=f'{14000+car:06d}', place=place,
                         status='FINISHED' if place is not None else 'DISQUALIFIED')
                    for car, place in enumerate(places, 1)]
        receipt = dict(schema='KEIRIN_OFFICIAL_RIDER_HISTORY_SOURCE_V1', source_day=day,
                       target_day=target_day, archive_commit='a'*40, index_sha256='b'*64,
                       knowledge_as_of=knowledge, expected_originals=1, expected_result_races=1)
        replay = dict(schema='KEIRIN_OFFICIAL_RIDER_HISTORY_REPLAY_V1', source_day=day,
                      target_day=receipt['target_day'], index_commit=receipt['archive_commit'],
                      knowledge_as_of=knowledge, replayed_at=KNOWLEDGE, target_scope='DAY_LEVEL_DOSSIER_NO_FORECAST_DEADLINE',
                      originals_by_as_of=1, admitted_races=1, no_result_by_as_of=0, held_races=0,
                      numeric_finishes=5-int(corrected), non_numeric_finishes=int(corrected), tied_races=0,
                      verified_revisions=len(revisions), historical_as_of_authenticated=False,
                      forecast_original_authenticated=False, predictive_model_changed=False, accuracy_improvement_proven=False)
        return dict(schema='KEIRIN_OFFICIAL_RIDER_HISTORY_PRIVATE_V1',
                    scope='DERIVED_OFFICIAL_RESULT_PROJECTION_NOT_FORECAST_OR_SECOND_STATE_AUTHORITY',
                    receipt=receipt, replay=replay, histories=[], races={race_id: dict(
                        original_evidence_sha256='f'*64, revisions=revisions, finishes=finishes)})

    def merge(self, raw, projection, *, at=MERGED_AT, **options):
        official = encode(projection)
        params = dict(expected_ledger_sha256=digest(raw), expected_official_sha256=digest(official),
                      clock=lambda: at)
        return self.module().merge_official(raw, official, **(params | options))

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

    def test_verified_correction_removes_the_numeric_start_without_rewriting_parent(self):
        initial, _ = self.build()
        first_projection = self.projection(CORRECTED_RACE)
        first, _ = self.merge(initial, first_projection)
        first_book, _ = self.read(first, knowledge_as_of=MERGED_AT.isoformat())
        self.assertEqual(first_book.finishes['014001'][-1][:2], (CORRECTED_RACE, 1))
        self.assertEqual(len(first_book.finishes['014001']), 7)
        self.assertEqual(first_book.finishes['014001'][-1][2:], self.read(initial)[0].finishes['014001'][-1][2:])

        later = MERGED_AT + timedelta(minutes=1)
        correction = self.projection(CORRECTED_RACE, corrected=True)
        corrected, report = self.merge(first, correction, at=later)
        book, _ = self.read(corrected, knowledge_as_of=later.isoformat(), clock=lambda: later)
        self.assertEqual(report['numeric_finish_records'], 34)
        self.assertEqual(report['verified_official_revisions'], 2)
        self.assertEqual(report['official_non_numeric_finishes'], 1)
        self.assertEqual(book.finish_history('014001', race_id=TARGET)['periods']['all']['observed_count'], 6)
        self.assertEqual(book.finish_history('014001', race_id=TARGET)['last_starts'][5]['first_observed_day'], '2026-10-26')
        self.assertEqual(self.read(first, knowledge_as_of=MERGED_AT.isoformat())[0].finishes['014001'][-1][0], CORRECTED_RACE)
        self.assertEqual(json.loads(corrected)['parent_ledger_sha256'], digest(first))
        self.assertNotIn(CORRECTED_RACE, json.dumps(report))
        self.assertEqual(self.merge(corrected, correction, at=later + timedelta(minutes=1))[0], corrected)
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_REVISION_CONFLICT'):
            self.merge(corrected, first_projection, at=later)
        with self.assertRaisesRegex(ValueError, 'KNOWLEDGE_UNAVAILABLE'):
            self.read(corrected, clock=lambda: later)

    def test_new_official_day_advances_the_next_day_windows_without_guessing_roles(self):
        initial, _ = self.build()
        merged, _ = self.merge(initial, self.projection(NEW_RACE))
        book, report = self.read(merged, knowledge_as_of=MERGED_AT.isoformat(),
                                 target_cutoff_at='2026-11-26T01:00:00Z')
        stats = book.finish_history('014001', race_id=TARGET)
        self.assertEqual(report['numeric_finish_records'], 40)
        self.assertEqual(stats['periods']['all']['observed_count'], 8)
        self.assertEqual(stats['last_starts'][5]['latest_observed_day'], '2026-11-25')
        self.assertEqual(book.finishes['014001'][-1], (NEW_RACE, 1, None, None))

    def test_official_result_must_match_archive_roster_and_both_pins(self):
        initial, _ = self.build()
        projection = self.projection(CORRECTED_RACE)
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_PIN_MISMATCH'):
            self.merge(initial, projection, expected_official_sha256='0'*64)
        with self.assertRaisesRegex(ValueError, 'LEDGER_PIN_MISMATCH'):
            self.merge(initial, projection, expected_ledger_sha256='0'*64)
        swapped = deepcopy(projection)
        finishes = swapped['races'][CORRECTED_RACE]['finishes']
        finishes[0]['registration_id'], finishes[1]['registration_id'] = finishes[1]['registration_id'], finishes[0]['registration_id']
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_IDENTITY_CONFLICT'):
            self.merge(initial, swapped)
        projection['races'][CORRECTED_RACE]['revisions'][0]['sealed_at'] = '2026-11-26T18:00:00Z'
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_CLOCK_INVALID'):
            self.merge(initial, projection)

    def test_same_race_clock_cannot_regress_even_with_a_longer_revision_chain(self):
        initial, _ = self.build()
        merged, _ = self.merge(initial, self.projection(CORRECTED_RACE))
        stale = self.projection(CORRECTED_RACE, corrected=True, knowledge='2026-11-25T14:00:00Z')
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_CLOCK_REGRESSION'):
            self.merge(merged, stale)

    def test_dossier_query_date_does_not_advance_the_historical_input_window(self):
        initial, _ = self.build()
        projection = self.projection(NEW_RACE, target_day='2027-01-01')
        merged, report = self.merge(initial, projection)
        self.assertEqual(report['as_of_exclusive'], '2026-11-26')
        self.read(merged, knowledge_as_of=MERGED_AT.isoformat(), target_cutoff_at='2026-11-26T01:00:00Z')

    def test_private_writer_reuses_identical_bytes_and_refuses_a_conflicting_snapshot(self):
        raw, report = self.build()
        root = self.root.resolve()/'ledgers'
        target = self.module().write_private(root, raw, report['ledger_sha256'])
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(self.module().write_private(root, raw, report['ledger_sha256']), target)
        target.write_bytes(b'preserved conflicting state')
        with self.assertRaisesRegex(ValueError, 'OUTPUT_CONFLICT'):
            self.module().write_private(root, raw, report['ledger_sha256'])
        self.assertEqual(target.read_bytes(), b'preserved conflicting state')

    def test_cli_holds_an_archive_disk_error_without_exposing_its_message(self):
        module = self.module()
        root = self.root.resolve()
        registry, manifest = root/'registry.json', root/'archive.json'
        for path, doc in ((registry, self.registry), (manifest, self.manifest)):
            path.write_bytes(encode(doc))
            path.chmod(0o600)
        out = StringIO()
        with patch.object(module, 'build_ledger', side_effect=sqlite3.OperationalError('private canary')), redirect_stdout(out):
            code = module.main(['build', '--database', str(self.paths[0]), '--registry', str(registry),
                '--archive-manifest', str(manifest), '--registry-sha256', digest(registry.read_bytes()),
                '--archive-manifest-sha256', digest(manifest.read_bytes()), '--as-of-day', DAY,
                '--output-dir', str(root/'out')])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue()), {'state': 'RIDER_HISTORY_LEDGER_INPUT_INVALID'})


if __name__ == '__main__':
    unittest.main()
