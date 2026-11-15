import copy
from datetime import datetime, timezone
import unittest
from race_ai import existing_model_coverage as module
try:
 from race_ai.existing_model_coverage import catalog,coverage
except ImportError:
 catalog=coverage=None
class CoverageTests(unittest.TestCase):
 def test_all_previous_sixteen_are_registered_without_forecasts_from_names(self):
  self.assertIsNotNone(catalog);models=catalog();self.assertEqual(len(models),16)
  self.assertEqual(len({x['model_id'] for x in models}),16)
  report=coverage([],{'boat':144,'keirin':75,'autorace':20,'horse':59})
  self.assertEqual(report['total_saved_forecasts'],0);self.assertFalse(report['all_models_operational'])
  self.assertEqual(report['model_family_count'],16)
 def test_specialists_do_not_silently_run_other_sports(self):
  self.assertIsNotNone(catalog)
  rows=coverage([],{'boat':144,'keirin':75,'autorace':20,'horse':59})['models']
  auto=next(x for x in rows if x['model_id']=='autorace-personal-observed-baseline-v1')
  self.assertEqual(auto['applicable_sports'],['autorace']);self.assertEqual(auto['saved_forecasts'],0)
 def test_real_saved_rows_count_without_claiming_full_coverage(self):
  self.assertIsNotNone(coverage)
  row=dict(sport='boat',stage='P1',model_id='boat-display-rating-PL-reference-v1-UNVALIDATED',race_id='20261104-17-01')
  r=coverage([row],{'boat':144});self.assertEqual(r['total_saved_forecasts'],1)
  self.assertFalse(r['all_models_operational'])


