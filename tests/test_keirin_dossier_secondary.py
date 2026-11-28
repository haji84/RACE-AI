from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import unittest

from race_ai import keirin_dossier_secondary as secondary
from tests.test_keirin_result_unread_racecard import KDREAMS_URL, RACE_ID, kdreams_card


DAY = '2030-01-15'
SOURCE_CUTOFF = DAY + 'T15:10:00+09:00'
OFFICIAL_CUTOFF = DAY + 'T15:12:00+09:00'
CAPTURED = DAY + 'T16:00:00+09:00'
PUBLISHED = DAY + 'T16:05:00+09:00'
CARS = (1, 2, 4, 6, 7)
COMMENTS = {1:'自力で',2:'例示選手７さんへ',4:'要約対象外の私的記述',6:'—',7:'単騎で'}


def saved_card():
    raw = kdreams_card(cars=CARS,formation=()).decode()
    headers = ('S','B','逃','捲','差','マ','1 着','2 着','3 着','着 外','勝 率','2連 対率','3連 対率')
    raw = raw.replace('<th>例</th>' * 13, ''.join(f'<th>{header}</th>' for header in headers))
    numbers = ('5','7','-','2','1','0','10','4','0','10','25.6%','30.0%','32.0%')
    raw = raw.replace('<td>99</td>' * 13, ''.join(f'<td>{value}</td>' for value in numbers))
    raw = raw.replace('</h2></div></div>',
                      '</h2></div><dl class="time"><dt>締切</dt><dd>15:10</dd></dl></div>')
    comments = '<table class="racecard_table none"><tr><th>選手コメント</th></tr>'
    for number, comment in COMMENTS.items():
        comments += (f'<tr><td class="num">{number}</td><td class="rider">例示選手{number}</td>'
                     f'<td class="comment">{comment}</td><td class="last_result">確定着順私的記述</td></tr>')
    return raw.replace('</tbody></table>', '</tbody></table>' + comments + '</table>', 1).encode()


def receipt(raw):
    return {'url':KDREAMS_URL,'status':200,'bytes':len(raw),'bytes_sha256':sha256(raw).hexdigest(),
            'captured_at':CAPTURED}


def performance_card(*, challenge=False):
    def table(title, labels, counts):
        headers = [(title,), *labels]
        heading_rows = ''.join('<tr>' + ''.join(f'<th>{value}</th>' for value in row) + '</tr>'
                               for row in headers)
        data_rows = ''.join(
            f'<tr><td class="num">{number}</td><td class="rider">例示選手{number}</td>'
            + '<td>0</td>' * 6 + '<td>90.25</td>'
            + ''.join(f'<td>{count if number == 1 else 0}</td>' for count in counts) + '</tr>'
            for number in CARS)
        return f'<table class="racecard_table none">{heading_rows}{data_rows}</table>'

    order = ('1着','2着','3着','着外')
    groups = ('決勝','準決','選抜','予選') if challenge else ('決勝','特選','準決','予選')
    offset = 4 * groups.index('準決')
    annual = table('年間勝利度数', [groups, order * 4],
                   (0,) * offset + (6,3,1,1) + (0,) * (12-offset))
    venue = table('当所5年', [order], (5,2,2,4))
    return saved_card().replace(b'</tbody></table>', b'</tbody></table>' + (annual + venue).encode(), 1)


def roster():
    return dict(race_id=RACE_ID,riders=[
        dict(number=number,name=f'例示選手 {number}',registration=str(100000+number))
        for number in CARS
    ])


def project(raw=None, *, entrants=None):
    raw = saved_card() if raw is None else raw
    return secondary.project_card(raw,receipt(raw),roster() if entrants is None else entrants,
                                  official_cutoff_at=OFFICIAL_CUTOFF,now=PUBLISHED)


def packet(rows):
    registry = {'schema':secondary.context.STARTERS_SCHEMA,'day':DAY,'published_at':CAPTURED,
                'races':[roster(),{**roster(),'race_id':RACE_ID[:-1]+'4'}]}
    return secondary.build_day(registry,rows,published_at=PUBLISHED)


