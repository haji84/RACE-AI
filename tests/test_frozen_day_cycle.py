import copy,io,json,unittest,zipfile,hashlib
from race_ai.boat_observed_pairwise_models import predict_pair
from tests.test_boat_observed_pairwise_models import fixture
try:
 from race_ai import frozen_day_cycle as cycle
except ImportError:
 cycle=None

def sample():
 s=predict_pair(fixture(research=True),allow_source=lambda *_:True)
 d={'schema':'RACE_AI_EXISTING_P0_DAY_V1','day_jst':'2030-04-01','predictions':[s],
    'schedule':[{'race_id':'20300401-01-01','cutoff_at':s['sales_cutoff_at']}],
    'race_count':1,'model_forecast_count':2,'actual_purchases':False,'skipped':[]}
 raw=json.dumps(d,sort_keys=True,separators=(',',':')).encode();b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:z.writestr('forecasts.json',raw)
 archive=b.getvalue();receipt={'id':1,'name':'boat-p0-existing-2','created_at':'2030-04-01T01:43:00Z','expired':False,'digest':'sha256:'+hashlib.sha256(archive).hexdigest(),'workflow_run':{'id':2,'head_repository_id':1416489937}}
 return d,archive,receipt

class FrozenCycleTest(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(cycle,'frozen day cycle is not implemented')
 def test_archive_authentication_and_two_original_models(self):
  d,z,r=sample();blob,rows=cycle.read_p0(z,r,expected_day='2030-04-01')
  self.assertEqual(len(rows),2);self.assertEqual(json.dumps(blob,sort_keys=True),json.dumps(d,sort_keys=True))
  self.assertEqual(rows[0]['race_id'],'20300401-01-01');self.assertFalse(blob['predictions'][0]['official_prediction'])
 def test_corruption_late_receipt_and_wrong_day_are_rejected(self):
  d,z,r=sample()
  with self.assertRaises(ValueError):cycle.read_p0(z+b'changed',r,expected_day='2030-04-01')
  r['created_at']='2030-04-01T02:00:00Z'
  with self.assertRaises(ValueError):cycle.read_p0(z,r,expected_day='2030-04-01')
  d,z,r=sample()
  with self.assertRaises(ValueError):cycle.read_p0(z,r,expected_day='2030-04-02')
 def test_pending_is_not_loss_and_no_change_to_original(self):
  d,z,r=sample();_,rows=cycle.read_p0(z,r,expected_day='2030-04-01');before=copy.deepcopy(rows)
  out=cycle.evaluate(rows,[])
  self.assertEqual(out['scored_forecasts'],0);self.assertEqual(out['pending_forecasts'],2);self.assertEqual(rows,before)
 def test_wrong_roster_and_result_before_cutoff_rejected(self):
  _,z,r=sample();_,rows=cycle.read_p0(z,r,expected_day='2030-04-01')
  obs=observation(rows[0]);obs['data']['results'][0]['racer_registration_id']='9999'
  out=cycle.evaluate(rows,[obs]);self.assertEqual(out['scored_forecasts'],0)
  obs=observation(rows[0]);obs['captured_at']='2030-04-01T01:00:00Z'
  out=cycle.evaluate(rows,[obs]);self.assertEqual(out['scored_forecasts'],0)
 def test_hit_miss_diagnostics_and_no_automatic_promotion(self):
  _,z,r=sample();_,rows=cycle.read_p0(z,r,expected_day='2030-04-01')
  obs=observation(rows[0]);out=cycle.evaluate(rows,[obs])
  self.assertEqual(out['scored_forecasts'],2)
  self.assertEqual(out['scoreboard'][0]['stake_yen'],800)
  self.assertEqual(out['scoreboard'][0]['hits'],1)
  self.assertFalse(out['auto_promoted']);self.assertFalse(out['past_forecasts_changed'])
 def test_refund_is_not_ordinary_miss(self):
  _,z,r=sample();_,rows=cycle.read_p0(z,r,expected_day='2030-04-01');o=observation(rows[0]);o['data']['refund_boats']=[6]
  out=cycle.evaluate(rows,[o]);self.assertEqual(out['scored_forecasts'],0)
  self.assertEqual(out['per_forecast'][0]['state'],'REFUND_REVIEW_REQUIRED')
 def test_conflicting_or_duplicate_forecasts_rejected(self):
  _,z,r=sample();_,rows=cycle.read_p0(z,r,expected_day='2030-04-01')
  with self.assertRaises(ValueError):cycle.evaluate(rows+rows,[])

def observation(row):
 winner=list(row['top8'][0]);rest=[n for n in range(1,7) if n not in winner];order=winner+rest
 return {'race_id':row['race_id'],'status':'AVAILABLE','body_identity_verified':True,'closed_at':row['cutoff_at'],
  'captured_at':'2030-04-01T02:10:00Z','source_url':'https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
  'source_sha256':'b'*64,'data':{'status':'settled','confirmed':True,'finish_confirmed':True,'refund_boats':[],
  'top3':winner,'results':[{'lane':n,'racer_registration_id':row['roster'][str(n)],'finish_status':'FINISHED','finish':order.index(n)+1} for n in range(1,7)],
  'payouts':[{'bet_type':'trifecta','combination':winner,'payout_per_100_yen':1230}]}}
