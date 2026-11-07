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
        s.advance(base,now=NOW,fetch=fetch,max_requests=2,result_targets=[target])
        self.assertIn(target['race_id'],s.control['settlement_captures']);self.assertEqual(len(calls),2)
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
