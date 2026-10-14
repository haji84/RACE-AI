import hashlib
import unittest
from datetime import date

from race_ai.core import SourceError
from race_ai.official_day_schedule import parse_day_schedule, endpoint, merge_schedule_programs

DAY = date(2026, 10, 15)
STAMP = '2026-10-15T03:06:00+09:00'


def fixture(day=DAY, venues=('02', '04')):
    rows = []
    for code in venues:
        rows.append(f'<tbody><tr><td><img src="/static_extra/pc/images/text_place1_{code}.png"></td>'
            f'<td>1R発売開始前</td><td><a href="/owpc/pc/race/raceindex?jcd={code}&amp;hd={day:%Y%m%d}">合成開催</a></td>'
            f'<td><a href="/owpc/pc/race/racelist?rno=1&amp;jcd={code}&amp;hd={day:%Y%m%d}">出走表</a></td>'
            '</tr><tr></tr></tbody>')
    return ('<div class="contentsFrame1_inner"><span class="title2_mainLabel">'
            f'{day.month}月{day.day}日のレース情報</span><p class="btnGroup3_refreshBtn">'
            f'<a href="/owpc/pc/race/index?hd={day:%Y%m%d}">更新</a></p><table>'
            '<thead><tr><th>ボート レース場</th><th>進行状況/締切予定時刻/投票</th>'
            '<th>グレード/開催時間帯/タイトル</th><th>開催期間/日次</th><th>レース別情報</th></tr></thead>'
            + ''.join(rows) + '</table><ul class="notes1"><li>締切予定時刻は締切5分前より赤く表示されます。</li></ul></div>').encode()


class OfficialScheduleTests(unittest.TestCase):
    def parse(self, raw=None):
        return parse_day_schedule(raw or fixture(), day=DAY, source_url=endpoint(DAY), observed_at=STAMP)

    def test_complete_same_date_index_identifies_active_and_not_listed_venues(self):
        result = self.parse()
        self.assertEqual(result['active_venues'], ['02', '04'])
        self.assertEqual(len(result['venues']), 24)
        self.assertEqual(result['source_sha256'], hashlib.sha256(fixture()).hexdigest())
        self.assertEqual(result['venues'][17]['status'], 'NO_EVENT')
        self.assertTrue(result['venues'][17]['schedule_verified'])
        self.assertEqual(result['venues'][17]['schedule_source_sha256'], result['source_sha256'])

    def test_stale_detached_duplicate_mismatched_and_truncated_tables_fail(self):
        for raw in (fixture(DAY.replace(day=14)), fixture() + fixture(),
                    fixture().replace(b'text_place1_02', b'text_place1_03'),
                    fixture().replace(b'jcd=02', b'jcd=03', 1),
                    fixture().replace(b'</tbody>', b'', 1),
                    fixture().replace(b'notes1', b'unknown'),
                    fixture(venues=('02', '02')), fixture(venues=())):
            with self.subTest(), self.assertRaises(SourceError):
                self.parse(raw)

    def test_schedule_merge_preserves_healthy_missing_and_explicit_error_states(self):
        schedule = self.parse()
        programs = dict(date_jst=DAY.isoformat(), source_url='https://example.org/B', source_sha256='a' * 64,
            first_observed_at=STAMP, venues=[dict(venue='02', races=[dict(race_id='20261015-02-01',
            boats=[dict(lane=i, racer_registration_id=str(4000+i), motor_no=i) for i in range(1,7)])])])
        result = merge_schedule_programs(schedule, programs, errors={'04': 'SOURCE_UNAVAILABLE'})
        self.assertEqual(result['venues'][1]['status'], 'PARTIAL')
        self.assertEqual(result['venues'][3]['status'], 'ERROR')
        self.assertEqual(result['venues'][17]['status'], 'NO_EVENT')
        self.assertEqual(result['races'], 1)
        self.assertFalse(result['redistribution_authorized'])
        self.assertEqual(len(result['sources']), 2)
        programs['venues'].append(dict(venue='18', races=[]))
        with self.assertRaises(SourceError):
            merge_schedule_programs(schedule, programs)
