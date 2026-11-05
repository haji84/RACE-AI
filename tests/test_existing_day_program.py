import unittest,copy
from datetime import datetime,timezone
from scripts import existing_day_program as d

AT='2030-04-01T00:00:00+00:00'

def program():
 return {'date_jst':'2030-04-01','source_url':'https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh','source_sha256':'a'*64,'first_observed_at':AT,'venues':[{'venue':'01','races':[{'race_id':'20300401-01-01','closed_at':'2030-04-01T10:00:00+09:00','preview_available':False,'boats':[{'lane':i,'racer_registration_id':str(4000+i),'motor_no':i,'boat_no':i+20,'national_win_rate':float(i),'motor_top2_rate':float(10*i)} for i in range(1,7)]}]}]}

class DayProgramTest(unittest.TestCase):
 def test_guard_wait_prevents_the_source_request(self):
  from unittest.mock import patch,Mock
  from race_ai.source_retry_policy import SourceWait
  guard=Mock();guard.charge.side_effect=SourceWait('HTTP_RATE_LIMIT','2030-04-01T01:00:00+00:00')
  with patch.object(d.request,'build_opener') as opener,self.assertRaises(SourceWait):
   d.collect(clock=lambda:datetime.fromisoformat(AT),source_guard=guard)
  opener.assert_not_called()
  guard.charge.assert_called_once_with('forecast')
 def test_http_retry_after_is_preserved_without_pretending_forecast_success(self):
  from unittest.mock import patch,Mock
  from urllib.error import HTTPError
  opener=Mock();opener.open.side_effect=HTTPError('https://www1.mbrace.or.jp/',429,'wait',{'Retry-After':'900'},None)
  with patch.object(d.request,'build_opener',return_value=opener):
   result=d.collect(clock=lambda:datetime.fromisoformat(AT))
  self.assertEqual(result['http_status'],429)
  self.assertEqual(result['source_response_headers'],{'Retry-After':'900'})
  self.assertEqual(result['source_requests'],1)
  self.assertEqual(result['predictions'],[])
  self.assertEqual(result['race_count'],0)
 def test_transport_subclasses_remain_retryable_without_claiming_source_success(self):
  from unittest.mock import patch,Mock
  opener=Mock();opener.open.side_effect=ConnectionResetError('fictional reset')
  with patch.object(d.request,'build_opener',return_value=opener):
   result=d.collect(clock=lambda:datetime.fromisoformat(AT))
  self.assertEqual(result['source_error_kind'],'TRANSPORT')
  self.assertEqual(result['source_requests'],1)
  self.assertEqual(result['predictions'],[])
 def test_existing_two_models_real_scope_explicit_missing_and_no_mutation(self):
  p=program();before=copy.deepcopy(p)
  result=d.forecast_program(p,clock=lambda:datetime.fromisoformat(AT))
  self.assertEqual(p,before)
  self.assertEqual(result['race_count'],1)
  self.assertEqual(result['model_forecast_count'],2)
  s=result['predictions'][0]
  self.assertEqual(s['scope'],'OPERATOR_SUPPLIED_RESEARCH')
  self.assertEqual(set(s['models']),set(d.EXISTING_IDS))
  self.assertEqual(set(s['observations'][0]['features']),{'national_win_rate','motor_top2_rate'})
  self.assertIn('recent_mean_finish',s['observations'][0]['missing'])
  self.assertFalse(result['external_receipt_verified'])
 def test_closed_retained_without_prediction(self):
  x=d.forecast_program(program(),clock=lambda:datetime.fromisoformat('2030-04-01T02:00:00+00:00'))
  self.assertEqual(len(x['schedule']),1);self.assertEqual(x['race_count'],0)
  self.assertEqual(x['skipped'][0]['reason'],'CUTOFF_BUFFER')
 def test_known_original_not_regenerated(self):
  x=d.forecast_program(program(),clock=lambda:datetime.fromisoformat(AT),already_frozen={'20300401-01-01'})
  self.assertEqual(x['race_count'],0);self.assertEqual(x['skipped'][0]['reason'],'ORIGINAL_EXISTS')
 def test_partial_original_only_runs_the_missing_existing_model(self):
  from unittest.mock import patch
  from race_ai import boat_observed_pairwise_models as models
  existing=d.EXISTING_IDS[0];missing=d.EXISTING_IDS[1]
  with patch.object(models,'_model_result',wraps=models._model_result) as inference:
   x=d.forecast_program(program(),clock=lambda:datetime.fromisoformat(AT),
                        already_frozen_models={('20300401-01-01',existing)})
  self.assertEqual([c.args[0] for c in inference.call_args_list],[missing])
  self.assertEqual(x['model_forecast_count'],1)
  self.assertEqual(set(x['predictions'][0]['models']),{missing})
 def test_complete_original_slots_do_not_invoke_any_model(self):
  from unittest.mock import patch
  slots={('20300401-01-01',mid) for mid in d.EXISTING_IDS}
  with patch.object(d,'predict_pair') as infer:
   x=d.forecast_program(program(),clock=lambda:datetime.fromisoformat(AT),already_frozen_models=slots)
  infer.assert_not_called()
  self.assertEqual(x['skipped'][0]['reason'],'ORIGINAL_EXISTS')
 def test_foreign_source_rejected(self):
  p=program();p['source_url']='https://example.test/pretend'
  with self.assertRaises(ValueError):d.forecast_program(p,clock=lambda:datetime.fromisoformat(AT))
 def test_duplicate_race_rejected(self):
  p=program();p['venues'][0]['races']*=2
  with self.assertRaises(ValueError):d.forecast_program(p,clock=lambda:datetime.fromisoformat(AT))
 def test_future_capture_rejected(self):
  p=program();p['first_observed_at']='2030-04-01T04:00:00+00:00'
  with self.assertRaises(ValueError):d.forecast_program(p,clock=lambda:datetime.fromisoformat(AT))
