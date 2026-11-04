import unittest
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
