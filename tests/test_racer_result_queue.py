"""Settlement targets share the actual athlete collector's request budget."""
from datetime import timedelta
import unittest
from tests import test_racer_intraday as RuntimeFixtures
from tests.test_boat_sp_settlement import document
from tests.intraday_fixture import packet,day_index
from tests.test_racer_daily import NOW
from race_ai.racer_intraday import IntradayState
from race_ai.racer_intraday_source import identity

class ResultQueueTests(unittest.TestCase):
    state=RuntimeFixtures.RuntimeTests.state
    base=RuntimeFixtures.RuntimeTests.base
    def targets(self,day='20261107',count=2):
        return [dict(race_id=f'{day}-17-{n:02d}',cutoff_at=f'{day[:4]}-{day[4:6]}-{day[6:]}T10:00:00+09:00',pending=True) for n in range(1,count+1)]
    def source_results(self,*,price='1250',day='20261107'):
        calls=[]
        def fetch(url):
            calls.append(url)
            if '/race/index?' in url:return day_index(venues=('17',),day=day),NOW.isoformat()
            date,venue,n=identity(url);d=document(day=date.replace('-',''),venue=venue,number=n);d['raceheader']['rlinklist'][n-1]['deadline']='10:00';d['maindata']['infolist3t'][0]['dividend']=price
            return packet(d)[0],NOW.isoformat()
        return calls,fetch
    def test_pending_result_is_fetched_even_when_K_already_contains_its_statistics(self):
        s=self.state();base=self.base();calls,fetch=self.source_results();target=self.targets('20261104')[0]
        s.advance(base,now=NOW,fetch=fetch,max_requests=2);calls.clear()
        s.advance(base,now=NOW,fetch=fetch,max_requests=1,result_targets=[target])
        self.assertIn(target['race_id'],s.control['settlement_captures']);self.assertEqual(len(calls),1)
        s.extra_rows(base,now=NOW+timedelta(days=3));self.assertIn(target['race_id'],s.control['settlement_captures'])
    def test_payout_only_change_retains_a_new_settlement_while_unchanged_replay_does_not(self):
        s=self.state();base=self.base();calls,fetch=self.source_results();target=self.targets(count=1)
        s.advance(base,now=NOW,fetch=fetch,max_requests=2,result_targets=target);first=dict(s.control['settlement_captures'][target[0]['race_id']]);captures=len(s.new_captures)
        s.advance(base,now=NOW+timedelta(minutes=5),fetch=fetch,max_requests=1,result_targets=target)
        self.assertEqual(s.control['settlement_captures'][target[0]['race_id']],first);self.assertEqual(len(s.new_captures),captures)
        _,revised=self.source_results(price='1500');s.advance(base,now=NOW+timedelta(minutes=10),fetch=revised,max_requests=1,result_targets=target)
        self.assertNotEqual(s.control['settlement_captures'][target[0]['race_id']]['settlement_sha256'],first['settlement_sha256'])
    def test_fast_result_only_first_check_is_one_minute_after_cutoff(self):
        s=self.state();base=self.base();calls,fetch=self.source_results()
        cutoff=NOW+timedelta(minutes=10)
        target=dict(race_id='20261107-19-11',cutoff_at=cutoff.isoformat(),pending=True)
        first=cutoff+timedelta(seconds=59)
        s.advance(base,now=first,fetch=fetch,max_requests=2,result_targets=[target])
        self.assertFalse(any('jcd=19' in url and 'rno=11' in url for url in calls),
                         'never GET this race before the one-minute first result check')
        calls.clear()
        second=cutoff+timedelta(minutes=1)
        def stamped(url):
            raw,_=fetch(url)
            return raw,second.isoformat()
        s.advance(base,now=second,fetch=stamped,max_requests=2,result_targets=[target])
        self.assertTrue(any('jcd=19' in url and 'rno=11' in url for url in calls),
                        'a newly due race must not wait a fixed five minutes')

    def test_pending_official_result_retries_at_two_minutes_with_one_get_per_run(self):
        s=self.state();base=self.base();calls=[]
        from tests.intraday_fixture import result_document,packet,day_index
        from race_ai.racer_intraday_source import identity
        cutoff=NOW+timedelta(minutes=8)
        target=dict(race_id='20261107-19-11',cutoff_at=cutoff.isoformat(),pending=True)
        def pending(now):
            def fetch(url):
                calls.append(url)
                if '/race/index?' in url:
                    return day_index(venues=('01',)),now.isoformat()
                day,venue,number=identity(url)
                doc=result_document(day=day.replace('-',''),venue=venue,number=number,pending=True)
                # Keep the official deadline aligned with the saved cutoff.
                # A genuinely postponed race must keep its longer wait.
                if venue=='19' and number==11:
                    doc['raceheader']['rlinklist'][number-1]['deadline']='11:08'
                raw,_=packet(doc)
                return raw,now.isoformat()
            return fetch
        first=cutoff+timedelta(minutes=1)
        s.advance(base,now=first,fetch=pending(first),max_requests=2,result_targets=[target])
        first_count=sum('jcd=19' in u and 'rno=11' in u for u in calls)
        self.assertEqual(first_count,1)
        s.advance(base,now=first+timedelta(minutes=1),fetch=pending(first+timedelta(minutes=1)),max_requests=2,result_targets=[target])
        self.assertEqual(first_count,sum('jcd=19' in u and 'rno=11' in u for u in calls))
        s.advance(base,now=first+timedelta(minutes=2),fetch=pending(first+timedelta(minutes=2)),max_requests=2,result_targets=[target])
        self.assertEqual(first_count+1,sum('jcd=19' in u and 'rno=11' in u for u in calls))
        self.assertLessEqual(len(calls),6,'the existing two GET per run cap must never grow')

    def test_previous_saved_day_can_catch_up_after_midnight_without_new_day_index(self):
        s=self.state();base=self.base();calls,fetch=self.source_results();late=NOW+timedelta(hours=13,minutes=5)
        s.advance(base,now=late,fetch=fetch,max_requests=2,result_targets=self.targets())
        self.assertEqual(len(calls),2);self.assertTrue(all('/spdata?' in url and 'hd=20261107' in url for url in calls));self.assertEqual(len(s.control['settlement_captures']),2)
    def test_result_targets_share_hard_budget_and_do_not_fetch_future_cutoffs(self):
        s=self.state();base=self.base();calls,fetch=self.source_results();targets=self.targets(count=12)
        targets[0]['cutoff_at']='2026-11-07T19:00:00+09:00'
        s.advance(base,now=NOW,fetch=fetch,max_requests=3,result_targets=targets)
        self.assertLessEqual(len(calls),3);self.assertNotIn(targets[0]['race_id'],s.control['settlement_captures']);self.assertTrue(s.control['settlement_captures'])
    def test_newer_foreign_rejection_requires_a_fresh_receipt_even_for_unchanged_facts(self):
        s=self.state();base=self.base();calls,fetch=self.source_results();target=self.targets(count=1)
        s.advance(base,now=NOW,fetch=fetch,max_requests=2,result_targets=target)
        target[0]['after']=(NOW+timedelta(minutes=1)).isoformat();later=NOW+timedelta(minutes=5)
        def fresh(url):raw,_=fetch(url);return raw,later.isoformat()
        s.advance(base,now=later,fetch=fresh,max_requests=1,result_targets=target)
        self.assertEqual(s.control['settlement_captures'][target[0]['race_id']]['captured_at'],later.isoformat())
    def test_old_result_backlog_cannot_starve_today_venue_discovery(self):
        s=self.state();base=self.base();calls,fetch=self.source_results()
        def venues(url):return (day_index(('01','02','03','04')),NOW.isoformat()) if '/race/index?' in url else fetch(url)
        s.advance(base,now=NOW,fetch=venues,max_requests=4,result_targets=self.targets('20261104',count=12))
        self.assertEqual(len(s.control['meetings']),3,'today headers need capacity before old unsettled races')
    def test_yesterday_unpublished_stats_cannot_take_the_last_slot_from_a_new_today_result(self):
        s=self.state();base=self.base();calls,fetch=self.source_results();s.advance(base,now=NOW,fetch=fetch,max_requests=2)
        s.control['races']['20261105-17-01']=dict(cutoff_at='2026-11-05T10:00:00+09:00',next_check='2026-11-05T10:05:00+09:00')
        s.control['races']['20261107-17-02']=dict(cutoff_at='2026-11-07T10:30:00+09:00',next_check='2026-11-07T10:35:00+09:00')
        s.advance(base,now=NOW,fetch=fetch,max_requests=1)
        self.assertIn('hd=20261107',calls[-1]);self.assertTrue(calls[-1].endswith('&rno=2'))
