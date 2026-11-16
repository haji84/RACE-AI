"""Source-free 13-venue/156-race P1 and existing experimental video-model gate.

Synthetic fixtures. No provider GET, private media, credentials, predictions
on closed races, release promotion or alteration of original model outputs.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from race_ai.actions_contract import digest
from tests.test_boat_video_connection import VideoConnectionTests, controlled_connection

JST = timezone(timedelta(hours=9))
DAY = '2030-04-01'
NOW = datetime(2030, 4, 1, 21, 0, tzinfo=JST)
MODELS = ('boat-course-motor-shadow-v0.1-UNTRAINED',
          'boat-display-rating-PL-reference-v1-UNVALIDATED',
          'boat-local-start-course-shadow-v0.1-UNTRAINED',
          'boat-observed-pairwise-factor-v1',
          'boat-observed-pairwise-start-v1')
P0_MODELS = ('boat-observed-pairwise-factor-v1', 'boat-observed-pairwise-start-v1')


def example_scope():
    # 13 fictional venues x 12 races, including the video model's 24-12 race.
    venues = [f'{v:02d}' for v in range(1, 13)] + ['24']
    schedule = []
    for venue in venues:
        for number in range(1, 13):
            schedule.append(dict(
                race_id=f'20300401-{venue}-{number:02d}',
                cutoff_at=f'2030-04-01T{10+(number-1)//2:02d}:{(number-1)%2*30:02d}:00+09:00'))
    target = next(r for r in schedule if r['race_id']=='20300401-24-12')
    target['cutoff_at'] = '2030-04-01T17:30:00+09:00'
    p0 = [dict(race_id=r['race_id'],stage='P0',model_id=m,
               as_of='2030-04-01T09:00:00+09:00',
               server_saved_at='2030-04-01T09:01:00+09:00',cutoff_at=r['cutoff_at'])
          for r in schedule[:136] for m in P0_MODELS]
    p1 = [dict(race_id=r['race_id'],stage='P1',model_id=m,
               as_of='2030-04-01T09:20:00+09:00',
               server_saved_at='2030-04-01T09:21:00+09:00',cutoff_at=r['cutoff_at'])
          for r in schedule[130:139] for m in MODELS]
    missing = [r for r in schedule if r['race_id'] not in {x['race_id'] for x in p1}]
    attempts = [dict(race_id=r['race_id'],state='ALREADY_CLOSED_BEFORE_SCHEDULE_CAPTURE')
                for r in missing[:21]]
    return schedule,p0,p1,attempts


class P1CoverageGateTests(unittest.TestCase):
    def audit(self, **override):
        from race_ai.boat_national_video_research_gate import audit
        schedule,p0,p1,attempts=example_scope()
        args=dict(day=DAY,now=NOW,schedule=schedule,p0_rows=p0,p1_rows=p1,
                  attempts=attempts,video_connections=[],expected_p1_models=MODELS,
                  official_schedule_authenticated=True,originals_authenticated=True)
        args.update(override)
        return audit(**args)

    def test_full_official_156_denominator_never_confused_with_136_p0(self):
        result=self.audit()
        self.assertEqual(result['official_schedule_races'],156)
        self.assertEqual(result['p0_races'],136)
        self.assertEqual(result['p0_original_slots'],272)
        self.assertEqual(result['p1_original_slots'],45)
        self.assertEqual(result['p1_any_races'],9)
        self.assertEqual(result['p1_complete_races'],9)
        self.assertEqual(result['p1_missing_races'],147)
        self.assertEqual(result['p1_missing_reasons'],{
            'ALREADY_CLOSED_BEFORE_SCHEDULE_CAPTURE':21,
            'NO_RETAINED_P1_ATTEMPT':126})
        self.assertEqual(result['video_experimental_races'],0)
        self.assertEqual(result['video_experimental_rows'],0)
        self.assertFalse(result['nationwide_p1_complete_proven'])
        self.assertFalse(result['video_production_proven'])
        self.assertEqual(result['state'],'HOLD_NATIONWIDE_P1_INCOMPLETE')
        self.assertEqual(len(result['per_venue']),13)
        self.assertEqual(sum(v['scheduled'] for v in result['per_venue'].values()),156)

    def test_real_cutoff_queue_eventually_admits_all_156_without_source_get(self):
        from race_ai.boat_deadline_queue import select_due_races
        schedule,_,_,_=example_scope()
        lines=[dict(row,schedule_captured_at='2030-04-01T09:30:00+09:00',
                    source_sha256='a'*64) for row in schedule]
        closed=set()
        for cutoff in sorted({x['cutoff_at'] for x in lines}):
            tick=(datetime.fromisoformat(cutoff)-timedelta(minutes=12)).isoformat()
            doc=select_due_races(lines,tick,already_frozen=frozenset(closed),max_items=None)
            self.assertFalse(doc['forecast_generated'])
            self.assertFalse(doc['source_fetch_performed'])
            self.assertFalse(doc['freeze_proven'])
            for row in doc['eligible']:
                self.assertNotIn(row['race_id'],closed)
                self.assertGreater((datetime.fromisoformat(row['cutoff_at'])-
                                    datetime.fromisoformat(tick)).total_seconds(),210)
                closed.add(row['race_id'])
        self.assertEqual(len(closed),156)

    def test_incomplete_model_group_not_misreported_as_p1_complete(self):
        schedule,p0,p1,attempts=example_scope()
        p1.pop()
        result=self.audit(p1_rows=p1,schedule=schedule,p0_rows=p0,attempts=attempts)
        self.assertEqual(result['p1_any_races'],9)
        self.assertEqual(result['p1_complete_races'],8)
        self.assertEqual(result['p1_missing_races'],148)
        self.assertEqual(result['p1_missing_reasons']['INCOMPLETE_MODEL_MATRIX'],1)

    def test_late_stored_forecast_is_not_counted(self):
        schedule,p0,p1,attempts=example_scope()
        p1[0]['server_saved_at']=p1[0]['cutoff_at']
        result=self.audit(p1_rows=p1,schedule=schedule,p0_rows=p0,attempts=attempts)
        self.assertEqual(result['p1_complete_races'],8)
        self.assertEqual(result['p1_missing_reasons']['UNVERIFIED_OR_LATE_P1_ORIGINAL'],1)

    def test_unverified_source_and_forecast_receipts_hold_even_if_all_slots_present(self):
        schedule,p0,p1,attempts=example_scope()
        for r in schedule:
            for m in MODELS:
                if not any(x['race_id']==r['race_id'] and x['model_id']==m for x in p1):
                    p1.append(dict(race_id=r['race_id'],stage='P1',model_id=m,
                                   as_of='2030-04-01T09:20:00+09:00',
                                   server_saved_at='2030-04-01T09:21:00+09:00',cutoff_at=r['cutoff_at']))
        result=self.audit(schedule=schedule,p0_rows=p0,p1_rows=p1,
                          official_schedule_authenticated=False)
        self.assertEqual(result['p1_complete_races'],156)
        self.assertEqual(result['state'],'HOLD_SOURCE_AUTHENTICATION_UNVERIFIED')
        result=self.audit(schedule=schedule,p0_rows=p0,p1_rows=p1,
                          originals_authenticated=False)
        self.assertEqual(result['state'],'HOLD_SOURCE_AUTHENTICATION_UNVERIFIED')

    def test_duplicate_conflicting_originals_and_foreign_race_are_rejected(self):
        schedule,p0,p1,attempts=example_scope()
        conflict=dict(p1[0],server_saved_at='2030-04-01T09:22:00+09:00')
        with self.assertRaises(ValueError):self.audit(p1_rows=p1+[conflict])
        foreign=dict(p1[0],race_id='20300402-24-12')
        with self.assertRaises(ValueError):self.audit(p1_rows=p1+[foreign])
        with self.assertRaises(ValueError):self.audit(schedule=schedule+[schedule[0]])


class VideoShadowGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        VideoConnectionTests.setUpClass()

    def connected(self):
        from race_ai.boat_video_connection import connect_report
        report,evidence,inputs,verifier,clock=controlled_connection(VideoConnectionTests.training)
        result=connect_report(report,identity_evidence=evidence,
                              model_inputs=inputs,receipt_verifier=verifier,clock=lambda:clock)
        self.assertEqual(result['status'],'CONNECTED_EXPERIMENTAL')
        self.assertEqual(len(result['shadows']),2)
        return result

    def test_actual_existing_video_model_math_is_admitted_as_research_only(self):
        from race_ai.boat_national_video_research_gate import audit
        schedule,p0,p1,attempts=example_scope()
        connected=self.connected()
        before=deepcopy((schedule,p0,p1,attempts,connected))
        result=audit(day=DAY,now=NOW,schedule=schedule,p0_rows=p0,p1_rows=p1,
                     attempts=attempts,video_connections=[connected],
                     expected_p1_models=MODELS,official_schedule_authenticated=True,
                     originals_authenticated=True)
        self.assertEqual(result['video_experimental_races'],1)
        self.assertEqual(result['video_experimental_rows'],2)
        self.assertFalse(result['video_production_proven'])
        self.assertFalse(result['nationwide_p1_complete_proven'])
        self.assertEqual((schedule,p0,p1,attempts,connected),before)

    def test_video_shadow_without_real_receipt_or_with_post_cutoff_is_not_accepted(self):
        connected=self.connected()
        broken=deepcopy(connected)
        broken['shadows'][0]['video_receipt_proof']={}
        broken['connection_sha256']=digest({k:v for k,v in broken.items() if k!='connection_sha256'})
        with self.assertRaises(ValueError):P1CoverageGateTests().audit(video_connections=[broken])
        late=deepcopy(connected)
        late['completed_at']=late['cutoff_at']
        late['connection_sha256']=digest({k:v for k,v in late.items() if k!='connection_sha256'})
        with self.assertRaises(ValueError):P1CoverageGateTests().audit(video_connections=[late])
        forged=deepcopy(connected)
        forged['production_eligible']=True
        forged['connection_sha256']=digest({k:v for k,v in forged.items() if k!='connection_sha256'})
        with self.assertRaises(ValueError):P1CoverageGateTests().audit(video_connections=[forged])

if __name__ == '__main__':
    unittest.main()
