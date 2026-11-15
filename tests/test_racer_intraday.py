"""Bounded live queue and existing-base integration, using invented source facts."""
from datetime import datetime,timedelta,timezone
import json,unittest
from tests.intraday_fixture import result_document,packet,day_index
from tests.test_racer_daily import NOW,ROSTER
from race_ai.racer_daily import DailyStore
from tests.test_boat_venue_history import archive
from race_ai.source_retry_policy import SourceWait
try:
    from race_ai.racer_intraday import IntradayState
except ImportError:IntradayState=None

class RuntimeTests(unittest.TestCase):
    def state(self):
        self.assertIsNotNone(IntradayState,'confirmed results need a resumable per-race queue')
        return IntradayState()
    def base(self):
        s=DailyStore(clock=lambda:NOW);self.addCleanup(s.close);s.record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z');return s
    def source(self,venues=('01',),*,pending=False):
        calls=[]
        def fetch(url):
            calls.append(url)
            if '/race/index?' in url:return day_index(venues),NOW.isoformat()
            from race_ai.racer_intraday_source import identity
            day,venue,n=identity(url);raw,_=packet(result_document(day=day.replace('-',''),venue=venue,number=n,pending=pending))
            return raw,NOW.isoformat()
        return calls,fetch
    def test_first_result_is_in_next_same_day_aggregate_and_repeated_get_does_not_add_start(self):
        s=self.state();base=self.base();calls,fetch=self.source()
        report=s.advance(base,now=NOW,fetch=fetch,max_requests=2)
        self.assertEqual(report['requests'],2);self.assertEqual(s.metadata(NOW)['confirmed_races'],1)
        d=base.catalogue(ROSTER,as_of=NOW.isoformat(),extra_rows=s.extra_rows(base,now=NOW),live=s.metadata(NOW))
        self.assertEqual(d['people'][0]['summary']['starts'],4)
        s.advance(base,now=NOW+timedelta(minutes=5),fetch=fetch,max_requests=2)
        self.assertEqual(s.metadata(NOW)['confirmed_races'],1)
    def test_queue_fairness_spreads_bootstrap_across_venues_with_hard_budget(self):
        s=self.state();base=self.base();calls,fetch=self.source(('01','02','03','04'))
        s.advance(base,now=NOW,fetch=fetch,max_requests=3)
        self.assertEqual(len(calls),3)
        s.advance(base,now=NOW+timedelta(minutes=5),fetch=fetch,max_requests=2)
        self.assertEqual(len(calls),5)
        self.assertEqual(s.metadata(NOW)['expected_races'],48)
        self.assertEqual(s.metadata(NOW)['confirmed_races'],4)
    def test_retry_wait_blocks_host_until_retry_after_without_more_calls(self):
        s=self.state();base=self.base();calls=[]
        def limited(url):calls.append(url);raise SourceWait('SOURCE_RATE_LIMITED',(NOW+timedelta(hours=1)).isoformat(),state='WAIT')
        s.advance(base,now=NOW,fetch=limited,max_requests=12)
        s.advance(base,now=NOW+timedelta(minutes=5),fetch=limited,max_requests=12)
        self.assertEqual(len(calls),1);self.assertEqual(s.metadata(NOW)['source_state'],'SOURCE_WAIT')
    def test_future_known_races_are_not_polled_and_unreconciled_old_facts_are_retained(self):
        s=self.state();base=self.base();calls,fetch=self.source()
        s.advance(base,now=NOW,fetch=fetch,max_requests=2);first=len(calls)
        s.advance(base,now=NOW+timedelta(minutes=5),fetch=fetch,max_requests=12)
        self.assertEqual(len(calls),first)
        later=NOW+timedelta(days=3)
        rows=s.extra_rows(base,now=later)
        self.assertEqual(len(rows),6,'a missing K race must not disappear merely because it is no longer today')
    def test_jst_morning_result_keeps_its_provenance_before_utc_midnight(self):
        s=self.state();base=self.base();morning=datetime(2026,11,6,23,40,tzinfo=timezone.utc)
        def fetch(url):
            if '/race/index?' in url:return day_index(),morning.isoformat()
            d=result_document();d['raceheader']['rlinklist'][0]['deadline']='08:30';raw,_=packet(d)
            return raw,morning.isoformat()
        s.advance(base,now=morning,fetch=fetch,max_requests=2)
        self.assertEqual(s.metadata(morning)['confirmed_races'],1)
        self.assertIsNotNone(s.metadata(morning)['latest_result_at'])
        self.assertEqual(len(s.metadata(morning)['source_receipts']),1)
    def test_new_day_bootstrap_cannot_be_redirected_to_yesterdays_pending_race(self):
        s=self.state();base=self.base();calls,fetch=self.source(pending=True)
        s.advance(base,now=NOW,fetch=fetch,max_requests=2)
        nextday=NOW+timedelta(days=1);urls=[]
        def tomorrow(url):
            urls.append(url)
            if '/race/index?' in url:return day_index(day='20261108'),nextday.isoformat()
            from race_ai.racer_intraday_source import identity
            day,venue,n=identity(url);raw,_=packet(result_document(day=day.replace('-',''),venue=venue,number=n,pending=True))
            return raw,nextday.isoformat()
        s.advance(base,now=nextday,fetch=tomorrow,max_requests=2)
        self.assertIn('hd=20261108',urls[-1]);self.assertTrue(s.metadata(nextday)['schedule_complete'])
    def test_unchanged_result_replay_keeps_identical_catalogue_but_advances_small_status_clock(self):
        s=self.state();base=self.base();calls,fetch=self.source();s.advance(base,now=NOW,fetch=fetch,max_requests=2)
        from race_ai import racer_intraday as module
        self.assertTrue(callable(getattr(module,'build_catalogue',None)),'incremental delivery needs deterministic replay of retained but unpublished facts')
        first=module.build_catalogue(base,s,ROSTER,now=NOW,base_sha='a'*64)
        s.advance(base,now=NOW+timedelta(minutes=5),fetch=fetch,max_requests=2)
        second=module.build_catalogue(base,s,ROSTER,now=NOW+timedelta(minutes=5),base_sha='a'*64)
        self.assertEqual(first,second);self.assertEqual(s.control['last_checked_at'],(NOW+timedelta(minutes=5)).isoformat())
    def test_pending_header_is_retained_without_becoming_a_finished_start(self):
        s=self.state();base=self.base();calls,fetch=self.source(pending=True);s.advance(base,now=NOW,fetch=fetch,max_requests=2)
        self.assertEqual(s.extra_rows(base,now=NOW),[])
        self.assertEqual(len(s.new_captures),2,'both dated day index and source-bound race deadlines need retained originals')
    def test_changed_deadline_moves_the_next_pending_probe_forward(self):
        s=self.state();base=self.base();calls,fetch=self.source();s.advance(base,now=NOW,fetch=fetch,max_requests=2)
        later=NOW+timedelta(minutes=30)
        def changed(url):
            d=result_document();d['raceheader']['rlinklist'][1]['deadline']='11:20';raw,_=packet(d);return raw,later.isoformat()
        s.advance(base,now=later,fetch=changed,max_requests=1)
        from race_ai.racer_daily import clock
        self.assertLessEqual(clock(s.control['races']['20261107-01-02']['next_check']),later)
    def test_newly_due_result_gets_the_saturated_budget_before_confirmed_revisions(self):
        s=self.state();base=self.base();calls,fetch=self.source();s.advance(base,now=NOW,fetch=fetch,max_requests=2)
        for n in range(2,13):
            q=s.control['races'][f'20261107-01-{n:02d}'];q.update(cutoff_at=NOW.isoformat(),next_check=(NOW+timedelta(minutes=31)).isoformat())
        later=NOW+timedelta(minutes=35)
        def newly_confirmed(url):
            from race_ai.racer_intraday_source import identity
            day,venue,number=identity(url);calls.append(url);doc=result_document(number=number);doc['raceheader']['rlinklist'][1]['deadline']='11:25';return packet(doc)[0],later.isoformat()
        before=len(calls);s.advance(base,now=later,fetch=newly_confirmed,max_requests=1)
        self.assertEqual(len(calls),before+1);self.assertTrue(calls[-1].endswith('&rno=2'),'new results must precede old result revision checks')
        self.assertIn('20261107-01-02',s.control['results'])
    def test_postponed_target_keeps_its_new_future_deadline(self):
        s=self.state();base=self.base();calls,fetch=self.source(pending=True);s.advance(base,now=NOW,fetch=fetch,max_requests=2)
        later=NOW+timedelta(minutes=5);seen=[]
        def postponed(url):
            seen.append(url);doc=result_document(pending=True);doc['raceheader']['rlinklist'][0]['deadline']='12:30';return packet(doc)[0],later.isoformat()
        s.advance(base,now=later,fetch=postponed,max_requests=1)
        s.advance(base,now=later+timedelta(minutes=5),fetch=postponed,max_requests=1)
        self.assertEqual(len(seen),1,'a postponed race must wait until the new cutoff plus publication delay')
