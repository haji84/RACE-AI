"""As-of-safe daily aggregation tests (synthetic only)."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.daily import build_daily
from race_ai.core import SourceError

CAPTURE='2026-10-14T05:58:00+09:00'
PUBLISHED='2026-10-14T05:57:00+09:00'
ASOF='2026-10-14T06:00:00+09:00'


def meta(**kwargs):
    return dict(rights_confirmed=True,published_at=PUBLISHED,
                captured_at=CAPTURE,**kwargs)


class DailyCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.write('inventory',meta(venues=[
          dict(venue='19',motor_cycle='2026-A',motors=[11,12])],
          current_meet_id_by_venue={'19':'shimonoseki_20261014'}))
    def tearDown(self):
        self.temp.cleanup()
    def write(self,stem,item):
        (self.root/(stem+'.json')).write_text(json.dumps(item),encoding='utf-8')
    def observation(self,motor=11,baseline=.3,finish=2):
        r=meta(venue='19',motor_cycle='2026-A',motor_no=motor,
          race_id='20261012-19-09',meeting_id='shimonoseki_20261012',
          racer_id='4999',lane=1,actual_course=1,
          race_at='2026-10-12T19:00:00+09:00',finish=finish,
          racer_experience_starts=50,rider_label='rookie',
          source_name='synthetic-official-structure')
        r['published_at']='2026-10-12T19:20:00+09:00'
        r['captured_at']='2026-10-12T19:21:00+09:00'
        if baseline is not None:
            r.update(baseline_top2=baseline,baseline_model='motor_blind_v1',
              baseline_decision_at='2026-10-12T18:50:00+09:00',
              baseline_excludes_motor=True)
        return r
    def bind(self,motor=11,lane=1):
        return meta(venue='19',motor_cycle='2026-A',motor_no=motor,
            race_id='20261014-19-09',lane=lane)
    def exhibition(self):
        return meta(race_id='20261014-19-09',source_name='synthetic',
          metrics=[
            dict(lane=1,metric='display',value=6.78),
            dict(lane=1,metric='lap',value=37.10),
            dict(lane=1,metric='turn',value=5.57),
            dict(lane=1,metric='straight',value=6.06),
            dict(lane=1,metric='start_exhibition',value=.11)])

    def test_both_motors_reported_even_with_missing_sources(self):
        report=build_daily(self.root,ASOF)
        self.assertEqual(report['inventory_count'],2)
        self.assertEqual(report['history_count'],0)
        self.assertEqual(report['current_exhibition_motor_count'],0)
        self.assertEqual(report['status'],'PARTIAL_VENUE_SCOPE')
        self.assertIn('HISTORICAL_RACE_RESULTS',report['motors'][1]['needs'])
        self.assertEqual(report['motors'][1]['rider_adjusted_motor_residual'],None)

    def test_history_join_and_same_race_display(self):
        self.write('motor_observations',meta(rows=[self.observation()]))
        self.write('assignments',meta(rows=[self.bind()]))
        self.write('exhibition',meta(rows=[self.exhibition()]))
        report=build_daily(self.root,ASOF)
        self.assertEqual(report['inventory_count'],2)
        self.assertEqual(report['history_count'],1)
        self.assertEqual(report['current_exhibition_motor_count'],1)
        found=report['motors'][0]
        self.assertEqual(found['motor_no'],11)
        self.assertTrue(found['previous_rider_is_rookie'])
        self.assertEqual(found['prior_meet']['meeting_id'],'shimonoseki_20261012')
        self.assertIsNotNone(found['rider_adjusted_motor_residual'])
        self.assertEqual(found['current_exhibition'][0]['metrics']['turn']['value'],5.57)
        self.assertTrue(found['current_exhibition'][0]['complete'])
        self.assertIn('CURRENT_DAY_MOTOR_ASSIGNMENT',report['motors'][1]['needs'])
        self.assertIn('motor_observations',report['source_sha256'])

    def test_future_source_is_not_used(self):
        self.write('exhibition',meta(rows=[
          {**self.exhibition(),'captured_at':'2026-10-14T06:01:00+09:00'}]))
        with self.assertRaises(SourceError):
            build_daily(self.root,ASOF)

    def test_partial_exhibition_marks_missing(self):
        self.write('assignments',meta(rows=[self.bind()]))
        e=self.exhibition()
        e['metrics']=e['metrics'][:1]
        self.write('exhibition',meta(rows=[e]))
        report=build_daily(self.root,ASOF)
        metrics=report['motors'][0]['current_exhibition'][0]['metrics']
        self.assertEqual(metrics['lap']['value'],None)
        self.assertEqual(metrics['turn']['missing_reason'],'not supplied or not published by decision time')
        self.assertFalse(report['motors'][0]['current_exhibition'][0]['complete'])

    def test_no_inventory_safe_stop(self):
        (self.root/'inventory.json').unlink()
        with self.assertRaises(SourceError):
            build_daily(self.root,ASOF)

    def test_duplicate_motor_inventory_rejected(self):
        self.write('inventory',meta(venues=[
          dict(venue='19',motor_cycle='2026-A',motors=[11,11])]))
        with self.assertRaises(SourceError):
            build_daily(self.root,ASOF)

    def test_assignment_outside_inventory_rejected(self):
        self.write('assignments',meta(rows=[self.bind(motor=98)]))
        with self.assertRaises(SourceError):
            build_daily(self.root,ASOF)

    def test_no_unsupported_actual_source_verification_claim(self):
        report=build_daily(self.root,ASOF)
        self.assertEqual(report['official_confirmation'],'UNVERIFIED')
        self.assertFalse(report['automatic_web_collection'])
        self.assertNotEqual(report['status'],'COMPLETE')

    def test_future_day_assignment_rejected(self):
        x=self.bind()
        x['race_id']='20261015-19-09'
        self.write('assignments',meta(rows=[x]))
        with self.assertRaises(SourceError):
            build_daily(self.root,ASOF)


if __name__=='__main__':
    unittest.main()
