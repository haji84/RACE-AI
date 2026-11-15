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