class SecondaryDossierTest(unittest.TestCase):
    def test_checked_performance_supplement_keeps_proof_and_counts(self):
        raw = performance_card()
        proof = {**receipt(raw),'url':KDREAMS_URL+'?pageType=yoso'}
        performance = secondary.project_performance(raw,proof,roster(),now=PUBLISHED)
        self.assertEqual(performance['riders'][0],
                         dict(number=1,registration='100001',semi=[6,3,1,1],venue=[5,2,2,4]))
        self.assertIsNone(performance['riders'][1]['semi'])
        self.assertEqual(performance['source_sha256'],proof['bytes_sha256'])
        row = {**project(),'performance':performance}
        self.assertEqual(packet([row])['races'][0]['performance'],performance)
        for field,value in [('source_at',DAY+'T16:06:00+09:00'),('source_url',KDREAMS_URL+'?pageType=odds')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                packet([{**row,'performance':{**performance,field:value}}])
        mismatched = deepcopy(row)
        mismatched['performance']['riders'][0]['registration'] = '100009'
        with self.assertRaisesRegex(ValueError,'PERFORMANCE_ROSTER'):
            packet([mismatched])

    def test_performance_accepts_published_race_urls_and_requires_exact_table_meanings(self):
        raw = performance_card()
        def capture(body, url):
            return secondary.project_performance(body,{**receipt(body),'url':url},roster(),now=PUBLISHED)

        tab = KDREAMS_URL+'?pageType=showResult'
        self.assertEqual(capture(raw,tab)['riders'][0]['venue'],[5,2,2,4])
        self.assertEqual(capture(raw,KDREAMS_URL)['riders'][0]['venue'],[5,2,2,4])
        self.assertEqual(capture(performance_card(challenge=True),KDREAMS_URL)['riders'][0]['semi'],[6,3,1,1])
        with self.assertRaisesRegex(ValueError,'PERFORMANCE_URL'):
            capture(raw,tab+'&pageType=yoso')
        with self.assertRaisesRegex(ValueError,'PERFORMANCE_HEADINGS'):
            capture(raw.replace('<th>準決</th>'.encode(),'<th>一般</th>'.encode()),tab)
        with self.assertRaisesRegex(ValueError,'PERFORMANCE_COUNTS'):
            capture(raw.replace(b'<td>6</td><td>3</td><td>1</td><td>1</td>',
                                b'<td>601</td><td>3</td><td>1</td><td>1</td>'),tab)

    def test_admits_sparse_registered_roster_and_keeps_two_cutoffs_and_capture_time_distinct(self):
        raw = saved_card()
        source = secondary.source_card(raw,receipt(raw),RACE_ID,now=PUBLISHED)
        self.assertEqual(source['riders'][0]['name'],'例示選手1')
        row = project(raw)
        self.assertEqual(datetime.fromisoformat(row['cutoff_at']),datetime.fromisoformat(OFFICIAL_CUTOFF))
        self.assertEqual(datetime.fromisoformat(row['source_cutoff_at']),datetime.fromisoformat(SOURCE_CUTOFF))
        self.assertEqual(datetime.fromisoformat(row['source_at']),datetime.fromisoformat(CAPTURED))
        self.assertEqual([person['number'] for person in row['riders']],list(CARS))
        self.assertEqual(row['riders'][0]['stats'],{
            'competition_points':90.25,'win_rate_percent':25.6,'home_count':None,'back_count':7,
            'escape_count':None,'makuri_count':2,'difference_count':1,'mark_count':0,
        })
        self.assertEqual(row['riders'][1]['comment']['target_car'],7)
        self.assertEqual(row['riders'][2]['comment'],{'state':'UNINTERPRETED'})
        self.assertEqual(row['riders'][3]['comment'],{'state':'NOT_PUBLISHED'})
        for output in (source,row):
            self.assertNotIn('私的記述',json.dumps(output,ensure_ascii=False))

    def test_requires_the_whole_registered_roster_exactly(self):
        different = roster()
        different['riders'][-1]['name'] = '同じ車番の別選手'
        with self.assertRaisesRegex(ValueError,'SECONDARY_ROSTER'):
            project(entrants=different)
        different = roster()
        different['riders'].pop()
        with self.assertRaisesRegex(ValueError,'SECONDARY_ROSTER'):
            project(entrants=different)
        changed = saved_card().replace('例示選手7</td>'.encode(),'同じ車番の別選手</td>'.encode())
        with self.assertRaisesRegex(ValueError,'SECONDARY_COMMENT_ROSTER'):
            project(changed)

    def test_tampering_with_receipt_domain_clock_or_headings_is_held(self):
        raw = saved_card()
        for overrides, reason in [
            ({'bytes_sha256':'a'*64}, 'RECEIPT'),
            ({'url':KDREAMS_URL+'?pageType=result'}, 'ORDINARY_URL'),
            ({'captured_at':DAY+'T16:06:00+09:00'}, 'RECEIPT_CLOCK'),
        ]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError,reason):
                secondary.source_card(raw,{**receipt(raw),**overrides},RACE_ID,now=PUBLISHED)
        for changed, reason in [
            (raw.replace(b'<th>B</th>',b'<th>S2</th>'), 'STATS_HEADINGS'),
            (raw.replace(b'>15:10</dd>',b'>25:00</dd>'), 'CUTOFF'),
        ]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError,reason):
                project(changed)

    def test_day_coverage_and_exact_public_validator(self):
        row = project()
        day = packet([row])
        self.assertEqual(day['coverage'],dict(registered_races=2,verified_races=1,registered_riders=10,
            verified_riders=5,comments_confirmed=3,comments_held=1,comments_missing=6))
        self.assertEqual(secondary.checked_day(json.loads(json.dumps(day))),day)
        changed = deepcopy(day)
        changed['races'][0]['riders'][0]['stats']['home_count'] = 0
        with self.assertRaisesRegex(ValueError,'STATS_FIELDS'):
            secondary.checked_day(changed)
        changed = deepcopy(day)
        changed['coverage']['comments_missing'] = 7
        with self.assertRaisesRegex(ValueError,'COVERAGE'):
            secondary.checked_day(changed)
        changed = deepcopy(row)
        changed['riders'][1]['registration'] = '999999'
        with self.assertRaisesRegex(ValueError,'REGISTRY_ROSTER'):
            packet([changed])


if __name__ == '__main__':
    unittest.main()
