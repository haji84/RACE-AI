"""Invented official HTML: live observations never rewrite saved forecasts."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import unittest
from race_ai.racer_intraday import IntradayState
from race_ai.racer_intraday_transport import allowed
from race_ai import saved_view_feed as F
from race_ai.source_retry_policy import SourceWait
from tests.test_boat_observation_context import frame,before_table,starts,weather
from tests.test_racer_result_bridge import saved_view
try:
    from race_ai.racer_beforeinfo import collect_beforeinfo,project_beforeinfo
except ImportError:
    collect_beforeinfo=project_beforeinfo=None

AT=datetime(2030,4,1,10,45,tzinfo=timezone.utc)
URL='https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300401&jcd=12&rno=12'

def preview_view():
    view=saved_view(('2030-04-01',));row=view['records'][0]
    row.update(race_id='20300401-12-12',race_no=12,venue='住之江',cutoff_at='2030-04-01T20:30:00+09:00',saved_cutoff_variants=['2030-04-01T20:30:00+09:00'])
    row['prediction']['cutoff_at']=row['cutoff_at']
    return view

def html(*,published=True):
    return frame(before_table(display='6.72' if published else '&nbsp;',tilt='0.0')+starts(populated=published)+weather())

class BeforeinfoTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(collect_beforeinfo),'the regular collector must fetch and retain live beforeinfo')
        self.view=preview_view();self.row=self.view['records'][0];self.state=IntradayState()

    def fetch(self,raw,at=AT):
        def source(url):
            self.assertEqual(url,URL)
            return raw,at.isoformat()
        return source

    def test_official_beforeinfo_is_retained_and_projected_without_changing_originals(self):
        pin=F.originals_sha(self.view);inventory=F.forecast_inventory(self.view)
        report=collect_beforeinfo(self.state,[self.row],now=AT,fetch=self.fetch(html()),max_requests=4)
        self.assertEqual(report['requests'],1)
        live=project_beforeinfo(self.row,self.state,now=AT)
        self.assertEqual(live['state'],'READY')
        self.assertEqual(len(live['context']['beforeinfo']['participants']),6)
        self.assertEqual(live['context']['beforeinfo']['participants'][0]['display_time'],6.72)
        self.assertEqual(live['context']['beforeinfo']['weather']['wind_speed_mps'],0)
        self.row['live_boat_observation']=live
        self.assertEqual(F.originals_sha(self.view),pin)
        self.assertEqual(F.forecast_inventory(self.view),inventory)
        self.assertFalse(live['context']['forecast_inputs_used'])

    def test_unpublished_exhibition_keeps_weather_and_retries_when_values_appear(self):
        collect_beforeinfo(self.state,[self.row],now=AT,fetch=self.fetch(html(published=False)),max_requests=4)
        live=project_beforeinfo(self.row,self.state,now=AT)
        self.assertEqual(live['state'],'AWAITING_EXHIBITION')
        self.assertEqual(live['context']['beforeinfo']['weather']['wave_height_cm'],0)
        later=AT+timedelta(minutes=6)
        collect_beforeinfo(self.state,[self.row],now=later,fetch=self.fetch(html(),later),max_requests=4)
        self.assertEqual(project_beforeinfo(self.row,self.state,now=later)['state'],'READY')

    def test_wrong_registration_or_race_never_attaches(self):
        for raw in [html().replace(b'toban=4001',b'toban=4999'),html().replace(b'hd=20300401',b'hd=20300402')]:
            state=IntradayState()
            collect_beforeinfo(state,[self.row],now=AT,fetch=self.fetch(raw),max_requests=4)
            live=project_beforeinfo(self.row,state,now=AT)
            self.assertIsNone(live['context']);self.assertEqual(live['state'],'SOURCE_ERROR')

    def test_source_wait_is_persisted_without_discarding_previous_good_capture(self):
        collect_beforeinfo(self.state,[self.row],now=AT,fetch=self.fetch(html()),max_requests=4)
        original=project_beforeinfo(self.row,self.state,now=AT)['context']
        later=AT+timedelta(minutes=11)
        def blocked(url):
            error=SourceWait('HTTP429',(later+timedelta(minutes=10)).isoformat(),state='SOURCE_WAIT');error.plan={'http_status':429};raise error
        collect_beforeinfo(self.state,[self.row],now=later,fetch=blocked,max_requests=4)
        live=project_beforeinfo(self.row,self.state,now=later)
        self.assertEqual(live['state'],'SOURCE_WAIT');self.assertEqual(live['context'],original)
        calls=[]
        report=collect_beforeinfo(self.state,[self.row],now=later+timedelta(minutes=5),fetch=lambda u:calls.append(u),max_requests=4)
        self.assertEqual(report['requests'],0);self.assertEqual(calls,[])
        self.assertIn('boatrace',self.state.control['waits'])

    def test_each_due_race_gets_a_turn_instead_of_repeating_the_first_four(self):
        rows=[]
        for n in range(1,7):
            row=deepcopy(self.row);row['race_id']=f'20300401-12-{n:02d}';row['race_no']=n;rows.append(row)
        calls=[]
        def source(url):
            calls.append(url)
            error=SourceWait('HTTP404',(AT+timedelta(minutes=5)).isoformat(),state='SOURCE_WAIT');error.plan={'http_status':404};raise error
        collect_beforeinfo(self.state,rows,now=AT,fetch=source,max_requests=4)
        self.assertEqual(len(calls),4)
        collect_beforeinfo(self.state,rows,now=AT+timedelta(minutes=6),fetch=source,max_requests=4)
        self.assertEqual(len(calls),8)
        self.assertTrue(any('rno=5' in u for u in calls));self.assertTrue(any('rno=6' in u for u in calls))

    def test_unpublished_404_without_retry_after_does_not_disable_future_collection(self):
        def unavailable(url):
            error=SourceWait('SOURCE_REVIEW_REQUIRED',state='SOURCE_REVIEW_WAIT');error.plan={'http_status':404};raise error
        collect_beforeinfo(self.state,[self.row],now=AT,fetch=unavailable,max_requests=4)
        later=AT+timedelta(minutes=6)
        report=collect_beforeinfo(self.state,[self.row],now=later,fetch=self.fetch(html(),later),max_requests=4)
        self.assertEqual(report['requests'],1)
        self.assertEqual(project_beforeinfo(self.row,self.state,now=later)['state'],'READY')

    def test_post_cutoff_empty_exhibition_retries_until_the_official_values_arrive(self):
        after=AT+timedelta(minutes=50)
        collect_beforeinfo(self.state,[self.row],now=after,fetch=self.fetch(html(published=False),after),max_requests=4)
        later=after+timedelta(minutes=6)
        report=collect_beforeinfo(self.state,[self.row],now=later,fetch=self.fetch(html(),later),max_requests=4)
        self.assertEqual(report['requests'],1)
        self.assertEqual(project_beforeinfo(self.row,self.state,now=later)['state'],'READY')

    def test_transport_accepts_only_exact_official_beforeinfo_race_queries(self):
        self.assertGreater(allowed(URL),0)
        for url in [URL.replace('beforeinfo','purchase'),URL+'&token=x',URL.replace('www.boatrace.jp','evil.test'),URL.replace('jcd=12','jcd=25'),URL.replace('rno=12','rno=13')]:
            with self.assertRaises(ValueError):allowed(url)

    def test_supported_registration_aliases_collect_but_conflicting_aliases_do_not(self):
        for person in self.row['participants']:person['registration_number']=person.pop('registration_no')
        report=collect_beforeinfo(self.state,[self.row],now=AT,fetch=self.fetch(html()),max_requests=4)
        self.assertEqual(report['parsed'],1)
        bad=deepcopy(self.row);bad['participants'][0]['registration_no']='4999'
        calls=[];report=collect_beforeinfo(IntradayState(),[bad],now=AT,fetch=lambda u:calls.append(u),max_requests=4)
        self.assertEqual(report['requests'],0);self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
