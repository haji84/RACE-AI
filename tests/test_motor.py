"""Synthetic cases only. Not validation against official race files."""
import tempfile
import unittest
from pathlib import Path

from race_ai.core import SourceError, connect
from race_ai.motor import (setup_motor, import_motor_observation, import_motor_service,
                           analyze_motor)


class MotorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.tmp.name)/'motor.db')
        setup_motor(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def race(self, *, race_id='20261001-19-01', racer_id='5001', label='rookie',
             finish=5, baseline=None, race_at='2026-10-01T13:00:00+09:00',
             published_at='2026-10-01T16:00:00+09:00',
             captured_at='2026-10-01T17:00:00+09:00'):
        row=dict(venue='19',motor_cycle='2026-A',motor_no=11,
                 race_id=race_id,racer_id=racer_id,rider_label=label,finish=finish,
                 lane=6,actual_course=6,race_at=race_at,published_at=published_at,
                 captured_at=captured_at,rights_confirmed=True,
                 source_name='synthetic fixture')
        if baseline is not None:
            row.update(baseline_top2=baseline,baseline_model='unit-test-motor-blind',
                       baseline_decision_at='2026-09-30T12:00:00+09:00',
                       baseline_excludes_motor=True)
        return row

    def test_rookie_failure_is_less_negative_than_strong_rider_failure(self):
        self.assertEqual(import_motor_observation(self.db,self.race(baseline=.1))['rows'],1)
        first=analyze_motor(self.db,'19','2026-A',11,'2026-10-02T00:00:00+09:00')
        self.assertEqual(first['rookie_ridden_n'],1)
        self.assertEqual(first['latest_previous_rider']['rider_label'],'rookie')
        self.assertLess(first['adjusted_rider_neutral_residual'],0)
        self.assertEqual(first['adjusted_sample_n'],1)
        import_motor_observation(self.db,self.race(race_id='20261002-19-01',racer_id='4002',
             label='other',finish=5,baseline=.8,race_at='2026-10-02T13:00:00+09:00',
             published_at='2026-10-02T16:00:00+09:00',
             captured_at='2026-10-02T17:00:00+09:00'))
        result=analyze_motor(self.db,'19','2026-A',11,'2026-10-03T00:00:00+09:00')
        self.assertLess(result['adjusted_rider_neutral_residual'],
                        first['adjusted_rider_neutral_residual'])
        self.assertEqual(result['finish_sample_n'],2)

    def test_rookie_label_does_not_change_adjustment(self):
        row=self.race(label='rookie',finish=1,baseline=.1)
        import_motor_observation(self.db,row)
        result=analyze_motor(self.db,'19','2026-A',11,'2026-10-02T00:00:00+09:00')
        self.assertGreater(result['adjusted_rider_neutral_residual'],0)
        self.assertEqual(result['raw_top2_rate'],1)

    def test_missing_baseline_means_no_adjusted_motor_score(self):
        import_motor_observation(self.db,self.race())
        r=analyze_motor(self.db,'19','2026-A',11,'2026-10-02T00:00:00+09:00')
        self.assertIsNone(r['adjusted_rider_neutral_residual'])
        self.assertEqual(r['confidence'],'INSUFFICIENT_BASELINE')

    def test_cannot_leak_after_decision(self):
        import_motor_observation(self.db,self.race())
        r=analyze_motor(self.db,'19','2026-A',11,'2026-10-01T15:00:00+09:00')
        self.assertEqual(r['finish_sample_n'],0)

    def test_cannot_forge_pre_race_baseline(self):
        bad=self.race(baseline=.4)
        bad['baseline_decision_at']='2026-10-03T13:00:00+09:00'
        with self.assertRaises(SourceError): import_motor_observation(self.db,bad)
        bad['baseline_decision_at']='2026-09-30T13:00:00+09:00'
        bad['baseline_excludes_motor']=False
        with self.assertRaises(SourceError): import_motor_observation(self.db,bad)

    def test_motor_cycle_not_mixed(self):
        import_motor_observation(self.db,self.race(baseline=.2))
        r=analyze_motor(self.db,'19','2027-A',11,'2026-10-03T00:00:00+09:00')
        self.assertEqual(r['finish_sample_n'],0)

    def test_major_parts_service_separates_prior_state(self):
        import_motor_observation(self.db,self.race(baseline=.1))
        event=dict(venue='19',motor_cycle='2026-A',motor_no=11,event_id='gear-2026-10-02',
                   service_at='2026-10-02T08:00:00+09:00',
                   published_at='2026-10-02T10:00:00+09:00',
                   captured_at='2026-10-02T10:15:00+09:00',change_type='gear_case_replaced',
                   rights_confirmed=True)
        import_motor_service(self.db,event)
        r=analyze_motor(self.db,'19','2026-A',11,'2026-10-03T00:00:00+09:00')
        self.assertEqual(r['finish_sample_n'],0)
        self.assertTrue(r['service_warning'])

    def test_service_future_publication_does_not_leak(self):
        import_motor_observation(self.db,self.race(baseline=.1))
        event=dict(venue='19',motor_cycle='2026-A',motor_no=11,event_id='major-2026-10-02',
                   service_at='2026-10-02T08:00:00+09:00',
                   published_at='2026-10-04T10:00:00+09:00',
                   captured_at='2026-10-04T11:00:00+09:00',change_type='major_parts_replaced',
                   rights_confirmed=True)
        import_motor_service(self.db,event)
        r=analyze_motor(self.db,'19','2026-A',11,'2026-10-03T00:00:00+09:00')
        self.assertEqual(r['finish_sample_n'],1)

    def test_invalid_probability_and_duplicate_observation(self):
        bad=self.race(baseline=1.2)
        with self.assertRaises(SourceError):import_motor_observation(self.db,bad)
        row=self.race(baseline=.2)
        import_motor_observation(self.db,row)
        import_motor_observation(self.db,row)
        self.assertEqual(analyze_motor(self.db,'19','2026-A',11,'2026-10-03T00:00:00+09:00')['finish_sample_n'],1)

    def test_previous_meet_uses_meet_identity_not_latest_race(self):
        first=self.race(race_id='20261001-19-01',racer_id='5001',baseline=.15)
        first['meeting_id']='2026-09-30_shimonoseki'
        import_motor_observation(self.db,first)
        latest=self.race(race_id='20261002-19-01',racer_id='4011',
                         label='other',baseline=.45,
                         race_at='2026-10-02T13:00:00+09:00',
                         published_at='2026-10-02T16:00:00+09:00',
                         captured_at='2026-10-02T17:00:00+09:00')
        latest['meeting_id']='2026-10-02_shimonoseki'
        import_motor_observation(self.db,latest)
        result=analyze_motor(self.db,'19','2026-A',11,
            '2026-10-03T00:00:00+09:00',target_meeting_id='2026-10-02_shimonoseki')
        self.assertEqual(result['previous_meet']['meeting_id'],'2026-09-30_shimonoseki')
        self.assertEqual(result['previous_meet']['rookie_starts'],1)
        self.assertEqual(result['previous_meet']['starts'],1)
        self.assertEqual(result['latest_observed_rider']['racer_id'],'4011')
        self.assertIsNone(analyze_motor(self.db,'19','2026-A',11,
            '2026-10-03T00:00:00+09:00')['previous_meet'])

    def test_missing_meeting_ids_do_not_fabricate_previous_meet(self):
        import_motor_observation(self.db,self.race(baseline=.2))
        r=analyze_motor(self.db,'19','2026-A',11,
          '2026-10-03T00:00:00+09:00',target_meeting_id='2026-10-03')
        self.assertIsNone(r['previous_meet'])

if __name__=='__main__':unittest.main()

