"""Invented linked result pages; no provider or owner-key access."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest


DAY='2030-01-15'
NOW=datetime(2030,1,16,0,tzinfo=timezone.utc)


def rid(day=DAY,n=1):return day.replace('-','')+'98'+f'{n:02d}'
def calendar(day):return 'https://keirin.kdreams.jp/kaisai/'+day.replace('-','/')+'/'
def meeting(day):return 'https://keirin.kdreams.jp/fictional/racecard/98'+day.replace('-','')+'0100/'
def detail(day,n):return 'https://keirin.kdreams.jp/fictional/racedetail/98'+day.replace('-','')+'0100'+f'{n:02d}'+'/'
def result_html(day,n,combo='1-2-3',payout='1,200',suffix=''):
    y,m,d=map(int,day.split('-'))
    return (f'<title>架空競輪 {y}年{m}月{d}日 {n}R 結果・払戻</title>'
        f'<p>結果確定 3連単 {combo} {payout}円</p>'+suffix).encode()


class ResultCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.root.chmod(0o700)
        self.urls=[];self.pages={};self.add_day(DAY,3)

    def add_day(self,day,count):
        self.pages[calendar(day)]=f'<a href="{meeting(day)}">架空開催</a>'.encode()
        self.pages[meeting(day)]=('<ul class="racecard_list">'+''.join(
            f'<li><p class="race"><a href="{detail(day,n)}">{n}R</a></p>'
            '<div class="header"><dl><dt>締切</dt><dd>12:00</dd></dl></div></li>'
            for n in range(1,count+1))+'</ul>').encode()
        for n in range(1,count+1):
            raw=result_html(day,n)
            self.pages[detail(day,n)+'?pageType=result']=raw
            self.pages['https://keirin.netkeiba.com/race/result/?race_id='+rid(day,n)]=raw

    def fetch(self,url):self.urls.append(url);return self.pages[url]

    def collect(self,**kwargs):
        from scripts.keirin_note_collect_results import collect_results
        return collect_results(days=kwargs.pop('days',[DAY]),private_root=self.root,
            fetch=self.fetch,clock=kwargs.pop('clock',lambda:NOW),**kwargs)

    def observations(self,result,day=DAY):
        return json.loads((Path(result['site_root'])/'data'/day/'research_results.json').read_bytes())['observations']

    def test_old_days_all_published_races_not_only_forecast_capture_ids(self):
        result=self.collect(result_checks={})
        self.assertEqual(result['safe_report']['observed_races'],3)
        self.assertEqual(result['safe_report']['matched_races'],3)
        self.assertEqual(len(self.observations(result)),3)
        self.assertEqual(len(self.urls),8)
        self.assertEqual(set(result['result_checks']),{rid(n=n) for n in range(1,4)})
        for row in self.observations(result):
            self.assertFalse(row['qualifies_for_formal_settlement'])
            self.assertIsNone(row['previous_observation_sha256'])
            self.assertEqual(row['winning_triple'],[1,2,3])
        self.assertTrue(list((self.root/'raw').glob('*.html')))
        self.assertNotIn('winning_triple',json.dumps(result['safe_report']))

    def test_unchanged_facts_ignore_capture_clocks_and_advertising_bytes(self):
        first=self.collect(result_checks={});checks=first['result_checks']
        for url,body in list(self.pages.items()):
            if 'pageType=result' in url or '/race/result/' in url:self.pages[url]=body+b'<aside>new ad</aside>'
        self.root=self.root/'next';self.root.mkdir(mode=0o700)
        second=self.collect(result_checks=checks,clock=lambda:NOW+timedelta(hours=1))
        self.assertEqual(second['safe_report']['changed_observations'],0)
        self.assertEqual(second['result_checks'][rid()]['digest'],checks[rid()]['digest'])
        self.assertGreater(second['result_checks'][rid()]['checked_at'],checks[rid()]['checked_at'])
        self.assertFalse((self.root/'data'/DAY/'research_results.json').exists())

    def test_result_revision_and_disagreement_replace_previous_fact_digest(self):
        first=self.collect(result_checks={});checks=first['result_checks']
        self.pages[detail(DAY,1)+'?pageType=result']=result_html(DAY,1,'3-2-1')
        self.root=self.root/'next';self.root.mkdir(mode=0o700)
        result=self.collect(result_checks=checks,clock=lambda:NOW+timedelta(hours=1))
        rows=self.observations(result)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['state'],'HOLD_SECONDARY_RESULT_DISAGREEMENT')
        self.assertIsNone(rows[0]['winning_triple'])
        self.assertEqual(rows[0]['previous_observation_sha256'],checks[rid()]['digest'])
        self.assertEqual(result['result_checks'][rid()]['status'],'HOLD')

    def test_not_due_matched_results_are_not_refetched(self):
        first=self.collect(result_checks={});checks=first['result_checks'];self.urls=[]
        self.root=self.root/'next';self.root.mkdir(mode=0o700)
        result=self.collect(result_checks=checks,clock=lambda:NOW+timedelta(minutes=10))
        self.assertEqual(len(self.urls),2)
        self.assertEqual(result['safe_report']['checked_races'],0)

    def test_today_future_and_unknown_cutoff_are_not_fetched_as_completed(self):
        rows=self.pages[meeting(DAY)].split(b'</li>')
        rows[0]=rows[0].replace('<dt>締切</dt>'.encode(),b'<dt>unknown</dt>')
        rows[1]=rows[1].replace(b'12:00',b'23:59')
        self.pages[meeting(DAY)]=b'</li>'.join(rows)
        now=datetime(2030,1,15,4,tzinfo=timezone.utc)
        result=self.collect(result_checks={},clock=lambda:now)
        self.assertEqual(result['safe_report']['checked_races'],2)
        self.assertEqual(result['safe_report']['unknown_cutoff_races'],1)
        self.assertEqual(result['result_checks'][rid()]['status'],'HOLD')
        self.assertNotIn(detail(DAY,1)+'?pageType=result',self.urls)

    def test_denial_stops_all_later_requests_and_retains_safe_stop(self):
        from scripts.keirin_capture_public_two_sources import SourceCaptureError
        original=self.fetch
        def denied(url):
            if 'pageType=result' in url:
                self.urls.append(url);raise SourceCaptureError('PROVIDER_DENIED_OR_RATE_LIMITED_STOP')
            return original(url)
        self.fetch=denied
        result=self.collect(result_checks={})
        self.assertTrue(result['safe_report']['provider_denied'])
        self.assertEqual(len(self.urls),3)
        self.assertTrue((self.root/'raw/provider-denial-stop.json').exists())

    def test_missing_source_document_never_becomes_a_matched_result(self):
        self.pages[detail(DAY,1)+'?pageType=result']=b'<p>unknown source layout</p>'
        result=self.collect(result_checks={})
        self.assertEqual(result['result_checks'][rid()]['status'],'HOLD')
        self.assertIsNone(self.observations(result)[0]['winning_triple'])

    def test_fair_progress_oldest_checks_first_and_no_race_count_cap(self):
        self.add_day(DAY,12)
        checks={rid(n=1):dict(checked_at=(NOW-timedelta(days=1)).isoformat(),digest='a'*64,status='MATCHED')}
        result=self.collect(result_checks=checks)
        result_urls=[url for url in self.urls if 'pageType=result' in url]
        self.assertEqual(len(result_urls),12)
        self.assertEqual(result_urls[-1],detail(DAY,1)+'?pageType=result')

    def test_budget_stops_without_new_requests_and_next_tick_reaches_unchecked_tail(self):
        elapsed=[0];original=self.fetch
        def costed(url):
            raw=original(url);elapsed[0]+=1;return raw
        self.fetch=costed
        first=self.collect(result_checks={},monotonic=lambda:elapsed[0],budget_seconds=6)
        self.assertTrue(first['safe_report']['budget_exhausted'])
        self.assertEqual(len(self.urls),6)
        self.assertEqual(set(first['result_checks']),{rid(n=1),rid(n=2)})
        self.root=self.root/'next';self.root.mkdir(mode=0o700);self.urls=[];elapsed[0]=0
        second=self.collect(result_checks=first['result_checks'],monotonic=lambda:elapsed[0],
            budget_seconds=6,clock=lambda:NOW+timedelta(minutes=10))
        self.assertEqual(set(second['result_checks']),{rid(n=3)})
        self.assertEqual(second['safe_report']['matched_races'],1)

    def test_all_known_historical_days_are_discovered_after_midnight(self):
        ancient='2028-01-01';self.add_day(ancient,1)
        result=self.collect(days=[DAY,ancient],result_checks={})
        self.assertEqual(result['safe_report']['discovered_days'],2)
        self.assertEqual(result['safe_report']['matched_races'],4)
        self.assertEqual(len(self.observations(result,ancient)),1)

    def test_current_day_reaches_result_checks_when_history_would_use_the_budget(self):
        days=['2030-01-12','2030-01-13','2030-01-14',DAY]
        for day in days:
            self.add_day(day,12)
        now=datetime(2030,1,15,12,tzinfo=timezone.utc)
        result=self.collect(days=days,result_checks={},clock=lambda:now,
            monotonic=lambda:len(self.urls),budget_seconds=6)

        self.assertEqual(self.urls[0],calendar(DAY))
        self.assertEqual(set(result['result_checks']),{rid(n=1),rid(n=2)})
        self.assertEqual(result['safe_report']['matched_races'],2)
        self.assertEqual(len(self.urls),6)

    def add_extra_meeting(self, day, venue, cutoff='12:00'):
        compact=day.replace('-','')
        card=meeting(day).replace('98'+compact,venue+compact)
        race=detail(day,1).replace('98'+compact,venue+compact)
        self.pages[calendar(day)]+=f'<a href="{card}">架空開催</a>'.encode()
        self.pages[card]=self.pages[meeting(day)].replace(detail(day,1).encode(),race.encode()).replace(b'12:00',cutoff.encode())
        self.pages[race+'?pageType=result']=result_html(day,1)
        self.pages['https://keirin.netkeiba.com/race/result/?race_id='+compact+venue+'01']=result_html(day,1)

    def test_history_gets_a_turn_before_the_second_current_meeting(self):
        old='2030-01-14'
        self.add_day(old,1)
        self.add_day(DAY,1)
        self.add_extra_meeting(DAY,'97')
        now=datetime(2030,1,15,12,10,tzinfo=timezone.utc)
        result=self.collect(days=[old,DAY],result_checks={},clock=lambda:now,
            monotonic=lambda:len(self.urls),budget_seconds=8)

        self.assertEqual(self.urls[0],calendar(DAY))
        self.assertEqual(len(result['result_checks']),2)
        self.assertEqual({race_id[:8] for race_id in result['result_checks']},
            {DAY.replace('-',''),old.replace('-','')})
        self.assertEqual(result['safe_report']['matched_races'],2)
        self.assertEqual(len(self.urls),8)

    def test_future_only_first_meeting_does_not_delay_a_due_current_meeting(self):
        old='2030-01-14'
        self.add_day(old,12)
        self.add_day(DAY,1)
        self.add_extra_meeting(DAY,'97',cutoff='23:50')
        now=datetime(2030,1,15,12,tzinfo=timezone.utc)
        result=self.collect(days=[old,DAY],result_checks={},clock=lambda:now,
            monotonic=lambda:len(self.urls),budget_seconds=9)

        self.assertIn(rid(),result['result_checks'], 'A due current race must be checked')
        self.assertEqual(result['result_checks'][rid()]['status'],'MATCHED')
        self.assertLess(self.urls.index(detail(DAY,1)+'?pageType=result'),
            self.urls.index(calendar(old)))
        self.assertEqual(result['safe_report']['future_races'],1)
        self.assertEqual(len(self.urls),9)

    def test_pending_retry_interval_and_special_results_hold_without_official_claim(self):
        self.pages[detail(DAY,1)+'?pageType=result']=result_html(DAY,1,payout='---')
        self.pages[detail(DAY,2)+'?pageType=result']=result_html(DAY,2,suffix='<p>返還</p>')
        first=self.collect(result_checks={})
        self.assertEqual(first['result_checks'][rid(n=1)]['status'],'PENDING')
        self.assertEqual(first['result_checks'][rid(n=2)]['status'],'HOLD')
        self.assertEqual(self.observations(first)[1]['state'],'HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL')
        self.root=self.root/'early';self.root.mkdir(mode=0o700);self.urls=[]
        early=self.collect(result_checks=first['result_checks'],clock=lambda:NOW+timedelta(seconds=599))
        self.assertEqual(early['safe_report']['checked_races'],0)
        self.root=self.root/'due';self.root.mkdir(mode=0o700);self.urls=[]
        due=self.collect(result_checks=first['result_checks'],clock=lambda:NOW+timedelta(seconds=600))
        self.assertEqual(due['safe_report']['checked_races'],2)
        self.assertEqual(due['safe_report']['changed_observations'],0)

    def test_restored_denial_from_yesterday_stops_before_every_get(self):
        raw=self.root/'raw';raw.mkdir(mode=0o700)
        (raw/'provider-denial-stop.json').write_text(json.dumps(dict(
            schema='RACE_AI_KEIRIN_PROVIDER_DENIAL_STOP_V1',state='HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP',
            day_jst=DAY,recorded_at='2030-01-15T00:00:00Z')))
        result=self.collect(result_checks={})
        self.assertTrue(result['safe_report']['provider_denied'])
        self.assertEqual(self.urls,[])

    def test_future_progress_clock_rejects_before_acquisition(self):
        with self.assertRaises(ValueError):self.collect(result_checks={rid():dict(
            checked_at=(NOW+timedelta(seconds=1)).isoformat(),digest='a'*64,status='MATCHED')})
        self.assertEqual(self.urls,[])

    def test_multiple_bounded_ticks_reach_every_historical_day_before_budget_is_spent_on_discovery(self):
        days=['2030-01-12','2030-01-13','2030-01-14','2030-01-15']
        for day in days:self.add_day(day,1)
        elapsed=[0];original=self.fetch;checks={};progress=[]
        def costed(url):
            raw=original(url);elapsed[0]+=1;return raw
        self.fetch=costed;original_root=self.root
        for turn in range(4):
            self.root=original_root/str(turn);self.root.mkdir(mode=0o700)
            self.urls=[];elapsed[0]=0
            result=self.collect(days=days,result_checks=checks,monotonic=lambda:elapsed[0],
                budget_seconds=6,clock=lambda turn=turn:NOW+timedelta(minutes=10*turn))
            self.assertLessEqual(len(self.urls),6)
            progress.append(result['safe_report']['checked_races'])
            checks.update(result['result_checks'])
        self.assertTrue(all(count>0 for count in progress),'Every bounded tick must make actual result-check progress')
        self.assertEqual({race_id[:8] for race_id in checks},{day.replace('-','') for day in days})

    def test_empty_and_unparseable_old_days_cannot_starve_a_valid_day(self):
        days=['2030-01-12','2030-01-13','2030-01-14','2030-01-15']
        for day in days[:-1]:self.add_day(day,0)
        self.pages[calendar(days[0])]=b'<html>no published meeting links</html>'
        elapsed=[0];original=self.fetch;checks={};original_root=self.root
        def costed(url):
            raw=original(url);elapsed[0]+=1;return raw
        self.fetch=costed
        for turn in range(4):
            self.root=original_root/str(turn);self.root.mkdir(mode=0o700);elapsed[0]=0;self.urls=[]
            result=self.collect(days=days,result_checks=checks,monotonic=lambda:elapsed[0],
                budget_seconds=6,clock=lambda turn=turn:NOW+timedelta(minutes=10*turn))
            self.assertLessEqual(len(self.urls),6)
            checks.update(result['result_checks'])
        self.assertEqual(set(checks),{rid(n=1),rid(n=2),rid(n=3)})

    def test_nested_day_and_meeting_rotation_reaches_every_link_with_a_one_pair_budget(self):
        days=['2030-01-14','2030-01-15'];venues=['91','92','93','94'];expected=set()
        for day in days:
            anchors=[]
            for venue in venues:
                old='98'+day.replace('-','');new=venue+day.replace('-','')
                card=meeting(day).replace(old,new);race=detail(day,1).replace(old,new)
                anchors.append(f'<a href="{card}">架空開催</a>')
                self.pages[card]=('<ul class="racecard_list"><li><p class="race">'
                    f'<a href="{race}">1R</a></p><div class="header"><dl><dt>締切</dt>'
                    '<dd>12:00</dd></dl></div></li></ul>').encode()
                self.pages[race+'?pageType=result']=result_html(day,1)
                race_id=day.replace('-','')+venue+'01';expected.add(race_id)
                self.pages['https://keirin.netkeiba.com/race/result/?race_id='+race_id]=result_html(day,1)
            self.pages[calendar(day)]=''.join(anchors).encode()
        elapsed=[0];original=self.fetch;checks={};original_root=self.root
        def costed(url):
            raw=original(url);elapsed[0]+=1;return raw
        self.fetch=costed
        for turn in range(len(expected)):
            self.root=original_root/str(turn);self.root.mkdir(mode=0o700);elapsed[0]=0;self.urls=[]
            result=self.collect(days=days,result_checks=checks,monotonic=lambda:elapsed[0],
                budget_seconds=4,clock=lambda turn=turn:NOW+timedelta(minutes=10*turn))
            self.assertLessEqual(len(self.urls),4)
            self.assertEqual(result['safe_report']['checked_races'],1)
            checks.update(result['result_checks'])
        self.assertEqual(set(checks),expected)


if __name__=='__main__':unittest.main()
