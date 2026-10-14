"""Synthetic structure fixtures, not official race observations."""
import hashlib
import unittest
from datetime import date

from race_ai.core import SourceError
from race_ai.official_racelist_adapter import parse_official_racelist, endpoint

DAY = date(2026, 10, 15)
CAPTURED = '2026-10-15T07:00:00+09:00'


def fixture(day=DAY, venue='18', number=1):
    heads = ''.join(f'<th{(" class=\"is-thColor2\"" if n != number else "")}>'
                    f'<a href="/owpc/pc/race/racelist?rno={n}&amp;jcd={venue}&amp;hd={day:%Y%m%d}">{n}R</a></th>'
                    for n in range(1, 13))
    times = ''.join(f'<td>{8 + n // 3:02d}:{n * 3:02d}</td>' for n in range(1, 13))
    rows = []
    for lane in range(1, 7):
        registration = 4000 + lane
        profile = f'/owpc/pc/data/racersearch/profile?toban={registration}'
        cells = (f'<td class="is-boatColor{lane}" rowspan="4">{lane}</td>'
                 f'<td rowspan="4"><a href="{profile}"><img></a></td>'
                 f'<td rowspan="4"><div>{registration} / <span>A2</span></div>'
                 f'<div class="is-fs18 is-fBold"><a href="{profile}">選手 {lane}</a></div><div>支部/出身</div></td>'
                 '<td>F0<br>L0<br>0.17</td><td>5.25<br>30.00<br>50.00</td>'
                 '<td>5.50<br>35.00<br>55.00</td>'
                 f'<td>{lane + 10}<br>30.00<br>50.00</td><td>{lane + 20}<br>40.00<br>60.00</td>')
        rows.append(f'<tbody><tr>{cells}</tr><tr><td>history</td></tr></tbody>')
    tabs = f'<div class="tab3"><a href="/owpc/pc/race/beforeinfo?rno={number}&amp;jcd={venue}&amp;hd={day:%Y%m%d}">直前情報</a></div>'
    return ('<div class="contentsFrame1_inner"><div class="table1 h-mt10"><table>'
            '<thead><tr><th colspan="2">レース</th>' + heads + '</tr></thead>'
            '<tbody><tr><td colspan="2">締切予定時刻</td>' + times + '</tr></tbody></table></div>'
            + tabs + '<div class="table1 is-tableFixed__3rdadd"><table>'
            '<thead><tr><th>枠</th><th>ボートレーサー</th><th>全国</th><th>当地</th><th>モーター</th><th>ボート</th></tr></thead>'
            + ''.join(rows) + '</table></div></div>')


class OfficialRaceListTests(unittest.TestCase):
    def parse(self, html=None, **kwargs):
        return parse_official_racelist((html or fixture()).encode(), day=DAY,
            venue='18', race_no=1, source_url=endpoint(DAY, '18', 1), captured_at=CAPTURED, **kwargs)

    def test_verified_fields_and_content_hash_come_from_same_body(self):
        data = self.parse()
        self.assertEqual(data['race_id'], '20261015-18-01')
        self.assertEqual(data['closed_at'], '2026-10-15T08:03:00+09:00')
        self.assertEqual(data['source_sha256'], hashlib.sha256(fixture().encode()).hexdigest())
        first = data['boats'][0]
        self.assertEqual((first['lane'], first['racer_registration_id'], first['motor_no'], first['boat_no']), (1, '4001', 11, 21))
        self.assertEqual(first['average_st'], 0.17)
        self.assertEqual(first['national_win_rate'], 5.25)
        self.assertTrue(first['verified_source'])
        self.assertFalse(data['redistribution_authorized'])

    def test_url_identity_date_venue_and_race_number_are_strict(self):
        for url in ('https://evil.example/', endpoint(DAY, '17', 1), endpoint(DAY, '18', 2),
                    endpoint(date(2026, 10, 14), '18', 1), endpoint(DAY, '18', 1) + '&rno=1'):
            with self.subTest(url=url), self.assertRaises(SourceError):
                parse_official_racelist(fixture().encode(), day=DAY, venue='18', race_no=1,
                    source_url=url, captured_at=CAPTURED)

    def test_detached_navigation_cannot_date_a_stale_or_other_race_table(self):
        for bad in (fixture(date(2026, 10, 14)), fixture(venue='17'), fixture(number=2)):
            with self.subTest(), self.assertRaises(SourceError):
                self.parse('<nav>' + fixture() + '</nav>' + bad)

    def test_body_identity_swaps_and_incomplete_lanes_fail_closed(self):
        html = fixture()
        for bad in (html.replace('>4001<', '>4999<'),
                    html.replace('4001 /', '4999 /'),
                    html.replace('toban=4001', 'toban=4999', 1),
                    html.replace('is-boatColor6', 'is-boatColor1'),
                    html.replace('<td>11<br>', '<td>0<br>'),
                    html.replace('<td>21<br>', '<td>欠場<br>'),
                    html.replace('>6</td>', '></td>'),
                    html.replace('08:03', '25:00'),
                    html.replace('</tbody>', '', 1),
                    html.replace('選手 1', ''),
                    '<p>データがありません。</p>'):
            if bad == html:
                continue
            with self.subTest(), self.assertRaises(SourceError):
                self.parse(bad)

    def test_duplicate_racer_motor_or_boat_is_rejected(self):
        for old, new in (('4002', '4001'), ('<td>12<br>', '<td>11<br>'), ('<td>22<br>', '<td>21<br>')):
            with self.subTest(old=old), self.assertRaises(SourceError):
                self.parse(fixture().replace(old, new))

    def test_optional_missing_statistics_stay_unknown(self):
        data = self.parse(fixture().replace('0.17', '-').replace('5.25', '-'))
        self.assertIsNone(data['boats'][0]['average_st'])
        self.assertIsNone(data['boats'][0]['national_win_rate'])

    def test_capture_requires_timezone_and_matching_jst_date(self):
        for timestamp in ('2026-10-15T07:00:00', '2026-10-14T07:00:00+09:00', 'invalid'):
            with self.subTest(timestamp=timestamp), self.assertRaises(SourceError):
                parse_official_racelist(fixture().encode(), day=DAY, venue='18', race_no=1,
                    source_url=endpoint(DAY, '18', 1), captured_at=timestamp)

