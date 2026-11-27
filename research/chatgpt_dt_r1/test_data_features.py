"""Leakage and source-contract tests using invented, tiny SQLite archives."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np

try:
    data = importlib.import_module('research.chatgpt_dt_r1.data')
    features = importlib.import_module('research.chatgpt_dt_r1.features')
except ModuleNotFoundError:
    data = features = None


SCHEMA = '''
CREATE TABLE races (race_date TEXT, venue_code TEXT, rno INTEGER,
 venue_name TEXT, title TEXT, race_type TEXT, grade TEXT, is_girls INTEGER,
 weather TEXT, wind_speed REAL, kimarite TEXT, fetched_at TEXT);
CREATE TABLE entries (race_date TEXT, venue_code TEXT, rno INTEGER,
 kumiban INTEGER, racer_name TEXT, prefecture TEXT, age INTEGER, kyu TEXT,
 racer_class TEXT, kyaku_shitsu TEXT, gear_ratio REAL, keisoku_tokuten REAL,
 recent_win_rate REAL, recent_2rentai_rate REAL, recent_3rentai_rate REAL,
 gender TEXT, fetched_at TEXT);
CREATE TABLE results (race_date TEXT, venue_code TEXT, rno INTEGER,
 kumiban INTEGER, rank TEXT, is_incident INTEGER, margin TEXT, agari REAL,
 sb_mark TEXT, fetched_at TEXT);
CREATE TABLE line_predictions (race_date TEXT, venue_code TEXT, rno INTEGER,
 line_no INTEGER, position_in_line INTEGER, line_size INTEGER, kumiban INTEGER,
 role TEXT, fetched_at TEXT);
'''


def archive(path, specs):
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        for spec in specs:
            day, venue, rno = spec.get('day', '20260101'), spec.get('venue', '01'), spec.get('rno', 1)
            n = spec.get('n', 3)
            key = (day, venue, rno)
            clock = spec.get('clock', '2026-11-23T03:56:27')
            con.execute('INSERT INTO races VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (*key, 'SYNTHETIC VENUE', 'SYNTHETIC MEETING', 'A級予選',
                         'F2', 0, spec.get('weather', '晴'), 2.0, '逃げ', clock))
            ranks = spec.get('ranks', [str(i) for i in range(1, n + 1)])
            points = spec.get('points', [90 - i for i in range(n)])
            for car in range(1, n + 1):
                person = 1 if spec.get('identity_collision') else car
                con.execute('INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (*key, car, f'SYNTHETIC RIDER {person}', 'TEST', 30 + car,
                             '100期', spec.get('class', 'A1'), '逃' if car == 1 else '追',
                             3.92, points[car - 1], 20.0, 40.0, 60.0, '男', clock))
                if car <= len(ranks) and ranks[car - 1] is not None:
                    con.execute('INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?)',
                                (*key, car, ranks[car - 1], 0, '', 11.0 + car / 10,
                                 'B' if car == 1 else '', clock))
            lines = spec.get('lines', [list(range(1, n + 1))])
            for number, group in enumerate(lines, 1):
                for position, car in enumerate(group, 1):
                    role = '競り' if spec.get('contested') and car == 2 else '先行' if position == 1 else '追込'
                    con.execute('INSERT INTO line_predictions VALUES (?,?,?,?,?,?,?,?,?)',
                                (*key, number, position, len(group), car, role, clock))
    return {str(path): sha256(Path(path).read_bytes()).hexdigest()}


class DataFeatureContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(data, 'historical adapter and feature builder are not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def load(self, specs, name='source.db'):
        path = self.root / name
        pins = archive(path, specs)
        return data.load_archives([path], expected_sha256=pins)

    def test_all_races_retained_and_missing_or_contested_lines_stay_unknown(self):
        records, audit = self.load([
            {}, {'rno': 2, 'contested': True}, {'rno': 3, 'lines': []},
            {'rno': 4, 'ranks': ['中止'] * 3},
            {'day': '20261122', 'venue': '45', 'rno': 6},
        ])
        self.assertEqual(len(records), 5)
        self.assertEqual(audit['unique_races'], 5)
        self.assertIn('202611224506', {x['race_id'] for x in records})
        self.assertEqual(records[0]['finish'], [1, 2, 3])
        self.assertEqual(records[1]['line_status'], 'CONTESTED')
        self.assertFalse(records[1]['lines_known'])
        self.assertEqual(records[1]['line_groups'], [])
        self.assertFalse(records[2]['lines_known'])
        self.assertEqual(records[2]['line_groups'], [])
        self.assertEqual(records[3]['result_status'], 'CANCELLED')
        self.assertIsNone(records[3]['top3'])
        self.assertTrue(all(x['cohort'] == 'retrospective' for x in records))
        self.assertTrue(all(x['pre_cutoff_authenticated'] is False for x in records))

    def test_pin_required_and_result_changes_do_not_change_input_digest(self):
        first, _ = self.load([{}], 'first.db')
        changed, _ = self.load([{'ranks': ['3', '1', '2'], 'weather': '雨'}], 'changed.db')
        self.assertEqual(first[0]['input_sha256'], changed[0]['input_sha256'])
        self.assertNotEqual(first[0]['source_sha256'], changed[0]['source_sha256'])
        self.assertNotEqual(first[0]['top3'], changed[0]['top3'])
        self.assertNotIn('published_cutoff_at', first[0])
        with self.assertRaisesRegex(data.ArchiveError, 'SHA256'):
            data.load_archives([self.root / 'first.db'], expected_sha256={str(self.root / 'first.db'): '0' * 64})

    def test_duplicate_identical_records_merge_and_conflicts_reject(self):
        a, b = self.root / 'a.db', self.root / 'b.db'
        pins = archive(a, [{}]) | archive(b, [{}])
        rows, audit = data.load_archives([a, b], expected_sha256=pins)
        self.assertEqual(len(rows), 1)
        self.assertEqual(audit['identical_duplicates'], 1)
        c = self.root / 'conflict.db'
        pins.update(archive(c, [{'points': [100, 89, 88]}]))
        with self.assertRaisesRegex(data.ArchiveError, 'CONFLICTING_DUPLICATE'):
            data.load_archives([a, c], expected_sha256=pins)

    def test_partial_finish_top3_and_ties_are_not_invented(self):
        rows, _ = self.load([
            {'n': 5, 'ranks': ['1', '2', '3', '落', None]},
            {'n': 5, 'rno': 2, 'ranks': ['1', '1', '3', '4', '5']},
            {'n': 3, 'rno': 3, 'ranks': []},
        ])
        self.assertIsNone(rows[0]['finish'])
        self.assertEqual(rows[0]['top3'], [1, 2, 3])
        self.assertIsNone(rows[1]['finish'])
        self.assertIsNone(rows[1]['top3'])
        self.assertEqual(rows[1]['result_status'], 'DEAD_HEAT')
        self.assertEqual(rows[2]['result_status'], 'MISSING')

    def test_class_and_unknown_scores_do_not_use_bad_gender_or_invent_identity(self):
        rows, _ = self.load([{'class': 'L1', 'lines': [], 'points': [0, 52, 53]},
                             {'rno': 2, 'identity_collision': True}])
        self.assertEqual(rows[0]['race_class'], 'L1')
        self.assertIsNone(rows[0]['riders'][0]['competition_points'])
        self.assertEqual(rows[0]['riders'][0]['identity_status'], 'UNRESOLVED_SOURCE_COMPOSITE')
        self.assertEqual(len(rows[0]['riders'][0]['identity_key']), 64)
        self.assertNotIn('racer_name', json.dumps(rows))
        self.assertTrue(all(not r['identity_usable'] for r in rows[1]['riders']))

    def test_features_do_not_use_current_or_same_day_results(self):
        rows, _ = self.load([{}, {'rno': 2}, {'day': '20260102'}, {'day': '20260103'}])
        changed = deepcopy(rows)
        for row in changed[:2]:
            row['finish'] = list(reversed(row['finish']))
            row['top3'] = list(reversed(row['top3']))
            for observation in row['result_rows']:
                observation['rank'] = 4 - observation['rank']
                observation['half_lap_seconds'] = 30.0
        a, b = features.build_features(rows), features.build_features(changed)
        np.testing.assert_array_equal(a[0]['features'], b[0]['features'])
        np.testing.assert_array_equal(a[1]['features'], b[1]['features'])
        self.assertFalse(np.array_equal(a[2]['features'], b[2]['features']))
        self.assertEqual(a[1]['history_evidence']['latest_history_day'], None)
        self.assertEqual(a[2]['history_evidence']['latest_history_day'], '2026-01-01')
        self.assertEqual(a[0]['features'].shape, (3, len(features.FEATURE_NAMES)))
        self.assertTrue(np.isfinite(a[0]['features']).all())

    def test_feature_digest_binds_prior_history_without_target_labels(self):
        rows, _ = self.load([{}, {'day': '20260102'}])
        baseline = features.build_features(rows)
        altered = deepcopy(rows)
        altered[1]['top3'] = [3, 2, 1]
        altered[1]['finish'] = [3, 2, 1]
        altered[1]['result_rows'][0]['half_lap_seconds'] = 25.0
        rebuilt = features.build_features(altered)
        self.assertEqual(baseline[1].get('feature_input_sha256'), rebuilt[1].get('feature_input_sha256'))
        self.assertEqual(len(baseline[1].get('feature_input_sha256', '')), 64)
        altered[0]['result_rows'][0]['half_lap_seconds'] = 25.0
        changed_history = features.build_features(altered)
        self.assertNotEqual(baseline[1]['feature_input_sha256'], changed_history[1]['feature_input_sha256'])
        self.assertEqual(baseline[1]['input_sha256'], changed_history[1]['input_sha256'])

    def test_future_target_with_archive_history_remains_unattested_shadow(self):
        rows, _ = self.load([{}, {'day': '20260102'}])
        rows[1]['cohort'] = 'prospective'
        built = features.build_features(rows)
        self.assertEqual(built[1].get('feature_scope'), 'PROSPECTIVE_SHADOW_UNATTESTED')
        self.assertFalse(built[1]['history_evidence']['publication_time_authenticated'])
        self.assertFalse(built[1].get('feature_availability_authenticated', True))

    def test_features_unknown_lines_missing_values_and_timing_definitions(self):
        rows, _ = self.load([{'points': [0, 89, 88], 'lines': []}, {'day': '20260102'}])
        built = features.build_features(rows)
        names = features.FEATURE_NAMES
        self.assertEqual(built[0]['features'][0, names.index('points_missing')], 1)
        self.assertEqual(built[0]['features'][0, names.index('line_unknown')], 1)
        self.assertEqual(built[1]['features'][0, names.index('history_half_lap_missing')], 0)
        self.assertEqual(built[1]['features'][0, names.index('history_final_lap_missing')], 1)
        self.assertTrue(all(np.isfinite(x['features']).all() for x in built))

    def test_full_lap_is_retired_and_only_prior_agari_changes_timing_features(self):
        rows, _ = self.load([{}, {'day': '20260102'}])
        baseline = features.build_features(rows)[1]
        modified = deepcopy(rows)
        modified[0]['result_rows'][0]['final_lap_seconds'] = 24.0
        ignored = features.build_features(modified)[1]
        np.testing.assert_array_equal(baseline['features'], ignored['features'])
        self.assertEqual(baseline['feature_input_sha256'], ignored['feature_input_sha256'])
        modified[0]['result_rows'][0]['half_lap_seconds'] = 18.0
        active = features.build_features(modified)[1]
        names = active['feature_names']
        self.assertNotEqual(active['features'][0, names.index('history_half_lap_mean')],
                            baseline['features'][0, names.index('history_half_lap_mean')])
        self.assertAlmostEqual(active['features'][0, names.index('history_venue_half_lap_mean')], 18. / 20.)
        self.assertEqual(active['features'][0, names.index('history_final_lap_mean')], 0.)
        self.assertEqual(active['features'][0, names.index('history_final_lap_missing')], 1.)

    def test_unsupported_rosters_are_retained_as_holds_without_failing_other_races(self):
        rows, audit = self.load([{'n': 0}, {'rno': 2, 'n': 2}, {'rno': 3, 'n': 3},
                                 {'rno': 4, 'n': 9}, {'rno': 5, 'n': 10}])
        built = features.build_features(rows)
        self.assertEqual(audit['unique_races'], 5)
        self.assertEqual([r['feature_status'] for r in built],
                         ['HOLD_UNSUPPORTED_ROSTER', 'HOLD_UNSUPPORTED_ROSTER', 'READY',
                          'READY', 'HOLD_UNSUPPORTED_ROSTER'])
        self.assertEqual([r['features'].shape[0] for r in built], [0, 2, 3, 9, 10])

    def test_incident_and_absence_do_not_become_numeric_history_or_measured_fatigue(self):
        rows, _ = self.load([{'ranks': ['落', '欠', '1']}, {'day': '20260102'}])
        built = features.build_features(rows)
        evidence = built[1]['history_evidence']['rider_evidence']
        self.assertEqual(evidence['1']['confirmed_start_proxy'], 1)
        self.assertEqual(evidence['1']['numeric_finishes'], 0)
        self.assertEqual(evidence['2']['confirmed_start_proxy'], 0)
        self.assertEqual(evidence['2']['numeric_finishes'], 0)
        self.assertEqual(evidence['3']['numeric_finishes'], 1)
        self.assertTrue(built[1]['history_evidence']['rest_and_starts_are_proxies'])

    def test_history_matches_strictly_earlier_days_even_when_stream_order_is_wrong(self):
        rows, _ = self.load([{}, {'day': '20260102'}, {'day': '20260103'}])
        builder = features.FeatureBuilder()
        builder.update_day([rows[2]])
        earlier = builder.transform(rows[1])
        empty = features.FeatureBuilder().transform(rows[1])
        np.testing.assert_array_equal(earlier['features'], empty['features'])
        self.assertIsNone(earlier['history_evidence']['latest_history_day'])
        with self.assertRaisesRegex(ValueError, 'SINGLE_DAY'):
            builder.update_day(rows[:2])

    def test_batch_order_is_deterministic_and_history_is_not_updated_twice(self):
        rows, _ = self.load([{}, {'day': '20260102'}, {'day': '20260103'}])
        forward = features.build_features(rows)
        reverse = features.build_features(list(reversed(rows)))
        self.assertEqual([x['race_id'] for x in forward], [x['race_id'] for x in reverse])
        for a, b in zip(forward, reverse):
            np.testing.assert_array_equal(a['features'], b['features'])
        builder = features.FeatureBuilder()
        builder.update_day([rows[0]])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_HISTORY_RACE'):
            builder.update_day([rows[0]])


if __name__ == '__main__':
    unittest.main()
