"""Synthetic official layouts: missing exhibition never removes an entrant."""
from hashlib import sha256
import importlib
import re
import unittest

from race_ai.boat_official_program import parse_program
from race_ai.boat_observation_context import parse_beforeinfo
from tests.test_boat_official_program import page, source_url, DAY
from tests.test_boat_observation_context import frame, before_table, starts, weather, ROSTER, url, CAPTURED

try:
    active = importlib.import_module('race_ai.boat_active_exhibition')
except ModuleNotFoundError:
    active = None


def program(*, lanes=(1, 2, 3, 4, 5, 6), withdrawn=(), unknown_withdrawn=False):
    options = {lane: dict(name=f'選手 {lane}') for lane in lanes}
    if unknown_withdrawn:
        for lane in withdrawn:
            options[lane]['identities'] = False
    raw = page(lanes=lanes, withdrawn=withdrawn, row_options=options, sg=True)
    return parse_program(raw, day=DAY, venue='12', race_no=12, source_url=source_url(),
                         captured_at='2030-04-01T17:59:00+09:00')


def main_table(*, lanes=(1, 2, 3, 4, 5, 6), missing=()):
    table = before_table(display='6.82', tilt='-0.5', adjustment='1.5')
    for body in re.findall(r'<tbody>.*?</tbody>', table, re.S):
        lane = int(re.search(r'is-boatColor([1-6])', body).group(1))
        if lane not in lanes:
            table = table.replace(body, '')
        elif lane in missing:
            table = table.replace(body, body.replace('<td rowspan="4">6.82</td>',
                                                    '<td rowspan="4">&nbsp;</td>'))
    return table


def start_table(*, lanes=(1, 2, 3, 4, 5, 6), flying=False):
    table = starts(populated=True, flying=flying)
    for row in re.findall(r'<tr>.*?</tr>', table, re.S):
        lane = re.search(r'img_boat2_([1-6])', row)
        if lane and int(lane.group(1)) not in lanes:
            table = table.replace(row, '')
    return table


