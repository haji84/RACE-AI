"""Pure evidence ledger: no provider, key, model or repository I/O."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import unittest
try:
    audit = importlib.import_module('scripts.boat_owner_evidence_audit')
except ModuleNotFoundError:
    audit = None

DAY='2030-04-01'
NOW=datetime(2030,4,2,tzinfo=timezone.utc)
def fixtures():
    schedule=[dict(race_id=f'20300401-01-{n:02}',cutoff_at=f'{DAY}T12:{n:02}:00+09:00') for n in range(1,5)]
    def row(n,stage,model='existing-model'):
        return dict(schedule[n-1],stage=stage,model_id=model,as_of=f'{DAY}T11:40:00+09:00',
                    server_saved_at=f'{DAY}T11:41:00+09:00',model_sha256='a'*64,
                    top8=['PRIVATE_PREDICTION'],roster={'PRIVATE_PERSON':'1'})
    return schedule,[row(1,'P0'),row(2,'P0')],[row(1,'P1')]

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(audit,'Evidence audit module is absent')
        self.schedule,self.p0,self.p1=fixtures()
    def call(self,**kw):
        return audit.summarize(self.schedule,self.p0,self.p1,[],day=DAY,now=NOW,
                               official_program_verified=True,**kw)
    def test_official_schedule_not_saved_forecasts_is_denominator(self):
        value=self.call()
        self.assertEqual(value['scheduled_races'],4)
        self.assertEqual(value['baseline_p0_races'],2)
        self.assertEqual(value['baseline_p1_races'],1)
        self.assertEqual(value['scheduled_without_baseline_p1'],3)
        self.assertEqual(value['p1_eligibility_unknown'],3)
        self.assertFalse(value['all_models_complete_proven'])
    def test_unverified_schedule_cannot_prove_nationwide_coverage(self):
        value=audit.summarize(self.schedule,self.p0,self.p1,[],day=DAY,now=NOW,official_program_verified=False)
        self.assertIsNone(value['scheduled_races'])
        self.assertEqual(value['retained_schedule_rows'],4)
        self.assertFalse(value['all_scheduled_baseline_p1_present'])
    def test_unpublished_observation_is_not_proof_of_all_day_ineligibility(self):
        attempt=dict(race_id=self.schedule[1]['race_id'],state='EXHIBITION_NOT_FULLY_PUBLISHED')
        value=audit.summarize(self.schedule,self.p0,self.p1,[attempt],day=DAY,now=NOW,official_program_verified=True)
        self.assertEqual(value['p1_eligibility_unknown'],3)
        self.assertEqual(value['missing_p1_last_observation']['EXHIBITION_NOT_FULLY_PUBLISHED'],1)
    def test_ready_but_unsaved_is_distinct_from_unobserved(self):
        attempt=dict(race_id=self.schedule[1]['race_id'],state='AB_GENERATED_NOT_YET_EXTERNAL_FROZEN',
                     exhibition_sha256='b'*64,generated_at=f'{DAY}T11:40:00+09:00')
        value=audit.summarize(self.schedule,self.p0,self.p1,[attempt],day=DAY,now=NOW,official_program_verified=True)
        self.assertEqual(value['p1_missing_after_confirmed_ready'],1)
        self.assertEqual(value['p1_eligibility_unknown'],2)
    def test_foreign_race_and_duplicate_schedule_rejected(self):
        cases=[]
        s,p0,p1=fixtures();s.append(deepcopy(s[0]));cases.append((s,p0,p1))
        s,p0,p1=fixtures();p1[0]['race_id']='20300401-02-01';cases.append((s,p0,p1))
        for s,p0,p1 in cases:
            with self.subTest(s=s),self.assertRaises(ValueError):
                audit.summarize(s,p0,p1,[],day=DAY,now=NOW,official_program_verified=True)
    def test_different_authenticated_source_cutoff_is_reported_not_rewritten(self):
        before=deepcopy(self.schedule)
        self.p1[0]['cutoff_at']=f'{DAY}T12:59:00+09:00'
        result=self.call()
        self.assertEqual(result['baseline_p1_races'],1)
        self.assertEqual(result['p1_schedule_cutoff_conflict_races'],1)
        self.assertFalse(result['all_scheduled_baseline_p1_present'])
        self.assertEqual(self.schedule,before)
        self.assertEqual(self.p1[0]['cutoff_at'],f'{DAY}T12:59:00+09:00')

    def test_real_pilot_attempt_field_is_used_and_legacy_guess_is_rejected(self):
        report={'schema':'RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1','candidate_attempts':[
            {'race_id':self.schedule[1]['race_id'],'state':'EXHIBITION_NOT_FULLY_PUBLISHED'}]}
        self.assertEqual(audit.retained_attempts(report),report['candidate_attempts'])
        with self.assertRaises(ValueError):audit.retained_attempts({'tries':[]})

    def test_unsaved_ready_after_program_cutoff_remains_unresolved(self):
        attempt=dict(race_id=self.schedule[1]['race_id'],state='AB_GENERATED_NOT_YET_EXTERNAL_FROZEN',
                     exhibition_sha256='b'*64,generated_at=f'{DAY}T13:00:00+09:00')
        value=audit.summarize(self.schedule,self.p0,self.p1,[attempt],day=DAY,now=NOW,official_program_verified=True)
        self.assertEqual(value['p1_missing_after_confirmed_ready'],0)
        self.assertEqual(value['p1_eligibility_unknown'],3)
        self.assertEqual(value['missing_p1_last_observation']['GENERATED_AFTER_PROGRAM_CUTOFF_UNRESOLVED'],1)

    def test_late_saved_or_future_rows_rejected(self):
        for change in (dict(server_saved_at=f'{DAY}T13:00:00+09:00'),dict(as_of='2030-04-03T00:00:00Z')):
            p1=deepcopy(self.p1);p1[0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                audit.summarize(self.schedule,self.p0,p1,[],day=DAY,now=NOW,official_program_verified=True)
    def test_duplicate_model_slots_not_counted_twice_and_inputs_unchanged(self):
        self.p1.append(deepcopy(self.p1[0]));before=deepcopy((self.schedule,self.p0,self.p1))
        value=self.call()
        self.assertEqual(value['baseline_p1_unique_model_slots'],1)
        self.assertEqual(value['baseline_p1_repeated_slots'],1)
        self.assertEqual((self.schedule,self.p0,self.p1),before)
    def test_aggregate_never_exports_forecasts_persons_or_grants_dispatch(self):
        value=self.call();raw=json.dumps(value)
        self.assertNotIn('PRIVATE_',raw)
        self.assertFalse(value['successor_dispatch_allowed'])
        self.assertFalse(value['live_recovery_to_new_p1_proven'])
        self.assertEqual(value['official_source_requests'],0)
    def test_existing_receipt_second_precision_rule_is_preserved(self):
        self.p1[0]['as_of']=f'{DAY}T11:41:00.400000+09:00'
        value=self.call()
        self.assertEqual(value['baseline_p1_races'],1)
        self.p1[0]['as_of']=f'{DAY}T11:41:01+09:00'
        with self.assertRaises(ValueError):self.call()

    def test_video_absence_is_scoped_not_claimed_as_global_absence(self):
        value=self.call(video_rows=[],video_rejections=0)
        self.assertEqual(value['verified_video_prediction_rows'],0)
        self.assertEqual(value['video_scope'],'SELECTED_OWNER_P1_ORIGINALS_ONLY')
    def test_video_invalid_stage_or_foreign_race_rejected(self):
        video=dict(self.p1[0],variant='LEARNED_VIDEO_EXPERIMENTAL',stage='P0')
        with self.assertRaises(ValueError):self.call(video_rows=[video])

class PendingLinkTests(unittest.TestCase):
    def setUp(self):
        from hashlib import sha256
        self.digest=lambda v:sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.run=dict(id=7,head_sha='b'*40)
        self.control=dict(completed_round=2,prepared_round=3,previous_session_requests=88,
            lifetime_requests=88,lifetime_completed_rounds=2,day_start_lifetime_requests=0,source_wait=None)
        self.report=dict(round_no=3,run_id=7,code_sha='b'*40,day_jst=DAY,bounded_repeat_session=dict(
            requests_used=88,completed_round=2,prepared_round=3,lifetime_requests=88,
            lifetime_completed_rounds=2,day_start_lifetime_requests=0,source_wait=None,halted_reason=None))
        self.report['report_sha256']=self.digest(self.report)
    def call(self):
        return audit.pending_pair_report(self.control,b'exact',self.report,b'exact',run=self.run,day=DAY,digest=self.digest)
    def test_real_report_link_does_not_mark_failed_run_successful_or_reset_counters(self):
        before=deepcopy((self.control,self.report));result=self.call()
        self.assertTrue(result['verified']);self.assertEqual(result['requests_used'],88)
        self.assertFalse(result['successor_dispatch_allowed'])
        self.assertEqual((self.control,self.report),before)
    def test_counter_mismatch_and_hash_tampering_rejected(self):
        self.control['previous_session_requests']=0
        with self.assertRaises(ValueError):self.call()
        self.control['previous_session_requests']=88;self.report['round_no']=4
        with self.assertRaises(ValueError):self.call()
    def test_different_nested_original_and_source_hold_rejected(self):
        with self.assertRaises(ValueError):
            audit.pending_pair_report(self.control,b'exact',self.report,b'changed',run=self.run,day=DAY,digest=self.digest)
        self.control['source_wait']={'state':'AUTHORIZATION_WAIT'}
        with self.assertRaises(ValueError):self.call()

if __name__=='__main__':unittest.main()
