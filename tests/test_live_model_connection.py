"""Already-retained synthetic official pages; no live transport."""
from datetime import date,datetime,timezone
import importlib
import os
from hashlib import sha256
from unittest.mock import patch
import unittest
from tests.test_boat_active_exhibition import program,main_table,start_table
from tests.test_boat_observation_context import frame,url

class LiveConnectionTests(unittest.TestCase):
 def pilot(self):
  return importlib.import_module('scripts.boat_nationwide_ab_pilot')
 def run_pair(self,*,withdrawn=(),missing=()):
  p=self.pilot();source=program(withdrawn=withdrawn)
  raw=frame(main_table(missing=missing)+start_table(lanes=tuple(n for n in range(1,7) if n not in withdrawn)))
  now=datetime(2030,4,1,9,0,tzinfo=timezone.utc)
  race=dict(race_id=source['race_id'],cutoff_at=source['closed_at'])
  def captured(uri,**kwargs):return raw,now,source['source_sha256'] if '/racelist?' in uri else sha256(raw).hexdigest()
  with patch.dict(os.environ,{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true'}),patch.object(p,'parse_official_racelist',return_value=source),patch.object(p,'get',side_effect=captured),patch.object(p,'_clock',return_value=now),patch.object(p,'observed_timestamp',return_value=now.isoformat()),patch.object(p,'collect_pitreport',return_value=None),patch.object(p,'collect_entry_history',return_value=None):
   return p.make_pair(date(2030,4,1),race)
 def test_explicit_withdrawal_does_not_block_the_remaining_five_exhibitions(self):
  status,pair,extended,priced,observed=self.run_pair(withdrawn=(6,),missing=(6,))
  self.assertIsNotNone(pair,status)
  self.assertEqual(len(pair['models'][0]['full_120']),60)
  self.assertTrue(all('6' not in r['ticket'].split('-') for r in pair['models'][0]['full_120']))
  self.assertEqual(len(observed['snapshot']['participants']),5)
 def test_an_unpublished_active_time_remains_pending(self):
  status,pair,*_=self.run_pair(withdrawn=(6,),missing=(3,6))
  self.assertIsNone(pair);self.assertEqual(status['state'],'EXHIBITION_TIME_INCOMPLETE')


 def test_required_p1_inputs_are_preserved_before_optional_odds(self):
  p=self.pilot();source=program()
  raw=frame(main_table()+start_table(lanes=tuple(range(1,7))))
  now=datetime(2030,4,1,9,0,tzinfo=timezone.utc)
  race=dict(race_id=source['race_id'],cutoff_at=source['closed_at'])
  class Budget:
   def __init__(self,remaining):self.left=remaining
   def remaining(self):return self.left
  def captured(uri,**kwargs):
   return raw,now,source['source_sha256'] if '/racelist?' in uri else sha256(raw).hexdigest()
  setup=(patch.dict(os.environ,{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true'}),
         patch.object(p,'parse_official_racelist',return_value=source),
         patch.object(p,'_clock',return_value=now),
         patch.object(p,'observed_timestamp',return_value=now.isoformat()),
         patch.object(p,'collect_pitreport',return_value=None),
         patch.object(p,'collect_entry_history',return_value=None))
  from contextlib import ExitStack
  with ExitStack() as stack:
   for adapter in setup:stack.enter_context(adapter)
   with patch.object(p,'SOURCE_GUARD',Budget(4)),patch.object(p,'get',side_effect=captured) as get:
    status,pair,extended,priced,observed=p.make_pair(date(2030,4,1),race,reserved_next_gets=4)
    self.assertIsNotNone(pair,status)
    self.assertIsNotNone(observed,status)
    self.assertEqual(priced['state'],'OPTIONAL_ODDS_DEFERRED_FOR_REQUIRED_P1_GETS')
    self.assertEqual(get.call_count,2)
    self.assertTrue(all('odds3t' not in args[0][0] for args in get.call_args_list))
   with patch.object(p,'SOURCE_GUARD',Budget(5)),patch.object(p,'get',side_effect=captured) as get:
    status,pair,_,_,observed=p.make_pair(date(2030,4,1),race,reserved_next_gets=4)
    self.assertIsNotNone(pair,status)
    self.assertIsNotNone(observed,status)
    self.assertEqual(get.call_count,3)
    self.assertIn('odds3t',get.call_args_list[-1][0][0])

 def test_unknown_optional_budget_fails_closed(self):
  p=self.pilot()
  class Unknown:
   def remaining(self):return None
  with patch.object(p,'SOURCE_GUARD',Unknown()):
   with self.assertRaisesRegex(ValueError,'OPTIONAL_SOURCE_REMAINING_INVALID'):
    p._optional_source_allowed(2)
  with patch.object(p,'SOURCE_GUARD',object()):
   self.assertFalse(p._optional_source_allowed(2))

if __name__=='__main__':unittest.main()
