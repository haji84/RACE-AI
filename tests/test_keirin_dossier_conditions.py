"""Condition labels and win counts require bounded, dated evidence."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest

from race_ai import keirin_dossier_conditions as conditions
from tests.test_keirin_official_schedule import meeting, page, venue
from tests.test_keirin_official_sp_receipt import DAY, AT, html, list_data


class DossierConditionsTests(unittest.TestCase):
    def inventory(self, *, grade='F1', icon='f1', duplicate=False):
        grade_image = f'<img alt="{grade}" src="/sp/static/img/icon/grade/ico_{icon}.png">'
        meeting_body = meeting('2030-01-14', '2030-01-16').replace(
            '<img alt="架空等級">', grade_image * (2 if duplicate else 1))
        calendar = page([venue(98, [meeting_body])])
        listing = list_data()
        entries = listing['SJ0301']['kaisaiDayList'][1]['raceProgramList']
        for row, label in zip(entries, ('Ａ級準決勝', 'Ｓ級初日特選', 'Ｓ級特別優秀')):
            row['strSyumokuName'] = label
        listed = html(listing)
        return dict(calendar_receipt=dict(raw_bytes=calendar, observed_at=AT,
                                         expected_sha256=sha256(calendar).hexdigest()),
                    list_sources=[dict(venue_code=98, raw_bytes=listed,
                                       observed_at=AT + timedelta(seconds=1),
                                       expected_sha256=sha256(listed).hexdigest())],
                    day=DAY, now=AT + timedelta(seconds=2))

    def test_distinct_official_grade_and_stage(self):
        rows = conditions.official_race_conditions(**self.inventory())
        self.assertEqual([(row['meeting_grade'], row['round_stage'], row['round_label'])
                          for row in rows.values()], [
            ('F1', 'SEMI_FINAL', 'A級準決勝'),
            ('F1', 'INITIAL_SPECIAL', 'S級初日特選'),
            ('F1', None, 'S級特別優秀'),
        ])
        self.assertEqual(conditions.round_stage('S級二次予選B'), 'PRELIMINARY')
        self.assertEqual(conditions.round_stage('L級ガールズ予選(第2走)'), 'PRELIMINARY')
        self.assertEqual(conditions.round_stage('A級敗者戦'), 'CONSOLATION')
        self.assertEqual(conditions.round_stage('A級特選'), 'SPECIAL_SELECTION')
        self.assertEqual(conditions.round_stage('A級一般'), 'GENERAL')
        self.assertEqual(conditions.round_stage('A級決勝'), 'FINAL')
        self.assertIsNone(conditions.round_stage('A級予選決勝'))

    def test_conflicting_or_unrecognized_grade_stays_unknown(self):
        for change in (dict(icon='f2'), dict(duplicate=True), dict(grade='S2', icon='s2')):
            rows = conditions.official_race_conditions(**self.inventory(**change))
            self.assertIsNone(rows['203001159801']['meeting_grade'])
            self.assertEqual(rows['203001159801']['round_stage'], 'SEMI_FINAL')

    def test_pre_race_feature_uses_only_past_dated_cells_and_actual_publication(self):
        now = AT + timedelta(minutes=1)
        rows = conditions.official_race_conditions(**self.inventory())
        reg = '013005'
        previous = conditions.result_slice('2030-01-14', 'a' * 64, [
            (reg, 'F1', 'SEMI_FINAL', 1),
            (reg, 'F1', 'SEMI_FINAL', 4),
            (reg, 'F1', None, 2),
            (reg, None, 'SEMI_FINAL', 3),
            (reg, None, None, 5),
         ])
        packet = conditions.build_day(day=DAY, published_at=now, registered_races=3,
                                      calendar_sha256='b' * 64, races=rows,
                                      past_results=[previous])
        self.assertEqual(packet['history']['numeric_finishes'], 5)
        self.assertEqual(packet['history']['condition_matched_finishes'], 4)
        self.assertEqual(conditions.rider_feature(packet, registration=reg, meeting_grade='F1',
                         round_stage='SEMI_FINAL', as_of=now), {
            'meeting_grade': 'F1', 'round_stage': 'SEMI_FINAL', 'numeric_finishes': 2,
            'wins': 1, 'top2': 1, 'top3': 1})
        self.assertIsNone(conditions.rider_feature(packet, registration=reg, meeting_grade='F2',
                                                  round_stage='SEMI_FINAL', as_of=now))
        self.assertIsNone(conditions.rider_feature(packet, registration=reg, meeting_grade='F1',
                                                  round_stage='SEMI_FINAL', as_of=AT))
        counts = {(cell['meeting_grade'], cell['round_stage']): cell['numeric_finishes']
                  for cell in packet['riders'][0]['cells']}
        self.assertEqual(counts, {('F1', 'SEMI_FINAL'): 2, ('F1', None): 3, (None, 'SEMI_FINAL'): 3})
        with self.assertRaises(ValueError):
            conditions.build_day(day=DAY, published_at=now, registered_races=3,
                                 calendar_sha256='b' * 64, races=rows,
                                 past_results=[dict(previous, day=DAY)])
        packet['riders'][0]['cells'][0]['top3'] = 9
        with self.assertRaises(ValueError):
            conditions.checked_day(packet)

    def test_archive_does_not_overlap_official_replay(self):
        now = AT + timedelta(minutes=1)
        rows = conditions.official_race_conditions(**self.inventory())
        reg = '013005'
        bootstrap = conditions.archive_slice(start_day='2029-12-01', end_day='2030-01-12',
            archive_sha256s=['d' * 64, 'c' * 64], registry_sha256='e' * 64,
            observations=[(reg, 'F1', 'SEMI_FINAL', 1)])
        previous = conditions.result_slice('2030-01-14', 'a' * 64,
                                           [(reg, 'F1', 'SEMI_FINAL', 4)])
        args = dict(day=DAY, published_at=now, registered_races=3,
                    calendar_sha256='b' * 64, races=rows, history_archive=bootstrap)
        packet = conditions.build_day(**args, past_results=[previous])
        self.assertEqual(packet['history']['scope'], conditions.MIXED_SCOPE)
        self.assertEqual((packet['history']['start_day'], packet['history']['end_day']),
                         ('2029-12-01','2030-01-14'))
        self.assertEqual(packet['history']['condition_matched_finishes'], 2)
        with self.assertRaises(ValueError):
            conditions.build_day(**args, past_results=[dict(previous, day='2030-01-12')])
