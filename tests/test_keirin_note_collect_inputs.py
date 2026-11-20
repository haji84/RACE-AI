"""Invented public-page fixtures only; no provider calls or production keys."""
from contextlib import redirect_stdout
from datetime import datetime,timedelta
from hashlib import sha256
import importlib
import io
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from scripts import keirin_capture_public_two_sources as capture

DAY='2030-01-15'
NOW=datetime.fromisoformat(DAY+'T12:00:00+09:00')
CALENDAR='https://keirin.kdreams.jp/kaisai/2030/01/15/'
MEETING='https://keirin.kdreams.jp/fictional/racecard/98203001150100/'


def rid(number):
    return '2030011598'+f'{number:02d}'


def urls(number):
    return ('https://keirin.netkeiba.com/race/entry/?race_id='+rid(number),
            'https://keirin.kdreams.jp/fictional/racedetail/98203001150100'+f'{number:02d}/')


def net_page(number):
    rows=[]
    for car in range(1,7):
        cells=[str(car),str(car),'',str(car),'EXAMPLE_RIDER_'+str(car),
               str(70+car),'逃' if car%2 else '追','2','3','4',
               '1','1','1','1','2','3','4','5','20.0%','30.0%','40.0%',
               '3.92','例示コメント']
        rows.append('<tr>'+''.join('<td>'+value+'</td>' for value in cells)+'</tr>')
    return ('<html><head><link rel="canonical" href="'+urls(number)[0]+
            '"></head><body><table>'+''.join(rows)+'</table></body></html>').encode()


def kd_page(number,cutoff):
    tables=[[],[],[],[],[],[]]
    for car in range(1,7):
        head='<td class="num">'+str(car)+'</td><td class="rider">'
        rider='EXAMPLE_RIDER_'+str(car)+'<br>例県 / 31 / 99</td>'
        values=['A1','逃' if car%2 else '追','3.92',str(90+car),'8','9',
                '1','2','3','4','5','6','7','8','25.0','35.0','45.0']
        tables[0].append('<tr><td class="tip">◎</td>'+head+rider+
                         ''.join('<td>'+value+'</td>' for value in values)+'</tr>')
        tables[1].append('<tr>'+head+rider+'<td class="comment">例示の方針</td>'
                         '<td class="last_result">過去開催の例示</td></tr>')
        tables[2].append('<tr>'+head+rider+'<td>地域</td><td>例示の近況</td></tr>')
        for index in (4,5):
            tables[index].append('<tr>'+head+rider+'<td>A1</td><td>逃</td>'
                                 '<td>3.92</td><td>91</td><td>11</td><td>22</td></tr>')
    formation=''.join('<span class="icon_p"><span>'+str(car)+
        '</span><span>追込</span></span>'+('<span class="space"></span>' if car%2==0 else '')
        for car in range(1,7))
    return ('<html><head><link rel="canonical" href="'+urls(number)[1]+
        '"></head><body><h1 class="raceinfo_headline">例示競輪 レース詳細</h1>'
        '<div class="racecard_header"><h2 class="title"><span class="status">A級予選</span></h2>'
        '<dl class="time"><dt class="start">発走</dt><dd>13:00</dd>'
        '<dt class="bet">締切</dt><dd>'+cutoff+'</dd></dl>'
        '<dl class="condition"><dd>例示の勝ち上がり条件</dd></dl></div>'
        '<div class="line_position">'+formation+'</div><p class="racereview">例示の見解</p>'+
        ''.join('<table class="racecard_table">'+''.join(rows)+'</table>' for rows in tables)+
        '<p>2030/01/15 12:00現在</p></body></html>').encode()


def pages_for(spec):
    rows=[]
    pages={CALENDAR:('<html><a href="'+MEETING+'">例示競輪</a></html>').encode()}
    for number,cutoff in spec:
        net,kd=urls(number)
        closing='<dt>締切</dt><dd>'+cutoff+'</dd>' if cutoff is not None else ''
        rows.append('<li><div class="header"><dl><dt>発走</dt><dd>13:00</dd>'+closing+
                    '</dl></div><p class="race"><a href="'+kd+'">'
                    '<span class="name">A級予選</span></a></p></li>')
        pages[net]=net_page(number)
        pages[kd]=kd_page(number,cutoff or '13:00')
    pages[MEETING]=('<html><ul class="racecard_list">'+''.join(rows)+
                    '</ul><a href="/fictional/raceresult/not-an-input/">結果</a></html>').encode()
    return pages


class NoteInputCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.root.chmod(0o700)
        self.calls=[]
        self.pages=pages_for([(1,'13:00'),(2,'12:12'),(3,'11:59'),(4,None)])

    def api(self):
        try:
            return importlib.import_module('scripts.keirin_note_collect_inputs')
        except ModuleNotFoundError:
            self.fail('The private owner input collector is not implemented')

    def fetch(self,url):
        self.calls.append(url)
        return self.pages[url]

    def collect(self,**kwargs):
        return self.api().collect_day(day_jst=DAY,private_root=self.root,
            fetch=self.fetch,clock=lambda:NOW,model_source_commit='a'*40,**kwargs)

    def documents(self,result):
        folder=Path(result['site_root'])/'data'/DAY
        return (json.loads((folder/'races.json').read_bytes()),
                json.loads((folder/'reference_AB.json').read_bytes()),
                json.loads((folder/'manifest.json').read_bytes()))

    def test_priority_collection_preserves_source_values_and_research_only_outputs(self):
        result=self.collect()
        races,refs,manifest=self.documents(result)
        self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2),*urls(1)])
        self.assertEqual(result['safe_report']['captured_race_ids'],[rid(2),rid(1)])
        self.assertEqual(result['safe_report']['priority_window_race_ids'],[rid(2)])
        self.assertEqual(result['safe_report']['past_cutoff_races'],1)
        self.assertEqual(result['safe_report']['missing_cutoff_hint_races'],1)
        first=races['races'][0]
        self.assertEqual(first['race_id'],rid(2))
        self.assertEqual(first['riders'][0]['score'],91)
        self.assertEqual(first['riders'][0]['H'],3)
        self.assertEqual(first['riders'][0]['comment'],'例示の方針')
        self.assertEqual(first['riders'][0]['recent_meets'],['例示の近況'])
        self.assertEqual(refs[0]['input']['riders'][0]['competition_points'],71)
        self.assertEqual(refs[0]['input']['riders'][0]['recent_form_score'],0.2)
        self.assertIs(refs[0]['output']['formal_model_promoted'],False)
        self.assertFalse(result['safe_report']['national_universe_verified'])
        self.assertFalse(result['safe_report']['formal_model_admission'])
        self.assertFalse((Path(result['site_root'])/'data'/DAY/'forecasts.json').exists())
        for receipt in manifest['source_receipts']:
            raw=self.pages[receipt['url']]
            self.assertEqual(receipt['bytes_sha256'],sha256(raw).hexdigest())
            self.assertEqual(receipt['captured_at'],NOW.astimezone(self.api().UTC).isoformat())
            self.assertEqual((self.root/'raw'/(receipt['bytes_sha256']+'.html')).read_bytes(),raw)
        self.assertEqual(stat.S_IMODE((Path(result['site_root'])/'data'/DAY/'races.json').stat().st_mode),0o600)

    def test_previously_collected_inputs_refresh_only_in_unrecorded_priority_window(self):
        self.pages=pages_for([(1,'13:00'),(2,'12:12'),(3,'12:11')])
        result=self.collect(already_captured_ids=(rid(1),rid(2),rid(3)),
                            priority_captured_ids=(rid(3),))
        self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2)])
        self.assertEqual(result['safe_report']['captured_race_ids'],[rid(2)])
        self.assertEqual(result['safe_report']['already_captured_races_skipped'],2)

    def test_priority_refresh_includes_ten_and_fifteen_minute_boundaries(self):
        self.pages=pages_for([(1,'12:16'),(2,'12:15'),(3,'12:10'),(4,'12:09')])
        result=self.collect(already_captured_ids=tuple(rid(n) for n in range(1,5)))
        self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(3),*urls(2)])
        self.assertEqual(result['safe_report']['priority_window_race_ids'],[rid(3),rid(2)])

    def test_every_new_future_race_is_processed_without_an_eight_race_limit(self):
        self.pages=pages_for([(number,'13:00') for number in range(1,10)])
        result=self.collect()
        races,refs,_=self.documents(result)
        self.assertEqual(len(races['races']),9)
        self.assertEqual(len(refs),9)
        self.assertEqual(len(result['safe_report']['captured_race_ids']),9)
        self.assertEqual(len(self.calls),20)

    def test_every_published_meeting_is_inspected_without_a_twenty_meeting_limit(self):
        self.pages=pages_for([(1,'13:00')])
        meetings=[]
        for number in range(20):
            url=('https://keirin.kdreams.jp/fictional'+f'{number:02d}'+
                 '/racecard/'+f'{number:02d}'+'203001150100/')
            meetings.append(url)
            self.pages[url]=b'<html><p>No linked race details in this fixture</p></html>'
        self.pages[CALENDAR]=('<html>'+''.join('<a href="'+url+'">example</a>'
            for url in [*meetings,MEETING])+'</html>').encode()
        result=self.collect()
        self.assertEqual(result['safe_report']['captured_race_ids'],[rid(1)])
        self.assertEqual(sum('/racecard/' in url for url in self.calls),21)

    def test_denial_stops_pairs_and_persists_existing_private_stop_format(self):
        original=self.fetch
        def deny(url):
            if url==urls(2)[0]:
                self.calls.append(url)
                raise capture.SourceCaptureError('PROVIDER_DENIED_OR_RATE_LIMITED_STOP')
            return original(url)
        self.fetch=deny
        result=self.collect()
        self.assertEqual(self.calls,[CALENDAR,MEETING,urls(2)[0]])
        self.assertEqual(result['safe_report']['public_page_requests'],3)
        self.assertTrue(result['safe_report']['provider_denied'])
        self.assertEqual(result['safe_report']['captured_race_ids'],[])
        marker=json.loads((self.root/'raw/provider-denial-stop.json').read_bytes())
        self.assertEqual(marker['schema'],'RACE_AI_KEIRIN_PROVIDER_DENIAL_STOP_V1')
        self.assertEqual(marker['state'],'HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP')

    def test_restored_denial_prevents_even_a_calendar_request(self):
        raw=self.root/'raw'
        raw.mkdir(mode=0o700)
        marker={'schema':'RACE_AI_KEIRIN_PROVIDER_DENIAL_STOP_V1',
                'state':'HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP',
                'day_jst':'2030-01-14','recorded_at':'2030-01-14T03:00:00+00:00'}
        (raw/'provider-denial-stop.json').write_text(json.dumps(marker))
        before=(raw/'provider-denial-stop.json').read_bytes()
        result=self.collect()
        self.assertTrue(result['safe_report']['provider_denied'])
        self.assertEqual(self.calls,[])
        self.assertEqual((raw/'provider-denial-stop.json').read_bytes(),before)

    def test_priority_receipt_requires_the_actual_capture_to_remain_in_the_window(self):
        self.pages=pages_for([(2,'12:12')])
        current=[NOW]
        def fetch(url):
            raw=self.fetch(url)
            if url==urls(2)[0]:
                current[0]+=timedelta(minutes=4)
            return raw
        result=self.api().collect_day(day_jst=DAY,private_root=self.root,
            fetch=fetch,clock=lambda:current[0],already_captured_ids=(rid(2),))
        self.assertEqual(result['safe_report']['captured_race_ids'],[rid(2)])
        self.assertEqual(result['safe_report']['priority_window_race_ids'],[])

    def test_a_pair_that_becomes_too_close_stops_before_fetching_its_second_page(self):
        self.pages=pages_for([(2,'12:12')])
        current=[NOW]
        def fetch(url):
            raw=self.fetch(url)
            if url==urls(2)[0]:
                current[0]+=timedelta(minutes=11,seconds=10)
            return raw
        result=self.api().collect_day(day_jst=DAY,private_root=self.root,
                                      fetch=fetch,clock=lambda:current[0])
        self.assertEqual(self.calls,[CALENDAR,MEETING,urls(2)[0]])
        self.assertEqual(result['safe_report']['captured_race_ids'],[])
        self.assertEqual(result['safe_report']['missing_source_races'],1)

    def test_unknown_net_H_is_held_without_an_invented_value(self):
        self.pages=pages_for([(2,'12:12')])
        self.pages[urls(2)[0]]=self.pages[urls(2)[0]].replace(
            b'<td>2</td><td>3</td><td>4</td>',b'<td>2</td><td>?</td><td>4</td>')
        result=self.collect()
        races,refs,_=self.documents(result)
        self.assertEqual(races['races'],[])
        self.assertEqual(refs,[])
        self.assertEqual(result['safe_report']['missing_source_races'],1)

    def test_existing_dated_snapshot_is_preserved_before_any_GET(self):
        result=self.collect()
        path=Path(result['site_root'])/'data'/DAY/'races.json'
        before=path.read_bytes()
        self.calls.clear()
        with self.assertRaises(ValueError):
            self.collect()
        self.assertEqual(self.calls,[])
        self.assertEqual(path.read_bytes(),before)

    def test_private_output_rejects_checkout_ancestors_and_symlinks(self):
        checkout=self.root/'checkout'
        (checkout/'.git').mkdir(parents=True)
        for private in (checkout/'private',self.root/'linked'):
            if private.name=='linked':
                private.symlink_to(self.root,target_is_directory=True)
            with self.subTest(path=private.name),self.assertRaises(ValueError):
                self.api().collect_day(day_jst=DAY,private_root=private,
                                      fetch=self.fetch,clock=lambda:NOW)
        self.assertEqual(self.calls,[])

    def test_CLI_prints_only_safe_aggregate_fields(self):
        output=io.StringIO()
        with redirect_stdout(output):
            code=self.api().main(['--day',DAY,'--private-root',str(self.root)],
                                 fetch=self.fetch,clock=lambda:NOW)
        self.assertEqual(code,0)
        safe=json.loads(output.getvalue())
        self.assertEqual(safe['research_references_generated'],2)
        self.assertNotIn('captured_race_ids',safe)
        for forbidden in ('https://','EXAMPLE_RIDER','例示の方針','ranked_tickets',str(self.root)):
            self.assertNotIn(forbidden,output.getvalue())

    def test_untrusted_provider_exception_text_never_enters_the_public_report(self):
        output=io.StringIO()
        def fail(url):
            self.calls.append(url)
            raise ValueError('EXAMPLE_PRIVATE_PROVIDER_BODY')
        with redirect_stdout(output):
            code=self.api().main(['--day',DAY,'--private-root',str(self.root)],
                                 fetch=fail,clock=lambda:NOW)
        self.assertEqual(code,0)
        self.assertNotIn('EXAMPLE_PRIVATE_PROVIDER_BODY',output.getvalue())
        self.assertEqual(self.calls,[CALENDAR])


if __name__=='__main__':
    unittest.main()
