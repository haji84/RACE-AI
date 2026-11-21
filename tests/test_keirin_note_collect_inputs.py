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


def selected_net_page(number,title):
    """Invented selected-header shape; class facts are separate from statistics."""
    header=('<div class="RaceList_NameBox"><div class="RaceList_NameBox_inner">'
        '<div class="RaceList_Item01"><div class="Race_Num">'+str(number)+'R</div></div>'
        '<div class="RaceList_Item02"><div class="Race_TitleBox"><h1>'
        '<div class="Race_Name">'+title+'</div></h1></div></div></div>'
        '<a class="Active" href="'+urls(number)[0]+'">対象レース</a></div>')
    return net_page(number).replace(b'<body>',('<body>'+header).encode())


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

    def selected_class_pages(self,competition='S級'):
        self.pages=pages_for([(2,'12:12')])
        self.pages[urls(2)[0]]=selected_net_page(2,competition+' 例示特別競走')
        self.pages[urls(2)[1]]=self.pages[urls(2)[1]].replace(
            'A級予選'.encode(),'例示特別競走'.encode())

    def test_new_reference_saves_confidence_beside_the_unchanged_baseline(self):
        from race_ai import keirin_nationwide_auto_generator as model
        self.pages=pages_for([(2,'12:12')])
        ticks=iter(NOW+timedelta(seconds=n) for n in range(120))
        result=self.api().collect_day(day_jst=DAY,private_root=self.root,
            fetch=self.fetch,clock=lambda:next(ticks),model_source_commit='a'*40)
        _,references,_=self.documents(result)
        self.assertEqual(len(references),1)
        reference=references[0]
        self.assertIn('confidence_assessment',set(reference))
        baseline=reference['output'];assessment=reference['confidence_assessment']
        self.assertEqual(assessment['source_prediction_sha256'],baseline['prediction_sha256'])
        self.assertEqual(assessment['source_facts_sha256'],baseline['source_facts_sha256'])
        self.assertGreater(model.when(assessment['assessed_at']),model.when(baseline['generated_at']))
        self.assertGreaterEqual((model.when(assessment['cutoff'])-
            model.when(assessment['assessed_at'])).total_seconds(),65)
        self.assertEqual(baseline,model.generate_A_B(reference['input'],
            generated_at=baseline['generated_at'],max_tickets=12))
        self.assertNotIn('confidence_assessment',baseline)

    def test_selected_net_class_fills_only_the_missing_class_and_keeps_original_receipts(self):
        self.selected_class_pages()
        before=dict(self.pages)
        result=self.collect();races,refs,manifest=self.documents(result)
        self.assertEqual(result['safe_report']['captured_race_ids'],[rid(2)])
        self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2)])
        self.assertEqual(refs[0]['input']['competition'],'S')
        self.assertEqual(refs[0]['input']['line_groups'],[[1,2],[3,4],[5,6]])
        self.assertEqual(refs[0]['input']['round_stage'],'OTHER')
        self.assertEqual(races['races'][0]['riders'][0]['score'],91)
        self.assertEqual(refs[0]['input']['riders'][0]['competition_points'],71)
        provenance=refs[0]['class_field_source']
        self.assertEqual(provenance['url'],urls(2)[0])
        self.assertEqual(provenance['bytes_sha256'],sha256(before[urls(2)[0]]).hexdigest())
        self.assertEqual(provenance['selected_header'],'S級 例示特別競走')
        self.assertEqual(provenance['selected_header_sha256'],sha256('S級 例示特別競走'.encode()).hexdigest())
        self.assertEqual(provenance['race_id'],rid(2))
        self.assertEqual(provenance['day_jst'],DAY)
        self.assertEqual(races['races'][0]['field_sources']['competition'],provenance)
        program=[p for p in refs[0]['input']['source_pages'] if p['kind']=='PROGRAM']
        self.assertEqual(len(program),1)
        self.assertEqual(program[0]['bytes_sha256'],provenance['bytes_sha256'])
        for receipt in manifest['source_receipts']:
            self.assertEqual((self.root/'raw'/(receipt['bytes_sha256']+'.html')).read_bytes(),before[receipt['url']])
        self.assertEqual(manifest['daily_coverage']['counts'],dict(observed=1,input_available=1,missing=0,held=0))
        self.assertFalse(result['safe_report']['formal_model_admission'])

    def test_selected_net_link_accepts_only_the_observed_tracking_value_in_either_query_order(self):
        from race_ai import keirin_public_two_source_normalizer as adapter
        for query in ('race_id='+rid(2)+'&rf=courselist','rf=courselist&race_id='+rid(2)):
            with self.subTest(query=query),TemporaryDirectory() as temp:
                self.selected_class_pages();self.calls.clear()
                original=self.pages[urls(2)[0]]
                href='https://keirin.netkeiba.com/race/entry/?'+query
                raw=original.replace(('<a class="Active" href="'+urls(2)[0]+'">').encode(),
                    ('<a class="Active" href="'+href+'">').encode())
                self.pages[urls(2)[0]]=raw
                root=Path(temp);root.chmod(0o700)
                result=self.api().collect_day(day_jst=DAY,private_root=root,
                    fetch=self.fetch,clock=lambda:NOW,model_source_commit='a'*40)
                races,references,manifest=self.documents(result)
                self.assertEqual(len(races['races']),1)
                self.assertEqual(references[0]['input']['competition'],'S')
                provenance=references[0]['class_field_source']
                self.assertEqual(provenance['url'],urls(2)[0])
                self.assertEqual(provenance['bytes_sha256'],sha256(raw).hexdigest())
                self.assertEqual((root/'raw'/(sha256(raw).hexdigest()+'.html')).read_bytes(),raw)
                self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2)])
                self.assertEqual(manifest['daily_coverage']['counts'],dict(observed=1,input_available=1,missing=0,held=0))
                with self.assertRaisesRegex(adapter.PublicPageNormalizeError,'KDREAMS_RACE_CLASS_NOT_IN_SOURCE'):
                    adapter.merge_pre_race_pages(race_id=rid(2),netkeirin_raw=raw,netkeirin_url=urls(2)[0],
                        netkeirin_captured_at=NOW.isoformat(),kdreams_raw=self.pages[urls(2)[1]],
                        kdreams_url=urls(2)[1],kdreams_captured_at=NOW.isoformat(),created_at=NOW.isoformat())

    def test_selected_tracking_link_rejects_identity_changes_and_unobserved_query_forms(self):
        from race_ai import keirin_public_two_source_normalizer as adapter
        self.selected_class_pages();source=urls(2)[0];tracked=source+'&rf=courselist'
        bad={
            'unknown_key':tracked+'&other=courselist',
            'duplicate_race_id':tracked+'&race_id='+rid(2),
            'conflicting_race_id':tracked+'&race_id='+rid(1),
            'blank_duplicate_race_id':tracked+'&race_id=',
            'duplicate_rf':tracked+'&rf=courselist',
            'conflicting_rf':tracked+'&rf=other',
            'blank_duplicate_rf':tracked+'&rf=',
            'blank_rf':source+'&rf=',
            'different_rf':source+'&rf=other',
            'wrong_case_rf':source+'&rf=courseList',
            'missing_race_id':'https://keirin.netkeiba.com/race/entry/?rf=courselist',
            'wrong_day':tracked.replace('20300115','20300116'),
            'wrong_race':tracked.replace(rid(2),rid(1)),
            'wrong_host':tracked.replace('keirin.netkeiba.com','example.invalid'),
            'wrong_path':tracked.replace('/race/entry/','/race/entry/results.html'),
            'http':tracked.replace('https://','http://'),
            'relative':tracked.removeprefix('https://keirin.netkeiba.com'),
            'userinfo':tracked.replace('https://','https://user@'),
            'port':tracked.replace('keirin.netkeiba.com','keirin.netkeiba.com:443'),
            'other_port':tracked.replace('keirin.netkeiba.com','keirin.netkeiba.com:8443'),
            'fragment':tracked+'#race',
            'empty_fragment':tracked+'#',
            'leading_space':' '+tracked,
            'malformed_query':tracked+'&',
        }
        for label,href in bad.items():
            with self.subTest(label=label):
                raw=self.pages[source].replace(('<a class="Active" href="'+source+'">').encode(),
                    ('<a class="Active" href="'+href+'">').encode())
                with self.assertRaisesRegex(adapter.PublicPageNormalizeError,'NET_SELECTED_CLASS_SELECTION_MISMATCH'):
                    adapter.merge_pre_race_pages(race_id=rid(2),netkeirin_raw=raw,netkeirin_url=source,
                        netkeirin_captured_at=NOW.isoformat(),kdreams_raw=self.pages[urls(2)[1]],
                        kdreams_url=urls(2)[1],kdreams_captured_at=NOW.isoformat(),created_at=NOW.isoformat(),
                        allow_selected_netkeirin_class=True)

    def test_tracking_link_does_not_relax_the_exact_source_canonical(self):
        from race_ai import keirin_public_two_source_normalizer as adapter
        self.selected_class_pages();source=urls(2)[0]
        tracked=self.pages[source].replace(('<a class="Active" href="'+source+'">').encode(),
            ('<a class="Active" href="'+source+'&rf=courselist">').encode())
        for other in (source+'&rf=courselist',source.replace('/race/entry/','/race/entry/results.html')):
            with self.subTest(canonical=other):
                raw=tracked.replace(('<link rel="canonical" href="'+source+'">').encode(),
                    ('<link rel="canonical" href="'+other+'">').encode())
                with self.assertRaisesRegex(adapter.PublicPageNormalizeError,'SOURCE_CANONICAL_URL_RACE_MISMATCH'):
                    adapter.merge_pre_race_pages(race_id=rid(2),netkeirin_raw=raw,netkeirin_url=source,
                        netkeirin_captured_at=NOW.isoformat(),kdreams_raw=self.pages[urls(2)[1]],
                        kdreams_url=urls(2)[1],kdreams_captured_at=NOW.isoformat(),created_at=NOW.isoformat(),
                        allow_selected_netkeirin_class=True)

    def test_explicit_selected_class_conflict_holds_before_generating_reference_outputs(self):
        self.pages=pages_for([(2,'12:12')])
        self.pages[urls(2)[0]]=selected_net_page(2,'S級 予選')
        result=self.collect();races,refs,manifest=self.documents(result)
        self.assertEqual(races['races'],[]);self.assertEqual(refs,[])
        self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2)])
        self.assertEqual(manifest['daily_coverage']['counts'],dict(observed=1,input_available=0,missing=0,held=1))

    def test_selected_class_source_rejects_wrong_day_race_canonical_roster_and_ambiguous_headers(self):
        changes={
            'wrong_day':lambda raw:raw.replace(b'race_id=203001159802',b'race_id=203001169802'),
            'wrong_race':lambda raw:raw.replace(b'>2R</div>',b'>1R</div>'),
            'missing_canonical':lambda raw:raw.replace(('<link rel="canonical" href="'+urls(2)[0]+'">').encode(),b''),
            'wrong_roster':lambda raw:raw.replace(b'EXAMPLE_RIDER_1',b'EXAMPLE_DIFFERENT_RIDER'),
            'duplicate_header':lambda raw:raw.replace(b'</h1>',b'<div class="Race_Name">S'+ '級 例示特別競走</div></h1>'.encode()),
            'missing_class':lambda raw:raw.replace('S級 例示特別競走'.encode(),'例示特別競走'.encode()),
            'wrong_label':lambda raw:raw.replace('S級 例示特別競走'.encode(),'S級 例示別競走'.encode()),
            'two_classes':lambda raw:raw.replace('S級 例示特別競走'.encode(),'S級 A級 例示特別競走'.encode()),
            'wrong_selected_day':lambda raw:raw.replace(('<a class="Active" href="'+urls(2)[0]+'">').encode(),('<a class="Active" href="'+urls(2)[0].replace('20300115','20300116')+'">').encode()),
            'wrong_selected_race':lambda raw:raw.replace(('<a class="Active" href="'+urls(2)[0]+'">').encode(),('<a class="Active" href="'+urls(1)[0]+'">').encode()),
            'missing_selected_link':lambda raw:raw.replace(b'class="Active"',b'class="inactive"'),
            'duplicate_selected_link':lambda raw:raw.replace(b'</div><table>',('<a class="Active" href="'+urls(2)[0]+'">duplicate</a></div><table>').encode()),
        }
        for label,change in changes.items():
            with self.subTest(label=label),TemporaryDirectory() as temp:
                self.selected_class_pages();self.calls.clear()
                self.pages[urls(2)[0]]=change(self.pages[urls(2)[0]])
                root=Path(temp);root.chmod(0o700)
                result=self.api().collect_day(day_jst=DAY,private_root=root,
                    fetch=self.fetch,clock=lambda:NOW,model_source_commit='a'*40)
                races,refs,manifest=self.documents(result)
                self.assertEqual(len(races['races']),0);self.assertEqual(refs,[])
                self.assertEqual(result['safe_report']['captured_races'],0)
                self.assertEqual(manifest['daily_coverage']['counts']['held'],1)
                self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2)])

    def test_selected_class_binds_full_responsive_names_without_tooltip_or_abbreviation_text(self):
        from bs4 import BeautifulSoup
        for mismatch in (False,True):
            with self.subTest(mismatch=mismatch),TemporaryDirectory() as temp:
                self.selected_class_pages();self.calls.clear()
                soup=BeautifulSoup(self.pages[urls(2)[0]],'html.parser')
                for row in list(soup.select('tr')):
                    cells=row.find_all('td',recursive=False)
                    mobile=BeautifulSoup(str(row),'html.parser').tr
                    mobile_cells=mobile.find_all('td',recursive=False)
                    mobile_cells[4].clear()
                    mobile_cells[4].append(BeautifulSoup('<div class="PlayerName DispB"><span>例示の補足</span><a class="Player01">省略名</a></div>','html.parser').div)
                    name=cells[4].get_text('',strip=True)
                    if mismatch and cells[1].get_text('',strip=True)=='1':
                        name='EXAMPLE_DIFFERENT_RIDER'
                    cells[4].clear()
                    cells[4].append(BeautifulSoup('<div class="Player_InfoWrap DispA"><dl><dt class="PlayerName">'+name+'<img class="Icon_Note"><span><svg><title>お気に入り例示</title></svg></span></dt></dl></div>','html.parser').div)
                    row.insert_before(mobile)
                self.pages[urls(2)[0]]=str(soup).encode()
                root=Path(temp);root.chmod(0o700)
                result=self.api().collect_day(day_jst=DAY,private_root=root,
                    fetch=self.fetch,clock=lambda:NOW,model_source_commit='a'*40)
                races,references,_=self.documents(result)
                self.assertEqual(len(races['races']),0 if mismatch else 1)
                self.assertEqual(len(references),0 if mismatch else 1)
                self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2)])

    def test_selected_class_does_not_replace_an_unpublished_lineup_or_use_historical_class(self):
        for mode in ('unpublished_line','historical_class_only'):
            with self.subTest(mode=mode),TemporaryDirectory() as temp:
                self.selected_class_pages();self.calls.clear()
                if mode=='unpublished_line':
                    raw=self.pages[urls(2)[1]].decode();start=raw.index('<div class="line_position">');end=raw.index('</div>',start)
                    self.pages[urls(2)[1]]=(raw[:start]+'<div class="line_position"><p>並び予想がありません</p>'+raw[end:]).encode()
                else:
                    self.pages[urls(2)[0]]=self.pages[urls(2)[0]].replace('S級 例示特別競走'.encode(),'例示特別競走'.encode()).replace(b'</body>','<table class="past_racecard_table"><tr><td>S級予選</td></tr></table></body>'.encode())
                root=Path(temp);root.chmod(0o700)
                result=self.api().collect_day(day_jst=DAY,private_root=root,fetch=self.fetch,clock=lambda:NOW)
                self.assertEqual(result['safe_report']['captured_races'],0)
                self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2)])
                if mode=='unpublished_line':self.assertEqual(result['safe_report']['states'],{'HOLD_KDREAMS_LINE_NOT_ALL_REAL_CARS':1})

    def test_selected_class_path_preserves_the_cutoff_guard_after_the_source_pair_is_read(self):
        self.selected_class_pages();clock=[NOW]
        def fetch(url):
            raw=self.fetch(url)
            if url==urls(2)[1]:clock[0]=NOW+timedelta(minutes=11)
            return raw
        result=self.api().collect_day(day_jst=DAY,private_root=self.root,fetch=fetch,clock=lambda:clock[0])
        self.assertEqual(result['safe_report']['captured_races'],0)
        self.assertIn('HOLD_PREDICTION_AFTER_OR_TOO_CLOSE_TO_PUBLISHED_CUTOFF',result['safe_report']['states'])

    def test_selected_net_class_is_an_explicit_normalizer_opt_in(self):
        self.selected_class_pages()
        from race_ai import keirin_public_two_source_normalizer as adapter
        arguments=dict(race_id=rid(2),netkeirin_raw=self.pages[urls(2)[0]],netkeirin_url=urls(2)[0],
            netkeirin_captured_at=NOW.isoformat(),kdreams_raw=self.pages[urls(2)[1]],
            kdreams_url=urls(2)[1],kdreams_captured_at=NOW.isoformat(),created_at=NOW.isoformat())
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,'KDREAMS_RACE_CLASS_NOT_IN_SOURCE'):
            adapter.merge_pre_race_pages(**arguments)
        result=adapter.merge_pre_race_pages(**arguments,allow_selected_netkeirin_class=True)
        self.assertEqual(result['source_packet']['competition'],'S')

    def test_explicit_A_and_L_classes_use_the_same_selected_source_binding(self):
        for label,expected in (('A級','A1_A2'),('L級ガールズ','GIRLS')):
            with self.subTest(label=label),TemporaryDirectory() as temp:
                self.selected_class_pages(label);self.calls.clear()
                root=Path(temp);root.chmod(0o700)
                result=self.api().collect_day(day_jst=DAY,private_root=root,fetch=self.fetch,clock=lambda:NOW)
                _,references,_=self.documents(result)
                self.assertEqual(result['safe_report']['captured_races'],1)
                self.assertEqual(references[0]['input']['competition'],expected)
                self.assertEqual(self.calls,[CALENDAR,MEETING,*urls(2)])
                if expected=='GIRLS':
                    self.assertEqual(references[0]['input']['line_groups'],[[n] for n in range(1,7)])

    def test_an_existing_K_class_does_not_require_a_missing_net_class_or_change_the_snapshot(self):
        from race_ai import keirin_public_two_source_normalizer as adapter
        for title in ('例示の見出し','A級予選'):
            for selection in ('normal','missing','other_race'):
                with self.subTest(title=title,selection=selection):
                    self.pages=pages_for([(2,'12:12')]);raw=selected_net_page(2,title)
                    if selection=='missing':raw=raw.replace(b'class="Active"',b'class="inactive"')
                    if selection=='other_race':raw=raw.replace(('<a class="Active" href="'+urls(2)[0]+'">').encode(),('<a class="Active" href="'+urls(1)[0]+'">').encode())
                    arguments=dict(race_id=rid(2),netkeirin_raw=raw,netkeirin_url=urls(2)[0],
                        netkeirin_captured_at=NOW.isoformat(),kdreams_raw=self.pages[urls(2)[1]],
                        kdreams_url=urls(2)[1],kdreams_captured_at=NOW.isoformat(),created_at=NOW.isoformat())
                    before=adapter.merge_pre_race_pages(**arguments)
                    after=adapter.merge_pre_race_pages(**arguments,allow_selected_netkeirin_class=True)
                    self.assertEqual(before,after)
                    self.assertNotIn('class_field_source',after)

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

    def test_daily_coverage_accounts_for_every_observed_race_without_inventing_results(self):
        result=self.collect()
        _,_,manifest=self.documents(result)
        coverage=manifest.get('daily_coverage')
        self.assertIsInstance(coverage,dict,'The encrypted manifest must retain daily coverage.')
        self.assertEqual(coverage['schema'],'RACE_AI_KEIRIN_NOTE_DAY_COVERAGE_V1')
        self.assertEqual(coverage['day_jst'],DAY)
        self.assertEqual(coverage['observed_at'],NOW.astimezone(self.api().UTC).isoformat())
        self.assertEqual(coverage['counts'],dict(observed=4,input_available=2,missing=1,held=1))
        rows={r['race_id']:r for r in coverage['races']}
        self.assertEqual(set(rows),{rid(n) for n in range(1,5)})
        self.assertEqual(rows[rid(1)]['input_status'],'available')
        self.assertTrue(rows[rid(2)]['captured_this_cycle'])
        self.assertEqual(rows[rid(3)]['input_status'],'missing')
        self.assertEqual(rows[rid(3)]['reason'],'PAST_PUBLISHED_CUTOFF')
        self.assertEqual(rows[rid(4)]['input_status'],'held')
        self.assertIsNone(rows[rid(4)]['published_cutoff_at'])
        self.assertFalse(coverage['national_universe_verified'])
        self.assertFalse(coverage['formal_model_admission'])
        self.assertNotIn('scored',coverage['counts'])
        self.assertNotIn('cancelled',coverage['counts'])
        self.assertNotIn('refunded',coverage['counts'])

    def test_daily_coverage_preserves_prior_input_after_failed_refresh_and_stop(self):
        self.pages=pages_for([(1,'13:00'),(2,'12:12'),(3,'12:11'),(4,'11:59')])
        original=self.fetch
        def deny(url):
            if url==urls(3)[0]:
                self.calls.append(url)
                raise capture.SourceCaptureError('PROVIDER_DENIED_OR_RATE_LIMITED_STOP')
            return original(url)
        self.fetch=deny
        result=self.collect(already_captured_ids=(rid(3),rid(4)))
        _,_,manifest=self.documents(result)
        coverage=manifest.get('daily_coverage')
        self.assertIsInstance(coverage,dict,'A stopped cycle must retain the complete observed roster.')
        self.assertEqual(coverage['counts'],dict(observed=4,input_available=2,missing=0,held=2))
        rows={r['race_id']:r for r in coverage['races']}
        self.assertEqual(rows[rid(3)]['input_status'],'available')
        self.assertEqual(rows[rid(3)]['reason'],'HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP')
        self.assertFalse(rows[rid(3)]['captured_this_cycle'])
        self.assertEqual(rows[rid(4)]['input_status'],'available')
        self.assertEqual(rows[rid(1)]['input_status'],'held')
        self.assertEqual(rows[rid(2)]['input_status'],'held')
        self.assertEqual(self.calls,[CALENDAR,MEETING,urls(3)[0]])

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

    def test_priority_receipt_also_requires_generation_before_the_ten_minute_boundary(self):
        self.pages=pages_for([(2,'12:12'),(3,'12:14')])
        current=[NOW]
        def fetch(url):
            raw=self.fetch(url)
            if url==urls(3)[0]:
                current[0]+=timedelta(minutes=3)
            return raw
        result=self.api().collect_day(day_jst=DAY,private_root=self.root,
                                      fetch=fetch,clock=lambda:current[0])
        _,references,_=self.documents(result)
        first=references[0]
        cutoff=datetime.fromisoformat(first['input']['published_cutoff_at'])
        self.assertEqual((cutoff-datetime.fromisoformat(first['input']['as_of'])).total_seconds(),720)
        self.assertEqual((cutoff-datetime.fromisoformat(first['output']['generated_at'])).total_seconds(),540)
        self.assertEqual(result['safe_report']['captured_race_ids'],[rid(2),rid(3)])
        self.assertEqual(result['safe_report']['priority_window_race_ids'],[rid(3)])

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
