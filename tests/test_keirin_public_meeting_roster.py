from datetime import datetime, timezone
import unittest

from race_ai import keirin_public_meeting_roster as roster


DAY = '2026-11-29'
MEETING = 'https://keirin.kdreams.jp/hiratsuka/racecard/35202611270300/'
DETAIL = 'https://keirin.kdreams.jp/hiratsuka/racedetail/3520261127030001/'
CALENDAR = 'https://keirin.kdreams.jp/kaisai/2026/11/29/'
AT = datetime(2026, 11, 28, 15, 30, tzinfo=timezone.utc)


def page(url, content):
    return (f'<html><head><link rel="canonical" href="{url}"></head>'
            f'<body>{content}</body></html>').encode()


def calendar(url=MEETING):
    return page(CALENDAR, f'<h2>本日2026年11月29日 開催一覧</h2><a href="{url}">出走表</a>')


def meeting(link=DETAIL, names=None, extra=''):
    names = ['例選手甲', '例選手乙', '例選手丙', '例選手丁', '例選手戊'] if names is None else names
    header = ''.join(f'<th>{name}</th>' for name in
                     ('予想','好気合','総評','枠番','車番','選手名','府県','年齢','期別','級班','脚質'))
    rows = ''.join(f'<tr class="n{i}"><td></td><td></td><td></td><td></td>'
                   f'<td class="num">{i}</td><td class="rider">{name}</td><td>神奈川</td>'
                   '<td>26</td><td>123</td><td>A1</td><td>逃</td></tr>'
                   for i, name in enumerate(names, 1))
    blank = '<tr class="missing"><td class="num"></td><td class="rider"></td>' + '<td></td>'*5 + '</tr>'
    return page(MEETING, f'<ul class="racecard_list"><li><p class="race"><a href="{link}">'
                         '<span class="num">1R</span><span class="name">Ａ級一般</span></a></p>'
                         '<div class="racecard_list_container"><div class="racecard_table"><table>'
                         f'<tr>{header}</tr>{rows}{blank}{extra}'
                         '</table></div></div></li><li class="page-break"></li></ul>')


class MeetingRosterTest(unittest.TestCase):
    def test_collect_dated_race_and_bind_only_exact_evidence(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return {CALENDAR: calendar(), MEETING: meeting()}[url]

        registrations = roster.registration_lookup([
            ('例 選手甲','神奈川県',123,'012345'),
            ('例選手乙','神奈川',122,'012346'),
            ('例選手丙','大阪府',123,'012347'),
            ('例選手丁','神奈川',123,'012348'),
            ('例選手丁','神奈川',123,'012349'),
        ])
        packet = roster.collect_day(DAY, fetch=fetch, clock=lambda:AT, registrations=registrations)
        self.assertEqual(calls,[CALENDAR,MEETING])
        self.assertEqual(packet['schema'],'RACE_AI_KEIRIN_PUBLIC_REFERENCE_STARTERS_V1')
        race, = packet['races']
        self.assertEqual(race['race_id'],'202611293501')
        self.assertEqual(race['source_url'],MEETING)
        self.assertEqual([r['registration'] for r in race['riders']],['012345',None,None,None,None])
        self.assertEqual(race['riders'][0],dict(number=1,name='例選手甲',registration='012345',
                                              region='神奈川',cohort=123,style='逃'))

    def test_reject_cross_origin_and_wrong_dated_link(self):
        for forged in (MEETING.replace('https://','https://evil.invalid@'),
                       MEETING+'?pageType=anything',MEETING.replace('270300','270200')):
            with self.subTest(forged=forged), self.assertRaisesRegex(ValueError,'MEETINGS'):
                roster.parse_calendar(calendar(forged),day=DAY)
        for forged in (DETAIL+'?pageType=yoso',DETAIL.replace('hiratsuka','seibuen')):
            with self.subTest(forged=forged), self.assertRaisesRegex(ValueError,'DETAIL'):
                roster.parse_meeting(meeting(forged),day=DAY,url=MEETING,observed_at=AT)

    def test_reject_nonempty_placeholder_and_unpublished_rows(self):
        malformed = '<tr class="missing"><td class="num">6</td><td class="rider">例選手己</td>' + '<td></td>'*5 + '</tr>'
        with self.assertRaisesRegex(ValueError,'PLACEHOLDER'):
            roster.parse_meeting(meeting(extra=malformed),day=DAY,url=MEETING,observed_at=AT)
        with self.assertRaisesRegex(ValueError,'ROSTER'):
            roster.parse_meeting(meeting(names=[]),day=DAY,url=MEETING,observed_at=AT)

    def test_exclude_explicit_withdrawal_without_guessing_status(self):
        row = ('<tr class="n6 missing"><td class="num">6</td>'
               '<td class="rider">例選手己<span class="caution">(欠車)</span></td>' + '<td></td>'*5 + '</tr>')
        race, = roster.parse_meeting(meeting(extra=row),day=DAY,url=MEETING,observed_at=AT)
        self.assertEqual([r['number'] for r in race['riders']],[1,2,3,4,5])
        with self.assertRaisesRegex(ValueError,'RIDER_STATUS'):
            roster.parse_meeting(meeting(extra=row.replace('欠車','注意')),day=DAY,url=MEETING,observed_at=AT)
        four = ['例選手甲', '例選手乙', '例選手丙', '例選手丁']
        with self.assertRaisesRegex(ValueError,'ROSTER'):
            roster.parse_meeting(meeting(names=four),day=DAY,url=MEETING,observed_at=AT)
        fifth = row.replace('n6 missing','n5 missing').replace('>6<','>5<')
        race, = roster.parse_meeting(meeting(names=four,extra=fifth),day=DAY,url=MEETING,observed_at=AT)
        self.assertEqual([r['number'] for r in race['riders']],[1,2,3,4])