class MatrixTests(unittest.TestCase):
 def setUp(self):
  self.matrix=getattr(module,'coverage_matrix',None)
  self.assertTrue(callable(self.matrix),'all-race/model coverage matrix is missing')
  self.now=datetime(2030,4,1,0,tzinfo=timezone.utc)
  self.race=dict(race_id='boat:2030-04-01:fictional:1',sport='boat',
                 cutoff_at='2030-04-01T10:00:00+09:00')
  self.mid='boat-display-rating-PL-reference-v1-UNVALIDATED'

 def slot(self,report,mid=None,stage='P1',version=None):
  return next(s for s in report['slots'] if s['model_id']==(mid or self.mid)
              and s['stage']==stage and s['model_version']==version)

 def saved(self,**extra):
  row=dict(race_id=self.race['race_id'],sport='boat',stage='P1',model_id=self.mid,
           cutoff_at=self.race['cutoff_at'],as_of='2030-04-01T00:30:00Z',
           server_saved_at='2030-04-01T00:31:00Z',artifact_id=123,
           original_json_sha256='a'*64,model_sha256='b'*64)
  row.update(extra)
  return row

 def test_counts_only_report_never_claims_schedule_completeness(self):
  report=coverage([],{'boat':144})
  self.assertTrue(report['counts_only'])
  self.assertFalse(report['schedule_completeness_proven'])

 def test_every_supplied_race_has_all_sixteen_families_including_specialists(self):
  # Fictional ledger only: independently hand-counted applicability is
  # 144*15 + 75*5 + 20*6 + 59*5 = 2950; remaining 1818 do not apply.
  schedule=[dict(race_id=f'{sport}:2030-04-01:fictional:{i+1}',sport=sport,
                 cutoff_at=self.race['cutoff_at'],scope='SYNTHETIC_ONLY')
            for sport,n in [('boat',144),('keirin',75),('autorace',20),('horse',59)]
            for i in range(n)]
  report=self.matrix(schedule,[],stages=('P1',),now=self.now)
  self.assertEqual(report['scheduled_races'],298)
  self.assertEqual(report['slot_count'],4768)
  self.assertEqual(report['applicable_slots'],2950)
  self.assertEqual(report['not_applicable_slots'],1818)
  self.assertEqual(report['missing_frozen_slots'],2950)
  self.assertEqual({sum(s['race_id']==r['race_id'] for s in report['slots']) for r in schedule},{16})
  self.assertFalse(report['schedule_completeness_proven'])
  self.assertFalse(report['all_models_operational'])

 def test_another_model_original_does_not_hide_missing_models_or_other_phase(self):
  before=copy.deepcopy(self.race)
  report=self.matrix([self.race],[self.saved()],stages=('P0','P1'))
  self.assertEqual(report['slot_count'],32)
  self.assertEqual(report['receipt_metadata_slots'],1)
  self.assertEqual(report['missing_frozen_slots'],30)
  self.assertEqual(report['missing_receipt_metadata_slots'],29)
  self.assertEqual(self.slot(report)['state'],'RECEIPT_METADATA_CONSISTENT')
  self.assertEqual(self.slot(report,stage='P0')['state'],'INPUT_MISSING')
  self.assertFalse(report['independent_receipts_verified'])
  self.assertEqual(self.race,before)

 def test_explicit_stage_ledger_preserves_both_stages_of_one_race(self):
  schedule=[dict(self.race,stage='P0'),dict(self.race,stage='P1')]
  report=self.matrix(schedule,[])
  self.assertEqual(report['scheduled_races'],1)
  self.assertEqual(report['race_stage_count'],2)
  self.assertEqual(report['slot_count'],32)
  with self.assertRaises(ValueError):self.matrix([schedule[0],schedule[0]],[])
  with self.assertRaises(ValueError):self.matrix(schedule,[],stages=('P0',))

 def test_forecast_cannot_self_attest_external_verification(self):
  row=dict(race_id=self.race['race_id'],sport='boat',stage='P1',model_id=self.mid,
           external_receipt_verified=True,verified=True)
  report=self.matrix([self.race],[row],stages=('P1',))
  slot=self.slot(report)
  self.assertEqual(slot['state'],'SAVED_RECEIPT_UNVERIFIED')
  self.assertIn('RECEIPT_METADATA_MISSING',slot['reasons'])
  self.assertEqual(report['receipt_metadata_slots'],0)
  self.assertFalse(report['independent_receipts_verified'])

 def test_generated_and_input_blocked_dispatcher_slots_are_not_frozen(self):
  generated=dict(race_id=self.race['race_id'],sport='boat',stage='P1',model_id=self.mid,
                 status='GENERATED_UNATTESTED',reason='EXTERNAL_RECEIPT_MISSING',
                 prediction={'private':'do not expose'},prediction_sha256='c'*64)
  blocked=dict(generated,model_id='multisport-chronological-ranker-v1',
               status='TRAINED_ARTIFACT_MISSING',reason='NO_GENUINE_ARTIFACT',prediction=None)
  report=self.matrix([self.race],[generated,blocked],stages=('P1',))
  self.assertEqual(self.slot(report)['state'],'GENERATED_UNATTESTED')
  self.assertNotIn('prediction',self.slot(report))
  self.assertEqual(self.slot(report,blocked['model_id'])['state'],'TRAINED_ARTIFACT_MISSING')
  self.assertEqual(report['receipt_metadata_slots'],0)
  self.assertEqual(report['missing_frozen_slots'],15)

 def test_deadline_and_invalid_receipt_time_are_visible_without_backfill(self):
  report=self.matrix([self.race],[],stages=('P1',),now='2030-04-01T01:00:00Z')
  self.assertEqual(self.slot(report)['state'],'DEADLINE_PASSED')
  self.assertIn('NO_PRE_CUTOFF_FORECAST',self.slot(report)['reasons'])
  late=self.saved(server_saved_at='2030-04-01T01:00:00Z')
  slot=self.slot(self.matrix([self.race],[late],stages=('P1',)))
  self.assertEqual(slot['state'],'SAVED_AFTER_CUTOFF')
  self.assertFalse(slot['receipt_metadata_consistent'])

 def test_declared_versions_have_independent_slots_and_never_pool_originals(self):
  report=self.matrix([self.race],[self.saved(model_version='v1')],stages=('P1',),
                     model_versions={self.mid:('v1','v2')})
  self.assertEqual(report['slot_count'],17)
  self.assertEqual(self.slot(report,version='v1')['state'],'RECEIPT_METADATA_CONSISTENT')
  self.assertEqual(self.slot(report,version='v2')['state'],'INPUT_MISSING')
  with self.assertRaises(ValueError):
   self.matrix([self.race],[self.saved(model_version='v3')],stages=('P1',),model_versions={self.mid:('v1','v2')})
  with self.assertRaises(ValueError):
   self.matrix([self.race],[self.saved(model_version='v1'),self.saved(model_version='v2')],stages=('P1',))

 def test_unknown_mismatched_duplicate_and_inapplicable_forecasts_fail_closed(self):
  cases=[dict(race_id='boat:2030-04-01:other:1'),dict(sport='horse'),dict(stage='P0'),
         dict(model_id='invented-family'),dict(cutoff_at='2030-04-01T01:01:00Z'),
         dict(model_id='autorace-personal-observed-baseline-v1'),dict(model_version='')]
  for updates in cases:
   with self.subTest(updates=updates),self.assertRaises(ValueError):
    self.matrix([self.race],[self.saved(**updates)],stages=('P1',))
  with self.assertRaises(ValueError):self.matrix([self.race],[self.saved(),self.saved()],stages=('P1',))

 def test_schedule_requires_real_supplied_identities_and_consistent_metadata(self):
  for schedule in ({'boat':144},[dict(self.race,race_id='')],[dict(self.race,sport='unknown')],
                   [dict(self.race,cutoff_at='2030-04-01T10:00:00')],
                   [dict(self.race,stage='P0'),dict(self.race,stage='P1',sport='horse')]):
   with self.subTest(schedule=schedule),self.assertRaises(ValueError):self.matrix(schedule,[])
  with self.assertRaises(ValueError):self.matrix([self.race],[],stages=('P1','P1'))
  with self.assertRaises(ValueError):self.matrix([self.race],[],stages=('P1',),now=datetime(2030,4,1))

 def test_dispatcher_cannot_claim_not_applicable_for_an_applicable_model(self):
  row=self.saved(status='NOT_APPLICABLE',reason='caller omitted this model')
  with self.assertRaises(ValueError):self.matrix([self.race],[row],stages=('P1',))

 def test_malformed_json_field_types_fail_with_contract_errors(self):
  for changes in (dict(stage=[]),dict(model_id={}),dict(model_version=[]),dict(status=[])):
   with self.subTest(changes=changes),self.assertRaises(ValueError):
    self.matrix([self.race],[self.saved(**changes)],stages=('P1',))
  with self.assertRaises(ValueError):self.matrix([dict(self.race,stage=[])],[])

 def test_future_or_reverse_chronology_is_not_consistent_receipt_metadata(self):
  for changes,reason in ((dict(as_of='2030-04-01T00:30:02Z'), 'RECEIPT_BEFORE_INPUT'),
                         (dict(server_saved_at='2030-04-01T00:50:00Z'), 'RECEIPT_OR_INPUT_IN_FUTURE')):
   row=self.saved(**changes)
   if reason=='RECEIPT_BEFORE_INPUT':row['server_saved_at']='2030-04-01T00:30:00Z'
   report=self.matrix([self.race],[row],stages=('P1',),now='2030-04-01T00:45:00Z')
   self.assertFalse(self.slot(report)['receipt_metadata_consistent'])
   self.assertIn(reason,self.slot(report)['reasons'])

 def test_missing_dispatcher_versions_do_not_invent_or_conflict_with_actual_versions(self):
  race2=dict(self.race,race_id='boat:2030-04-01:fictional:2')
  generated=self.saved(model_version='v1',status='GENERATED_UNATTESTED')
  blocked=dict(race_id=race2['race_id'],sport='boat',stage='P1',model_id=self.mid,
               model_version=None,status='INPUT_MISSING',reason='NO_NATIVE_INPUT')
  for versions in (None,{self.mid:('v1','v2')}):
   report=self.matrix([self.race,race2],[generated,blocked],stages=('P1',),model_versions=versions)
   missing=[s for s in report['slots'] if s['race_id']==race2['race_id'] and s['model_id']==self.mid]
   self.assertEqual({s['model_version'] for s in missing},{'v1'} if versions is None else {'v1','v2'})
   self.assertTrue(all(s['state']=='INPUT_MISSING' and s['reported_model_version'] is None for s in missing))
  with self.assertRaises(ValueError):
   self.matrix([self.race],[dict(blocked,race_id=self.race['race_id']),generated],stages=('P1',))

 def test_native_autorace_stages_remain_distinct_without_inventing_p0_aliases(self):
  race=dict(race_id='autorace:2030-04-01:fictional:1',sport='autorace',cutoff_at=self.race['cutoff_at'])
  report=self.matrix([dict(race,stage='A_PRE_TRIAL'),dict(race,stage='B_POST_TRIAL')],[])
  self.assertEqual(report['race_stage_count'],2)
  self.assertEqual(report['slot_count'],32)
  self.assertEqual({s['stage'] for s in report['slots']},{'A_PRE_TRIAL','B_POST_TRIAL'})
  self.assertEqual(self.matrix([race],[],stages=('A_PRE_TRIAL',))['slot_count'],16)

 def test_race_version_roster_keeps_unissued_versions_and_validates_each_original(self):
  first=dict(self.race,stage='P1',model_versions={self.mid:('v1','v2')})
  second=dict(self.race,race_id='boat:2030-04-01:fictional:2',stage='P1',
              model_versions={self.mid:'v3'})
  rows=[self.saved(model_version='v1'),self.saved(race_id=second['race_id'],model_version='v3')]
  report=self.matrix([first,second],rows)
  self.assertEqual(report['slot_count'],33)
  self.assertEqual(self.slot(report,version='v2')['state'],'INPUT_MISSING')
  with self.assertRaises(ValueError):self.matrix([first],[self.saved(model_version='v3')])
  with self.assertRaises(ValueError):
   self.matrix([dict(first,model_versions={'unknown-family':('v1',)})],[])