class ActiveExhibitionTests(unittest.TestCase):
    def parse(self, raw, source=None, **kwargs):
        self.assertIsNotNone(active, 'owned active exhibition adapter is missing')
        return active.parse_active_beforeinfo(raw, program=source or program(),
            source_url=kwargs.pop('source_url', url()), captured_at=kwargs.pop('captured_at', CAPTURED), **kwargs)

    def test_full_six_observed_context_matches_existing_values_and_provenance(self):
        raw = frame(main_table()+starts(populated=True, flying=True)+weather())
        out = self.parse(raw)
        old = parse_beforeinfo(raw, source_url=url(), captured_at=CAPTURED,
                               expected_race_id='20300401-12-12', roster=ROSTER)
        self.assertEqual(out['context'], old)
        self.assertEqual(out['race_id'], '20300401-12-12')
        self.assertEqual(out['closed_at'], '2030-04-01T20:30:00+09:00')
        self.assertEqual(out['status'], 'AVAILABLE')
        self.assertEqual(out['active_lanes'], [1, 2, 3, 4, 5, 6])
        self.assertEqual(out['withdrawn_lanes'], [])
        self.assertEqual(out['source_sha256'], sha256(raw).hexdigest())
        self.assertTrue(out['body_identity_verified'])
        self.assertTrue(out['eligible_pre_race'])
        self.assertEqual(out['data']['weather'], old['weather'])
        first = out['data']['boats'][0]
        self.assertEqual((first['lane'], first['racer_registration_id'], first['display_time']), (1, '4001', 6.82))
        self.assertEqual(first['preview_st_status'], 'F')
        self.assertIsNone(first['preview_st'])

    def test_explicit_withdrawal_excludes_blank_time_or_previous_display(self):
        for missing in ((6,), ()):
            source = program(withdrawn=(6,))
            raw = frame(main_table(missing=missing)+starts(populated=True))
            out = self.parse(raw, source)
            self.assertEqual(out['status'], 'AVAILABLE')
            self.assertEqual(out['active_lanes'], [1, 2, 3, 4, 5])
            self.assertEqual(out['withdrawn_lanes'], [6])
            self.assertEqual([r['lane'] for r in out['data']['boats']], [1, 2, 3, 4, 5])
            self.assertEqual([r['lane'] for r in out['context']['participants']], [1, 2, 3, 4, 5])

    def test_missing_active_display_is_pending_even_with_observed_start(self):
        source = program(withdrawn=(6,))
        out = self.parse(frame(main_table(missing=(3, 6))+starts(populated=True)), source)
        self.assertEqual(out['status'], 'PENDING')
        self.assertEqual(out['active_lanes'], [1, 2, 3, 4, 5])
        self.assertEqual(out['withdrawn_lanes'], [6])
        row = next(r for r in out['data']['boats'] if r['lane'] == 3)
        self.assertIsNone(row['display_time'])
        self.assertEqual(row['preview_st'], .12)

    def test_explicit_withdrawal_ignores_its_stale_start_text(self):
        source = program(withdrawn=(6,))
        grid = starts(populated=True).replace(
            'img_boat2_6.png"/><span class="table1_boatImage1Time">.12',
            'img_boat2_6.png"/><span class="table1_boatImage1Time">欠場（展示中止）')
        out = self.parse(frame(main_table()+grid), source)
        self.assertEqual(out['status'], 'AVAILABLE')
        self.assertEqual([row['lane'] for row in out['data']['boats']], [1, 2, 3, 4, 5])

    def test_three_noncontiguous_physical_lanes_keep_printed_start_position(self):
        source = program(withdrawn=(2, 4, 5), unknown_withdrawn=True)
        raw = frame(main_table(lanes=(1, 3, 6))+start_table(lanes=(1, 3, 6)))
        out = self.parse(raw, source)
        self.assertEqual(out['status'], 'AVAILABLE')
        self.assertEqual(out['active_lanes'], [1, 3, 6])
        self.assertEqual(out['withdrawn_lanes'], [2, 4, 5])
        self.assertEqual([r['racer_registration_id'] for r in out['data']['boats']], ['4001', '4003', '4006'])
        first = out['context']['participants'][0]
        self.assertEqual(first['exhibition_source_position_number'], 2)
        self.assertIsNone(first['exhibition_course'])
        for row in out['data']['boats']:
            self.assertIsNone(row['preview_course'])
            self.assertIsNone(row['actual_course'])

    def test_official_three_row_program_binds_exactly_its_active_rows(self):
        source = program(lanes=(1, 3, 6))
        raw = frame(main_table(lanes=(1, 3, 6))+start_table(lanes=(1, 3, 6)))
        out = self.parse(raw, source)
        self.assertEqual(out['status'], 'AVAILABLE')
        self.assertEqual(out['active_lanes'], [1, 3, 6])
        self.assertEqual(out['withdrawn_lanes'], [])

    def test_empty_start_grid_or_missing_start_is_optional_and_never_numeric_zero(self):
        for grid in (starts(), start_table(lanes=())):
            out = self.parse(frame(main_table()+grid))
            self.assertEqual(out['status'], 'AVAILABLE')
            self.assertTrue(all(r['preview_st'] is None and r['preview_st_status'] == 'PENDING'
                                for r in out['data']['boats']))
        raw = frame(main_table()+start_table(lanes=(1, 3, 6), flying=True))
        out = self.parse(raw)
        self.assertEqual(out['status'], 'AVAILABLE')
        self.assertEqual(out['data']['boats'][0]['preview_st_status'], 'F')
        self.assertEqual(out['data']['boats'][1]['preview_st_status'], 'PENDING')

    def test_wrong_body_profile_program_cutoff_and_provenance_fail_closed(self):
        raw = frame(main_table()+starts(populated=True))
        bad_bodies = (raw.replace(b'jcd=12', b'jcd=13'),
                      raw.replace(b'hd=20300401', b'hd=20300402'),
                      raw.replace(b'toban=4001', b'toban=4999', 1),
                      raw.replace(b'20:30', b'20:31'),
                      raw.replace(b'img_boat2_6.png', b'img_boat2_1.png'))
        for body in bad_bodies:
            with self.subTest(body=body[-40:]), self.assertRaises(ValueError):
                self.parse(body)
        for key, value in (('body_identity_verified', False), ('source_sha256', 'invalid'),
                           ('race_id', '20300401-12-11')):
            source = program()
            source[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.parse(raw, source)
        with self.assertRaises(ValueError):
            self.parse(raw, captured_at='2030-04-01T17:58:00+09:00')

    def test_unlisted_preview_lane_and_duplicate_registration_are_rejected(self):
        source = program(lanes=(1, 3, 6))
        with self.assertRaises(ValueError):
            self.parse(frame(main_table()+starts(populated=True)), source)
        source = program()
        source['boats'][1]['racer_registration_id'] = '4001'
        with self.assertRaises(ValueError):
            self.parse(frame(main_table()+starts()), source)

    def test_late_retained_capture_remains_observed_but_not_pre_cutoff(self):
        out = self.parse(frame(main_table()+starts(populated=True)),
                         captured_at='2030-04-02T08:00:00+09:00')
        self.assertEqual(out['status'], 'AVAILABLE')
        self.assertFalse(out['eligible_pre_race'])


if __name__ == '__main__':
    unittest.main()
