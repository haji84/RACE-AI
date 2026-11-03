import unittest,copy
from datetime import datetime,timezone
from scripts import existing_day_program as d

AT='2030-04-01T00:00:00+00:00'

def program():
 return {'date_jst':'2030-04-01','source_url':'https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh','source_sha256':'a'*64,'first_observed_at':AT,'venues':[{'venue':'01','races':[{'race_id':'20300401-01-01','closed_at':'2030-04-01T10:00:00+09:00','preview_available':False,'boats':[{'lane':i,'racer_registration_id':str(4000+i),'motor_no':i,'boat_no':i+20,'national_win_rate':float(i),'motor_top2_rate':float(10*i)} for i in range(1,7)]}]}]}

class DayProgramTest(unittest.TestCase):
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
 def test_foreign_source_rejected(self):
  p=program();p['source_url']='https://example.test/pretend'
  with self.assertRaises(ValueError):d.forecast_program(p,clock=lambda:datetime.fromisoformat(AT))
 def test_duplicate_race_rejected(self):
  p=program();p['venues'][0]['races']*=2
  with self.assertRaises(ValueError):d.forecast_program(p,clock=lambda:datetime.fromisoformat(AT))
 def test_future_capture_rejected(self):
  p=program();p['first_observed_at']='2030-04-01T04:00:00+00:00'
  with self.assertRaises(ValueError):d.forecast_program(p,clock=lambda:datetime.fromisoformat(AT))
