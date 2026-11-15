"""Source-free national P1 priority: optional source reads must not starve P1.

The fake body and timestamps are not real source/forecast acceptance evidence.
"""
from datetime import datetime,timedelta,timezone
import unittest
from unittest.mock import patch
import race_ai
from pathlib import Path
PIN=str(Path(__file__).resolve().parents[1]/'pr64-reference/race_ai')
if PIN not in race_ai.__path__:race_ai.__path__.append(PIN)
from scripts import boat_nationwide_ab_pilot as pilot

NOW=datetime(2030,4,1,3,35,tzinfo=timezone.utc)
DAY=NOW.astimezone(pilot.JST).date()
CUTOFF=(NOW+timedelta(minutes=20)).astimezone(pilot.JST).isoformat()
RACE=dict(race_id='20300401-01-01',cutoff_at=CUTOFF)

def official_program():
    return dict(race_id=RACE['race_id'],closed_at=CUTOFF,race_status='LISTED',boats=[
        dict(lane=i,entry_status='listed',racer_registration_id=f'{1000+i}')
        for i in (1,3,6)])

class MandatoryExhibitionPriorityTests(unittest.TestCase):
    def evaluate(self, data):
        observed=dict(context=dict(schema='FICTIONAL_CONTEXT'),data=data)
        requests=[]
        def fake_get(url, **kw):
            requests.append(url)
            return b'fictional-source',NOW,'a'*64
        waiting=dict(state='WAITING_PUBLICATION',reason='EXHIBITION_NOT_READY',retry_at=None,
                     race_id=RACE['race_id'],cutoff_at=CUTOFF)
        with patch.object(pilot,'_clock',return_value=NOW), \
             patch.object(pilot,'get',side_effect=fake_get), \
             patch.object(pilot,'parse_official_racelist',return_value=official_program()), \
             patch.object(pilot,'parse_active_beforeinfo',return_value=observed), \
             patch.object(pilot,'collect_pitreport') as pit, \
             patch.object(pilot,'collect_entry_history') as history, \
             patch.object(pilot,'_publication_wait',return_value=waiting) as pub:
            result=pilot.make_pair(DAY,RACE)
        return result,requests,pit,history,pub,waiting

    def test_missing_published_exhibition_does_not_collect_optional_sources(self):
        result,requests,pit,history,pub,wait=self.evaluate(None)
        self.assertEqual(result[0]['state'],'EXHIBITION_NOT_FULLY_PUBLISHED')
        self.assertEqual(result[0]['source_wait'],wait)
        self.assertEqual(result[1:],(None,None,None,None))
        self.assertEqual(len(requests),2) # one racelist and one beforeinfo, no more
        self.assertIn('beforeinfo',requests[1])
        pit.assert_not_called();history.assert_not_called()
        pub.assert_called_once()

    def test_partial_real_lanes_wait_without_adding_phantom_boats_or_optional_gets(self):
        # 1, 3, 6 are real active lanes: do not renumber to 1,2,3.
        data={'boats':[dict(lane=i,display_time=None) for i in (1,3,6)]}
        result,requests,pit,history,pub,wait=self.evaluate(data)
        self.assertEqual(result[0]['state'],'EXHIBITION_TIME_INCOMPLETE')
        self.assertEqual(result[0]['source_wait'],wait)
        self.assertEqual(result[1:],(None,None,None,None))
        self.assertEqual(len(requests),2)
        pit.assert_not_called();history.assert_not_called()
        pub.assert_called_once()


if __name__=='__main__':unittest.main()
