"""First-race facts change the next same-day card once, with canonical K replay."""
from datetime import datetime,timezone
import unittest
from race_ai.racer_daily import DailyStore,JST
from race_ai.racer_intraday_source import parse_result
from tests.intraday_fixture import packet,result_document
from tests.test_boat_venue_history import archive
from tests.test_racer_daily import ROSTER,NOW

def live():return dict(day='2026-11-07',last_checked_at=NOW.isoformat(),latest_result_at='2026-11-07T01:10:00Z',expected_races=12,confirmed_races=1,pending_races=11,schedule_complete=True,source_state='READY',revision_conflicts=0,source_receipts=[])

class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.now=NOW;self.s=DailyStore(clock=lambda:self.now);self.addCleanup(self.s.close)
        self.s.record('2026-11-04',archive(),captured_at='2026-11-05T00:00:00Z')
        raw,receipt=packet(result_document(venue='17'));self.rows=parse_result(raw,receipt,now=NOW)['rows']
    def catalogue(self,rows):
        meta=live();meta.update(day=self.now.astimezone(JST).date().isoformat(),last_checked_at=self.now.isoformat())
        try:return self.s.catalogue(ROSTER,as_of=self.now.isoformat(),extra_rows=rows,live=meta)
        except TypeError as e:self.fail('confirmed same-day result is not connected to the aggregate: '+str(e))
    def test_morning_result_increases_same_registration_and_actual_course_for_afternoon_card(self):
        d=self.catalogue(self.rows);p=d['people'][0]
        self.assertEqual(d['schema'],'RACE_AI_RACER_DAILY_V2')
        self.assertEqual((p['summary']['starts'],p['summary']['wins'],p['courses'][1]['starts']),(4,2,2))
        self.assertEqual(p['today_stats']['starts'],1);self.assertEqual(p['today_races'][0]['race_id'],'20261107-17-01')
        self.assertEqual(p['today_races'][0]['course'],2)
        self.assertEqual(d['today']['confirmed_races'],1)
    def test_duplicate_and_later_revision_replace_instead_of_adding_a_second_start(self):
        newer=[dict(r,captured_at='2026-11-07T01:20:00Z',finish=2 if r['racer_id']=='4001' else r['finish']) for r in self.rows]
        d=self.catalogue(self.rows+self.rows+newer);p=d['people'][0]
        self.assertEqual((p['summary']['starts'],p['summary']['wins']),(4,1));self.assertEqual(len(p['today_races']),1)
    def test_next_day_k_replaces_all_six_sp_rows_without_double_counting(self):
        self.now=datetime(2026,11,8,2,tzinfo=timezone.utc)
        self.s.record('2026-11-07',archive(day='2026-11-07'),captured_at=self.now.isoformat())
        d=self.catalogue(self.rows);p=d['people'][0]
        self.assertEqual(p['summary']['starts'],6)
        self.assertEqual(p['courses'][1]['starts'],2,'K actual course takes priority; SP cannot be counted again')
        self.assertEqual(self.s.catalogue(ROSTER,as_of=self.now.isoformat())['people'][0]['summary'],p['summary'])
    def test_future_or_partial_race_is_not_admitted(self):
        for rows in [self.rows[:-1],[dict(r,captured_at='2026-11-08T00:00:00Z') for r in self.rows]]:
            with self.subTest(),self.assertRaises(ValueError):self.catalogue(rows)
