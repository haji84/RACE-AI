"""Archive admission tests use invented riders in real, local SQLite files."""

from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


SCHEMA = """
CREATE TABLE races (race_date TEXT, venue_code TEXT, rno INTEGER,
    is_girls INTEGER, fetched_at TEXT, weather TEXT);
CREATE TABLE entries (race_date TEXT, venue_code TEXT, rno INTEGER,
    kumiban INTEGER, racer_name TEXT, kyu TEXT, racer_class TEXT,
    kyaku_shitsu TEXT, keisoku_tokuten REAL, recent_win_rate REAL,
    recent_2rentai_rate REAL, recent_3rentai_rate REAL, forecast_mark TEXT,
    fetched_at TEXT);
CREATE TABLE line_predictions (race_date TEXT, venue_code TEXT, rno INTEGER,
    kumiban INTEGER, line_no INTEGER, position_in_line INTEGER,
    line_size INTEGER, role TEXT, fetched_at TEXT);
CREATE TABLE results (race_date TEXT, venue_code TEXT, rno INTEGER,
    kumiban INTEGER, rank TEXT, is_incident INTEGER, racer_name TEXT,
    fetched_at TEXT);
CREATE TABLE payouts (race_date TEXT, venue_code TEXT, rno INTEGER,
    bet_type TEXT, combination TEXT, payout INTEGER, fetched_at TEXT);
"""


def fixture(day='20261001', number=1):
    key = {'race_date': day, 'venue_code': '22', 'rno': number}
    clock = '2026-11-24T02:00:00'
    return {
        'races': [{**key, 'is_girls': 0, 'fetched_at': clock,
                   'weather': 'AFTER_RACE_WEATHER'}],
        'entries': [
            {**key, 'kumiban': car, 'racer_name': f'Invented {car}',
             'kyu': '123', 'racer_class': 'S2', 'kyaku_shitsu': '逃' if car == 1 else '追',
             'keisoku_tokuten': 105 - car, 'recent_win_rate': 10,
             'recent_2rentai_rate': 30, 'recent_3rentai_rate': 50,
             'forecast_mark': {1: '◎', 2: '○', 3: '▲', 4: '注', 5: ''}[car],
             'fetched_at': clock}
            for car in range(1, 6)
        ],
        'line_predictions': [
            {**key, 'kumiban': car, 'line_no': line, 'position_in_line': position,
             'line_size': size, 'role': '先行' if position == 1 else '追込',
             'fetched_at': clock}
            for car, line, position, size in ((1, 1, 1, 3), (3, 1, 2, 3),
                                               (4, 1, 3, 3), (2, 2, 1, 2),
                                               (5, 2, 2, 2))
        ],
        'results': [
            {**key, 'kumiban': car, 'rank': str(rank), 'is_incident': 0,
             'racer_name': f'Invented {car}', 'fetched_at': clock}
            for rank, car in enumerate((3, 1, 5, 2, 4), 1)
        ],
        'payouts': [
            {**key, 'bet_type': market, 'combination': combination,
             'payout': 1200, 'fetched_at': clock}
            for market, combination in (('2車単', '3-1'), ('3連単', '3-1-5'))
        ],
    }


def write_database(path, *races):
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        for race in races:
            for table, rows in race.items():
                for row in rows:
                    columns = ','.join(row)
                    placeholders = ','.join('?' for _ in row)
                    connection.execute(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})',
                                       tuple(row.values()))
    return path


class ArchiveStudyAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.keirin_archive_study'),
                             'The bounded archive loader has not been implemented.')
        self.archive = importlib.import_module('race_ai.keirin_archive_study')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def load(self, race=None, **kwargs):
        path = write_database(self.root / 'source.db', race or fixture())
        return self.archive.load_databases([path], **kwargs)

    def assert_held(self, race, reason):
        examples, report = self.load(race)
        self.assertEqual(examples, [])
        self.assertEqual(report['examples_loaded'], 0)
        self.assertEqual(report['held_by_reason'], {reason: 1})

    def test_admits_only_allowlisted_pre_race_fields_with_full_verified_finish(self):
        examples, report = self.load()
        self.assertEqual(len(examples), 1)
        example = examples[0]
        self.assertEqual(example['cohort'], 'archived_replay')
        self.assertEqual(set(example['input']), {'race_id', 'riders', 'line_groups'})
        self.assertEqual(example['input']['race_id'], '202610012201')
        self.assertEqual(example['input']['line_groups'], [[1, 3, 4], [2, 5]])
        self.assertEqual(example['input']['riders'][0], {
            'car': 1, 'competition_points': 104.0, 'win_rate': 10.0,
            'top2_rate': 30.0, 'top3_rate': 50.0, 'mark_rank': 1,
            'style': 'NIGE', 'class': 'S2'})
        self.assertEqual([x['mark_rank'] for x in example['input']['riders']],
                         [1, 2, 3, 4, 'UNMARKED'])
        self.assertEqual(example['finish_order'], [3, 1, 5, 2, 4])
        self.assertEqual(example['outcomes'], {'2t': [[3, 1]], '3t': [[3, 1, 5]]})
        self.assertEqual(example['source']['scope'],
                         'RETROSPECTIVE_ARCHIVE_NO_PRE_CUTOFF_ATTESTATION')
        self.assertEqual(example['source']['fetched_at'], '2026-11-24T02:00:00')
        source = self.root / 'source.db'
        self.assertEqual(example['source']['database_sha256'], sha256(source.read_bytes()).hexdigest())
        self.assertEqual(report['sources'][0]['database_sha256'], example['source']['database_sha256'])
        self.assertEqual(report['held_by_reason'], {})

    def test_class_comes_from_racer_class_and_never_graduation_term(self):
        race = fixture()
        race['entries'][0]['racer_class'] = None
        race['entries'][0]['kyu'] = 'S1'
        self.assert_held(race, 'INVALID_RIDER_CLASS')

    def test_absent_entry_marker_holds_the_whole_race(self):
        race = fixture()
        race['entries'][0]['kyu'] = '123(欠車)'
        self.assert_held(race, 'ABSENT_ENTRY')

    def test_missing_ordinary_line_is_a_hold(self):
        race = fixture()
        race['line_predictions'] = []
        self.assert_held(race, 'MISSING_PUBLISHED_LINES')

    def test_girls_missing_line_uses_only_declared_singleton_policy(self):
        race = fixture()
        race['races'][0]['is_girls'] = 1
        race['line_predictions'] = []
        for rider in race['entries']:
            rider['racer_class'] = 'L1'
        examples, report = self.load(race)
        self.assertEqual(examples[0]['input']['line_groups'], [[1], [2], [3], [4], [5]])
        self.assertEqual(report['girls_singleton_count'], 1)
        self.assertIn('is_girls', report['girls_missing_line_policy'])

    def test_partial_girls_line_cannot_hide_missing_starters(self):
        race = fixture()
        race['races'][0]['is_girls'] = 1
        race['line_predictions'].pop()
        self.assert_held(race, 'LINE_STARTER_SET_MISMATCH')

    def test_contested_published_position_is_not_arbitrarily_ordered(self):
        race = fixture()
        race['line_predictions'][1]['position_in_line'] = 1
        self.assert_held(race, 'CONTESTED_LINE_POSITION')

    def test_explicit_competition_for_a_position_is_held(self):
        race = fixture()
        race['line_predictions'][1]['role'] = '競り'
        self.assert_held(race, 'CONTESTED_LINE_POSITION')

    def test_published_line_must_have_the_exact_unique_starter_set(self):
        race = fixture()
        race['line_predictions'][-1]['kumiban'] = 9
        self.assert_held(race, 'LINE_STARTER_SET_MISMATCH')

    def test_line_size_and_position_gaps_are_validated(self):
        for edit, reason in (({'line_size': 4}, 'LINE_SIZE_MISMATCH'),
                             ({'position_in_line': 4}, 'LINE_POSITION_GAP')):
            with self.subTest(edit=edit):
                race = fixture()
                race['line_predictions'][2].update(edit)
                directory = self.root / reason
                directory.mkdir()
                examples, report = self.archive.load_databases([write_database(directory / 'source.db', race)])
                self.assertEqual(examples, [])
                self.assertEqual(report['held_by_reason'], {reason: 1})

    def test_duplicate_and_too_few_starters_are_held(self):
        for mutate in ('duplicate', 'four_cars'):
            with self.subTest(mutate=mutate):
                race = fixture()
                if mutate == 'duplicate':
                    race['entries'][1]['kumiban'] = 1
                else:
                    race['entries'].pop()
                path = write_database(self.root / (mutate + '.db'), race)
                examples, report = self.archive.load_databases([path])
                self.assertEqual(examples, [])
                self.assertEqual(report['held_by_reason'], {'INVALID_STARTER_SET': 1})

    def test_nonfinite_out_of_range_and_nonmonotone_rates_hold(self):
        cases = ((None, 'MISSING_RIDER_METRIC'), ('unknown', 'INVALID_RIDER_METRIC'),
                 (float('inf'), 'INVALID_RIDER_METRIC'), (-1, 'INVALID_RIDER_METRIC'),
                 (101, 'INVALID_RIDER_METRIC'), (40, 'INCONSISTENT_FINISH_RATES'))
        for index, (value, reason) in enumerate(cases):
            with self.subTest(value=value):
                race = fixture()
                race['entries'][0]['recent_win_rate'] = value
                examples, report = self.archive.load_databases([
                    write_database(self.root / f'rates-{index}.db', race)])
                self.assertEqual(examples, [])
                self.assertEqual(report['held_by_reason'], {reason: 1})

    def test_unknown_style_or_forecast_mark_cannot_silently_become_zero(self):
        for index, (field, value, reason) in enumerate((
                ('kyaku_shitsu', 'unknown', 'INVALID_RIDER_STYLE'),
                ('forecast_mark', '?', 'INVALID_SOURCE_MARK'))):
            race = fixture()
            race['entries'][0][field] = value
            examples, report = self.archive.load_databases([
                write_database(self.root / f'field-{index}.db', race)])
            self.assertEqual(examples, [])
            self.assertEqual(report['held_by_reason'], {reason: 1})

    def test_missing_and_special_finishes_never_enter_all_finish_order_training(self):
        for index, mutate in enumerate(('missing', 'incident', 'tie', 'special', 'extra_car')):
            race = fixture()
            if mutate == 'missing':
                race['results'].pop()
            elif mutate == 'incident':
                race['results'][0]['is_incident'] = 1
            elif mutate == 'tie':
                race['results'][1]['rank'] = '1'
            elif mutate == 'special':
                race['results'][0]['rank'] = '落棄'
            else:
                race['results'][0]['kumiban'] = 9
            with self.subTest(mutate=mutate):
                examples, report = self.archive.load_databases([
                    write_database(self.root / f'finish-{index}.db', race)])
                self.assertEqual(examples, [])
                self.assertEqual(report['held_by_reason'], {'INCOMPLETE_OR_SPECIAL_RESULT': 1})

    def test_result_identity_changes_on_same_car_are_held(self):
        race = fixture()
        race['results'][0]['racer_name'] = 'Different invented rider'
        self.assert_held(race, 'RESULT_STARTER_IDENTITY_MISMATCH')

    def test_missing_multiple_malformed_and_conflicting_paid_orders_are_held(self):
        for index, mutate in enumerate(('missing', 'tie', 'malformed', 'conflict', 'zero_payout')):
            race = fixture()
            if mutate == 'missing':
                race['payouts'].pop()
            elif mutate == 'tie':
                race['payouts'].append({**race['payouts'][0], 'combination': '1-3'})
            elif mutate == 'malformed':
                race['payouts'][1]['combination'] = '3-1-5 trailing text'
            elif mutate == 'conflict':
                race['payouts'][1]['combination'] = '1-3-5'
            else:
                race['payouts'][1]['payout'] = 0
            expected = 'PAYOUT_FINISH_MISMATCH' if mutate == 'conflict' else 'NONUNIQUE_OR_INVALID_PAYOUT'
            with self.subTest(mutate=mutate):
                examples, report = self.archive.load_databases([
                    write_database(self.root / f'payout-{index}.db', race)])
                self.assertEqual(examples, [])
                self.assertEqual(report['held_by_reason'], {expected: 1})

    def test_same_revision_deduplicates_and_conflicting_revision_holds(self):
        first = fixture()
        same = deepcopy(first)
        same['races'][0]['fetched_at'] = '2026-11-25T02:00:00'
        paths = [write_database(self.root / 'one.db', first),
                 write_database(self.root / 'same.db', same)]
        examples, report = self.archive.load_databases(paths)
        self.assertEqual(len(examples), 1)
        self.assertEqual(report['duplicate_same_count'], 1)
        conflict = deepcopy(first)
        conflict['entries'][0]['keisoku_tokuten'] = 110
        paths.append(write_database(self.root / 'conflict.db', conflict))
        examples, report = self.archive.load_databases(paths)
        self.assertEqual(examples, [])
        self.assertEqual(report['held_by_reason'], {'DUPLICATE_RACE_CONFLICT': 1})

    def test_invalid_duplicate_revision_cannot_leave_an_earlier_valid_copy(self):
        invalid = fixture()
        invalid['results'][0]['rank'] = '失'
        examples, report = self.archive.load_databases([
            write_database(self.root / 'valid.db', fixture()),
            write_database(self.root / 'invalid.db', invalid)])
        self.assertEqual(examples, [])
        self.assertEqual(report['held_by_reason'], {'DUPLICATE_RACE_CONFLICT': 1})

    def test_window_exclusions_and_output_order_are_explicit(self):
        path = write_database(self.root / 'days.db', fixture('20260930'),
                              fixture('20261002'), fixture('20261001', 2), fixture('20261001', 1))
        examples, report = self.archive.load_databases(
            [path], start_day='20261001', end_day='20261002',
            excluded_race_ids=('202610012202',))
        self.assertEqual([row['input']['race_id'] for row in examples],
                         ['202610012201', '202610022201'])
        self.assertEqual(report['outside_window_count'], 1)
        self.assertEqual(report['excluded_count'], 1)
        self.assertEqual(report['held_by_reason'], {})

    def test_invalid_windows_and_impossible_source_dates_are_rejected(self):
        path = write_database(self.root / 'window.db', fixture())
        for start, end in (('20261002', '20261001'), ('20260230', '20261001'),
                           ('2026-10-01', '20261122')):
            with self.subTest(start=start):
                with self.assertRaisesRegex(ValueError, 'ARCHIVE_DATE_WINDOW_INVALID'):
                    self.archive.load_databases([path], start_day=start, end_day=end)
        malformed = fixture('20261032')
        examples, report = self.archive.load_databases([
            write_database(self.root / 'bad-date.db', malformed)])
        self.assertEqual(examples, [])
        self.assertEqual(report['held_by_reason'], {'INVALID_RACE_IDENTITY': 1})

    def test_readonly_loading_preserves_database_bytes_and_creates_no_sidecars(self):
        path = write_database(self.root / 'readonly.db', fixture())
        path.chmod(0o400)
        before = sha256(path.read_bytes()).hexdigest()
        self.archive.load_databases([path])
        self.assertEqual(sha256(path.read_bytes()).hexdigest(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['readonly.db'])

    def test_missing_symlinked_and_non_sqlite_inputs_fail_without_creation(self):
        missing = self.root / 'missing.db'
        invalid = self.root / 'invalid.db'
        invalid.write_bytes(b'not sqlite')
        real = write_database(self.root / 'real.db', fixture())
        link = self.root / 'linked.db'
        link.symlink_to(real)
        for path in (missing, invalid, link):
            with self.subTest(path=path.name):
                with self.assertRaises(ValueError):
                    self.archive.load_databases([path])
        self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
